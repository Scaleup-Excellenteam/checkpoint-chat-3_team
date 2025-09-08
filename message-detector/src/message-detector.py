#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
message-detector.py
Two-pass filter:
  1) Local pass (fast, literal): deny immediately on excludes (or missing required include)
  2) Gemini pass (optional): semantic validation; excludes still win

Improvements:
- Local matching normalizes text (lowercase + collapse whitespace)
- Multi-word phrases: substring on normalized text
- Single words: whole-word boundary
- Debug mode: send {"debug": true} to get match details

ENV:
  GEMINI_API_KEY (optional)
  GEMINI_MODEL   (default: gemini-1.5-flash)
  HOST/PORT/DEBUG standard
"""
import os, re, json, logging
from flask import Flask, request, jsonify

try:
    import google.generativeai as genai  # optional
except Exception:
    genai = None

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s - %(message)s")
logger = logging.getLogger("message-detector")

app = Flask(__name__)

try:
    from flask_cors import CORS  # optional
    CORS(app)
except Exception:
    pass

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
DEBUG = str(os.getenv("DEBUG", "0")).lower() in ("1", "true", "yes")


# ---------- Local helpers ----------
def _norm_text(s: str) -> str:
    # Lowercase + collapse all whitespace to a single space
    return re.sub(r"\s+", " ", (s or "")).strip().lower()

def _norm_terms(terms):
    if not terms:
        return []
    if isinstance(terms, str):
        terms = [terms]
    out = []
    for t in terms:
        if isinstance(t, str):
            t = _norm_text(t)
            if t:
                out.append(t)
    return out

def _match_single_word(word: str, text_norm: str) -> bool:
    # Whole word on normalized text
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text_norm) is not None

def _local_keyword_check(text, include_any, exclude_any, include_required=True, want_debug=False):
    """
    Improved local matching:
    - Normalize text (lowercase + collapse whitespace)
    - Multi-word terms -> substring search on normalized text
    - Single words -> whole-word boundary search
    """
    text_norm = _norm_text(text)
    include_any = _norm_terms(include_any)
    exclude_any = _norm_terms(exclude_any)

    include_hits = []
    exclude_hits = []

    # Includes
    for term in include_any:
        if " " in term:
            if term in text_norm:
                include_hits.append(term)
        else:
            if _match_single_word(term, text_norm):
                include_hits.append(term)

    # Excludes
    for term in exclude_any:
        if " " in term:
            if term in text_norm:
                exclude_hits.append(term)
        else:
            if _match_single_word(term, text_norm):
                exclude_hits.append(term)

    match = (bool(include_hits) or (not include_required)) and not bool(exclude_hits)
    if match:
        reason = "No excluded terms found." if not include_required else "Included terms present and no excluded terms found."
    else:
        reason = "Found excluded terms." if exclude_hits else ("No include terms found." if include_required else "Blocked by policy.")

    res = {
        "ok": True,
        "source": "local",
        "match": match,
        "include_hits": include_hits,
        "exclude_hits": exclude_hits,
        "reason": reason,
    }
    if want_debug:
        res["debug"] = {
            "text_norm": text_norm,
            "include_any_norm": include_any,
            "exclude_any_norm": exclude_any,
        }
    return res


# ---------- Gemini helper ----------
def _gemini_check(text, include_any, exclude_any):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or genai is None:
        return None
    try:
        genai.configure(api_key=api_key)

        require_include = bool(_norm_terms(include_any))

        system_instruction = (
            "You are a precise content filter. Decide if the TEXT matches the rule:\n"
            "- NORMAL: MATCH = (at least one INCLUDE_ANY is semantically present) AND (no EXCLUDE_ANY present).\n"
            "- EXCLUDE-ONLY (REQUIRE_INCLUDE=false): ignore include; MATCH = (no EXCLUDE_ANY present).\n"
            "- Consider paraphrases.\n"
            "Return STRICT JSON ONLY: {\"match\":bool,\"include_hits\":[],\"exclude_hits\":[],\"reason\":str}"
        )
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=system_instruction,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0, "top_p": 0.0, "top_k": 1
            },
        )
        payload = {
            "REQUIRE_INCLUDE": require_include,
            "INCLUDE_ANY": _norm_terms(include_any),
            "EXCLUDE_ANY": _norm_terms(exclude_any),
            "TEXT": text,
        }
        result = model.generate_content(json.dumps(payload, ensure_ascii=False))
        out_text = getattr(result, "text", "") or ""
        try:
            parsed = json.loads(out_text)
        except Exception:
            # minimal fallback to first JSON
            start = out_text.find("{"); parsed = None
            while start != -1 and parsed is None:
                depth = 0
                for i, ch in enumerate(out_text[start:], start):
                    if ch == "{": depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                parsed = json.loads(out_text[start:i+1])
                            except Exception:
                                parsed = None
                            break
                start = out_text.find("{", start+1)
            if parsed is None:
                return {"ok": False, "source": "gemini", "error": "Non-JSON response from Gemini"}

        match = bool(parsed.get("match"))
        include_hits = [str(x) for x in (parsed.get("include_hits") or []) if isinstance(x, (str, int, float, str))]
        exclude_hits = [str(x) for x in (parsed.get("exclude_hits") or []) if isinstance(x, (str, int, float, str))]
        reason = parsed.get("reason") or ("Match" if match else "No match")

        # ---- Heuristic fallback to ensure semantic blocking for recipes ----
        t = re.sub(r"\s+", " ", (text or "")).lower()
        cues = []
        if re.search(r"\bpreheat(?:\s+the)?\s+oven\b", t): cues.append("preheat the oven")
        if re.search(r"\bbake\s+(?:at|for)\b", t):         cues.append("bake at/for")
        if re.search(r"\b\d{2,3}\s*°\s*[cf]\b", t):        cues.append("temperature °C/°F")
        if re.search(r"\b\d+\s*(?:min|minutes|hr|hrs|hours)\b", t): cues.append("time in minutes/hours")
        if re.search(r"\bstep[-\s]?by[-\s]?step\b", t):    cues.append("step by step")
        if re.search(r"\bguide\b", t):                     cues.append("guide")

        if cues:
            exclude_hits = sorted(set((exclude_hits or []) + cues))
            include_ok = (not require_include) or bool(include_hits)
            match = include_ok and not bool(exclude_hits)
            if not match:
                reason = "Recipe/how-to cues detected."

        return {
            "ok": True,
            "source": "gemini",
            "match": match,
            "include_hits": include_hits,
            "exclude_hits": exclude_hits,
            "reason": reason,
        }
    except Exception as e:
        logger.exception("Gemini check failed")
        return {"ok": False, "source": "gemini", "error": str(e)}





# ---------- Routes ----------
@app.get("/health")
def health():
    try:
        return jsonify({
            "status": "ok",
            "model": MODEL_NAME,
            "gemini_available": bool(os.getenv("GEMINI_API_KEY") and genai)
        }), 200
    except Exception as e:
        logger.exception("/health failed")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.post("/detect")
def detect():
    """
    JSON:
      text: str
      include_any: list[str]
      exclude_any: list[str]
      mode: "auto" | "gemini" | "local"   (default auto)
      require_include: bool               (default: include_any != [])
      debug: bool                         (optional: include local debug info)
    """
    try:
        data = request.get_json(silent=True) or {}
        text = data.get("text") or ""
        include_any = data.get("include_any") or []
        exclude_any = data.get("exclude_any") or []
        mode = (data.get("mode") or "auto").lower()
        include_required = data.get("require_include")
        debug_req = bool(data.get("debug", False))

        if include_required is None:
            include_required = bool(include_any)

        if mode not in ("auto", "gemini", "local"):
            mode = "auto"

        # PASS 1: LOCAL
        local_res = _local_keyword_check(
            text, include_any, exclude_any,
            include_required=include_required,
            want_debug=debug_req
        )
        if not local_res.get("match", False):
            local_res["source"] = "local-first"
            return jsonify(local_res), 200

        if mode == "local":
            local_res["source"] = "local-first"
            return jsonify(local_res), 200

        # PASS 2: GEMINI (optional)
        g = _gemini_check(text, include_any, exclude_any) if mode in ("gemini", "auto") else None

        if g and g.get("ok"):
            final_include = sorted(set((g.get("include_hits") or []) + (local_res.get("include_hits") or [])))
            final_exclude = sorted(set((g.get("exclude_hits") or []) + (local_res.get("exclude_hits") or [])))
            include_condition = (bool(final_include) or (not include_required))
            match = include_condition and not bool(final_exclude)
            reason = g.get("reason") or local_res.get("reason") or ("Allowed" if match else "Blocked")
            if final_exclude and "exclude" not in (reason or "").lower():
                reason = "Found excluded terms: " + ", ".join(final_exclude)
            resp = {
                "ok": True,
                "source": "local->gemini",
                "match": match,
                "include_hits": final_include,
                "exclude_hits": final_exclude,
                "reason": reason
            }
            if debug_req and "debug" in local_res:
                resp["debug"] = local_res["debug"]
            return jsonify(resp), 200

        # Gemini failed/unavailable -> allow by local pass (already allowed)
        if g and g.get("error"):
            local_res["gemini_error"] = str(g.get("error"))
            local_res["reason"] = "Gemini error — allowed by local pass. " + local_res.get("reason", "")
        elif not g:
            local_res["reason"] = "Gemini unavailable — allowed by local pass. " + local_res.get("reason", "")
        local_res["source"] = "local-only"
        return jsonify(local_res), 200

    except Exception as e:
        logger.exception("/detect failed")
        return jsonify({"ok": False, "error": str(e)}), 400


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    logger.exception("Unhandled exception")
    return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    logger.info("Starting message-detector on %s:%s (debug=%s)", HOST, PORT, DEBUG)
    app.run(host=HOST, port=PORT, debug=DEBUG)

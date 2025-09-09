# test/test_gemini_config_chat.py
import os
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict

import pytest
import requests

# =========================
# Docker / Server config
# =========================
DOCKER_COMPOSE_FILE = "docker-compose.yml"
SERVICE_NAME = "main-server"
BASE_URL = "http://localhost:5000"
HEALTH_URL = f"{BASE_URL}/health"

# =========================
# Artifacts
# =========================
START_TS = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
ARTIFACT_DIR = Path("test_artifacts") / START_TS
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# Compose helpers
# =========================
def _compose(*args, check=True, capture_output=False):
    return subprocess.run(
        ["docker-compose", "-f", DOCKER_COMPOSE_FILE, *args],
        check=check,
        capture_output=capture_output,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

def _start_server_process_in_container():
    print("[SETUP] Starting server inside container…")
    start_script = r'''
set -eu
PY="$(command -v python || true)"; [ -z "$PY" ] && PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "ERROR: no python/python3 in PATH" >&2; exit 1; }

if [ -f /app/src/server.py ]; then
  MODPATH="/app/src"
elif [ -f /app/server.py ]; then
  MODPATH="/app"
elif [ -f /app/app.py ]; then
  MODPATH="/app"; export TARGET="app"
elif [ -f /app/main.py ]; then
  MODPATH="/app"; export TARGET="main"
else
  echo "ERROR: server entry not found under /app/src or /app" >&2
  ls -la /app || true
  ls -la /app/src || true
  exit 1
fi

: > /tmp/server.log || true
nohup "$PY" -c "import sys; sys.path.insert(0,'$MODPATH'); import ${TARGET:-server} as server; server.socketio.run(server.app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)" \
  >/tmp/server.log 2>&1 & echo $! >/tmp/server.pid
'''
    subprocess.run(
        ["docker-compose", "-f", DOCKER_COMPOSE_FILE, "exec", "-T",
         SERVICE_NAME, "sh", "-lc", start_script],
        check=False
    )
    print("[SETUP] Server start command issued.")


def _wait_for_health(timeout=90):
    print("[SETUP] Waiting for /health endpoint…")
    start = time.time()
    last = None
    while time.time() - start < timeout:
        try:
            r = requests.get(HEALTH_URL, timeout=2)
            if r.status_code == 200 and r.json().get("status") == "ok":
                print("[SETUP] Server is healthy.")
                return
            last = f"{r.status_code} {r.text}"
        except Exception as e:
            last = str(e)
        time.sleep(1)
    logs = _compose("logs", SERVICE_NAME, capture_output=True).stdout
    raise RuntimeError(f"Health failed: {last}\n---- logs ({SERVICE_NAME}) ----\n{logs}")

# =========================
# Pytest fixture
# =========================
@pytest.fixture(scope="session", autouse=True)
def bring_up_stack():
    print("[SETUP] docker-compose up --build -d …")
    _compose("up", "--build", "-d")
    _start_server_process_in_container()
    _wait_for_health(90)
    yield
    print("[TEARDOWN] Collecting logs + docker-compose down …")
    try:
        logs = {
            "compose_all": _compose("logs", "-t", "--no-color", capture_output=True).stdout,
            "compose_main-server": _compose("logs", "-t", "--no-color", "main-server", capture_output=True).stdout,
        }
        (ARTIFACT_DIR / "compose_logs_config.json").write_text(
            json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        _compose("down")
    print("[TEARDOWN] Done.")

# =========================
# Load config
# =========================
def _load_config() -> dict:
    cfg_path = os.environ.get("CHAT_CONFIG_PATH", "test/chat_config.json")
    print(f"[CONFIG] Loading {cfg_path} …")
    if not Path(cfg_path).exists():
        print("[CONFIG] Not found. Using defaults.")
        return {
            "category": "bakery",
            "total_turns": 12,
            "users": ["user0", "user1"],
            "personas": {"user0": "friendly baker", "user1": "curious customer"},
            "seed": [
                "Hey, did you try the new sourdough loaf today?",
                "Yes! The crust was great—how did you tweak the hydration?"
            ]
        }
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # normalize "backery" -> "bakery"
    cat = (data.get("category") or "bakery").strip().lower()
    if cat == "backery":
        cat = "bakery"
    data["category"] = cat

    # basic defaults if missing
    data.setdefault("total_turns", 12)
    data.setdefault("users", ["user0", "user1"])
    data.setdefault("personas", {})
    data.setdefault("seed", [])

    # enforce minimal requirements
    if len(data["users"]) < 2:
        data["users"] = ["user0", "user1"]
    if data["total_turns"] < len(data["seed"]):
        data["total_turns"] = len(data["seed"])
    return data

# =========================
# The config-driven chat test
# =========================
def test_gemini_config_chat(bring_up_stack):
    # Deps
    try:
        import socketio
    except ImportError:
        pytest.skip("Install: pip install python-socketio websocket-client")
    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Schema, Type
    except Exception as e:
        pytest.skip(f"Install: pip install google-genai ({e})")

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("Set GOOGLE_API_KEY to run this test")

    cfg = _load_config()
    category: str = cfg["category"]
    users: List[str] = cfg["users"]
    total_turns: int = int(cfg["total_turns"])
    personas: Dict[str, str] = cfg.get("personas", {})
    seed_lines: List[str] = cfg.get("seed", [])

    print(f"[TEST] Category: {category}")
    print(f"[TEST] Users: {users}")
    print(f"[TEST] Turns: {total_turns}")

    # ---- Gemini setup
    client_genai = genai.Client(api_key=api_key)
    MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

    reply_schema = Schema(
        type=Type.OBJECT,
        properties={"reply": Schema(type=Type.STRING)},
        required=["reply"]
    )

    # Build a category-specific system instruction
    SYSTEM = (
        f"You write the NEXT single message in an active '{category}' conversation.\n"
        "Constraints:\n"
        f"• Stay strictly on the '{category}' topic; friendly; no emojis.\n"
        "• 7–18 words, one sentence, no newlines.\n"
        "• Reflect the user's persona naturally (do not say 'persona').\n"
        "• Avoid repeating earlier lines; add something fresh and relevant.\n"
        "• Prefer conversational phrasing; avoid heavy stats unless asked."
    )

    def persona_for(user: str) -> str:
        # fallback persona if not provided
        return personas.get(user, "friendly conversationalist")

    def next_reply(history_text: str, persona: str) -> str:
        cfg_gc = GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=reply_schema,
        )
        prompt = (
            f"Persona: {persona}\n\n"
            "Conversation so far:\n"
            f"{history_text}\n\n"
            "Write ONLY the next user's message."
        )
        for _ in range(6):
            try:
                resp = client_genai.models.generate_content(
                    model=MODEL,
                    contents=[{"role": "user", "parts": [{"text": prompt[:6000]}]}],
                    config=cfg_gc
                )
                data = resp.parsed or {}
                msg = (data.get("reply") or "").strip()
                msg = " ".join(msg.split())
                if 7 <= len(msg.split()) <= 18 and "\n" not in msg:
                    return msg
            except Exception:
                time.sleep(0.2)
        return f"Quick thought on {category}: what do you think?"

    # ---- Socket clients
    class Client:
        def __init__(self, name, room):
            self.name = name
            self.room = room
            self.err = []
            import socketio
            self.sio = socketio.Client(reconnection=False)

            @self.sio.on("error")
            def on_err(p):
                self.err.append(p)

        def connect(self):
            self.sio.connect(BASE_URL, wait=True, wait_timeout=15, transports=["polling"])

        def join(self):
            self.sio.emit("join", {"name": self.name, "room": self.room})

        def send(self, body):
            self.sio.emit("chat", {"body": body})

        def disconnect(self):
            try:
                self.sio.emit("leave", {})
                self.sio.disconnect()
            except Exception:
                pass

    room = f"room-{category}-{int(time.time())}"
    print(f"[TEST] Using room {room}")

    # Connect & join all users
    clients = [Client(u, room) for u in users]
    for c in clients:
        print(f"[STEP] Connecting {c.name} …")
        c.connect()
    for c in clients:
        print(f"[STEP] {c.name} joining room …")
        c.join()

    # Build transcript with seed or default seed
    transcript_lines: List[str] = []
    if not seed_lines:
        if category == "bakery":
            seed_lines = [
                "Tried the new sourdough—great crust, open crumb; how's your starter?",
                "I fed it yesterday; thinking longer autolyse—would that help the chew?"
            ]
        else:
            seed_lines = [
                f"Anyone into {category} today? I’ve got a quick question.",
                f"Sure, what about {category} are you curious about?"
            ]

    # Ensure we have at least one seed and send them with the first users
    seed_pairs = []
    for i, text in enumerate(seed_lines[:min(len(users), 2)]):
        seed_pairs.append((users[i], text))

    print("[STEP] Sending seed messages…")
    for speaker, text in seed_pairs:
        print(f"  {speaker} -> {text}")
        clients[users.index(speaker)].send(text)
        transcript_lines.append(f"{speaker}: {text}")

    # Helper: wait until a specific message is persisted
    def wait_persist(author: str, body: str, limit=400, tries=60, sleep=0.1):
        for attempt in range(tries):
            r = requests.get(f"{BASE_URL}/rooms/{room}/messages?limit={limit}", timeout=5)
            if r.status_code == 200:
                data = r.json()
                found = next((m for m in data if isinstance(m, dict)
                              and m.get("from") == author and m.get("body") == body and m.get("ts")), None)
                if found:
                    if attempt > 0:
                        print(f"[PERSIST] {author} found after {attempt} polls")
                    return True
            time.sleep(sleep)
        return False

    # Ensure seeds are persisted
    for speaker, text in seed_pairs:
        assert wait_persist(speaker, text), f"Seed by {speaker} not persisted"

    # Generate remaining turns round-robin over users
    turns_so_far = len(seed_pairs)
    print("[STEP] Generating replies (round-robin) …")
    while turns_so_far < total_turns:
        speaker = users[turns_so_far % len(users)]
        persona = persona_for(speaker)
        history_text = "\n".join(transcript_lines[-24:])
        reply = next_reply(history_text, persona)
        print(f"  {speaker} ({persona}) -> {reply}")
        clients[users.index(speaker)].send(reply)
        assert wait_persist(speaker, reply), f"{speaker} message not persisted"
        transcript_lines.append(f"{speaker}: {reply}")
        turns_so_far += 1

    # Verify count
    print("[VERIFY] Counting persisted user messages …")
    r = requests.get(f"{BASE_URL}/rooms/{room}/messages?limit=500", timeout=5)
    r.raise_for_status()
    persisted_users = [m for m in r.json() if isinstance(m, dict) and str(m.get("from", "")).startswith("user")]
    assert len(persisted_users) >= len(transcript_lines), \
        f"Expected >= {len(transcript_lines)} user messages, got {len(persisted_users)}"

    # Save artifact
    out = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "room": room,
        "category": category,
        "users": users,
        "turns": len(transcript_lines),
        "transcript": transcript_lines,
        "note": "Config-driven chat; Gemini generates each turn from the running history."
    }
    out_path = ARTIFACT_DIR / f"config_chat_{category}_{room}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] Transcript saved to {out_path.resolve()}")

    # Disconnect
    for c in clients:
        c.disconnect()
    print("[DONE] Users disconnected.")

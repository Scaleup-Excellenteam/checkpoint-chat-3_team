# server.py
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from collections import defaultdict
from pathlib import Path
from datetime import datetime, timezone
import threading
import json
import os

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# -------------------------
# Config (simple constants)
# -------------------------
MAX_LEN = 2048
MAX_MESSAGES_PER_ROOM = 1000
STATE_PATH = Path("data/state.json")

# -------------------------
# In-memory runtime state
# -------------------------
clients = {}  # sid -> {"name": str, "room": str}

# Persistent state (rooms + messages), guarded by a lock
state_lock = threading.Lock()
state = {
    "rooms": {},      # room -> {"members": [names], "created_at": iso, "last_updated": iso}
    "messages": {}    # room -> [{"from": str, "body": str, "ts": iso}, ...]
}

# -------------------------
# Persistence helpers
# -------------------------
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+03:00", "Z")

def _safe_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_state() -> None:
    """Load from disk; if not exists, keep the defaults.
       We always reset 'members' (active connections) on startup."""
    global state
    if STATE_PATH.exists():
        try:
            with STATE_PATH.open("r", encoding="utf-8") as f:
                on_disk = json.load(f)
            # basic shape check
            if isinstance(on_disk, dict):
                state.update(on_disk)
        except Exception:
            # if corrupted, keep defaults
            pass
    # Ensure required keys exist
    state.setdefault("rooms", {})
    state.setdefault("messages", {})
    # Active members should start empty after restart
    for room, meta in state["rooms"].items():
        meta["members"] = []

def save_state() -> None:
    with state_lock:
        _safe_write_json(STATE_PATH, state)

def ensure_room(room: str) -> None:
    with state_lock:
        if room not in state["rooms"]:
            now = _utc_now()
            state["rooms"][room] = {
                "members": [],
                "created_at": now,
                "last_updated": now,
            }
        if room not in state["messages"]:
            state["messages"][room] = []

def add_member(room: str, name: str) -> None:
    ensure_room(room)
    with state_lock:
        members = state["rooms"][room]["members"]
        if name not in members:
            members.append(name)
        state["rooms"][room]["last_updated"] = _utc_now()
    save_state()

def remove_member(room: str, name: str) -> None:
    ensure_room(room)
    with state_lock:
        members = state["rooms"][room]["members"]
        if name in members:
            members.remove(name)
        state["rooms"][room]["last_updated"] = _utc_now()
    save_state()

def append_message(room: str, sender: str, body: str) -> dict:
    ensure_room(room)
    msg = {"from": sender, "body": body, "ts": _utc_now()}
    with state_lock:
        bucket = state["messages"][room]
        bucket.append(msg)
        # keep only the last N messages
        if len(bucket) > MAX_MESSAGES_PER_ROOM:
            del bucket[: len(bucket) - MAX_MESSAGES_PER_ROOM]
        state["rooms"][room]["last_updated"] = msg["ts"]
    save_state()
    return msg

# -------------------------
# Startup: load persisted state
# -------------------------
load_state()

# -------------------------
# REST — inspect state
# -------------------------
@app.get("/health")
def health():
    return jsonify(status="ok", ts=_utc_now())

@app.get("/rooms")
def rooms():
    # return counts based on current 'members' list
    with state_lock:
        return jsonify({r: len(meta.get("members", [])) for r, meta in state["rooms"].items()})

@app.get("/rooms/<room>")
def room_info(room: str):
    ensure_room(room)
    with state_lock:
        meta = state["rooms"][room]
        msg_count = len(state["messages"].get(room, []))
        out = {
            "name": room,
            "members": list(meta.get("members", [])),
            "created_at": meta.get("created_at"),
            "last_updated": meta.get("last_updated"),
            "message_count": msg_count,
        }
    return jsonify(out)

@app.get("/rooms/<room>/messages")
def room_messages(room: str):
    limit = max(1, min(5000, int(request.args.get("limit", 50))))
    ensure_room(room)
    with state_lock:
        msgs = list(state["messages"].get(room, []))
    # newest first
    result = list(reversed(msgs))[:limit]
    return jsonify(result)

# -------------------------
# Socket.IO events
# -------------------------
@socketio.event
def connect():
    emit("system", {"msg": "connected"})

@socketio.on("join")
def on_join(data):
    name = (data or {}).get("name", "guest")
    room = (data or {}).get("room", "general")

    # If this sid was already in another room, leave it
    prev = clients.get(request.sid)
    if prev and prev["room"] != room:
        leave_room(prev["room"])
        remove_member(prev["room"], prev["name"])

    join_room(room)
    clients[request.sid] = {"name": name, "room": room}
    add_member(room, name)

    # Persist a "system" message for history context
    sys_msg = append_message(room, "server", f"{name} joined {room}")
    emit("system", {"msg": sys_msg["body"]}, room=room)

@socketio.on("chat")
def on_chat(data):
    body = (data or {}).get("body", "").strip()
    if not body:
        emit("error", {"reason": "empty message"})
        return
    if len(body) > MAX_LEN:
        emit("error", {"reason": "message too long"})
        return

    info = clients.get(request.sid, {"name": "guest", "room": "general"})
    room, sender = info["room"], info["name"]

    # Persist message, then broadcast
    msg = append_message(room, sender, body)
    emit("chat", {"from": sender, "room": room, "body": body, "ts": msg["ts"]}, room=room)

@socketio.on("leave")
def on_leave(_):
    info = clients.get(request.sid)
    if info:
        leave_room(info["room"])
        remove_member(info["room"], info["name"])
        sys_msg = append_message(info["room"], "server", f"{info['name']} left")
        emit("system", {"msg": sys_msg["body"]}, room=info["room"])
        clients.pop(request.sid, None)

@socketio.event
def disconnect():
    info = clients.pop(request.sid, None)
    if info:
        leave_room(info["room"])
        remove_member(info["room"], info["name"])
        append_message(info["room"], "server", f"{info['name']} disconnected")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)

# server.py
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from collections import defaultdict
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

MAX_LEN = 2048
room_counts = defaultdict(int)       # room -> member count
clients = {}                         # sid -> {"name": str, "room": str}

@app.get("/health")
def health():
    return jsonify(status="ok", ts=int(time.time()))

@app.get("/rooms")
def rooms():
    return jsonify(room_counts)

@socketio.event
def connect():
    # client connected; will "join" with details next
    emit("system", {"msg": "connected"})

@socketio.on("join")
def on_join(data):
    name = (data or {}).get("name", "guest")
    room = (data or {}).get("room", "general")
    join_room(room)
    clients[request.sid] = {"name": name, "room": room}
    room_counts[room] += 1
    emit("system", {"msg": f"{name} joined {room}"}, room=room)

@socketio.on("chat")
def on_chat(data):
    # expected payload: {"body": "..."}
    body = (data or {}).get("body", "").strip()
    if not body:
        emit("error", {"reason": "empty message"})
        return
    if len(body) > MAX_LEN:
        emit("error", {"reason": "message too long"})
        return

    info = clients.get(request.sid, {"name": "guest", "room": "general"})
    emit("chat", {"from": info["name"], "room": info["room"], "body": body}, room=info["room"])

@socketio.on("leave")
def on_leave(_):
    info = clients.get(request.sid)
    if info:
        leave_room(info["room"])
        room_counts[info["room"]] = max(0, room_counts[info["room"]] - 1)
        emit("system", {"msg": f"{info['name']} left {info['room']}"}, room=info["room"])
        clients.pop(request.sid, None)

@socketio.event
def disconnect():
    info = clients.pop(request.sid, None)
    if info:
        room = info["room"]
        room_counts[room] = max(0, room_counts[room] - 1)
        emit("system", {"msg": f"{info['name']} disconnected"}, room=room)

if __name__ == "__main__":
    # For higher concurrency later, consider installing 'eventlet' and running socketio.run(..., async_mode="eventlet")
    socketio.run(app, host="0.0.0.0", port=5000)

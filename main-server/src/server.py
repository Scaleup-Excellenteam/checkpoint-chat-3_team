# server.py
from flask import Flask, jsonify, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from utils import load_config, utc_now
from state_manager import StateManager
from url_det import analyze_message

# Load configuration
config = load_config()

# Initialize Flask app and SocketIO
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins=config['server']['cors_origins'])

# Configuration
MAX_LEN = config['messages']['max_length']
URL_DETECTION_ENABLED = config['url_detection']['enabled']
LOG_URL_DETECTIONS = config['url_detection']['log_detections']

# State management
state_manager = StateManager(
    config['storage']['state_file'],
    config['messages']['max_per_room']
)

# Active clients
clients = {}  # sid -> {"name": str, "room": str}

# -------------------------
# REST API endpoints
# -------------------------
@app.get("/health")
def health():
    return jsonify(status="ok", ts=utc_now())

@app.get("/rooms")
def rooms():
    return jsonify(state_manager.get_rooms())

@app.get("/rooms/<room>")
def room_info(room: str):
    return jsonify(state_manager.get_room_info(room))

@app.get("/rooms/<room>/messages")
def room_messages(room: str):
    limit = max(1, min(5000, int(request.args.get("limit", 50))))
    return jsonify(state_manager.get_room_messages(room, limit))

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
        state_manager.remove_member(prev["room"], prev["name"])

    join_room(room)
    clients[request.sid] = {"name": name, "room": room}
    state_manager.add_member(room, name)

    # Persist a "system" message for history context
    sys_msg = state_manager.append_message(room, "server", f"{name} joined {room}")
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

    # Analyze message for URLs
    if URL_DETECTION_ENABLED:
        url_analysis = analyze_message(body)
        if url_analysis:
            for result in url_analysis:
                if result['valid']:
                    threat_level = result.get('threat_level', 'UNKNOWN')
                    threat_score = result.get('threat_score', 0)
                    should_block = result.get('should_block', False)
                    
                    if LOG_URL_DETECTIONS:
                        print(f"1. URL detected: {result['url']}")
                        print(f"2. Threat Level: {threat_level} ({threat_score:.1f}%)")
                        
                        detailed_cats = result.get('detailed_categories', {})
                        if detailed_cats:
                            print("3. Categories:")
                            for category in detailed_cats.values():
                                print(f"   - {category}")
                        else:
                            print("3. Categories: None")
                        print("---")
                    
                    # Block URLs based on threat level
                    if should_block:
                        emit("error", {"reason": f"Message blocked: {threat_level} threat level URL detected ({result['url']})"})
                        return
                        
                elif LOG_URL_DETECTIONS:
                    print(f"1. URL detected: {result['url']}")
                    print(f"2. Status: ERROR - {result.get('error')}")
                    print("3. Categories: Unable to analyze")
                    print("---")

    # Persist message, then broadcast
    msg = state_manager.append_message(room, sender, body)
    emit("chat", {"from": sender, "room": room, "body": body, "ts": msg["ts"]}, room=room)

@socketio.on("leave")
def on_leave(_):
    info = clients.get(request.sid)
    if info:
        leave_room(info["room"])
        state_manager.remove_member(info["room"], info["name"])
        sys_msg = state_manager.append_message(info["room"], "server", f"{info['name']} left")
        emit("system", {"msg": sys_msg["body"]}, room=info["room"])
        clients.pop(request.sid, None)

@socketio.event
def disconnect():
    info = clients.pop(request.sid, None)
    if info:
        leave_room(info["room"])
        state_manager.remove_member(info["room"], info["name"])
        state_manager.append_message(info["room"], "server", f"{info['name']} disconnected")

if __name__ == "__main__":
    socketio.run(app, 
                host=config['server']['host'], 
                port=config['server']['port'],
                debug=config['server']['debug'])

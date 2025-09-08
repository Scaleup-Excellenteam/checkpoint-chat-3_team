# client.py
import socketio
import sys
import json
import os
from datetime import datetime

# Load configuration
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

config = load_config()

# Command line args override config
ROOM = sys.argv[1] if len(sys.argv) > 1 else config['client']['default_room']
NAME = sys.argv[2] if len(sys.argv) > 2 else config['client']['default_name']
SERVER_URL = config['server']['url']
TIMEOUT = config['connection']['timeout']
TRANSPORTS = config['connection']['transports']

sio = socketio.Client(logger=config['logging']['enabled'], engineio_logger=config['logging']['enabled'])

@sio.event
def connect():
    sio.emit("join", {"room": ROOM, "name": NAME})

@sio.on("system")
def on_system(data):
    msg = data.get("msg", "")
    if f"{NAME} joined {ROOM}" in msg:
        # Show own join message
        print(f"Joined room: {ROOM}")
    elif "joined" in msg or "left" in msg or "disconnected" in msg:
        # Show other users' join/leave messages
        print(f"[system] {msg}")

@sio.on("chat")
def on_chat(data):
    print(f"[{data.get('room')}] {data.get('from')}: {data.get('body')}")

@sio.on("error")
def on_error(data):
    print("[error]", data.get("reason"))

@sio.event
def disconnect():
    pass

def log_message(msg):
    if config['logging']['show_timestamps']:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {msg}")
    else:
        print(msg)

if __name__ == "__main__":
    try:
        sio.connect(SERVER_URL, 
                   wait_timeout=TIMEOUT,
                   transports=TRANSPORTS)
        
        while True:
            msg = input("> ")
            if msg.strip().lower() in ("/q", "/quit", "/exit"):
                sio.emit("leave", {})
                break
            sio.emit("chat", {"body": msg})
    except Exception as e:
        log_message(f"Connection failed: {e}")
    finally:
        sio.disconnect()

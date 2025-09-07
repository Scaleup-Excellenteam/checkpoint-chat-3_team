# client.py
import socketio
import sys

ROOM = sys.argv[1] if len(sys.argv) > 1 else "general"
NAME = sys.argv[2] if len(sys.argv) > 2 else "cli"

sio = socketio.Client()

@sio.event
def connect():
    print("[client] connected")
    sio.emit("join", {"room": ROOM, "name": NAME})

@sio.on("system")
def on_system(data):
    print("[system]", data.get("msg"))

@sio.on("chat")
def on_chat(data):
    print(f"[{data.get('room')}] {data.get('from')}: {data.get('body')}")

@sio.on("error")
def on_error(data):
    print("[error]", data.get("reason"))

@sio.event
def disconnect():
    print("[client] disconnected")

if __name__ == "__main__":
    # use 'http://main-server:5000' if running in Docker with a service named main-server
    sio.connect("http://11.7.16.1:5000")
    try:
        while True:
            msg = input("> ")
            if msg.strip().lower() in ("/q", "/quit", "/exit"):
                sio.emit("leave", {})
                break
            sio.emit("chat", {"body": msg})
    finally:
        sio.disconnect()

from flask import Flask
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on('message')
def handle_message(data):
    print(f"Received message: {data}")
    emit('response', f"Server received: {data}")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
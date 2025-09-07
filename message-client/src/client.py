import socketio
import time

sio = socketio.Client()

@sio.on('response')
def on_response(data):
    print(f"Server response: {data}")

if __name__ == '__main__':
    sio.connect('http://main-server:5000')
    
    while True:
        message = input("Enter message: ")
        sio.emit('message', message)
        time.sleep(1)
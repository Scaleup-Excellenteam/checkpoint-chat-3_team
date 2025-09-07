import requests
import time

def send_message():
    try:
        response = requests.get('http://main-server:5000')
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    while True:
        send_message()
        time.sleep(5)
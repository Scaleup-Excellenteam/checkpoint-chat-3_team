import requests
import time
import json
from datetime import datetime

# Configuration
SERVERS = [
    {"name": "main-server", "url": "http://main-server:5000/health"}
]
CHECK_INTERVAL = 2  # seconds

def check_server(server):
    try:
        response = requests.get(server["url"], timeout=5)
        if response.status_code == 200:
            return {"status": "UP", "response_time": response.elapsed.total_seconds()}
        else:
            return {"status": "DOWN", "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"status": "DOWN", "error": str(e)}

def log_status(server_name, result):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = result["status"]
    if status == "UP":
        print(f"[{timestamp}] {server_name}: {status} ({result['response_time']:.3f}s)")
    else:
        print(f"[{timestamp}] {server_name}: {status} - {result['error']}")

def main():
    print("Watchdog started - monitoring servers...")
    
    while True:
        for server in SERVERS:
            result = check_server(server)
            log_status(server["name"], result)
        
        print(f"Next check in {CHECK_INTERVAL} seconds...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
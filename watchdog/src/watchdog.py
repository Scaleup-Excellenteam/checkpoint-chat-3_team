import requests
import time
import json
from datetime import datetime
import os

# Load configuration
def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(config_path, 'r') as f:
        return json.load(f)

config = load_config()
CHECK_INTERVAL = config['check_interval']
TIMEOUT = config['timeout']
RETRY_ATTEMPTS = config['retry_attempts']
SERVERS = [s for s in config['servers'] if s['enabled']]

def check_server(server):
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = requests.get(server["url"], timeout=TIMEOUT)
            if response.status_code == 200:
                return {"status": "UP", "response_time": response.elapsed.total_seconds()}
            else:
                return {"status": "DOWN", "error": f"HTTP {response.status_code}"}
        except Exception as e:
            if attempt == RETRY_ATTEMPTS - 1:
                return {"status": "DOWN", "error": str(e)}
            time.sleep(1)  # Wait 1 second between retries

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
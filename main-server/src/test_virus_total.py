import requests
import base64
import json

# API KEY
API_KEY = "70fb8199e7a8fca7cfe691e979bd7c88a4623d25346d23b777420e696c3893e5"

def test_url(url):
    print(f"Testing URL: {url}")
    
    # Encode URL to base64
    url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")
    
    headers = {
        "x-apikey": API_KEY
    }
    
    try:
        response = requests.get(
            f"https://www.virustotal.com/api/v3/urls/{url_id}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            
            print("\n=== FULL RESPONSE ===")
            print(json.dumps(data, indent=2))
            
            print("\n=== ANALYSIS RESULTS ===")
            scans = data["data"]["attributes"].get("last_analysis_results", {})
            print(f"Found {len(scans)} scan results")
            
            for engine, result in list(scans.items())[:10]:  # Show first 10
                print(f"{engine}:")
                print(f"  category: {result.get('category')}")
                print(f"  result: {result.get('result')}")
                print(f"  method: {result.get('method')}")
                print()
                
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    test_url("https://www.youtube.com/")
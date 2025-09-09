import requests
import base64
from urlextract import URLExtract
import time
from utils import load_config

# Load VirusTotal API key from configuration
config = load_config()
API_KEY = config['url_detection']['virustotal_api_key']

# URL Cache - stores results to avoid duplicate API calls
# Format: {url: {"result": {...}, "timestamp": time, "expires": time}}
url_cache = {}
CACHE_DURATION = 3600  # 1 hour in seconds

def extract_urls(text):
    """Extract URLs from text message using URLExtract library"""
    extractor = URLExtract()
    urls = extractor.find_urls(text)
    
    # Ensure all URLs have protocol
    normalized_urls = []
    for url in urls:
        if not url.startswith(('http://', 'https://')):
            normalized_urls.append(f"http://{url}")
        else:
            normalized_urls.append(url)
    
    return normalized_urls

def is_cache_valid(cache_entry):
    """Check if cache entry is still valid"""
    return time.time() < cache_entry["expires"]

def get_from_cache(url):
    """Get URL result from cache if valid"""
    if url in url_cache and is_cache_valid(url_cache[url]):
        print(f"[CACHE HIT] Using cached result for {url}")
        return url_cache[url]["result"]
    return None

def save_to_cache(url, result):
    """Save URL result to cache"""
    current_time = time.time()
    url_cache[url] = {
        "result": result,
        "timestamp": current_time,
        "expires": current_time + CACHE_DURATION
    }
    print(f"[CACHE SAVE] Cached result for {url}")

def check_url(url):
    """הפונקציה מקבלת URL ובודקת אותו מול VirusTotal"""
    # Check cache first
    cached_result = get_from_cache(url)
    if cached_result:
        return cached_result
    
    # צריך לקודד את ה-URL ל-base64 לפי הפורמט של VirusTotal
    url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")

    headers = {
        "x-apikey": API_KEY
    }

    try:
        print(f"[API CALL] Checking {url} with VirusTotal")
        # שולחים בקשה ל-API
        response = requests.get(
            f"https://www.virustotal.com/api/v3/urls/{url_id}",
            headers=headers,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            stats = data["data"]["attributes"]["last_analysis_stats"]
            categories = data["data"]["attributes"].get("categories", {})
            
            # Get detailed categories from VirusTotal categories field
            detailed_categories = data["data"]["attributes"].get("categories", {})
            
            result = {
                "url": url,
                "valid": True,
                "detection_stats": stats,
                "categories": list(categories.keys()) if categories else ["unknown"],
                "detailed_categories": detailed_categories,
                "malicious": stats.get("malicious", 0) > 0
            }
            
            # Save to cache
            save_to_cache(url, result)
            return result
        else:
            result = {
                "url": url,
                "valid": False,
                "error": f"API Error: {response.status_code}"
            }
            # Don't cache errors
            return result
    except Exception as e:
        result = {
            "url": url,
            "valid": False,
            "error": str(e)
        }
        # Don't cache errors
        return result

def analyze_message(message):
    """Main function to analyze message for URLs"""
    urls = extract_urls(message)
    
    if not urls:
        return None
    
    results = []
    for url in urls:
        result = check_url(url)
        results.append(result)
    
    return results
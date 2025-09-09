import requests
import base64
from urlextract import URLExtract
import time
from utils import load_config

# Load VirusTotal API key from configuration
config = load_config()
API_KEY = config['url_detection']['virustotal_api_key']
BLOCK_THREAT_LEVEL = config['url_detection']['block_threat_level']

# Debug: print loaded configuration
print(f"[CONFIG] Block threat level set to: {BLOCK_THREAT_LEVEL}")

# Threat level hierarchy for comparison
THREAT_LEVELS = {
    "CLEAN": 0,
    "SUSPICIOUS": 1,
    "LOW": 2,
    "MEDIUM": 3,
    "HIGH": 4
}

def calculate_threat_level(stats):
    """Calculate threat level based on VirusTotal stats"""
    malicious = stats.get("malicious", 0)
    suspicious = stats.get("suspicious", 0) 
    harmless = stats.get("harmless", 0)
    undetected = stats.get("undetected", 0)
    
    total_engines = malicious + suspicious + harmless + undetected
    
    if total_engines == 0:
        return "UNKNOWN", 0
    
    # Calculate percentages
    malicious_percent = (malicious / total_engines) * 100
    suspicious_percent = (suspicious / total_engines) * 100
    
    # Determine threat level - more sensitive thresholds
    if malicious_percent >= 5:  # 5% or more engines detect as malicious
        return "HIGH", malicious_percent + suspicious_percent
    elif malicious_percent >= 2:  # 2-5% engines detect as malicious
        return "MEDIUM", malicious_percent + suspicious_percent
    elif suspicious_percent >= 10:  # 10% or more engines are suspicious
        return "MEDIUM", malicious_percent + suspicious_percent
    elif malicious_percent > 0 or suspicious_percent >= 5:  # Any malicious or 5%+ suspicious
        return "LOW", malicious_percent + suspicious_percent
    elif suspicious_percent > 0:  # Any suspicious activity
        return "SUSPICIOUS", suspicious_percent
    else:
        return "CLEAN", 0

def should_block_url(threat_level):
    """Check if URL should be blocked based on threat level"""
    url_threat_score = THREAT_LEVELS.get(threat_level, 0)
    block_threshold = THREAT_LEVELS.get(BLOCK_THREAT_LEVEL, 3)
    return url_threat_score >= block_threshold

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
            
            # Calculate threat level
            threat_level, threat_score = calculate_threat_level(stats)
            
            result = {
                "url": url,
                "valid": True,
                "detection_stats": stats,
                "categories": list(categories.keys()) if categories else ["unknown"],
                "detailed_categories": detailed_categories,
                "malicious": stats.get("malicious", 0) > 0,
                "threat_level": threat_level,
                "threat_score": threat_score,
                "should_block": should_block_url(threat_level)
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
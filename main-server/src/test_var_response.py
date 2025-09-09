import requests
import base64
import json
from utils import load_config

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

def test_url_threat_level(url):
    """Test URL and return threat level"""
    config = load_config()
    api_key = config['url_detection']['virustotal_api_key']
    
    # Encode URL to base64
    url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")
    
    headers = {
        "x-apikey": api_key
    }
    
    try:
        print(f"Testing URL: {url}")
        response = requests.get(
            f"https://www.virustotal.com/api/v3/urls/{url_id}",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            stats = data["data"]["attributes"]["last_analysis_stats"]
            
            threat_level, threat_score = calculate_threat_level(stats)
            
            print(f"\n=== THREAT ANALYSIS ===")
            print(f"URL: {url}")
            print(f"Threat Level: {threat_level}")
            print(f"Threat Score: {threat_score:.1f}%")
            print(f"\nDetection Stats:")
            print(f"  Malicious: {stats.get('malicious', 0)}")
            print(f"  Suspicious: {stats.get('suspicious', 0)}")
            print(f"  Harmless: {stats.get('harmless', 0)}")
            print(f"  Undetected: {stats.get('undetected', 0)}")
            
            return {
                "url": url,
                "threat_level": threat_level,
                "threat_score": threat_score,
                "stats": stats
            }
        else:
            print(f"API Error: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    # Test different URLs
    test_urls = [
        "https://www.youtube.com/",
        "https://www.google.com/",
        "https://www.facebook.com/",
        "https://office-activator.com/activate-office-2021-without-product-key-for-free-using-batch-file/"
    ]
    
    for url in test_urls:
        result = test_url_threat_level(url)
        if result:
            print(f"Result: {result['threat_level']} ({result['threat_score']:.1f}%)")
        print("-" * 50)
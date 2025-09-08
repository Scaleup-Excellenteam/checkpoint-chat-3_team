import requests
import base64
from urlextract import URLExtract

# הכנס כאן את ה-API KEY שלך מ-VirusTotal
API_KEY = "70fb8199e7a8fca7cfe691e979bd7c88a4623d25346d23b777420e696c3893e5"

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

def check_url(url):
    """הפונקציה מקבלת URL ובודקת אותו מול VirusTotal"""
    # צריך לקודד את ה-URL ל-base64 לפי הפורמט של VirusTotal
    url_id = base64.urlsafe_b64encode(url.encode()).decode().strip("=")

    headers = {
        "x-apikey": API_KEY
    }

    try:
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
            
            return {
                "url": url,
                "valid": True,
                "detection_stats": stats,
                "categories": list(categories.keys()) if categories else ["unknown"],
                "detailed_categories": detailed_categories,
                "malicious": stats.get("malicious", 0) > 0
            }
        else:
            return {
                "url": url,
                "valid": False,
                "error": f"API Error: {response.status_code}"
            }
    except Exception as e:
        return {
            "url": url,
            "valid": False,
            "error": str(e)
        }

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
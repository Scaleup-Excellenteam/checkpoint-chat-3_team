import json
import re
from pathlib import Path
from utils import load_config

try:
    import google.generativeai as genai
except ImportError:
    genai = None

def load_filter_keywords():
    """Load content filter keywords from JSON file"""
    keywords_path = Path(__file__).parent / "filter_keywords.json"
    if not keywords_path.exists():
        return {}
    
    with open(keywords_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def normalize_text(text):
    """Normalize text for keyword matching"""
    return re.sub(r'\s+', ' ', text.lower().strip())

def calculate_keyword_match_score(text, keywords):
    """Calculate percentage of keyword matches in text"""
    if not keywords:
        return 0
    
    text_norm = normalize_text(text)
    matches = 0
    
    for keyword in keywords:
        keyword_norm = normalize_text(keyword)
        if keyword_norm in text_norm:
            matches += 1
    
    return (matches / len(keywords)) * 100

def check_with_gemini(text, topic, api_key):
    """Ask Gemini if message is related to blocked topic"""
    print(f"[GEMINI DEBUG] genai available: {genai is not None}")
    print(f"[GEMINI DEBUG] api_key provided: {bool(api_key)}")
    
    if not genai:
        print("[GEMINI DEBUG] genai module not available")
        return False, "Gemini module not installed"
    
    if not api_key:
        print("[GEMINI DEBUG] No API key provided")
        return False, "No Gemini API key"
    
    try:
        print(f"[GEMINI DEBUG] Configuring with API key...")
        genai.configure(api_key=api_key)
        
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0
            }
        )
        
        prompt = f"""
        Analyze if this message is related to "{topic}".
        
        Message: "{text}"
        
        Return JSON with:
        - "related": true/false
        - "confidence": 0-100 (percentage)
        - "reason": brief explanation
        
        Consider recipes, instructions, tips, discussions about {topic}.
        """
        
        print(f"[GEMINI DEBUG] Sending request to Gemini...")
        response = model.generate_content(prompt)
        print(f"[GEMINI DEBUG] Gemini response: {response.text}")
        
        result = json.loads(response.text)
        
        return result.get("related", False), result.get("reason", "No reason provided")
        
    except Exception as e:
        print(f"[GEMINI DEBUG] Exception: {str(e)}")
        return False, f"Gemini error: {str(e)}"

def should_block_content(message):
    """Main content filtering function"""
    print(f"[CONTENT FILTER DEBUG] Checking message: '{message}'")
    
    config = load_config()
    content_filter = config.get('content_filter', {})
    
    print(f"[CONTENT FILTER DEBUG] Config loaded: {content_filter}")
    
    if not content_filter.get('enabled', False):
        print("[CONTENT FILTER DEBUG] Content filter is disabled")
        return False, "Content filter disabled"
    
    blocked_topic = content_filter.get('blocked_topic', '')
    if not blocked_topic:
        print("[CONTENT FILTER DEBUG] No blocked topic configured")
        return False, "No blocked topic configured"
    
    # Load keywords for the topic
    filter_keywords = load_filter_keywords()
    topic_keywords = filter_keywords.get(blocked_topic, [])
    
    print(f"[CONTENT FILTER DEBUG] Keywords for '{blocked_topic}': {len(topic_keywords)} keywords")
    
    if not topic_keywords:
        print(f"[CONTENT FILTER DEBUG] No keywords found for topic: {blocked_topic}")
        return False, f"No keywords found for topic: {blocked_topic}"
    
    # Calculate keyword match score
    match_score = calculate_keyword_match_score(message, topic_keywords)
    threshold = content_filter.get('keyword_threshold', 20)  # 20% default
    
    print(f"[CONTENT FILTER] Topic: {blocked_topic}, Match score: {match_score:.1f}%, Threshold: {threshold}%")
    
    if match_score < threshold:
        print(f"[CONTENT FILTER DEBUG] Score too low: {match_score:.1f}% < {threshold}%")
        return False, f"Match score {match_score:.1f}% below threshold {threshold}%"
    
    print(f"[CONTENT FILTER DEBUG] Threshold exceeded, checking with Gemini...")
    
    # If keywords match, check with Gemini
    gemini_api_key = content_filter.get('gemini_api_key')
    if not gemini_api_key:
        print("[CONTENT FILTER DEBUG] No Gemini API key configured")
        return True, f"Keyword threshold exceeded ({match_score:.1f}%), Gemini not configured"
    
    is_related, reason = check_with_gemini(message, blocked_topic, gemini_api_key)
    print(f"[CONTENT FILTER DEBUG] Gemini result: related={is_related}, reason={reason}")
    
    if is_related:
        return True, f"Gemini confirmed: {reason}"
    else:
        return False, f"Gemini rejected: {reason}"

def check_url_categories(categories, blocked_topic, gemini_api_key):
    """Check if URL categories are related to blocked topic"""
    if not categories or not blocked_topic or not gemini_api_key:
        return False, "Missing parameters"
    
    categories_text = " ".join(categories)
    print(f"[URL CATEGORIES] Checking: {categories_text}")
    
    is_related, reason = check_with_gemini(categories_text, blocked_topic, gemini_api_key)
    return is_related, reason
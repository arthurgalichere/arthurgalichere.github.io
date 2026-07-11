import os
import sys
import json
import urllib.request
import urllib.error
import openpyxl
import tempfile
import time  # New import for retry handling

def clean_json_with_llm():
    # ... [Keep your existing file setup code here] ...
    base_dir = os.path.dirname(os.path.abspath(__file__))
    temp_text_path = os.path.join(base_dir, "raw_cv.txt")
    output_json_path = os.path.join(base_dir, "cv.json")
    
    # ... [Keep your existing PDF text reading code here] ...
    with open(temp_text_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: The GEMINI_API_KEY environment variable is missing.")
        sys.exit(1)

    # --- PART A: Call Gemini with Retry Logic ---
    print("Streaming structured PDF data request to Gemini...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": f"Extract ONLY 'Employment' and 'Selected Presentations' from:\n{raw_text}"}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
    }
    
    merged_sections = []
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode("utf-8"))
                json_text_out = result["candidates"][0]["content"]["parts"][0]["text"]
                gemini_data = json.loads(json_text_out)
                if isinstance(gemini_data, dict) and "sections" in gemini_data:
                    merged_sections.extend(gemini_data["sections"])
            print("Successfully extracted data from PDF.")
            break # Success, exit retry loop
            
        except urllib.error.HTTPError as e:
            if e.code == 429: # Too Many Requests
                wait_time = (attempt + 1) * 10
                print(f"Rate limit hit (429). Retrying in {wait_time} seconds (Attempt {attempt+1}/{max_retries})...")
                time.sleep(wait_time)
                continue
            else:
                print(f"CRITICAL API Error: {e}")
                sys.exit(1)
        except Exception as e:
            print(f"CRITICAL Processing Error: {e}")
            sys.exit(1)

    # ... [Keep your existing Excel Part B and Final JSON output code here] ...

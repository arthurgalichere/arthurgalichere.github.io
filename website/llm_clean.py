import os
import sys
import json
import urllib.request
import urllib.error

def clean_json_with_llm():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "cv.json")
    
    if not os.path.exists(file_path):
        print(f"CRITICAL ERROR: Target file not found at {file_path}")
        sys.exit(1)

    with open(file_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Fetch your Gemini API key from the system environment
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: The GEMINI_API_KEY environment variable is empty or missing.")
        print("Ensure you have added it to your GitHub Repository Secrets.")
        sys.exit(1)

    system_instruction = (
        "You are an expert data cleaning assistant. Your task is to process a raw, messy JSON CV file.\n"
        "Fix the following extraction errors:\n"
        "1. Missing Spaces: Fix word spacing collisions caused by PDF font matrix conversion issues "
        "(e.g., convert 'AssistantProfessor(TeachingFocussed)' to 'Assistant Professor (Teaching Focussed)', "
        "and 'UniversityofWarwick' to 'University of Warwick').\n"
        "2. Character Glitches: Fix text casing artifacts like 'UNIVErSITY' to 'University' or 'WArWICK' to 'Warwick'.\n"
        "3. Structural Cleanup: Eliminate redundant duplicate sections (like repeated Education entries) and normalize dates.\n"
        "4. Mapping: Output items matching a standardized array structure containing keys: 'role', 'institution', 'date', and 'details'.\n"
        "Return ONLY the updated valid JSON object matching the input array style."
    )

    prompt = f"{system_instruction}\n\nClean this data thoroughly and return it as valid JSON:\n{json.dumps(raw_data)}"

    # Set up the endpoint URL targeting gemini-2.5-flash
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    # Configure payload forcing a native application/json enforcement response
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    print("Streaming raw extraction matrix to Gemini API for structural cleaning...")
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            
            # Extract raw string block text from the nested Gemini response tree
            json_text_out = result["candidates"][0]["content"]["parts"][0]["text"]
            cleaned_json = json.loads(json_text_out)

            # Overwrite the temporary messy cv.json with clean structural arrays
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(cleaned_json, f, indent=2, ensure_ascii=False)
                
            print(f"Stage 2 Complete: Clean data saved back to {file_path}")

    except urllib.error.HTTPError as e:
        print(f"CRITICAL API HTTP Error: {e.code} - {e.read().decode('utf-8')}")
        sys.exit(1)
    except Exception as e:
        print(f"CRITICAL Processing Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    clean_json_with_llm()

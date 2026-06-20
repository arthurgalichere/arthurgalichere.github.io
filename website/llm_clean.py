import os
import json
from openai import OpenAI

def clean_json_with_llm():
    # Automatically tracks down cv.json in the same folder as this script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "cv.json")
    
    if not os.path.exists(file_path):
        print(f"Error: Target file not found at {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    client = OpenAI()

    system_prompt = (
        "You are an expert data cleaning assistant. Your task is to process a raw, messy JSON CV file.\n"
        "Fix the following extraction errors:\n"
        "1. Missing Spaces: Fix word spacing collisions caused by PDF font matrix conversion issues "
        "(e.g., convert 'AssistantProfessor(TeachingFocussed)' to 'Assistant Professor (Teaching Focussed)', "
        "and 'UniversityofWarwick' to 'University of Warwick').\n"
        "2. Character Glitches: Fix text casing artifacts like 'UNIVErSITY' to 'University' or 'WArWICK' to 'Warwick'.\n"
        "3. Structural Cleanup: Eliminate redundant duplicate sections (like repeated Education entries) and normalize dates.\n"
        "4. Mapping: Output items matching a standardized array structure containing keys: 'role', 'institution', 'date', and 'details'.\n"
        "Return ONLY the updated valid JSON object matching the input array style. Do not include markdown code block backticks or conversational text."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Clean this data thoroughly:\n\n{json.dumps(raw_data)}"}
            ],
            temperature=0.1
        )
        
        cleaned_content = response.choices[0].message.content.strip()
        
        if cleaned_content.startswith("```json"):
            cleaned_content = cleaned_content[7:-3].strip()
        elif cleaned_content.startswith("```"):
            cleaned_content = cleaned_content[3:-3].strip()

        cleaned_json = json.loads(cleaned_content)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_json, f, indent=2, ensure_ascii=False)
            
        print(f"Stage 2 Complete: Clean data saved back to {file_path}")

    except Exception as e:
        print(f"LLM Processing Error: {e}")

if __name__ == "__main__":
    clean_json_with_llm()

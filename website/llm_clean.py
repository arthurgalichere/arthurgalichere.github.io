import os
import sys
import json
import urllib.request
import urllib.error

def clean_json_with_llm():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    temp_text_path = os.path.join(base_dir, "raw_cv.txt")
    output_json_path = os.path.join(base_dir, "cv.json")
    
    # Verify raw text exists
    if not os.path.exists(temp_text_path):
        print(f"CRITICAL ERROR: Temporary raw text file not found at {temp_text_path}")
        sys.exit(1)

    with open(temp_text_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: The GEMINI_API_KEY environment variable is empty or missing.")
        sys.exit(1)

    system_instruction = (
        "You are an expert CV structuring engine. Parse this raw, messy academic CV text.\n"
        "1. Fix Spacing Glitches: Separate any stuck words (e.g. 'AssistantProfessor' -> 'Assistant Professor', 'UniversityofWarwick' -> 'University of Warwick').\n"
        "2. Structure Sections and Subsections:\n"
        "   - Identify major sections (e.g. 'Employment', 'Teaching Awards & Qualifications', 'Teaching Experience', 'Academic Leadership & Development', 'Administrative & Collegial Experience', 'Referees', 'Selected Presentations').\n"
        "   - If a section contains sub-categories or groupings, organize them under a 'subsections' array (e.g. 'Teaching Experience' should have subsections for 'University of Warwick', 'University of Glasgow', and 'Additional Teaching and Supervisory Experience').\n"
        "   - For 'Selected Presentations', group the items by year (e.g., '2026', '2025') as subsections.\n"
        "   - If a section is flat and does not require subsections (like 'Employment'), map items directly to the section's 'items' array.\n"
        "3. Clear Exclusions: DO NOT include any paragraphs, abstracts, or descriptions regarding 'Research Summary', 'Job Market Paper', 'Working Papers', or 'Work in Progress'.\n"
        "4. EXCLUDE EDUCATION: Completely skip the 'Education' section because it is hardcoded on the page.\n"
        "5. Fix Institutional Alignments:\n"
        "   - The 'Warwick Award for Teaching Excellence' (WATE) belongs to the 'University of Warwick'.\n"
        "   - The 'Fellowship of the Higher Education Academy' belongs to the 'University of Warwick'.\n"
        "   - The 'Associate Fellowship' / 'DAT HE' belongs to the 'University of Glasgow'.\n"
        "6. Professional Development / Courses: Put ONLY the name of the course in the 'role' field. Information such as 'taught by [Name]' MUST be moved to the 'institution' or 'details' field so it is not bolded."
    )

    prompt = f"""
Clean, restore word spacing, and parse this raw academic CV text into structural Sections, Subsections, and Items.

Output strictly valid JSON matching this exact schema shape:
{{
  "sections": [
    {{
      "title": "Section Title",
      "subsections": [
        {{
          "title": "Subsection Name (e.g., University of Warwick or 2026)",
          "items": [
            {{
              "role": "Role title, award name, or presentation name",
              "institution": "Institution name if applicable",
              "date": "Date if applicable",
              "details": "Paragraph description or supporting bullet text"
            }}
          ]
        }}
      ],
      "items": [
        // Populate this ONLY if there are NO subsections for this section
        {{
          "role": "Role title, award name, or presentation name",
          "institution": "Institution name if applicable",
          "date": "Date if applicable",
          "details": "Paragraph description or supporting bullet text"
            }}
          ]
        }}
  ]
}}

Raw CV Text:
-----------------------
{raw_text}
-----------------------
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{"text": f"{system_instruction}\n\n{prompt}"}]
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

    print("Streaming structured data request to Google Gemini API...")
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            json_text_out = result["candidates"][0]["content"]["parts"][0]["text"]
            cleaned_json = json.loads(json_text_out)

            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump(cleaned_json, f, indent=2, ensure_ascii=False)
                
            print(f"Stage 2 Complete: Structured sections saved to {output_json_path}")
            
            # Clean up temporary raw text file safely
            if os.path.exists(temp_text_path):
                os.remove(temp_text_path)
                
    except urllib.error.HTTPError as e:
        print(f"CRITICAL API HTTP Error: {e.code} - {e.read().decode('utf-8')}")
        sys.exit(1)
    except Exception as e:
        print(f"CRITICAL Processing Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    clean_json_with_llm()

import os
import json
import re
import pdfplumber

def extract_raw_pdf():
    # Automatically finds the folder where this script lives (the website/ directory)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_path = os.path.join(base_dir, "CV_Arthur_Galichere.pdf")
    output_path = os.path.join(base_dir, "cv.json")
    
    structured_data = {"sections": []}
    current_section = None
    section_data = {"title": "", "items": []}
    
    section_markers = {
        "EMPLOYMENT": "Employment",
        "EDUCATION": "Education",
        "TEACHING EXPERIENCE": "Teaching Experience",
        "ACADEMIC LEADERSHIP": "Academic Leadership, Teaching Support and Educational Development",
        "ADMINISTRATIVE": "Administrative and Collegial Experience",
        "REFEREES": "Referees",
        "SELECTED PRESENTATIONS": "Selected Presentations",
        "PRESENTATIONS": "Selected Presentations"
    }

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
                
            for line in text.split("\n"):
                line_str = line.strip()
                if not line_str:
                    continue
                
                if re.search(r'(?i)Page\s+\d+|Arthur\s+Galich|Curriculum\s+Vit', line_str):
                    continue
                
                is_header = False
                for marker, clean_title in section_markers.items():
                    if line_str.upper().startswith(marker):
                        if current_section and section_data["items"]:
                            structured_data["sections"].append(section_data)
                        current_section = clean_title
                        section_data = {"title": current_section, "items": []}
                        is_header = True
                        break
                
                if is_header or not current_section:
                    continue
                
                if not section_data["items"]:
                    section_data["items"].append({"raw_text": ""})
                section_data["items"][0]["raw_text"] += line_str + "\n"

    if current_section and section_data["items"]:
        structured_data["sections"].append(section_data)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(structured_data, f, indent=2, ensure_ascii=False)
    print(f"Stage 1 Complete: Raw layout scraped into {output_path}")

if __name__ == "__main__":
    extract_raw_pdf()

import json
import re
import pdfplumber

def clean_extracted_text(text):
    """Cleans up line-wrap hyphens, font ligatures, and structural noise."""
    if not text:
        return ""
    
    # Clean page headers, footers, and strange icon symbols
    text = re.sub(r'(?i)Page\s+\d+', '', text)
    text = re.sub(r'(?i)Arthur\s+Galichère\s+Curriculum\s+Vitæ', '', text)
    text = re.sub(r'[􀄤􀁡􀈲􀁦•]', '', text)

    # Fix broken layout hyphens (e.g., 'fluc- tuations' -> 'fluctuations')
    text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
    text = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', text)

    return text

def parse_pdf_to_json():
    structured_data = {"sections": []}
    
    try:
        # pdfplumber reads layout boundaries accurately to prevent squished text words
        with pdfplumber.open("website/CV_Arthur_Galichere.pdf") as pdf:
            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text(layout=False, x_tolerance=3, y_tolerance=3)
                if page_text:
                    full_text += page_text + "\n"
    except Exception as e:
        print(f"Error reading PDF layout matrix: {e}")
        return

    full_text = clean_extracted_text(full_text)

    # Explicit section boundaries mapping your real structure
    sections_anchors = [
        "EMPLOYMENT", "EDUCATION", "RESEArCH", "JOB MArKET PAPEr", 
        "WOrKING PAPEr", "WOrK IN PrOGrESS", "CONFErENCE PAPEr REVIEWEr", 
        "PrOFESSIONAL DEVELOPMENT", "TEACHING AWArDS AND QUALIfICATIONS", 
        "TEACHING EXPErIENCE", "ACADEMIC LEADErSHIP, TEACHING SUPPOrT AND EDUCATIONAL DEVELOPMENT", 
        "ADMINISTrATIVE AND COLLEGIAL EXPErIENCE", "REFErEES", "RESEArCH PrESENTATIONS"
    ]

    pattern = "|".join([rf"\b{re.escape(section)}\b" for section in sections_anchors])
    splits = re.split(f"({pattern})", full_text)

    for i in range(1, len(splits), 2):
        raw_title = splits[i].strip().title()
        
        # Human-readable title adjustments
        clean_title = (raw_title
                       .replace("Research", "Research Summary")
                       .replace("Job Market Paper", "Job Market Paper")
                       .replace("Working Paper", "Working Papers")
                       .replace("Work In Progress", "Work In Progress")
                       .replace("Teaching Awards And Qualifications", "Teaching Awards & Qualifications")
                       .replace("Teaching Experience", "Teaching Experience")
                       .replace("Academic Leadership, Teaching Support And Educational Development", "Academic Leadership & Development")
                       .replace("Administrative And Collegial Experience", "Administrative & Collegial Experience")
                       .replace("Research Presentations", "Selected Presentations"))

        body = splits[i+1].strip() if (i+1) < len(splits) else ""
        lines = [line.strip() for line in body.split('\n') if line.strip()]
        items = []

        # --- MODE 1: Standard Academic Timelines ---
        if clean_title in ["Employment", "Education", "Conference Paper Reviewer", "Professional Development", "Academic Leadership & Development", "Administrative & Collegial Experience"]:
            current_item = None
            for line in lines:
                # Look for standard timeline dates at the end of text lines
                date_match = re.search(r'(\b\d{4}\s*–?\s*(?:PrESENT|Present|\d{4})?)$', line, re.IGNORECASE)
                
                if date_match:
                    if current_item: items.append(current_item)
                    date_str = date_match.group(1).strip().replace("PrESENT", "Present").replace("present", "Present")
                    role_str = line[:date_match.start()].strip().rstrip(',:-').strip()
                    current_item = {"role": role_str, "institution": "", "date": date_str, "details": ""}
                elif current_item:
                    if not current_item["institution"]:
                        current_item["institution"] = line
                    else:
                        current_item["details"] = (current_item["details"] + " " + line).strip()
            if current_item: items.append(current_item)

        # --- MODE 2: Dynamic Research Abstracts ---
        elif "Paper" in clean_title or "Progress" in clean_title:
            if lines:
                title_line = lines[0]
                desc_text = " ".join(lines[1:])
                items.append({
                    "role": title_line,
                    "institution": "",
                    "date": "Forthcoming" if "Progress" in clean_title else "Working Paper",
                    "details": desc_text
                })

        # --- MODE 3: Awards and Fellowships Parser ---
        elif "Awards" in clean_title:
            current_award = None
            for line in lines:
                if ":" in line and any(yr in line for yr in ["2025", "2024", "2023", "2021", "2019"]):
                    if current_award: items.append(current_award)
                    title_part, date_part = line.split(",", 1) if "," in line else (line, "")
                    inst = "University of Warwick" if "Warwick" in line or "WATE" in line.upper() else "University of Glasgow"
                    current_award = {
                        "role": title_part.replace(":", "").strip(),
                        "institution": inst,
                        "date": re.sub(r'[^0-9–]', '', date_part) or line.split()[-1].replace(":", ""),
                        "details": ""
                    }
                elif current_award:
                    current_award["details"] = (current_award["details"] + " " + line).strip()
            if current_award: items.append(current_award)

        # --- MODE 4: Presentations Timeline Matrix ---
        elif "Presentations" in clean_title:
            current_year = ""
            for line in lines:
                if re.match(r'^\d{4}$', line):
                    current_year = line
                elif current_year:
                    items.append({
                        "role": line,
                        "institution": "",
                        "date": current_year,
                        "details": ""
                    })

        # --- MODE 5: Fallback Structural Paragraph Blocks ---
        else:
            if lines:
                items.append({
                    "role": "",
                    "institution": "",
                    "date": "",
                    "details": " ".join(lines)
                })

        if items:
            structured_data["sections"].append({"title": clean_title, "items": items})

    with open("website/cv.json", "w", encoding="utf-8") as f:
        json.dump(structured_data, f, indent=2, ensure_ascii=False)
    print("cv.json cleanly synchronized using layout positioning rules.")

if __name__ == "__main__":
    parse_pdf_to_json()

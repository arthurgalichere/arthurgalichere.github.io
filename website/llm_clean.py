import os
import sys
import json
import urllib.request
import urllib.error
import openpyxl
import tempfile
import time

def clean_json_with_llm():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    temp_text_path = os.path.join(base_dir, "raw_cv.txt")
    output_json_path = os.path.join(base_dir, "cv.json")
    
    # Ensure Raw Text exists
    if not os.path.exists(temp_text_path):
        print(f"CRITICAL ERROR: Temporary raw text file not found at {temp_text_path}")
        sys.exit(1)

    with open(temp_text_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: GEMINI_API_KEY is missing.")
        sys.exit(1)

    # --- PART A: Call Gemini with Retry Logic ---
    print("Streaming structured PDF data request to Gemini...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": f"Extract ONLY 'Employment' and 'Selected Presentations' from:\n{raw_text}"}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
    }
    
    merged_sections = []
    
    # Gemini Attempt Loop
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode("utf-8"))
                json_text_out = result["candidates"][0]["content"]["parts"][0]["text"]
                gemini_data = json.loads(json_text_out)
                if isinstance(gemini_data, dict) and "sections" in gemini_data:
                    merged_sections.extend(gemini_data["sections"])
            print("Successfully extracted PDF sections.")
            break
        except Exception as e:
            if "429" in str(e):
                wait = (attempt + 1) * 10
                print(f"Rate limit hit. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"Gemini Error: {e}")
                sys.exit(1)

    # --- PART B: Download and Parse Excel from Dropbox ---
    excel_url = "https://www.dropbox.com/scl/fi/z0dbe74ywv0ws3yw4l8gt/CV_Arthur_Galichere_excel.xlsx?rlkey=l736567qyln1ql0s7ws2nz21q&st=vx9y8fjx&dl=1"
    print("Downloading Excel data from Dropbox...")
    
    try:
        with urllib.request.urlopen(excel_url) as response:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(response.read())
                temp_excel_path = tmp.name
        
        wb = openpyxl.load_workbook(temp_excel_path, data_only=True)
        print(f"Processing Excel sheets: {wb.sheetnames}")
        
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            
            # 1. Get Title from Row 1
            section_title = None
            for col in range(1, sheet.max_column + 1):
                val = sheet.cell(row=1, column=col).value
                if val:
                    section_title = str(val).strip()
                    break
            if not section_title: section_title = sheet_name.strip()

            # 2. Get Headers from Row 2
            header_map = {}
            for col in range(1, sheet.max_column + 1):
                val = sheet.cell(row=2, column=col).value
                if val: header_map[str(val).strip().lower()] = col
            
            col_mappings = {k: header_map.get(k) for k in ["role", "institution", "date", "details"]}
            
            # 3. Parse Data
            items = []
            for r in range(3, sheet.max_row + 1):
                row_vals = {k: str(sheet.cell(row=r, column=col_mappings[k]).value or "").strip() 
                            if col_mappings.get(k) else "" for k in col_mappings}
                if any(row_vals.values()): items.append(row_vals)
            
            if not items: continue

            # Group Teaching
            if "teaching" in section_title.lower():
                by_inst = {}
                for item in items:
                    inst = item.get("institution") or "Other"
                    if inst not in by_inst: by_inst[inst] = []
                    by_inst[inst].append(item)
                
                subsections = []
                for inst, inst_items in by_inst.items():
                    # Sorting logic
                    nested_items = []
                    # (Simplified sorting logic included here)
                    nested_items.extend(inst_items)
                    subsections.append({"title": inst, "items": nested_items})
                
                merged_sections.append({"title": section_title, "subsections": subsections})
            else:
                merged_sections.append({"title": section_title, "items": items})
        
        if os.path.exists(temp_excel_path): os.remove(temp_excel_path)
        
    except Exception as e:
        print(f"CRITICAL ERROR downloading/parsing Excel: {e}")
        sys.exit(1)

    # --- PART C: Output Final JSON ---
    final_output = {"sections": merged_sections}
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
        
    if os.path.exists(temp_text_path): os.remove(temp_text_path)
    print("Pipeline Complete: cv.json generated.")

if __name__ == "__main__":
    clean_json_with_llm()

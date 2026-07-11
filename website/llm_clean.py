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
    
    # 1. PDF Extraction (Gemini)
    merged_sections = []
    if os.path.exists(temp_text_path):
        with open(temp_text_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
        
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            print("Streaming structured PDF data request to Gemini...")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
            payload = {
                "contents": [{"parts": [{"text": f"Extract 'Employment' and 'Selected Presentations' from this CV. Output ONLY as JSON.\n{raw_text}"}]}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
            }
            try:
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    gemini_data = json.loads(result["candidates"][0]["content"]["parts"][0]["text"])
                    if "sections" in gemini_data:
                        merged_sections.extend(gemini_data["sections"])
            except Exception as e:
                print(f"Warning: PDF extraction skipped or failed: {e}")

    # 2. Excel Parsing (Dropbox)
    excel_url = "https://www.dropbox.com/scl/fi/z0dbe74ywv0ws3yw4l8gt/CV_Arthur_Galichere_excel.xlsx?rlkey=l736567qyln1ql0s7ws2nz21q&st=vx9y8fjx&dl=1"
    print("Downloading Excel data...")
    try:
        with urllib.request.urlopen(excel_url) as response:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(response.read())
                temp_excel_path = tmp.name
        
        wb = openpyxl.load_workbook(temp_excel_path, data_only=True)
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            section_title = str(sheet.cell(row=1, column=1).value or sheet_name).strip()
            
            header_map = {str(sheet.cell(row=2, column=col).value).strip().lower(): col 
                         for col in range(1, sheet.max_column + 1) if sheet.cell(row=2, column=col).value}
            
            cols = ["role", "institution", "date", "details", "other_details"]
            col_map = {k: header_map.get(k) for k in cols}
            
            items = []
            for r in range(3, sheet.max_row + 1):
                row = {k: str(sheet.cell(row=r, column=col_map[k]).value or "").strip() 
                       if col_map.get(k) else "" for k in cols}
                
                if not any(row.values()): continue
                
                # Combine details and other_details with a newline
                if row["other_details"]:
                    row["details"] = f"{row['details']}\n{row['other_details']}".strip()
                
                items.append({"role": row["role"], "institution": row["institution"], "date": row["date"], "details": row["details"]})
            
            if not items: continue

            # Only group by institution if it is specifically Teaching Experience
            if section_title.lower() == "teaching experience":
                by_inst = {}
                for item in items:
                    inst = item.get("institution") or "Other"
                    if inst not in by_inst: by_inst[inst] = []
                    by_inst[inst].append(item)
                
                subsections = [{"title": inst, "items": inst_items} for inst, inst_items in by_inst.items()]
                merged_sections.append({"title": section_title, "subsections": subsections})
            else:
                merged_sections.append({"title": section_title, "items": items})
        
        if os.path.exists(temp_excel_path): os.remove(temp_excel_path)
    except Exception as e:
        print(f"Error parsing Excel: {e}")

    # 3. Save
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump({"sections": merged_sections}, f, indent=2, ensure_ascii=False)
    print("Pipeline Complete.")

if __name__ == "__main__":
    clean_json_with_llm()

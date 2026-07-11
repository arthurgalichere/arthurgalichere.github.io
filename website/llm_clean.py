import os
import sys
import json
import urllib.request
import urllib.error
import openpyxl
import tempfile

def clean_json_with_llm():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    temp_text_path = os.path.join(base_dir, "raw_cv.txt")
    output_json_path = os.path.join(base_dir, "cv.json")
    
    excel_url = "https://www.dropbox.com/scl/fi/z0dbe74ywv0ws3yw4l8gt/CV_Arthur_Galichere_excel.xlsx?rlkey=l736567qyln1ql0s7ws2nz21q&st=vx9y8fjx&dl=1"
    temp_excel_path = None
    
    try:
        print(f"Fetching Excel data from Dropbox...")
        req = urllib.request.Request(excel_url)
        with urllib.request.urlopen(req) as response:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(response.read())
                temp_excel_path = tmp.name
    except Exception as e:
        print(f"CRITICAL ERROR fetching remote Excel: {e}")
        sys.exit(1)

    if not os.path.exists(temp_text_path):
        print(f"CRITICAL ERROR: Temporary raw text file not found at {temp_text_path}")
        sys.exit(1)

    with open(temp_text_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: The GEMINI_API_KEY environment variable is empty.")
        sys.exit(1)

    system_instruction = (
        "You are an expert CV data extraction engine.\n"
        "Extract ONLY 'Employment' and 'Selected Presentations' from the raw CV text.\n"
        "Format the output strictly as a JSON object with a single 'sections' array."
    )

    prompt = f"""
    Extract ONLY the Employment and Selected Presentations sections from the text.
    Output strictly valid JSON matching this schema:
    {{"sections": [{{"title": "Section Title", "items": [{{"role": "Title", "institution": "Name", "date": "Date", "details": "Desc"}}]}}]}}
    Raw CV Text:
    {raw_text}
    """

    merged_sections = []

    print("Streaming structured PDF data request to Gemini...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": f"{system_instruction}\n\n{prompt}"}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
    }
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            json_text_out = result["candidates"][0]["content"]["parts"][0]["text"]
            gemini_data = json.loads(json_text_out)
            
            if isinstance(gemini_data, dict) and "sections" in gemini_data:
                merged_sections.extend(gemini_data["sections"])
    except Exception as e:
        print(f"CRITICAL ERROR during Gemini parsing: {e}")
        sys.exit(1)

    if temp_excel_path:
        print(f"Processing Excel data...")
        try:
            wb = openpyxl.load_workbook(temp_excel_path, data_only=True)
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                section_title = sheet.cell(row=1, column=1).value or sheet_name.strip()
                
                header_map = {str(sheet.cell(row=2, column=col).value).strip().lower(): col 
                             for col in range(1, sheet.max_column + 1) if sheet.cell(row=2, column=col).value}
                
                col_map = {k: header_map.get(k) for k in ["role", "institution", "date", "details"]}
                
                items = []
                for r in range(3, sheet.max_row + 1):
                    row_vals = {k: str(sheet.cell(row=r, column=col_map[k]).value or "").strip() 
                               if col_map.get(k) else "" for k in col_map}
                    if any(row_vals.values()):
                        items.append(row_vals)
                
                merged_sections.append({"title": section_title, "items": items})
        finally:
            if os.path.exists(temp_excel_path):
                os.remove(temp_excel_path)

    final_output = {"sections": merged_sections}
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, indent=2, ensure_ascii=False)
        
    if os.path.exists(temp_text_path):
        os.remove(temp_text_path)
    print(f"Pipeline Complete: Saved to {output_json_path}")

if __name__ == "__main__":
    clean_json_with_llm()

import os
import sys
import json
import urllib.request
import urllib.error
import openpyxl
import tempfile # ... existing code ...

# ... existing code ...
    # --- PART B: Parse Local Excel Database ---
    excel_url = "https://www.dropbox.com/scl/fi/z0dbe74ywv0ws3yw4l8gt/CV_Arthur_Galichere_excel.xlsx?rlkey=l736567qyln1ql0s7ws2nz21q&st=vx9y8fjx&dl=1"
    
    print(f"Fetching Excel data from Dropbox...")
    try:
        req = urllib.request.Request(excel_url)
        with urllib.request.urlopen(req) as response:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(response.read())
                temp_excel_path = tmp.name
        
        wb = openpyxl.load_workbook(temp_excel_path, data_only=True)
        print(f"Loaded sheets from remote data: {wb.sheetnames}")
        
        for sheet_name in wb.sheetnames:
            sheet = wb[sheet_name]
            
            # Fetch full Section Name from Row 1
# ... existing code ...

            #def clean_json_with_llm():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    temp_text_path = os.path.join(base_dir, "raw_cv.txt")
    output_json_path = os.path.join(base_dir, "cv.json")
    
    # Locate the verbatim Excel file
    excel_name = "CV_Arthur_Galichere_excel.xlsx"
    excel_path = None
    
    # Try searching relative paths recursively
    search_paths = [
        os.path.join(base_dir, excel_name),
        os.path.join(os.path.dirname(base_dir), excel_name),
        excel_name
    ]
    for path in search_paths:
        if os.path.exists(path):
            excel_path = path
            break
            
    if not excel_path:
        # Recursive scan for safety fallback
        for root, dirs, files in os.walk(os.path.dirname(base_dir)):
            if excel_name in files:
                excel_path = os.path.join(root, excel_name)
                break

    if not os.path.exists(temp_text_path):
        print(f"CRITICAL ERROR: Temporary raw text file not found at {temp_text_path}")
        sys.exit(1)

    with open(temp_text_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("CRITICAL ERROR: The GEMINI_API_KEY environment variable is empty or missing.")
        sys.exit(1)

    #    system_instruction = (
        "You are an expert CV data extraction engine.\n"
        "Extract ONLY the following two sections from the raw CV text:\n"
        "1. 'Employment'\n"
        "2. 'Selected Presentations' / 'Research Presentations'\n\n"
        "DO NOT extract Education, Teaching, Admin, Leadership, or Referees sections. Skip those completely.\n"
        "For the extracted sections:\n"
        "- Fix word spacing issues (e.g., 'AssistantProfessor' -> 'Assistant Professor').\n"
        "- Maintain literal wording and exact titles.\n"
        "Format the output strictly as a JSON object with a single 'sections' array."
    )

    prompt = f"""
Clean, restore word spacing, and extract ONLY the Employment and Selected Presentations sections from the text.

Output strictly valid JSON matching this schema:
{{
  "sections": [
    {{
      "title": "Section Title",
      "items": [
        {{
          "role": "Role Title",
          "institution": "University / Institution",
          "date": "Date Range",
          "details": "Details description"
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

    merged_sections = []

    # --- PART A: Call Gemini for PDF data ---
    print("Streaming structured PDF data request to Gemini...")
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
    
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            json_text_out = result["candidates"][0]["content"]["parts"][0]["text"]
            gemini_data = json.loads(json_text_out)
            
            if isinstance(gemini_data, dict) and "sections" in gemini_data:
                merged_sections.extend(gemini_data["sections"])
            elif isinstance(gemini_data, list):
                merged_sections.extend(gemini_data)
                
            print(f"Part A Complete: Extracted {len(merged_sections)} dynamic sections from PDF.")
            
    except Exception as e:
        print(f"CRITICAL ERROR during Gemini parsing: {e}")
        sys.exit(1)

    # --- PART B: Parse Local Excel Database ---
    #    if not excel_path:
        print(f"WARNING: local Excel file '{excel_name}' not found. Skipping Excel merge.")
    else:
        print(f"Successfully located Excel file at {excel_path}. Loading sheets...")
        try:
            wb = openpyxl.load_workbook(excel_path, data_only=True)
            print(f"Loaded sheets: {wb.sheetnames}")
            
            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                
                # Fetch full Section Name from Row 1
                section_title = None
                for col in range(1, sheet.max_column + 1):
                    val = sheet.cell(row=1, column=col).value
                    if val:
                        section_title = str(val).strip()
                        break
                
                if not section_title:
                    section_title = sheet_name.strip()
                
                # Row 2 contains column headers
                header_map = {}
                for col in range(1, sheet.max_column + 1):
                    val = sheet.cell(row=2, column=col).value
                    if val:
                        header_map[str(val).strip().lower()] = col
                
                # Find closest matching column indices dynamically
                col_mappings = {}
                for key in ["role", "institution", "date", "details"]:
                    for h_name, idx in header_map.items():
                        if key in h_name:
                            col_mappings[key] = idx
                            break
                
                # Extract actual data starting from Row 3
                items = []
                for r in range(3, sheet.max_row + 1):
                    row_vals = {}
                    for key in ["role", "institution", "date", "details"]:
                        col_idx = col_mappings.get(key)
                        if col_idx:
                            val = sheet.cell(row=r, column=col_idx).value
                            row_vals[key] = str(val or "").strip()
                        else:
                            row_vals[key] = ""
                    
                    # Skip completely empty rows
                    if not any(row_vals.values()):
                        continue
                        
                    items.append(row_vals)
                
                if not items:
                    continue

                #                # Special Grouping Logic for "Teaching Experience"
                if "teaching" in section_title.lower():
                    by_inst = {}
                    inst_order = []  # Maintain visual order of entry
                    
                    for item in items:
                        inst = item.get("institution") or "Other"
                        inst = inst.strip()
                        if not inst:
                            inst = "Other"
                        if inst not in by_inst:
                            by_inst[inst] = []
                            inst_order.append(inst)
                        by_inst[inst].append(item)
                    
                    subsections = []
                    for inst in inst_order:
                        inst_items = by_inst[inst]
                        by_format = {}
                        
                        # Group by class formats
                        for item in inst_items:
                            fmt = item.get("details") or "Other"
                            fmt_lower = fmt.lower().strip()
                            
                            # Normalize plural format names
                            if "lecture" in fmt_lower:
                                fmt_clean = "Lectures"
                            elif "seminar" in fmt_lower:
                                fmt_clean = "Seminars"
                            elif "tutorial" in fmt_lower:
                                fmt_clean = "Tutorials"
                            elif "supervision" in fmt_lower:
                                fmt_clean = "Supervision"
                            else:
                                fmt_clean = fmt.strip() if fmt.strip() else "Other"
                                
                            if fmt_clean not in by_format:
                                by_format[fmt_clean] = []
                            by_format[fmt_clean].append(item)
                        
                        # Set custom academic sorting order for Teaching blocks
                        format_order = ["Lectures", "Seminars", "Tutorials", "Supervision"]
                        sorted_formats = sorted(
                            by_format.keys(),
                            key=lambda x: format_order.index(x) if x in format_order else len(format_order)
                        )
                        
                        nested_items = []
                        for fmt in sorted_formats:
                            # Insert category subheader row
                            nested_items.append({
                                "role": fmt,
                                "isFormatHeader": True
                            })
                            # Append courses under this category
                            for item in by_format[fmt]:
                                nested_items.append({
                                    "role": item.get("role") or "",
                                    "institution": "",  # Hidden (handled by Subsection Name)
                                    "date": item.get("date") or "",
                                    "details": ""       # Hidden (handled by Format Header)
                                })
                        
                        subsections.append({
                            "title": inst,
                            "items": nested_items
                        })
                    
                    merged_sections.append({
                        "title": section_title,
                        "subsections": subsections
                    })
                    print(f"Merged section '{section_title}' with {len(subsections)} grouped sub-categories from Excel.")
                
                else:
                    # Generic flat sections (Admin, Leadership, Referees, Professional Development)
                    merged_sections.append({
                        "title": section_title,
                        "items": items
                    })
                    print(f"Merged section '{section_title}' with {len(items)} items from Excel.")
                    
        except Exception as e:
            print(f"CRITICAL ERROR parsing Excel workbook: {e}")
            sys.exit(1)

    # --- PART C: Output Merged cv.json file ---
    #    try:
        final_output = {"sections": merged_sections}
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(final_output, f, indent=2, ensure_ascii=False)
        print(f"Pipeline Complete: Merged output saved to {output_json_path}")
        
        # Clean up raw text extraction safely
        if os.path.exists(temp_text_path):
            os.remove(temp_text_path)
            
    except Exception as e:
        print(f"CRITICAL ERROR saving final JSON output: {e}")
        sys.exit(1)

if __name__ == "__main__":
    clean_json_with_llm()

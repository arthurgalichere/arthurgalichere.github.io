import os
import sys
import pdfplumber

def extract_raw_pdf():
    # Detect folders relative to this script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_path = os.path.join(base_dir, "CV_Arthur_Galichere.pdf")
    temp_text_path = os.path.join(base_dir, "raw_cv.txt")
    
    # Check if the PDF file exists
    if not os.path.exists(pdf_path):
        print(f"CRITICAL ERROR: PDF file not found at: {pdf_path}")
        sys.exit(1)
        
    print("Scraping clean text matrices from the PDF...")
    raw_text = ""
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=1.5, y_tolerance=1.5)
                if text:
                    raw_text += text + "\n"
                    
        with open(temp_text_path, "w", encoding="utf-8") as f:
            f.write(raw_text)
            
        print(f"Stage 1 Complete: Full text layout written to temporary file: {temp_text_path}")
    except Exception as e:
        print(f"CRITICAL ERROR during raw extraction: {e}")
        sys.exit(1)

if __name__ == "__main__":
    extract_raw_pdf()

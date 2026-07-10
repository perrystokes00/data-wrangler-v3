"""
Run: python debug_survey.py "path\to\survey.pdf"
Shows exactly what pdfplumber extracts from the table.
"""
import sys
import pdfplumber

path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\sample_pdfs\Survey_ANADARKO_1H_Landmark.pdf"

with pdfplumber.open(path) as pdf:
    for pi, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        if tables:
            print(f"\n=== Page {pi+1}: {len(tables)} table(s) ===")
            for ti, table in enumerate(tables):
                print(f"\n  Table {ti+1}: {len(table)} rows x {len(table[0]) if table else 0} cols")
                for ri, row in enumerate(table[:5]):
                    print(f"    Row {ri}: {row}")

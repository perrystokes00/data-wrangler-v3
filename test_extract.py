path = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\sample_pdfs\End_of_Well_Report_PERMIAN_7H.pdf"

from modules.pdf_survey_catalog import classify_pdf
import pprint

cl = classify_pdf(path)
print("=== classify_pdf ===")
for k, v in cl.items():
    print(f"  {k}: {v}")

try:
    from modules.pdf_survey_catalog import extract_eowr
    print("\n=== extract_eowr ===")
    ew = extract_eowr(path)
    pprint.pprint(ew)
except Exception as e:
    print(f"extract_eowr error: {e}")

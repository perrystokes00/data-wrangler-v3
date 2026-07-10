"""verify_classifier_uwi.py — the flattened UWI is in the text layer, but does the
CLASSIFIER's regex actually resolve it? (regex wants UWI/API: adjacent to the number.)
Run the real classifier on the _flattened PDFs. py verify_classifier_uwi.py --dir "..._flattened" """
import sys, os, glob, re
OUT = r"C:\Bulk\reports\classifier_uwi.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
d = None
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
d = d or r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs\_flattened"

# the exact classifier regex
UWI_RX = re.compile(r'(?:UWI|API|API.?NUM|API.?NO)[:\s]+([0-9\-]{10,20})', re.IGNORECASE)
import pdfplumber
# also try the real classifier if importable
clf = None
try:
    try: from pdf_survey_catalog import extended_classify_pdf as clf
    except Exception: from modules.pdf_survey_catalog import extended_classify_pdf as clf
except Exception: pass

for p in sorted(glob.glob(os.path.join(d,"*.pdf"))):
    with pdfplumber.open(p) as pdf:
        t = pdf.pages[0].extract_text() or ""
    m = UWI_RX.findall(t)
    # show the text right around 'UWI'/'API' to see adjacency
    ctx = ""
    for line in t.splitlines():
        if re.search(r'\b(UWI|API)\b', line, re.IGNORECASE):
            ctx = line.strip()[:90]; break
    log(f"{os.path.basename(p)}")
    log(f"   regex UWI match: {m if m else 'NONE'}")
    log(f"   label line: {ctx!r}")
    if clf:
        try:
            r = clf(p); log(f"   classifier uwi: {r.get('uwi')!r}  type: {r.get('report_type')!r}")
        except Exception as e:
            log(f"   classifier err: {str(e)[:60]}")

log("\n=== VERDICT ===")
log("  regex match = the number is adjacent enough to the label -> extractor WILL get it.")
log("  NONE = the flattened text landed away from the label; need label-anchored insert.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

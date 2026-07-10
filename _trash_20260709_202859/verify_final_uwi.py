"""verify_final_uwi.py — final check on the _flattened folder AFTER the regex patch is
deployed: does each PDF resolve the UWI with the NEW (broadened) regex? py verify_final_uwi.py --dir "..._flattened" """
import sys, os, glob, re
OUT = r"C:\Bulk\reports\final_uwi.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
d = None
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
d = d or r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs\_flattened"

OLD = re.compile(r'(?:UWI|API|API.?NUM|API.?NO)[:\s]+([0-9\-]{10,20})', re.IGNORECASE)
NEW = re.compile(r'(?:UWI|API)(?:\s*(?:NUM(?:BER)?|NO|#|/\s*UWI|/\s*API))?\s*[:#]?\s+([0-9\-]{10,20})', re.IGNORECASE)
import pdfplumber
for p in sorted(glob.glob(os.path.join(d,"*.pdf"))):
    with pdfplumber.open(p) as pdf:
        t = pdf.pages[0].extract_text() or ""
    om = OLD.findall(t); nm = NEW.findall(t)
    lbl = next((ln.strip()[:80] for ln in t.splitlines() if re.search(r'\b(UWI|API)\b',ln,re.I)), "")
    log(f"{os.path.basename(p)}")
    log(f"   OLD regex: {om or 'NONE'}   NEW regex: {nm or 'NONE'}   label: {lbl!r}")

log("\n=== after deploying patch_uwi_regex.py, the NEW column is what the extractor uses ===")
log("  All NEW should show 15007243240000. If any NONE remains, tell me the label line.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

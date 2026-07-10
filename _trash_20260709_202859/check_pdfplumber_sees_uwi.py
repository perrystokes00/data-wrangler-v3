"""check_pdfplumber_sees_uwi.py — pymupdf sees the target UWI (annotations) but does
pdfplumber (what the extractor uses) see it? Annotations are read by pymupdf get_text but
NOT by pdfplumber extract_text. This decides if the typed UWIs actually work. py check_pdfplumber_sees_uwi.py --dir "..." --target 15-007-24324-00-00"""
import sys, os, glob
OUT = r"C:\Bulk\reports\pdfplumber_uwi.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
d = target = None
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
if "--target" in sys.argv: target = sys.argv[sys.argv.index("--target")+1]
d = d or r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs"
target = target or "15-007-24324-00-00"
tnorm = target.replace("-","").replace(" ","")

import pdfplumber, fitz
for p in sorted(glob.glob(os.path.join(d,"*.pdf"))):
    # pdfplumber (the extractor's library) — text only, NOT annotations
    with pdfplumber.open(p) as pdf:
        pt = pdf.pages[0].extract_text() or ""
    pdfp = tnorm in pt.replace("-","").replace(" ","")
    # pymupdf get_text default (may include annotations depending on version)
    doc = fitz.open(p); mt = doc[0].get_text();
    # pymupdf annotations specifically
    annots = []
    for a in (doc[0].annots() or []):
        annots.append(a.info.get("content","") or "")
    doc.close()
    mup = tnorm in mt.replace("-","").replace(" ","")
    inannot = any(tnorm in (a.replace("-","").replace(" ","")) for a in annots)
    log(f"{os.path.basename(p)}")
    log(f"   pdfplumber(extractor) sees target: {pdfp}   pymupdf sees: {mup}   in annotation: {inannot}")

log("\n=== VERDICT ===")
log("  If pdfplumber=False but pymupdf/annotation=True: your typed UWIs are ANNOTATIONS,")
log("  invisible to the extractor. Need to write to the real TEXT LAYER instead.")
log("  Fix: flatten annotations into the page content, OR insert as true text.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

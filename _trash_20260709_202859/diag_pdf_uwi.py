"""diag_pdf_uwi.py — the edited UWI isn't being extracted. Read each PDF the SAME way the
extractor does (pdfplumber text) and show: (1) the raw text around any UWI/API label,
(2) what the classifier's regex matches. Tells us if the edit is in the text layer.
py diag_pdf_uwi.py --dir "C:\\...\\sample_pdfs" """
import sys, os, glob, re
OUT = r"C:\Bulk\reports\pdf_uwi_diag.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

d = None
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
d = d or r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs"

try:
    import pdfplumber
except ImportError:
    log("pdfplumber not installed: pip install pdfplumber --break-system-packages")
    open(OUT,"w").write("\n".join(L)); print("\n".join(L)); sys.exit()

# the exact pattern the classifier uses
UWI_RX = re.compile(r'(?:UWI|API|API.?NUM|API.?NO)[:\s]+([0-9\-]{10,20})', re.IGNORECASE)

pdfs = sorted(glob.glob(os.path.join(d,"*.pdf")))
log(f"reading {len(pdfs)} PDFs the way the extractor does (pdfplumber page-0 text)\n")
for p in pdfs:
    log(f"=== {os.path.basename(p)} ===")
    try:
        with pdfplumber.open(p) as pdf:
            text = pdf.pages[0].extract_text() or ""
    except Exception as e:
        log(f"  read error: {str(e)[:80]}"); continue
    # what does the classifier regex find?
    matches = UWI_RX.findall(text)
    log(f"  classifier regex matches: {matches if matches else 'NONE'}")
    # show any line containing API/UWI so we see the actual text + format
    for line in text.splitlines():
        if re.search(r'\b(API|UWI)\b', line, re.IGNORECASE):
            log(f"    text line: {line.strip()[:100]!r}")
    # also: is there ANY api-looking number anywhere (even without a label)?
    loose = re.findall(r'\b\d{2}[- ]?\d{3}[- ]?\d{5}(?:[- ]?\d{2}[- ]?\d{2})?\b', text)
    if loose:
        log(f"    api-shaped numbers in text: {set(loose)}")
    if not text.strip():
        log("    (page-0 text is EMPTY — image-only PDF? extractor can't read it)")

log("\n=== VERDICT ===")
log("  If 'classifier regex matches' shows your NEW UWI -> the edit is in the text layer;")
log("     the extraction problem is elsewhere (re-crawl, or a different code path).")
log("  If it shows the OLD UWI -> your edit didn't replace the text layer (overlay/image).")
log("  If NONE / empty text -> the label format changed (e.g. no colon) or the edit made")
log("     the PDF image-only. Compare the 'text line' output to the regex: it needs")
log("     'API:' or 'UWI:' followed by the number.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

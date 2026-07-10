"""diag_pdf_textlayer.py — 8/9 PDFs show 'no api number in text layer' but earlier the
classifier extracted UWIs from them. Did editing destroy the text layer? Check how much
extractable text each PDF has now, and whether it's image-only. py diag_pdf_textlayer.py --dir "..." """
import sys, os, glob
OUT = r"C:\Bulk\reports\pdf_textlayer.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
d = None
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
d = d or r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs"
try:
    import pdfplumber, fitz
except ImportError as e:
    log("need pdfplumber+pymupdf: " + str(e)); open(OUT,"w").write("\n".join(L)); sys.exit()

for p in sorted(glob.glob(os.path.join(d,"*.pdf"))):
    log(f"\n=== {os.path.basename(p)} ===")
    # pdfplumber text length
    try:
        with pdfplumber.open(p) as pdf:
            t = pdf.pages[0].extract_text() or ""
        log(f"  pdfplumber page-0 text chars: {len(t)}")
        if t.strip():
            log(f"  first 200 chars: {t[:200]!r}")
        else:
            log("  page-0 text is EMPTY")
    except Exception as e:
        log(f"  pdfplumber err: {str(e)[:60]}")
    # pymupdf: is there a text layer vs images?
    try:
        doc = fitz.open(p)
        pg = doc[0]
        txt = pg.get_text()
        imgs = pg.get_images()
        log(f"  pymupdf text chars: {len(txt)}   images on page-0: {len(imgs)}")
        # rasterized/scanned indicator: little/no text but a full-page image
        if len(txt.strip()) < 20 and imgs:
            log("  -> LIKELY IMAGE-ONLY (scanned/flattened): text layer gone, needs OCR")
        doc.close()
    except Exception as e:
        log(f"  pymupdf err: {str(e)[:60]}")

log("\n=== VERDICT ===")
log("  If most show 0 text + an image: editing FLATTENED them to images (text layer")
log("  destroyed). The originals had text (classifier read UWIs earlier). Restore the")
log("  ORIGINAL PDFs (OneDrive version history / backup) and don't hand-edit them.")
log("  Then either regenerate from source with the new UWI, or use the text-replace tool")
log("  on the ORIGINALS (which still have a text layer).")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

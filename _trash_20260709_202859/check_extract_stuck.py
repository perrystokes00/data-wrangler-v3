"""check_extract_stuck.py — crawl seems stuck on 'extracting'. Check whether extract is
progressing (row counts moving) or genuinely hung, and flag files that commonly hang the
extractor (image-only, huge, or the 17-page scout_ticket). py check_extract_stuck.py --dir "..." """
import pyodbc, os, sys, glob
OUT = r"C:\Bulk\reports\extract_stuck.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== is extract progressing? (run twice ~20s apart, compare) ===")
log("  files with HEADER_EXTRACTED set: " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE HEADER_EXTRACTED IS NOT NULL AND HEADER_EXTRACTED<>''")))
log("  files still pending (N/null):    " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE ISNULL(HEADER_EXTRACTED,'N') IN ('N','')")))
log("  total in catalog:                " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG")))

log("\n=== files that commonly HANG the extractor ===")
d = None
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
if d and os.path.isdir(d):
    try:
        import fitz
        for p in sorted(glob.glob(os.path.join(d,"*.pdf"))):
            try:
                doc = fitz.open(p)
                pg = doc[0]; txt = len(pg.get_text()); imgs = len(pg.get_images()); drw = len(pg.get_drawings())
                npages = doc.page_count; doc.close()
                sz = os.path.getsize(p)//1024
                flag = ""
                if txt < 20 and imgs: flag = " <-- IMAGE-ONLY (OCR may hang)"
                if npages > 10: flag += " <-- MANY PAGES"
                if drw > 500: flag += f" <-- {drw} vector drawings (slow)"
                if sz > 5000: flag += f" <-- LARGE {sz}KB"
                log(f"  {os.path.basename(p)}: {npages}pg text={txt} imgs={imgs} draw={drw} {sz}KB{flag}")
            except Exception as e:
                log(f"  {os.path.basename(p)}: OPEN ERROR {str(e)[:50]} <-- may hang extractor")
    except ImportError:
        log("  (pymupdf not available to scan files)")
else:
    log("  pass --dir <crawl folder> to scan for problem files")

log("\n=== VERDICT ===")
log("  If 'pending' count is DROPPING between runs: extract is working, just slow.")
log("  If it's STUCK at the same number: one file is hanging the stage. The flagged")
log("  files above (image-only / many-pages / huge) are the usual culprits — the")
log("  17-page image-only scout_ticket.pdf especially. Move it out and re-run.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

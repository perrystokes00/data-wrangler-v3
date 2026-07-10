"""preflight_edited_crawl.py — before crawling the UWI-edited PDFs: confirm the catalog is
clear (or tell you to clear), confirm the edited files are on disk, and sanity-check that
the new target UWI actually exists in dv_well with coords. py preflight_edited_crawl.py
   --dir "C:\\...\\sample_pdfs"  --target 15007243240000"""
import sys, pyodbc, os, glob
OUT = r"C:\Bulk\reports\preflight_edited.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

d = None; target = None
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
if "--target" in sys.argv: target = sys.argv[sys.argv.index("--target")+1]
d = d or r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs"

c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== 1) is the catalog clear? ===")
gfc = one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG")
catw = one("SELECT COUNT(*) FROM file_catalog.cat_well")
sta = one("SELECT COUNT(*) FROM file_catalog.cat_well_dir_srvy_sta")
log(f"  GLOBAL_FILE_CATALOG: {gfc}   cat_well: {catw}   cat_well_dir_srvy_sta: {sta}")
if isinstance(gfc,int) and gfc>0:
    log("  -> NOT clear. Click 'Clear catalog & data rows' first (resets stamps too),")
    log("     so the edited files re-extract instead of fingerprint-skipping.")
else:
    log("  -> clear. good to crawl.")

log("\n=== 2) edited PDFs on disk ===")
pdfs = glob.glob(os.path.join(d,"*.pdf")) + glob.glob(os.path.join(d,"*.xlsx")) + glob.glob(os.path.join(d,"*.docx")) + glob.glob(os.path.join(d,"*.xml"))
log(f"  folder: {d}")
log(f"  docs: {len(pdfs)}")

log("\n=== 3) target UWI check (must exist in dv_well WITH coords) ===")
if target:
    norm = "".join(ch for ch in target if ch.isdigit())
    norm = (norm+"00000000000000")[:14]
    r = c.execute("SELECT well_name, surface_latitude, surface_longitude FROM dataview.dv_well WHERE uwi=?", norm).fetchone()
    if r:
        log(f"  {norm}: FOUND '{r[0]}' coords=({r[1]},{r[2]})" + ("  OK" if r[1] is not None else "  <-- NO COORDS, pick another"))
    else:
        log(f"  {norm}: NOT in dv_well -> extractions will still be held. Pick a UWI that exists with coords.")
else:
    log("  (pass --target <uwi> to verify the substituted UWI has coords)")
    log("  coord-bearing candidates:")
    for r in c.execute("SELECT TOP 5 uwi, well_name FROM dataview.dv_well WHERE surface_latitude IS NOT NULL ORDER BY uwi").fetchall():
        log(f"    {r[0]}  {r[1]}")

log("\n=== plan ===")
log("  1. Clear catalog & data rows  ->  py verify_clean_slate.py")
log("  2. Crawl this folder with SCAN + EXTRACT + CAPTURE + PROMOTE + APPLY all ON")
log("     (Scan ON so SCAN_DATE stamps today & scorecard populates)")
log("  3. py check_extraction_full.py   (what each PDF extracted)")
log("  4. verify promote: the extracted data should land in dv_* under the new UWI")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

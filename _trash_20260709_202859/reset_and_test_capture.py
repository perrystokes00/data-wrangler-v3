"""reset_and_test_capture.py — reset CAPTURED_HASH on the PDFs so they re-capture, then
directly call the capture path on ONE PDF with full error output, to see if cat_well gets
written or an exception is swallowed. py reset_and_test_capture.py [--reset-only]"""
import pyodbc, os, sys, traceback
OUT = r"C:\Bulk\reports\reset_capture_test.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

conn = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
conn.autocommit = True
c = conn.cursor()

# 1) reset CAPTURED_HASH on the pdfs so the app will re-capture them
n = c.execute("UPDATE file_catalog.GLOBAL_FILE_CATALOG SET CAPTURED_HASH=NULL WHERE FILE_EXT='.pdf'").rowcount
log(f"reset CAPTURED_HASH on {n} PDF(s) — they will re-capture on next Run.")

if "--reset-only" in sys.argv:
    log("\n--reset-only: now go to the app and Run the pipeline (Capture+Promote+Apply)")
    log("on the _flattened folder. Then run check_crawl_result.py again.")
    open(OUT,"w",encoding="utf-8").write("\n".join(L)); print("\n".join(L)); sys.exit()

# 2) try to directly exercise the capture path on one file to catch swallowed errors
log("\n=== direct capture test on one PDF (full errors) ===")
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP,"modules"))
test_pdf = None
r = c.execute("SELECT FILE_PATH, MATCHED_UWI, INVENTORY_ID FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.pdf' AND MATCHED_UWI IS NOT NULL AND FILE_NAME LIKE 'Well_Test%'").fetchone()
if not r:
    r = c.execute("SELECT FILE_PATH, MATCHED_UWI, INVENTORY_ID FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.pdf' AND MATCHED_UWI IS NOT NULL").fetchone()
if not r:
    log("no pdf with UWI found"); open(OUT,"w").write("\n".join(L)); sys.exit()
fpath, uwi, inv = r
log(f"file: {os.path.basename(fpath)}  uwi={uwi}  inv={inv}")

try:
    from sqlalchemy import create_engine
    eng = create_engine(r"mssql+pyodbc://@localhost\SQLEXPRESS/DataView_Demo?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&Encrypt=no")
    from worker_core import _do_pdf
    def say(m): log("   [say] " + str(m)[:150])
    log("calling _do_pdf ...")
    res = _do_pdf(eng, fpath, uwi, inv, say)
    log("result: " + str(res)[:300])
    # did cat_well get a row now?
    cw = c.execute("SELECT COUNT(*) FROM file_catalog.cat_well WHERE INVENTORY_ID=?", inv).fetchone()[0]
    log(f"cat_well rows for this file after direct call: {cw}")
except Exception as e:
    log("EXCEPTION:\n" + traceback.format_exc()[-1500:])

log("\n=== VERDICT ===")
log("  If the direct call wrote cat_well: capture logic is fine; the pipeline's capture")
log("  path skipped/swallowed it -> reset + re-run via the app should now work.")
log("  If it threw: the traceback shows the real error (a missing column, loader import,")
log("  coord cast, etc.) — that's the actual bug to fix.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

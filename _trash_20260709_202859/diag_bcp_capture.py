"""diag_bcp_capture.py — run the REAL run_bcp_capture on the 20 LAS files exactly as
the pipeline does, and report its return + any error. Pinpoints why it writes 0
cat_well headers. Requires bcp_capture.py present. writes to file.
  py diag_bcp_capture.py --dir "C:\\...\\training\\test_crawl\\las_files" """
import sys, os, glob, traceback
OUT = r"C:\Bulk\reports\bcp_capture.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

# find LAS files
d = None
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
files = []
if d: files = glob.glob(os.path.join(d,"**","*.las"), recursive=True)
if not files:
    for cand in (r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\las_files",
                 r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl"):
        files += glob.glob(os.path.join(cand,"**","*.las"), recursive=True)
if not files:
    log("no LAS files found — pass --dir"); open(OUT,"w").write("\n".join(L)); raise SystemExit
log(f"found {len(files)} LAS file(s)")

# import the fast-path
try:
    from bcp_capture import run_bcp_capture
except Exception:
    try:
        from modules.bcp_capture import run_bcp_capture
    except Exception as e:
        log("could NOT import bcp_capture:", str(e)); open(OUT,"w").write("\n".join(L)); raise SystemExit
log("imported run_bcp_capture OK")

# build the ODBC conn string the same way the app does
odbc = ("DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\\SQLEXPRESS;"
        "DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")

# build recs EXACTLY like pipeline_run (MATCHED_UWI empty, INVENTORY_ID = a test id)
recs = [{"FILE_PATH": f, "MATCHED_UWI": "", "INVENTORY_ID": f"BCPDIAG{i}"}
        for i, f in enumerate(files)]
log(f"\ncalling run_bcp_capture on {len(recs)} rec(s), MATCHED_UWI='' (as pipeline does)...")

# capture counts before
import pyodbc
c = pyodbc.connect(odbc, autocommit=True).cursor()
def cnt():
    return {
        "cat_well_LAS": c.execute("SELECT COUNT(*) FROM file_catalog.cat_well WHERE SOURCE='LAS_HEADER'").fetchone()[0],
        "cat_well_all": c.execute("SELECT COUNT(*) FROM file_catalog.cat_well").fetchone()[0],
        "curves": c.execute("SELECT COUNT(*) FROM file_catalog.cat_well_log_curve").fetchone()[0],
        "well_hdr": c.execute("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER").fetchone()[0],
    }
before = cnt(); log("before:", before)

try:
    res = run_bcp_capture(recs, conn_str=odbc, workers=4, log=lambda m: log("  bcp:", m))
    log("\nRETURN:", repr(res))
    log("sum(values):", sum(res.values()) if hasattr(res,"values") else "n/a")
except Exception as e:
    log("\n!!! run_bcp_capture RAISED:")
    log(traceback.format_exc())

after = cnt(); log("\nafter:", after)
log("delta cat_well_LAS:", after["cat_well_LAS"]-before["cat_well_LAS"])
log("delta curves:", after["curves"]-before["curves"])
log("delta FILE_WELL_HEADER:", after["well_hdr"]-before["well_hdr"])
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

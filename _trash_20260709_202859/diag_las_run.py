"""diag_las_run.py — run the REAL _do_las on one of the 20 LAS files and capture what
actually happens: the say() messages (which include caught exceptions) and any
uncaught traceback. This tells us why header+curves write nothing.
  py diag_las_run.py --file "C:\\path\\to\\17_031_10176_0000.las"
  py diag_las_run.py --dir  "C:\\...\\training\\test_crawl"
writes to file."""
import sys, os, glob, traceback
OUT = r"C:\Bulk\reports\las_run.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

# find a LAS file
f = None
if "--file" in sys.argv:
    f = sys.argv[sys.argv.index("--file")+1]
elif "--dir" in sys.argv:
    d = sys.argv[sys.argv.index("--dir")+1]
    g = glob.glob(os.path.join(d,"**","*.las"), recursive=True)
    f = g[0] if g else None
else:
    for d in (r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl",
              r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl_4"):
        g = glob.glob(os.path.join(d,"**","*.las"), recursive=True)
        if g: f = g[0]; break
if not f or not os.path.exists(f):
    log("no LAS file found — pass --file or --dir"); open(OUT,"w").write("\n".join(L)); raise SystemExit
log("testing:", f)

# capture say() output
says = []
def say(m): says.append(str(m)); log("  say:", m)

# build the engine the same way the app does
try:
    from db_pool import get_engine
    engine = get_engine()
except Exception:
    try:
        from sqlalchemy import create_engine
        engine = create_engine(
            "mssql+pyodbc://@localhost\\SQLEXPRESS/DataView_Demo"
            "?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&Encrypt=no")
    except Exception as e:
        log("engine build failed:", e); open(OUT,"w").write("\n".join(L)); raise SystemExit

import worker_core
inv = "DIAG_LAS_TEST"
log("\n=== calling _do_las directly ===")
try:
    res = worker_core._do_las(engine, f, None, inv, say)
    log("RESULT status:", getattr(res,"status",None), "rows_written:", getattr(res,"rows_written",None))
    log("detail:", getattr(res,"detail",None))
except Exception as e:
    log("\n!!! UNCAUGHT EXCEPTION in _do_las:")
    log(traceback.format_exc())

log("\n=== all say() messages ===")
for s in says: log("  ", s)
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

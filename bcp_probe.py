"""bcp_probe.py — prints ONLY the few critical verdicts, each prefixed >>> so they're
easy to spot/paste even if console output is noisy. Paste the >>> lines into chat.
py bcp_probe.py --dir "C:\\...\\las_files" """
import sys, os, glob, traceback

def out(tag, msg):
    print(f">>> {tag}: {msg}", flush=True)

d = None
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
files = []
if d: files = glob.glob(os.path.join(d, "**", "*.las"), recursive=True)
if not files:
    for cand in (r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\las_files",
                 r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl"):
        files += glob.glob(os.path.join(cand, "**", "*.las"), recursive=True)
out("LAS_FILES", len(files))
if not files:
    sys.exit()

odbc = ("DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\\SQLEXPRESS;"
        "DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")

# A) parse one file
try:
    try: from bcp_capture import parse_las_rows, run_bcp_capture
    except Exception: from modules.bcp_capture import parse_las_rows, run_bcp_capture
    out("IMPORT", "ok")
except Exception as e:
    out("IMPORT", "FAILED " + str(e)[:80]); sys.exit()

try:
    o = parse_las_rows((files[0], "", "PROBE1", False))
    out("PARSE_cat_well", len(o.get("cat_well", [])))
    out("PARSE_curves", len(o.get("cat_well_log_curve", [])))
    if o.get("cat_well"):
        out("PARSE_uwi", repr(o["cat_well"][0].get("uwi")))
    else:
        out("PARSE_uwi", "NONE — parser skipped the file")
except Exception as e:
    out("PARSE", "RAISED " + str(e)[:80])

# B) BULK INSERT temp-path test (the prime suspect)
import pyodbc
c = pyodbc.connect(odbc, autocommit=True).cursor()
try:
    os.makedirs(r"C:\bcp_tmp", exist_ok=True)
    tp = r"C:\bcp_tmp\_probe.tsv"
    open(tp, "w", encoding="utf-8").write("1\ttest\n")
    c.execute("IF OBJECT_ID('tempdb..#p') IS NOT NULL DROP TABLE #p")
    c.execute("CREATE TABLE #p (a nvarchar(max), b nvarchar(max))")
    try:
        c.execute("BULK INSERT #p FROM '" + tp + "' WITH (FIELDTERMINATOR='\\t', ROWTERMINATOR='0x0a')")
        out("BULK_INSERT", f"OK ({c.execute('SELECT COUNT(*) FROM #p').fetchone()[0]} row) — SQL can read C:\\bcp_tmp")
    except Exception as e:
        out("BULK_INSERT", "FAILED — " + str(e)[:120])
except Exception as e:
    out("BULK_PROBE", "err " + str(e)[:80])

# C) full run on all files, before/after delta
def n(w=""):
    try: return c.execute(f"SELECT COUNT(*) FROM file_catalog.cat_well {w}").fetchone()[0]
    except Exception: return -1
before = n("WHERE SOURCE='LAS_HEADER'")
recs = [{"FILE_PATH": f, "MATCHED_UWI": "", "INVENTORY_ID": f"PROBE{i}"} for i, f in enumerate(files)]
try:
    res = run_bcp_capture(recs, conn_str=odbc, workers=4, log=lambda *_: None)
    out("RUN_RETURN", repr(res))
except Exception as e:
    out("RUN", "RAISED " + str(e)[:120])
after = n("WHERE SOURCE='LAS_HEADER'")
out("DELTA_cat_well_LAS", f"{before} -> {after}")

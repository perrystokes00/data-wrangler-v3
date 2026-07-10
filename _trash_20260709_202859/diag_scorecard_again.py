"""diag_scorecard_again.py — the per-run scorecard is empty again. Check: (1) is the
ROW_CHANGED_DATE fix deployed in modules/current_run_scorecard.py, (2) does ROW_CHANGED_DATE
actually move for the latest crawl, (3) what's the run window vs the data. py diag_scorecard_again.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\scorecard_again.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

# 1) is the fix deployed?
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
p = os.path.join(APP, "modules", "current_run_scorecard.py")
if not os.path.exists(p): p = os.path.join(APP, "current_run_scorecard.py")
log("=== 1) deployed scorecard module ===")
if os.path.exists(p):
    s = open(p, encoding="utf-8", errors="replace").read()
    log(f"  {p}")
    log(f"  uses ROW_CHANGED_DATE: {'ROW_CHANGED_DATE' in s}")
    log(f"  uses SCAN_DATE only:   {'SCAN_DATE' in s and 'ROW_CHANGED_DATE' not in s}")
    log(f"  has grace buffer:      {'timedelta' in s or 'grace' in s}")
else:
    log("  current_run_scorecard.py NOT FOUND")

c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("\n=== 2) does ROW_CHANGED_DATE move? (recent activity) ===")
log("  now(UTC): " + str(one("SELECT GETUTCDATE()")))
log("  MAX ROW_CHANGED_DATE: " + str(one("SELECT MAX(TRY_CAST(ROW_CHANGED_DATE AS DATETIME2)) FROM file_catalog.GLOBAL_FILE_CATALOG")))
log("  MAX SCAN_DATE:        " + str(one("SELECT MAX(TRY_CAST(SCAN_DATE AS DATETIME2)) FROM file_catalog.GLOBAL_FILE_CATALOG")))
for mins in (5, 30, 120):
    n = one(f"SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE TRY_CAST(ROW_CHANGED_DATE AS DATETIME2) >= DATEADD(minute,-{mins},GETUTCDATE())")
    log(f"  ROW_CHANGED_DATE within last {mins} min: {n}")

log("\n=== 3) is ROW_CHANGED_DATE even populated? ===")
log("  rows with ROW_CHANGED_DATE null: " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE ROW_CHANGED_DATE IS NULL")))
log("  rows with ROW_CHANGED_DATE set:  " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE ROW_CHANGED_DATE IS NOT NULL")))
log("  total GFC rows:                  " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG")))

log("\n=== VERDICT ===")
log("  If module still SCAN_DATE-only: redeploy current_run_scorecard.py + restart Streamlit.")
log("  If ROW_CHANGED_DATE is mostly NULL: extract/capture didn't stamp it this run")
log("  (e.g. inventory-only run, or files skipped) -> scorecard has nothing recent to show.")
log("  If ROW_CHANGED_DATE IS recent but scorecard still empty: run-start stamp (fp_run_started)")
log("  wasn't set -> the wiring patch didn't deploy / Streamlit not restarted.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

"""check_after_run.py — after reset+rerun, diagnose which 'same error' persists:
(A) did LAS capture? (B) did capture run at all? (C) scorecard window sanity.
writes to file. py check_after_run.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\after_run.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== A) LAS capture state NOW ===")
rows = c.execute("SELECT FILE_NAME, CATALOG_READINESS, CAPTURED_HASH, FILE_HASH, HEADER_EXTRACTED FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' ORDER BY FILE_NAME").fetchall()
blocked = sum(1 for r in rows if r[2] is not None and r[2] == r[3])
elig = len(rows) - blocked
for r in rows[:3]:
    log(f"   sample: {r[0]} ready={r[1]} chash={'set' if r[2] else 'NULL'} extracted={r[4]}")
log(f"   LAS still HASH-blocked: {blocked}   eligible: {elig}   total: {len(rows)}")
log("   cat_well from LAS_HEADER: " + str(one("SELECT COUNT(*) FROM file_catalog.cat_well WHERE SOURCE='LAS_HEADER'")))
log("   cat_well total:           " + str(one("SELECT COUNT(*) FROM file_catalog.cat_well")))
log("   cat_well_log_curve total: " + str(one("SELECT COUNT(*) FROM file_catalog.cat_well_log_curve")))

log("\n=== B) did capture run at all? (CAPTURED_HASH re-stamped after the reset?) ===")
log("   files WITH CAPTURED_HASH now: " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE CAPTURED_HASH IS NOT NULL")))
log("   .las WITH CAPTURED_HASH now:  " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' AND CAPTURED_HASH IS NOT NULL")))
log("   (0 = capture never ran; >0 on .las = capture ran and re-stamped them)")

log("\n=== C) cat table capture recency ===")
for t in ("cat_well", "cat_well_log_curve", "cat_well_formation_top"):
    log(f"   {t}: rows=" + str(one(f"SELECT COUNT(*) FROM file_catalog.{t}")) +
        " last_captured=" + str(one(f"SELECT MAX(CAPTURED_AT) FROM file_catalog.{t}")))

log("\n=== D) scorecard window sanity ===")
log("   SCAN_DATE min=" + str(one("SELECT MIN(TRY_CAST(SCAN_DATE AS DATETIME2)) FROM file_catalog.GLOBAL_FILE_CATALOG")))
log("   SCAN_DATE max=" + str(one("SELECT MAX(TRY_CAST(SCAN_DATE AS DATETIME2)) FROM file_catalog.GLOBAL_FILE_CATALOG")))
log("   now(UTC)=      " + str(one("SELECT GETUTCDATE()")))
open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("\n>>> written to", OUT, "— upload it")

"""check_demo_fresh.py — DataView_Demo ONLY. After the crawl, show the actual newest rows
and their timestamps so we see if the crawl wrote here and which column (if any) is stale.
py check_demo_fresh.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\demo_fresh.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:45]}"

log("  connected DB: " + str(one("SELECT DB_NAME()")))
log("  now local:    " + str(one("SELECT GETDATE()")))
log("  now UTC:      " + str(one("SELECT GETUTCDATE()")))
log("  total rows:   " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG")))

log("\n=== the 10 MOST RECENTLY scanned rows (by SCAN_DATE) ===")
try:
    for r in c.execute("SELECT TOP 10 FILE_NAME, SCAN_DATE, ROW_CREATED_DATE, ROW_CHANGED_DATE, FILE_PATH FROM file_catalog.GLOBAL_FILE_CATALOG ORDER BY TRY_CAST(SCAN_DATE AS DATETIME2) DESC").fetchall():
        log(f"  scan={r[1]}  changed={r[3]}  {r[0]}")
except Exception as e:
    log("  err: " + str(e)[:60])

log("\n=== distinct SCAN_DATE values present (are there ANY from today?) ===")
try:
    for r in c.execute("SELECT LEFT(SCAN_DATE,16) d, COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG GROUP BY LEFT(SCAN_DATE,16) ORDER BY d DESC").fetchall()[:10]:
        log(f"  {r[0]}: {r[1]}")
except Exception as e:
    log("  err: " + str(e)[:60])

log("\n=== sample_pdfs rows: their timestamps ===")
try:
    for r in c.execute("SELECT FILE_NAME, SCAN_DATE, ROW_CHANGED_DATE FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_PATH LIKE '%sample_pdfs%' ORDER BY FILE_NAME").fetchall():
        log(f"  {r[0]}  scan={r[1]}  changed={r[2]}")
except Exception as e:
    log("  err: " + str(e)[:60])

open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

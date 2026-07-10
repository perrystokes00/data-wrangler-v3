"""check_crawl_landed.py — you just ran a crawl but the DB showed no today-activity.
Did it land? Check newest timestamps, today's counts, and what ROOT_PATH/paths exist now.
py check_crawl_landed.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\crawl_landed.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:45]}"

log("  now (server local): " + str(one("SELECT GETDATE()")))
log("  now (UTC):          " + str(one("SELECT GETUTCDATE()")))

log("\n=== newest timestamps RIGHT NOW ===")
log("  MAX SCAN_DATE:        " + str(one("SELECT MAX(TRY_CAST(SCAN_DATE AS DATETIME2)) FROM file_catalog.GLOBAL_FILE_CATALOG")))
log("  MAX ROW_CREATED_DATE: " + str(one("SELECT MAX(TRY_CAST(ROW_CREATED_DATE AS DATETIME2)) FROM file_catalog.GLOBAL_FILE_CATALOG")))
log("  MAX ROW_CHANGED_DATE: " + str(one("SELECT MAX(TRY_CAST(ROW_CHANGED_DATE AS DATETIME2)) FROM file_catalog.GLOBAL_FILE_CATALOG")))
log("  total GFC rows:       " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG")))

log("\n=== scanned in the last 15 minutes (your just-finished crawl) ===")
log("  by SCAN_DATE:        " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE TRY_CAST(SCAN_DATE AS DATETIME2) >= DATEADD(minute,-15,GETUTCDATE())")))
log("  by ROW_CREATED_DATE: " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE TRY_CAST(ROW_CREATED_DATE AS DATETIME2) >= DATEADD(minute,-15,GETUTCDATE())")))
log("  also try LOCAL time (in case scan stamps local not UTC):")
log("  by SCAN_DATE (local):" + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE TRY_CAST(SCAN_DATE AS DATETIME2) >= DATEADD(minute,-15,GETDATE())")))

log("\n=== ROOT_PATH values + newest scan each ===")
try:
    for r in c.execute("SELECT ROOT_PATH, COUNT(*), MAX(TRY_CAST(SCAN_DATE AS DATETIME2)) FROM file_catalog.GLOBAL_FILE_CATALOG GROUP BY ROOT_PATH ORDER BY MAX(TRY_CAST(SCAN_DATE AS DATETIME2)) DESC").fetchall():
        log(f"  {r[1]:5}  last={r[2]}  {r[0]}")
except Exception as e:
    log("  err: " + str(e)[:60])

log("\n=== is sample_pdfs in the catalog at all? ===")
log("  rows with FILE_PATH containing sample_pdfs: " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_PATH LIKE '%sample_pdfs%'")))
log("  rows with FILE_PATH containing test_crawl:  " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_PATH LIKE '%test_crawl%'")))

log("\n=== which DATABASE am I connected to? (sanity: is the app using the same one?) ===")
log("  DB name:     " + str(one("SELECT DB_NAME()")))
log("  server name: " + str(one("SELECT @@SERVERNAME")))
log("  instance:    " + str(one("SELECT SERVERPROPERTY('InstanceName')")))

log("\n=== VERDICT ===")
log("  If a 15-min count is >0: the crawl DID land — the earlier check was just before it.")
log("  If still 0 and MAX dates are yesterday: the crawl isn't writing to THIS db/instance")
log("  -> the app may be pointed at a different DB, or the crawl errored before insert.")
log("  Compare DB_NAME/instance above with what the app connects to.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

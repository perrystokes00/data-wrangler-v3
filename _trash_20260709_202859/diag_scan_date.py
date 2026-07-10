"""diag_scan_date.py — why does the per-run scorecard show 'No files scanned'?
Show the actual SCAN_DATE strings stored vs the format I compare against, so we can fix
the (string) comparison. writes to file. py diag_scan_date.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\scan_date.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

log("=== raw SCAN_DATE values (as stored, NVARCHAR) ===")
rows = c.execute("""SELECT TOP 10 FILE_NAME, SCAN_DATE,
    LEN(SCAN_DATE) AS len FROM file_catalog.GLOBAL_FILE_CATALOG
    ORDER BY SCAN_DATE DESC""").fetchall()
for r in rows:
    log(f"   {r[1]!r}  (len={r[2]})  {r[0]}")

log("\n=== distinct SCAN_DATE formats present ===")
rows = c.execute("""SELECT LEFT(SCAN_DATE,19) AS d, COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE SCAN_DATE IS NOT NULL GROUP BY LEFT(SCAN_DATE,19) ORDER BY d DESC""").fetchall()
for r in rows[:8]:
    log(f"   {r[0]!r}: {r[1]} files")

log("\n=== MIN/MAX SCAN_DATE + is it castable to datetime? ===")
r = c.execute("""SELECT MIN(SCAN_DATE), MAX(SCAN_DATE),
    SUM(CASE WHEN TRY_CAST(SCAN_DATE AS DATETIME2) IS NULL THEN 1 ELSE 0 END) AS uncastable,
    COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE SCAN_DATE IS NOT NULL""").fetchone()
log(f"   MIN={r[0]!r}  MAX={r[1]!r}")
log(f"   uncastable to datetime: {r[2]} of {r[3]}")

log("\n=== how many files scanned in the last hour (datetime compare, the RIGHT way)? ===")
for mins in (60, 240, 1440):
    n = c.execute(f"""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE TRY_CAST(SCAN_DATE AS DATETIME2) >= DATEADD(minute,-{mins},GETUTCDATE())""").fetchone()[0]
    log(f"   scanned in last {mins} min: {n}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

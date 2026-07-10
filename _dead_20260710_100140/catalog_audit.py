"""catalog_audit.py — why does extract show far more 'ok' than files on disk?
Checks for duplicate catalog rows vs a re-processing loop. Read-only.
Run: py catalog_audit.py"""
import pyodbc
cn = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = cn.cursor()
one = lambda q: cur.execute(q).fetchone()[0]

total   = one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG")
d_path  = one("SELECT COUNT(DISTINCT FILE_PATH) FROM file_catalog.GLOBAL_FILE_CATALOG")
d_inv   = one("SELECT COUNT(DISTINCT INVENTORY_ID) FROM file_catalog.GLOBAL_FILE_CATALOG")
d_hash  = one("SELECT COUNT(DISTINCT FILE_HASH) FROM file_catalog.GLOBAL_FILE_CATALOG")
print(f"total rows        : {total:,}")
print(f"distinct FILE_PATH: {d_path:,}")
print(f"distinct INV_ID   : {d_inv:,}")
print(f"distinct FILE_HASH: {d_hash:,}")

print("\nHEADER_EXTRACTED breakdown:")
for r in cur.execute("SELECT ISNULL(HEADER_EXTRACTED,'(null)') s, COUNT(*) n "
                     "FROM file_catalog.GLOBAL_FILE_CATALOG "
                     "GROUP BY HEADER_EXTRACTED ORDER BY n DESC"):
    print(f"  {r.s:8} {r.n:,}")

print("\nFILE_PATHs with more than one row (top 10):")
dups = cur.execute("SELECT TOP 10 FILE_PATH, COUNT(*) n "
                   "FROM file_catalog.GLOBAL_FILE_CATALOG "
                   "GROUP BY FILE_PATH HAVING COUNT(*) > 1 ORDER BY n DESC").fetchall()
if not dups:
    print("  (none — each path appears once)")
for r in dups:
    print(f"  {r.n}x  {r.FILE_PATH}")

print("\n=> Read:")
print("   total >> distinct FILE_PATH  -> DUPLICATE inventory rows (scan not deduping)")
print("   total ~= distinct FILE_PATH  -> catalog is fine; the 'ok' count was a")
print("                                   re-processing loop (HEADER_EXTRACTED not set)")

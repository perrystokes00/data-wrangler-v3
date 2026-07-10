"""catalog_breakdown.py — show what the catalog actually crawled: by crawl root,
by year folder, and by scan date. Explains a bigger-than-expected count."""
import pyodbc
cn = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = cn.cursor()

print("=== files by crawl ROOT_PATH (each distinct root you ran on) ===")
for r in cur.execute(
        "SELECT ROOT_PATH, COUNT(*) n, MIN(SCAN_DATE) firsts, MAX(SCAN_DATE) lasts "
        "FROM file_catalog.GLOBAL_FILE_CATALOG "
        "GROUP BY ROOT_PATH ORDER BY COUNT(*) DESC"):
    print(f"  {r.n:6,}  {r.ROOT_PATH}")
    print(f"          first scan {r.firsts}  ·  last {r.lasts}")

print("\n=== files by year folder (parsed from FILE_PATH) ===")
for r in cur.execute(r"""
    SELECT SUBSTRING(FILE_PATH, CHARINDEX('LAS Files\', FILE_PATH)+10, 4) AS yr,
           COUNT(*) AS n
    FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE FILE_PATH LIKE '%LAS Files\%'
    GROUP BY SUBSTRING(FILE_PATH, CHARINDEX('LAS Files\', FILE_PATH)+10, 4)
    ORDER BY n DESC"""):
    print(f"  {r.n:6,}  year {r.yr}")

print("\n=== files by scan date (when they entered the catalog) ===")
for r in cur.execute(
        "SELECT CAST(SCAN_DATE AS DATE) d, COUNT(*) n "
        "FROM file_catalog.GLOBAL_FILE_CATALOG "
        "GROUP BY CAST(SCAN_DATE AS DATE) ORDER BY d"):
    print(f"  {r.d}: {r.n:,}")

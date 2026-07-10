"""reconcile.py — split the 564 pending into content-duplicates (intentionally
skipped) vs a real backlog, and reconcile catalog vs LAS files on disk."""
import pyodbc
from pathlib import Path

LAS_ROOT = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\las_files"

cn = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = cn.cursor()
one = lambda q: cur.execute(q).fetchone()[0]

pend_dupe = one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG "
                "WHERE HEADER_EXTRACTED IS NULL AND DUPLICATE_GROUP IS NOT NULL")
pend_real = one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG "
                "WHERE HEADER_EXTRACTED IS NULL AND DUPLICATE_GROUP IS NULL "
                "AND ISNULL(FLAG_DELETE,'N')<>'Y'")
print(f"pending & duplicate (skipped by design) : {pend_dupe:,}")
print(f"pending & NOT duplicate (real backlog)  : {pend_real:,}")

# reconcile disk vs catalog for the LAS tree
if Path(LAS_ROOT).exists():
    disk = sum(1 for _ in Path(LAS_ROOT).rglob("*.las"))
    cat_las = one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG "
                  "WHERE FILE_EXT='.las'")
    print(f"\n.las on disk under root : {disk:,}")
    print(f".las rows in catalog    : {cat_las:,}")

print("\n=> pend_real 0  -> nothing stuck; the 564 are just duplicates (all good)")
print("   pend_real >0 -> real backlog; deploy the write fix + re-run to clear it")

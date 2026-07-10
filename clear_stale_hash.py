"""clear_stale_hash.py — clear CAPTURED_HASH on .las files that have NO cat_well row
(the stamp bug marked them captured without capturing). Uses an aliased correlated
subquery so the join is correct. py clear_stale_hash.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
T = "file_catalog.GLOBAL_FILE_CATALOG"
f = lambda q: c.execute(q).fetchone()[0]

print("before:")
print("  .las CAPTURED_HASH set        :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las' AND CAPTURED_HASH IS NOT NULL"))

# correct correlated delete: g is the outer catalog row, w is cat_well
n = c.execute(f"""
    UPDATE g SET g.CAPTURED_HASH = NULL
    FROM {T} g
    WHERE LOWER(g.FILE_EXT) = '.las'
      AND g.CAPTURED_HASH IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM file_catalog.cat_well w
                      WHERE w.INVENTORY_ID = g.INVENTORY_ID)""").rowcount
print(f"\ncleared CAPTURED_HASH on {n} .las file(s) with no cat_well row")

sel = f(f"""SELECT COUNT(*) FROM {T} g WHERE LOWER(g.FILE_EXT)='.las'
    AND ISNULL(g.FLAG_DELETE,'N')<>'Y'
    AND ISNULL(g.CATALOG_READINESS,'') NOT IN ('SKIPPED','CATALOGED')
    AND g.DUPLICATE_GROUP IS NULL
    AND (g.CAPTURED_HASH IS NULL OR g.CAPTURED_HASH <> g.FILE_HASH)""")
print(f"\nafter — capture would now select: {sel} .las file(s)  (expect ~400)")

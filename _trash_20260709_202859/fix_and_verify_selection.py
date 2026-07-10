"""fix_and_verify_selection.py — clear the stale CAPTURED_HASH (which the reset left
set on 402 uncaptured files) and re-check what capture would now select.
py fix_and_verify_selection.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
T = "file_catalog.GLOBAL_FILE_CATALOG"
f = lambda q: c.execute(q).fetchone()[0]

# confirm the paradox: CAPTURED_HASH set but no cat_well row
print("before fix:")
print("  .las with CAPTURED_HASH set  :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las' AND CAPTURED_HASH IS NOT NULL"))
print("  ...of those, WITH cat_well row:", f(f"""SELECT COUNT(*) FROM {T} g WHERE LOWER(g.FILE_EXT)='.las'
      AND g.CAPTURED_HASH IS NOT NULL AND EXISTS
      (SELECT 1 FROM file_catalog.cat_well w WHERE w.INVENTORY_ID=g.INVENTORY_ID)"""))

# clear the stale stamp
n = c.execute(f"UPDATE {T} SET CAPTURED_HASH=NULL WHERE LOWER(FILE_EXT)='.las' "
              f"AND NOT EXISTS (SELECT 1 FROM file_catalog.cat_well w WHERE w.INVENTORY_ID=INVENTORY_ID)").rowcount
print(f"\ncleared CAPTURED_HASH on {n} .las file(s) with no cat_well row")

# re-check the full capture selection
sel = f(f"""SELECT COUNT(*) FROM {T} g WHERE LOWER(g.FILE_EXT)='.las'
    AND ISNULL(g.FLAG_DELETE,'N')<>'Y'
    AND ISNULL(g.CATALOG_READINESS,'') NOT IN ('SKIPPED','CATALOGED')
    AND g.DUPLICATE_GROUP IS NULL
    AND (g.CAPTURED_HASH IS NULL OR g.CAPTURED_HASH <> g.FILE_HASH)""")
print(f"\nafter fix — capture would now select: {sel} .las file(s)")
print("(expect ~402 — the non-duplicate LAS files)")

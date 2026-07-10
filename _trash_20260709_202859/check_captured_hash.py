"""check_captured_hash.py — is CAPTURED_HASH stamped on files that have NO cat_well
row? That would make capture skip them forever. py check_captured_hash.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]
print("CAPTURED_HASH set (non-null) :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE CAPTURED_HASH IS NOT NULL"))
print("  ...but NO cat_well row     :", f("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
     WHERE g.CAPTURED_HASH IS NOT NULL AND NOT EXISTS
     (SELECT 1 FROM file_catalog.cat_well w WHERE w.INVENTORY_ID=g.INVENTORY_ID)"""))
print("  ...WITH a cat_well row     :", f("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
     WHERE g.CAPTURED_HASH IS NOT NULL AND EXISTS
     (SELECT 1 FROM file_catalog.cat_well w WHERE w.INVENTORY_ID=g.INVENTORY_ID)"""))
print("\n=> if 'NO cat_well row' > 0, the fingerprint stamp is marking uncaptured files")
print("   captured, so capture skips them on every later run. That's the bug.")

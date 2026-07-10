"""reset_stuck.py — reset extracted-but-not-captured files to pending so the next
run captures them. py reset_stuck.py"""
import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
n = cur.execute("""UPDATE file_catalog.GLOBAL_FILE_CATALOG
    SET HEADER_EXTRACTED='N', CATALOG_READINESS=NULL, ROW_CHANGED_DATE=GETUTCDATE()
    WHERE HEADER_EXTRACTED='Y' AND INVENTORY_ID NOT IN
    (SELECT INVENTORY_ID FROM file_catalog.cat_well WHERE INVENTORY_ID IS NOT NULL)""").rowcount
print(f"reset {n} stuck file(s) to pending")
print("now re-run: Use all CPU cores ON, Batch mode OFF, scan root = _selected")

"""diag_ui_capture.py — why did the UI capture only 2? Check UWI resolution state
that capture depends on. py diag_ui_capture.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]

print("=== catalog UWI-resolution state (what capture keys on) ===")
print("  GLOBAL_FILE_CATALOG total :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG"))
print("  HEADER_EXTRACTED='Y'      :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE HEADER_EXTRACTED='Y'"))
print("  MATCHED_UWI not null      :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE MATCHED_UWI IS NOT NULL"))
print("  CATALOG_READINESS values  :")
for r in c.execute("SELECT ISNULL(CATALOG_READINESS,'(null)'), COUNT(*) "
                   "FROM file_catalog.GLOBAL_FILE_CATALOG GROUP BY CATALOG_READINESS").fetchall():
    print(f"       {r[0]:20} {r[1]}")

print("\n=== FILE_WELL_HEADER (capture reads UWI from here for LAS) ===")
print("  FILE_WELL_HEADER rows     :", f("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER"))
print("  with UWI14                :", f("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER WHERE UWI14 IS NOT NULL"))

print("\n=== the capture selection: docs 'with a UWI' ===")
# capture logs 'N document(s) with a UWI'. Replicate roughly:
try:
    n = f("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
             WHERE g.HEADER_EXTRACTED='Y'
               AND (g.MATCHED_UWI IS NOT NULL
                    OR EXISTS (SELECT 1 FROM file_catalog.FILE_WELL_HEADER h
                               WHERE h.INVENTORY_ID=g.INVENTORY_ID AND h.UWI14 IS NOT NULL))""")
    print("  docs with a resolvable UWI:", n)
except Exception as e:
    print("  (query err:", str(e)[:60], ")")

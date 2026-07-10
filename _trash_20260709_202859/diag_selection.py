"""diag_selection.py — replicate the capture-stage SELECT and see WHY only ~2 files
pass. Tests each WHERE condition separately. py diag_selection.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]

T = "file_catalog.GLOBAL_FILE_CATALOG"
print("total .las in catalog        :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las'"))
print()
print("-- capture SELECT conditions, peeled one at a time (for .las) --")
print("FILE_EXT='.las' (self-parsing):", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las'"))
print("  & FLAG_DELETE<>'Y'          :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las' AND ISNULL(FLAG_DELETE,'N')<>'Y'"))
print("  & READINESS NOT IN(SKIP,CAT):", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las' AND ISNULL(CATALOG_READINESS,'') NOT IN ('SKIPPED','CATALOGED')"))
print("  & DUPLICATE_GROUP IS NULL   :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las' AND DUPLICATE_GROUP IS NULL"))
print("  & CAPTURED_HASH gate        :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las' AND (CAPTURED_HASH IS NULL OR CAPTURED_HASH <> FILE_HASH)"))
print()
print("-- ALL conditions together (what capture actually selects) --")
n = f(f"""SELECT COUNT(*) FROM {T} g WHERE LOWER(g.FILE_EXT)='.las'
    AND ISNULL(g.FLAG_DELETE,'N')<>'Y'
    AND ISNULL(g.CATALOG_READINESS,'') NOT IN ('SKIPPED','CATALOGED')
    AND g.DUPLICATE_GROUP IS NULL
    AND (g.CAPTURED_HASH IS NULL OR g.CAPTURED_HASH <> g.FILE_HASH)""")
print("  capture would select        :", n)
print()
print("-- DUPLICATE_GROUP breakdown (prime suspect: dedup collapsing them) --")
for r in c.execute(f"SELECT CASE WHEN DUPLICATE_GROUP IS NULL THEN 'NULL' ELSE 'set' END, COUNT(*) "
                   f"FROM {T} WHERE LOWER(FILE_EXT)='.las' GROUP BY CASE WHEN DUPLICATE_GROUP IS NULL THEN 'NULL' ELSE 'set' END").fetchall():
    print(f"     DUPLICATE_GROUP {r[0]:5}: {r[1]}")
print()
print("-- CATALOG_READINESS breakdown --")
for r in c.execute(f"SELECT ISNULL(CATALOG_READINESS,'(null)'), COUNT(*) FROM {T} "
                   f"WHERE LOWER(FILE_EXT)='.las' GROUP BY CATALOG_READINESS").fetchall():
    print(f"     {r[0]:15}: {r[1]}")

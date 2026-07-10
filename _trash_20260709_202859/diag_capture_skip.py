"""diag_capture_skip.py — why does BCP capture write 2 of 402? Check what the LAS
headers hold vs what capture needs. py diag_capture_skip.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]

print("cat_well rows                :", f("SELECT COUNT(*) FROM file_catalog.cat_well"))
print("FILE_WELL_HEADER rows        :", f("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER"))
print("  header UWI14 not null      :", f("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER WHERE UWI14 IS NOT NULL"))
print("  header UWI14 valid 14-dig  :", f("""SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER
     WHERE UWI14 IS NOT NULL AND LEN(RTRIM(UWI14))=14 AND UWI14 NOT LIKE '%[^0-9]%'"""))

print("\n-- sample header UWI14 values (what capture reads) --")
for r in c.execute("SELECT TOP 8 UWI14, LEN(RTRIM(UWI14)) FROM file_catalog.FILE_WELL_HEADER "
                   "WHERE UWI14 IS NOT NULL").fetchall():
    print("   ", repr(r[0]), "len", r[1])

print("\n-- the 2 that DID capture: what's different? --")
for r in c.execute("""SELECT TOP 5 w.uwi, h.UWI14, g.MATCHED_UWI
     FROM file_catalog.cat_well w
     LEFT JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID=w.INVENTORY_ID
     LEFT JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID=w.INVENTORY_ID""").fetchall():
    print("   cat_well.uwi:", repr(r[0]), "| header UWI14:", repr(r[1]), "| MATCHED_UWI:", repr(r[2]))

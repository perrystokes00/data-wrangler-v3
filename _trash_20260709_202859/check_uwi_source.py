"""check_uwi_source.py — where does the KGS UWI come from? Filename? Header? Confirm
so we know what to resolve before capture. py check_uwi_source.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
print("sample: FILE_NAME vs the header UWI14 it resolved to")
for r in c.execute("""SELECT TOP 10 g.FILE_NAME, h.UWI14
    FROM file_catalog.GLOBAL_FILE_CATALOG g
    JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID=g.INVENTORY_ID
    WHERE h.UWI14 IS NOT NULL""").fetchall():
    print(f"   {r[0]:45} -> {r[1]}")
print("\n=> if the FILE_NAME contains the UWI digits, the UWI comes from the filename")
print("   (enrich/triage parse it), NOT the LAS header — so capture needs MATCHED_UWI")
print("   populated BEFORE it runs.")

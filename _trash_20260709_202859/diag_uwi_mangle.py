"""diag_uwi_mangle.py — is the UWI stored as scientific notation (4.23171E+13) in
the catalog + cat_ tables, breaking the join to dv_well? py diag_uwi_mangle.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

print("=== how is the ANADARKO UWI stored in each place? ===")
# catalog
print("\nGLOBAL_FILE_CATALOG (the doc files):")
for r in c.execute("""SELECT FILE_NAME, MATCHED_UWI, UWI14 FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE FILE_NAME LIKE '%ANADARKO%' OR FILE_NAME='Formation_Tops.xlsx'""").fetchall():
    print(f"   {str(r[0])[:40]:40} MATCHED_UWI={r[1]!r}  UWI14={r[2]!r}")

# cat_ dir survey
print("\ncat_well_dir_srvy_hdr (staged, not promoted):")
try:
    for r in c.execute("SELECT DISTINCT UWI FROM file_catalog.cat_well_dir_srvy_hdr").fetchall():
        print(f"   UWI={r[0]!r}")
except Exception as e:
    print("   ", e)

# what dv_well actually has
print("\ndv_well (the target — what promote joins to):")
for r in c.execute("""SELECT uwi FROM dataview.dv_well
    WHERE uwi LIKE '4231712345%' OR uwi LIKE '42317%'""").fetchall():
    print(f"   uwi={r[0]!r}")

print("\n=== the smoking gun ===")
print("If cat_ UWI = '4.23171E+13' but dv_well uwi = '42317123450000',")
print("the join fails and promote can't lift the rows. Excel mangled the UWI")
print("to scientific notation during xlsx read.")

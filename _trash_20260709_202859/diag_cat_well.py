"""diag_cat_well.py — cat_well has 10 rows but 0 with SOURCE='LAS_HEADER'. What ARE
they, and do they have UWIs/coords? And did the 20 LAS files each try to write a
header? writes to file. py diag_cat_well.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\cat_well.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

log("=== all cat_well rows: UWI, SOURCE, coords, INVENTORY_ID ===")
try:
    rows = c.execute("""SELECT UWI, SOURCE, SURFACE_LATITUDE, SURFACE_LONGITUDE,
        WELL_NAME, INVENTORY_ID FROM file_catalog.cat_well""").fetchall()
    for r in rows:
        log(f"   uwi={r[0]!r} src={r[1]!r} lat={r[2]} lon={r[3]} name={r[4]!r} inv={r[5]}")
except Exception as e:
    log("   err:", str(e)[:80])

log("\n=== distinct SOURCE values in cat_well ===")
for r in c.execute("SELECT SOURCE, COUNT(*) FROM file_catalog.cat_well GROUP BY SOURCE").fetchall():
    log(f"   {r[0]!r}: {r[1]}")

log("\n=== the 20 .las files: INVENTORY_ID + do they have a cat_well row? ===")
try:
    rows = c.execute("""SELECT g.FILE_NAME, g.INVENTORY_ID, g.HEADER_EXTRACTED,
        CASE WHEN EXISTS(SELECT 1 FROM file_catalog.cat_well w WHERE w.INVENTORY_ID=g.INVENTORY_ID)
             THEN 'has cat_well' ELSE 'NO cat_well' END,
        CASE WHEN EXISTS(SELECT 1 FROM file_catalog.cat_well_log_curve cc WHERE cc.INVENTORY_ID=g.INVENTORY_ID)
             THEN 'has curves' ELSE 'no curves' END
        FROM file_catalog.GLOBAL_FILE_CATALOG g WHERE g.FILE_EXT='.las'""").fetchall()
    for r in rows:
        log(f"   {r[0]}  inv={r[1]}  extracted={r[2]}  {r[3]}  {r[4]}")
except Exception as e:
    log("   err:", str(e)[:80])

log("\n=== does cat_well_log_curve carry UWI, and is it populated? ===")
try:
    rows = c.execute("""SELECT TOP 5 UWI, INVENTORY_ID, curve_mnem
        FROM file_catalog.cat_well_log_curve""").fetchall()
    for r in rows:
        log(f"   uwi={r[0]!r} inv={r[1]} mnem={r[2]!r}")
except Exception as e:
    # column name may differ
    try:
        cols = [x[0] for x in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='cat_well_log_curve'").fetchall()]
        log("   cat_well_log_curve cols:", cols)
    except Exception as e2:
        log("   err:", str(e2)[:60])
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

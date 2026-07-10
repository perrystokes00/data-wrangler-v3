"""check_las_load.py — did the LAS files actually load end to end?
LAS produces: cat_well header -> dv_well, plus cat_well_log/curve -> dv_well_log/curve.
Checks each stage so we see exactly how far LAS got. writes to file. py check_las_load.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\las_load.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

def one(q, *a):
    try:
        return c.execute(q, *a).fetchone()[0]
    except Exception as e:
        return f"ERR {str(e)[:40]}"

log("=== 1) LAS files in the catalog ===")
log("   .las inventoried:", one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las'"))
log("   .las extracted:  ", one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' AND HEADER_EXTRACTED='Y'"))

log("\n=== 2) LAS well headers (cat_well) ===")
log("   cat_well total:           ", one("SELECT COUNT(*) FROM file_catalog.cat_well"))
log("   cat_well from LAS_HEADER:  ", one("SELECT COUNT(*) FROM file_catalog.cat_well WHERE SOURCE='LAS_HEADER'"))
log("   cat_well held (PROMOTED=0):", one("SELECT COUNT(*) FROM file_catalog.cat_well WHERE PROMOTED=0"))

log("\n=== 3) did LAS wells reach dv_well? ===")
log("   dv_well total:", one("SELECT COUNT(*) FROM dataview.dv_well"))

log("\n=== 4) LAS log + curve data ===")
log("   cat_well_log total:      ", one("SELECT COUNT(*) FROM file_catalog.cat_well_log"),
    " held:", one("SELECT COUNT(*) FROM file_catalog.cat_well_log WHERE PROMOTED=0"))
log("   cat_well_log_curve total:", one("SELECT COUNT(*) FROM file_catalog.cat_well_log_curve"),
    " held:", one("SELECT COUNT(*) FROM file_catalog.cat_well_log_curve WHERE PROMOTED=0"))
log("   dv_well_log:             ", one("SELECT COUNT(*) FROM dataview.dv_well_log"))
log("   dv_well_log_curve:       ", one("SELECT COUNT(*) FROM dataview.dv_well_log_curve"))

log("\n=== 5) sample LAS files: UWI + is the well in dv_well? ===")
NORM = "LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),w.UWI),'-',''),' ',''),'/','')))+'00000000000000',14)"
q = ("SELECT TOP 8 g.FILE_NAME, w.UWI, "
     "CASE WHEN EXISTS(SELECT 1 FROM dataview.dv_well d WHERE d.uwi=" + NORM + ") "
     "THEN 'in dv_well' ELSE 'MISSING' END "
     "FROM file_catalog.GLOBAL_FILE_CATALOG g "
     "LEFT JOIN file_catalog.cat_well w ON w.INVENTORY_ID=g.INVENTORY_ID "
     "WHERE g.FILE_EXT='.las'")
try:
    for r in c.execute(q).fetchall():
        log("  ", r[0], " uwi=", r[1], " ", r[2])
except Exception as e:
    log("   sample err:", str(e)[:60])

open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("\n>>> written to", OUT, "— upload it")

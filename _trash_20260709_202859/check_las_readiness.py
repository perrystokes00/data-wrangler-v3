"""check_las_readiness.py — LAS data promoted, but the report says not promoted. Is it
PROMOTED_AT (gated on CATALOG_READINESS='CATALOGED') never getting set because LAS stay
at READY? py check_las_readiness.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\las_readiness.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:35]}"

log("=== LAS: readiness + promoted_at distribution ===")
for r in c.execute("SELECT CATALOG_READINESS, COUNT(*), SUM(CASE WHEN PROMOTED_AT IS NOT NULL THEN 1 ELSE 0 END) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' GROUP BY CATALOG_READINESS").fetchall():
    log(f"  readiness={r[0]!r}: {r[1]} files, {r[2]} with PROMOTED_AT")

q_cat = "SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' AND CATALOG_READINESS='CATALOGED'"
q_rdy = "SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' AND CATALOG_READINESS='READY'"
log("\n=== promote stamp rule: PROMOTED_AT set WHERE CATALOG_READINESS='CATALOGED' ===")
log("  LAS at CATALOGED: " + str(one(q_cat)))
log("  LAS at READY:     " + str(one(q_rdy)))

q_dv = ("SELECT COUNT(DISTINCT w.uwi) FROM file_catalog.cat_well cw "
        "JOIN dataview.dv_well w ON w.uwi = LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),cw.uwi),'-',''),' ',''),'/','')))+'00000000000000',14) "
        "WHERE cw.SOURCE='LAS_HEADER'")
log("\n=== did their data actually promote? ===")
log("  LAS wells that reached dv_well: " + str(one(q_dv)))
log("  dv_well_log_curve total:        " + str(one("SELECT COUNT(*) FROM dataview.dv_well_log_curve")))

log("\n=== VERDICT ===")
log("  If LAS are at READY with data in dv_well: report is wrong (PROMOTED_AT gated on")
log("  CATALOGED, which LAS never reach). Fix = credit LAS promoted when data in dv_*.")
open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("\n>>> written to", OUT, "— upload it")

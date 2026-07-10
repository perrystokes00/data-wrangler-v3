"""check_crawl_result.py — 9 PDFs extracted but only 1 cataloged, 0 promoted. Why?
Check each file's resolved UWI, readiness, and whether cat_* / dv_* got rows. py check_crawl_result.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\crawl_result.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== per-file: resolved UWI + readiness + extract status ===")
for r in c.execute("""SELECT g.FILE_NAME, g.MATCHED_UWI, g.HEADER_EXTRACTED, g.CATALOG_READINESS,
    wh.REPORT_TYPE, wh.UWI, g.CATALOG_ISSUES
    FROM file_catalog.GLOBAL_FILE_CATALOG g
    LEFT JOIN file_catalog.FILE_WELL_HEADER wh ON wh.INVENTORY_ID=g.INVENTORY_ID
    WHERE g.FILE_EXT='.pdf' ORDER BY g.FILE_NAME""").fetchall():
    log(f"  {r[0]}")
    log(f"      matched_uwi={r[1]!r} header_uwi={r[5]!r} type={r[4]} extracted={r[2]} ready={r[3]}" + (f" issue={r[6][:50]}" if r[6] else ""))

log("\n=== does MAYBERRY (15007243240000) exist in dv_well with coords? ===")
log("  " + str(one("SELECT well_name FROM dataview.dv_well WHERE uwi='15007243240000'")) + " coords=" + str(one("SELECT CONVERT(varchar,surface_latitude)+','+CONVERT(varchar,surface_longitude) FROM dataview.dv_well WHERE uwi='15007243240000'")))

log("\n=== what landed in cat_* mirrors? ===")
for t in ("cat_well","cat_well_formation_top","cat_prod_volume","cat_well_completion","cat_well_dir_srvy_sta","cat_well_dst","cat_well_petro_interp"):
    log(f"  {t}: " + str(one(f"SELECT COUNT(*) FROM file_catalog.{t}")))

log("\n=== promote gate: is the coord check the blocker? ===")
log("  REQUIRE_WELL_COORDS holds wells with no coords. MAYBERRY HAS coords, so if UWI")
log("  resolved to it, promote should work. If matched_uwi is blank/wrong above, that's why.")

log("\n=== why only 1 cataloged? which file got cat_well? ===")
for r in c.execute("SELECT DISTINCT INVENTORY_ID, uwi FROM file_catalog.cat_well").fetchall():
    fn = one("SELECT FILE_NAME FROM file_catalog.GLOBAL_FILE_CATALOG WHERE INVENTORY_ID=?", r[0])
    log(f"  cat_well: {fn}  uwi={r[1]}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

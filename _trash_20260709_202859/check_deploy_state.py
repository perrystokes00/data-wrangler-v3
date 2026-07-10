"""check_deploy_state.py — did the fixes deploy, and why are docs still unpromoted?
Checks: (1) are the reference codes seeded now? (2) are document rows still held in
cat_*? (3) what would promote say. Writes to file. py check_deploy_state.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\deploy_state.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

log("=== 1) are the deep-loader reference codes seeded? ===")
for code in ("DATA_LOADER","OFFICE","WITSML","DLIS"):
    n = c.execute("SELECT COUNT(*) FROM dataview.dv_r_source WHERE source=?", code).fetchone()[0]
    log(f"   dv_r_source '{code}': {'YES' if n else 'NO  <-- not seeded'}")
for code in ("ft","FT","BBL","MCF","0.1 in"):
    n = c.execute("SELECT COUNT(*) FROM dataview.dv_r_uom WHERE uom_code=?", code).fetchone()[0]
    log(f"   dv_r_uom '{code}': {'YES' if n else 'NO  <-- not seeded'}")

log("\n=== 2) are document rows still staged/held in cat_*? ===")
for t in ("cat_well_formation_top","cat_well_dir_srvy_hdr","cat_well_dir_srvy_sta","cat_prod_volume"):
    try:
        tot = c.execute(f"SELECT COUNT(*) FROM file_catalog.{t}").fetchone()[0]
        p0  = c.execute(f"SELECT COUNT(*) FROM file_catalog.{t} WHERE PROMOTED=0").fetchone()[0]
        log(f"   {t}: total={tot}  PROMOTED=0(held)={p0}")
    except Exception as e:
        log(f"   {t}: {str(e)[:40]}")

log("\n=== 3) already-promoted document data in dv_*? ===")
for t in ("dv_well_formation_top","dv_well_dir_srvy_sta","dv_prod_volume"):
    n = c.execute(f"SELECT COUNT(*) FROM dataview.{t}").fetchone()[0]
    log(f"   {t}: {n} rows")

log("\n=== verdict ===")
src_ok = c.execute("SELECT COUNT(*) FROM dataview.dv_r_source WHERE source='OFFICE'").fetchone()[0]
if not src_ok:
    log("   entity_seeder fix NOT deployed (OFFICE missing) — deploy + reseed first.")
else:
    held = c.execute("SELECT COUNT(*) FROM file_catalog.cat_well_formation_top WHERE PROMOTED=0").fetchone()[0]
    if held:
        log(f"   codes seeded but {held} tops still held — run promote to lift them.")
    else:
        log("   seeded and nothing held — should be promoted.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

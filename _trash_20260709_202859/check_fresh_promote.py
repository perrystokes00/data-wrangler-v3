"""check_fresh_promote.py — after the fresh crawl, did document DATA land in dv_*?
The inventory CSV's 'promoted' column is a per-file PROMOTED_AT flag (only stamped
for seismic/header files), so it shows blank for docs even when their data promoted.
This checks dv_* directly. writes to file. py check_fresh_promote.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\fresh_promote.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

log("=== document DATA in dv_* (did it promote?) ===")
for t in ("dv_well_formation_top","dv_well_dir_srvy_hdr","dv_well_dir_srvy_sta",
          "dv_well_completion","dv_prod_volume","dv_prod_entity","dv_well_log_curve",
          "dv_well_petro_interp","dv_well_pressure","dv_well_dst","dv_well_core"):
    try:
        n = c.execute(f"SELECT COUNT(*) FROM dataview.{t}").fetchone()[0]
        log(f"  {t}: {n}")
    except Exception as e:
        log(f"  {t}: {str(e)[:40]}")

log("\n=== still held in cat_* + WHY ===")
NORM=("LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/','')))+'00000000000000',14)")
for cat in ("cat_well_formation_top","cat_prod_volume","cat_well_dir_srvy_hdr",
            "cat_well_dir_srvy_sta","cat_well_completion"):
    try:
        held = c.execute(f"SELECT COUNT(*) FROM file_catalog.{cat} WHERE PROMOTED=0").fetchone()[0]
        if not held:
            log(f"  {cat}: 0 held (all promoted)"); continue
        no_well = c.execute(f"""SELECT COUNT(*) FROM file_catalog.{cat} m WHERE m.PROMOTED=0
            AND NOT EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi={NORM.format(col='m.UWI')})""").fetchone()[0]
        log(f"  {cat}: {held} held ({no_well} missing well, {held-no_well} other)")
    except Exception as e:
        log(f"  {cat}: {str(e)[:40]}")

log("\n=== how many wells exist in dv_well? (parents for the doc data) ===")
n = c.execute("SELECT COUNT(*) FROM dataview.dv_well").fetchone()[0]
log(f"  dv_well: {n}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

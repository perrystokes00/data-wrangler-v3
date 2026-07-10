"""check_held_now.py — after the repair + clean promote, what's still held and why?
Should be ONLY missing-parent-well rows now (correct governance). writes to file."""
import pyodbc, os
OUT = r"C:\Bulk\reports\held_now.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
NORM=("LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/','')))+'00000000000000',14)")

log("=== what's still held, and why? ===")
for cat in ("cat_well_formation_top","cat_prod_volume","cat_well_dir_srvy_hdr",
            "cat_well_dir_srvy_sta","cat_well_completion","cat_well_log_curve"):
    try:
        held = c.execute(f"SELECT COUNT(*) FROM file_catalog.{cat} WHERE PROMOTED=0").fetchone()[0]
        if not held:
            log(f"  {cat}: CLEAN (0 held)"); continue
        no_well = c.execute(f"""SELECT COUNT(*) FROM file_catalog.{cat} m WHERE m.PROMOTED=0
            AND NOT EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi={NORM.format(col='m.UWI')})""").fetchone()[0]
        reason = "all missing parent well (correct)" if no_well==held else f"{no_well} missing well, {held-no_well} OTHER"
        log(f"  {cat}: {held} held -> {reason}")
    except Exception as e:
        log(f"  {cat}: {str(e)[:50]}")

log("\n=== dv_* document data totals (what promoted) ===")
for t in ("dv_well_formation_top","dv_well_dir_srvy_sta","dv_prod_volume","dv_well_completion"):
    n = c.execute(f"SELECT COUNT(*) FROM dataview.{t}").fetchone()[0]
    log(f"  {t}: {n}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

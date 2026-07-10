"""probe_remap_targets.py — for a test remap, find (a) a good existing dv_well UWI with
coords to use as the target parent, and (b) every held cat_* table + its UWI column that
needs updating so the doc data promotes under the new UWI. py probe_remap_targets.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\remap_targets.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== candidate TARGET wells: existing dv_well UWIs WITH coords ===")
rows = c.execute("""SELECT TOP 5 uwi, well_name, surface_latitude, surface_longitude
    FROM dataview.dv_well
    WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
    ORDER BY uwi""").fetchall()
for r in rows:
    log(f"  {r[0]}  {r[1]!r}  ({r[2]},{r[3]})")
log(f"  total dv_well with coords: {one('SELECT COUNT(*) FROM dataview.dv_well WHERE surface_latitude IS NOT NULL')}")

log("\n=== held cat_* tables with PROMOTED=0 rows + their UWI column ===")
# find cat_ tables that have a UWI-ish column and held rows
cat_tabs = [r[0] for r in c.execute("""SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME LIKE 'cat[_]%'""").fetchall()]
for t in cat_tabs:
    cols = [r[0] for r in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME=?", t).fetchall()]
    uwicol = next((x for x in cols if x.upper()=="UWI"), None)
    hasprom = any(x.upper()=="PROMOTED" for x in cols)
    if uwicol and hasprom:
        held = one(f"SELECT COUNT(*) FROM file_catalog.{t} WHERE PROMOTED=0")
        if isinstance(held,int) and held>0:
            log(f"  {t}: {held} held rows (UWI col='{uwicol}')")

log("\n=== the held UWIs (distinct across held cat_* rows) ===")
for t in ("cat_well_formation_top","cat_prod_volume","cat_well_completion","cat_well_dir_srvy_hdr","cat_well_dir_srvy_sta"):
    try:
        uwis = [r[0] for r in c.execute(f"SELECT DISTINCT UWI FROM file_catalog.{t} WHERE PROMOTED=0").fetchall()]
        if uwis:
            log(f"  {t}: {uwis}")
    except Exception:
        pass
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

"""check_gold_cols.py — what columns does well_master_gold have, and which UWIs from
the held document rows exist in gold? This tells us we CAN bootstrap wells from gold.
writes to file. py check_gold_cols.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\gold_cols.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

log("=== well_master_gold columns ===")
try:
    cols = c.execute("""SELECT COLUMN_NAME, DATA_TYPE FROM WELL_REF.INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME='well_master_gold' ORDER BY ORDINAL_POSITION""").fetchall()
    for cn, dt in cols:
        log(f"   {cn} ({dt})")
except Exception as e:
    log(f"   err: {str(e)[:80]}")

log("\n=== of the held-for-missing-well UWIs, how many ARE in gold? ===")
NORM=("LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/','')))+'00000000000000',14)")
for cat in ("cat_well_formation_top","cat_prod_volume","cat_well_dir_srvy_hdr"):
    try:
        # distinct held UWIs (missing parent well)
        held_uwis = c.execute(f"""SELECT DISTINCT {NORM.format(col='m.UWI')}
            FROM file_catalog.{cat} m WHERE m.PROMOTED=0
            AND NOT EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi={NORM.format(col='m.UWI')})""").fetchall()
        uwis = [r[0] for r in held_uwis if r[0]]
        in_gold = 0
        for u in uwis:
            n = c.execute("SELECT COUNT(*) FROM WELL_REF.well_ref.well_master_gold WHERE uwi14=?", u).fetchone()[0]
            if n: in_gold += 1
        log(f"   {cat}: {len(uwis)} distinct held wells, {in_gold} of them ARE in gold")
        if uwis[:5]:
            log(f"      sample held UWIs: {uwis[:5]}")
    except Exception as e:
        log(f"   {cat}: err {str(e)[:60]}")

# do those gold rows have coords?
log("\n=== do the in-gold held wells have coords? ===")
try:
    sample = c.execute(f"""SELECT TOP 5 g.uwi14, g.surface_latitude, g.surface_longitude, g.well_name
        FROM WELL_REF.well_ref.well_master_gold g
        WHERE g.uwi14 IN (
            SELECT DISTINCT {NORM.format(col='m.UWI')} FROM file_catalog.cat_well_formation_top m
            WHERE m.PROMOTED=0 AND NOT EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi={NORM.format(col='m.UWI')})
        )""").fetchall()
    for r in sample:
        log(f"   {r[0]}  lat={r[1]} lon={r[2]}  {r[3]}")
except Exception as e:
    log(f"   err: {str(e)[:80]}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

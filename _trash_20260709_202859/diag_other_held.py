"""diag_other_held.py — the 33 tops / 216 prod held with a parent well AND seeded
codes: are they DUPLICATES of rows already in dv_* (re-captured by re-crawl)? Or
held on some other predicate? writes to file. py diag_other_held.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\other_held.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

NORM = ("LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/','')))+'00000000000000',14)")

# For prod_volume: is each held row's (uwi, prod month/date) already in dv_prod_volume?
log("=== cat_prod_volume: are the 216 'other-held' rows already in dv_prod_volume? ===")
try:
    # held rows WITH a parent well (the 216)
    total_other = c.execute(f"""
        SELECT COUNT(*) FROM file_catalog.cat_prod_volume m
        WHERE m.PROMOTED=0
          AND EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi={NORM.format(col='m.UWI')})
    """).fetchone()[0]
    log(f"   held with parent well: {total_other}")
    # how many of those already exist in dv_prod_volume (same uwi + prod_date)?
    # find the date column
    cols = [r[0] for r in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME='dv_prod_volume'").fetchall()]
    log(f"   dv_prod_volume cols: {cols}")
    datecol = next((x for x in cols if 'date' in x.lower() or 'period' in x.lower() or 'prod' in x.lower()), None)
    log(f"   using date-ish column: {datecol}")
except Exception as e:
    log(f"   err: {str(e)[:80]}")

# Simpler: does dv_prod_volume already hold this well's data? (count per well)
log("\n=== per-well: cat_ held vs dv_ existing (prod_volume) ===")
try:
    rows = c.execute(f"""
        SELECT {NORM.format(col='m.UWI')} AS uwi,
               COUNT(*) AS held_in_cat,
               (SELECT COUNT(*) FROM dataview.dv_prod_volume d WHERE d.uwi={NORM.format(col='m.UWI')}) AS in_dv
        FROM file_catalog.cat_prod_volume m
        WHERE m.PROMOTED=0
          AND EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi={NORM.format(col='m.UWI')})
        GROUP BY {NORM.format(col='m.UWI')}
    """).fetchall()
    for r in rows:
        flag = "<-- already in dv_ (likely dup)" if r[2] and r[2] >= r[1] else ""
        log(f"   uwi={r[0]}  held_in_cat={r[1]}  already_in_dv={r[2]}  {flag}")
except Exception as e:
    log(f"   err: {str(e)[:80]}")

# same for formation tops
log("\n=== per-well: cat_ held vs dv_ existing (formation_top) ===")
try:
    rows = c.execute(f"""
        SELECT {NORM.format(col='m.UWI')} AS uwi,
               COUNT(*) AS held_in_cat,
               (SELECT COUNT(*) FROM dataview.dv_well_formation_top d WHERE d.uwi={NORM.format(col='m.UWI')}) AS in_dv
        FROM file_catalog.cat_well_formation_top m
        WHERE m.PROMOTED=0
          AND EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi={NORM.format(col='m.UWI')})
        GROUP BY {NORM.format(col='m.UWI')}
    """).fetchall()
    for r in rows:
        flag = "<-- already in dv_ (likely dup)" if r[2] and r[2] >= r[1] else ""
        log(f"   uwi={r[0]}  held_in_cat={r[1]}  already_in_dv={r[2]}  {flag}")
except Exception as e:
    log(f"   err: {str(e)[:80]}")

open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

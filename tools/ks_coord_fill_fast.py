"""
ks_coord_fill_fast.py — same as ks_coord_fill but stages ONLY the wells that need
coords (~hundreds), not all 477K. Reads ks_wells.txt into a dict, matches the
cat_well/dv_well UWIs that are missing coords, stages just those, updates.

  py ks_coord_fill_fast.py           # preview
  py ks_coord_fill_fast.py --apply   # fill cat_well (un-promote) + dv_well (geog)
  py ks_coord_fill_fast.py --file "C:\\...\\ks_wells.txt"
"""
import sys, os, urllib.parse as _u
import pandas as pd
from sqlalchemy import create_engine, text

KS = sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else \
     r"C:\Users\perry\OneDrive\Documents\KSGS\ks_wells.txt"
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN),
                    fast_executemany=True)

def norm14(v):
    d = "".join(c for c in str(v) if c.isdigit())
    return (d + "00000000000000")[:14] if len(d) >= 10 else None

# 1) ks_wells.txt -> {uwi14: (lat, lon)}  (vectorized read, dict build)
df = pd.read_csv(KS, dtype=str)
cols = {c.lower().strip(): c for c in df.columns}
uc = next((cols[k] for k in ("api_num_nodash", "uwi14", "uwi") if k in cols), None)
la = next((cols[k] for k in ("latitude", "lat") if k in cols), None)
lo = next((cols[k] for k in ("longitude", "lon") if k in cols), None)
api   = df[uc].fillna("").str.replace(r"\D", "", regex=True)
uwi14 = (api + "00000000000000").str[:14]
lat   = pd.to_numeric(df[la], errors="coerce")
lon   = pd.to_numeric(df[lo], errors="coerce")
m = (api.str.len() >= 10) & lat.notna() & lon.notna() & ~((lat == 0) & (lon == 0))
coords = dict(zip(uwi14[m], zip(lat[m], lon[m])))
print(f"ks_wells.txt: {len(df):,} rows -> {len(coords):,} wells with coords")

# 2) which cat_well / dv_well UWIs need coords?
with eng.begin() as c:
    cw = [r[0] for r in c.execute(text(
        "SELECT DISTINCT UWI FROM file_catalog.cat_well w "
        "WHERE (w.SURFACE_LATITUDE IS NULL OR w.SURFACE_LONGITUDE IS NULL "
        "OR (w.SURFACE_LATITUDE=0 AND w.SURFACE_LONGITUDE=0)) AND UWI IS NOT NULL"))]
    dv = [r[0] for r in c.execute(text(
        "SELECT DISTINCT uwi FROM dataview.dv_well "
        "WHERE (surface_latitude IS NULL OR surface_longitude IS NULL "
        "OR (surface_latitude=0 AND surface_longitude=0)) AND uwi IS NOT NULL"))]

need = {norm14(u) for u in cw} | {norm14(u) for u in dv}
need.discard(None)
have = [(u, coords[u][0], coords[u][1]) for u in need if u in coords]
print(f"cat_well needing coords: {len(set(norm14(u) for u in cw)):,}  "
      f"dv_well: {len(set(norm14(u) for u in dv)):,}")
print(f"of those, ks_wells.txt can fill: {len(have):,}")

if not have:
    print("nothing to fill."); sys.exit(0)
if "--apply" not in sys.argv:
    print("\n[dry run] add --apply to fill.")
    sys.exit(0)

# 3) stage only the needed rows (tiny), then set-based UPDATE
sdf = pd.DataFrame(have, columns=["uwi14", "lat", "lon"])
with eng.begin() as c:
    c.execute(text("IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg')"))
    c.execute(text("IF OBJECT_ID('stg.ks_coord') IS NOT NULL DROP TABLE stg.ks_coord"))
sdf.to_sql("ks_coord", eng, schema="stg", if_exists="replace", index=False)

CW_NORM = ("LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(w.UWI)),'-',''),' ',''),"
           "'/',''),'.',''),'_','') + '00000000000000', 14)")
with eng.begin() as c:
    n1 = c.execute(text(
        f"UPDATE w SET w.SURFACE_LATITUDE=k.lat, w.SURFACE_LONGITUDE=k.lon, w.PROMOTED=0 "
        f"FROM file_catalog.cat_well w JOIN stg.ks_coord k ON k.uwi14={CW_NORM} "
        f"WHERE (w.SURFACE_LATITUDE IS NULL OR w.SURFACE_LONGITUDE IS NULL "
        f"OR (w.SURFACE_LATITUDE=0 AND w.SURFACE_LONGITUDE=0))")).rowcount
    n2 = c.execute(text(
        "UPDATE w SET w.surface_latitude=k.lat, w.surface_longitude=k.lon "
        "FROM dataview.dv_well w JOIN stg.ks_coord k ON k.uwi14=w.uwi "
        "WHERE (w.surface_latitude IS NULL OR w.surface_longitude IS NULL "
        "OR (w.surface_latitude=0 AND w.surface_longitude=0))")).rowcount
    g = c.execute(text(
        "UPDATE dataview.dv_well SET geog=geography::Point(surface_latitude,surface_longitude,4326) "
        "WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL "
        "AND NOT (surface_latitude=0 AND surface_longitude=0)")).rowcount
    c.execute(text("DROP TABLE stg.ks_coord"))
print(f"\nfilled cat_well {n1:,} (un-promoted) · dv_well {n2:,} · geog {g:,}")
print("next: re-run promote, then  py run_h3.py --all  &&  py grids.py")

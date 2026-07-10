"""
ks_coord_fill.py — fill Kansas well coords from ks_wells.txt (the authoritative
KS header file: API_NUM_NODASH=UWI14 + LATITUDE/LONGITUDE). Gold has ~0.3% of KS,
so this is the real source. Fills held cat_well (clears PROMOTED so they promote)
AND already-promoted dv_well (0,0) rows (rebuilds geog). Vectorized for 516k rows.

  py ks_coord_fill.py           # preview
  py ks_coord_fill.py --apply   # fill cat_well + dv_well
  py ks_coord_fill.py --file "C:\\...\\ks_wells.txt"
"""
import sys, os, urllib.parse as _u
import pandas as pd
from sqlalchemy import create_engine, text

KS = sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else \
     r"C:\Users\perry\OneDrive\Documents\KSGS\ks_wells.txt"
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))

df = pd.read_csv(KS, dtype=str)
cols = {c.lower().strip(): c for c in df.columns}
uc = next((cols[k] for k in ("api_num_nodash", "uwi14", "uwi") if k in cols), None)
la = next((cols[k] for k in ("latitude", "lat") if k in cols), None)
lo = next((cols[k] for k in ("longitude", "lon") if k in cols), None)
if not (uc and la and lo):
    sys.exit(f"need UWI/lat/lon cols. found: {list(df.columns)}")

api   = df[uc].fillna("").str.replace(r"\D", "", regex=True)
uwi14 = (api + "00000000000000").str[:14]
lat   = pd.to_numeric(df[la], errors="coerce")
lon   = pd.to_numeric(df[lo], errors="coerce")
m = (api.str.len() >= 10) & lat.notna() & lon.notna() & ~((lat == 0) & (lon == 0))
out = pd.DataFrame({"uwi14": uwi14[m], "lat": lat[m], "lon": lon[m]}).drop_duplicates("uwi14")
print(f"ks_wells.txt: {len(df):,} rows -> {len(out):,} wells with usable coords")

with eng.begin() as c:
    c.execute(text("IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg')"))
    c.execute(text("IF OBJECT_ID('stg.ks_coord') IS NOT NULL DROP TABLE stg.ks_coord"))
out.to_sql("ks_coord", eng, schema="stg", if_exists="replace", index=False, chunksize=20000)
with eng.begin() as c:
    c.execute(text("CREATE INDEX IX_ks_coord ON stg.ks_coord(uwi14)"))

CW_NORM = ("LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(w.UWI)),'-',''),' ',''),"
           "'/',''),'.',''),'_','') + '00000000000000', 14)")
CW_MISS = ("(w.SURFACE_LATITUDE IS NULL OR w.SURFACE_LONGITUDE IS NULL "
           "OR (w.SURFACE_LATITUDE = 0 AND w.SURFACE_LONGITUDE = 0))")
DV_MISS = ("(w.surface_latitude IS NULL OR w.surface_longitude IS NULL "
           "OR (w.surface_latitude = 0 AND w.surface_longitude = 0))")

with eng.begin() as c:
    cwf = c.execute(text(f"SELECT COUNT(*) FROM file_catalog.cat_well w "
                         f"JOIN stg.ks_coord k ON k.uwi14 = {CW_NORM} WHERE {CW_MISS}")).scalar()
    dvf = c.execute(text(f"SELECT COUNT(*) FROM dataview.dv_well w "
                         f"JOIN stg.ks_coord k ON k.uwi14 = w.uwi WHERE {DV_MISS}")).scalar()
print(f"cat_well fillable : {cwf:,}")
print(f"dv_well  fillable : {dvf:,}")

if "--apply" not in sys.argv:
    print("\n[dry run] add --apply to fill cat_well (un-promote) + dv_well (rebuild geog).")
    with eng.begin() as c:
        c.execute(text("DROP TABLE stg.ks_coord"))
    sys.exit(0)

with eng.begin() as c:
    n1 = c.execute(text(
        f"UPDATE w SET w.SURFACE_LATITUDE = k.lat, w.SURFACE_LONGITUDE = k.lon, w.PROMOTED = 0 "
        f"FROM file_catalog.cat_well w JOIN stg.ks_coord k ON k.uwi14 = {CW_NORM} WHERE {CW_MISS}")).rowcount
    n2 = c.execute(text(
        f"UPDATE w SET w.surface_latitude = k.lat, w.surface_longitude = k.lon "
        f"FROM dataview.dv_well w JOIN stg.ks_coord k ON k.uwi14 = w.uwi WHERE {DV_MISS}")).rowcount
    g = c.execute(text(
        "UPDATE dataview.dv_well SET geog = geography::Point(surface_latitude, surface_longitude, 4326) "
        "WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL "
        "AND NOT (surface_latitude = 0 AND surface_longitude = 0)")).rowcount
    c.execute(text("DROP TABLE stg.ks_coord"))
print(f"\nfilled cat_well: {n1:,} (un-promoted)   dv_well: {n2:,}   geog rebuilt: {g:,}")
print("next: re-run promote, then  py run_h3.py --all  &&  py grids.py")

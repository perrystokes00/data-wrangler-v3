"""check_held_coord_sources.py — the 10 held wells aren't in well_header.csv. Where COULD
their coords come from? Check: (1) the documents themselves (do the PDFs/surveys carry
lat/long that extract captured somewhere), (2) the gold reference (WELL_MASTER),
(3) FILE_WELL_HEADER (LATITUDE/LONGITUDE cols). py check_held_coord_sources.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\held_coord_sources.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

held = ["17717123400000","42135222220000","42227111110000","42227087650000",
        "42461209870000","42317678900000","42301456780000","03912345000000","35101100450000"]

log("=== 1) does FILE_WELL_HEADER have LAT/LONG for these held wells? (extract may have captured coords) ===")
for u in held:
    r = one(f"SELECT TOP 1 CONVERT(varchar(20),LATITUDE)+','+CONVERT(varchar(20),LONGITUDE) FROM file_catalog.FILE_WELL_HEADER WHERE UWI14=? OR UWI=?", u, u)
    log(f"  {u}: FILE_WELL_HEADER coords = {r}")

log("\n=== 2) is each held well in the gold reference WELL_MASTER (with coords)? ===")
for u in held:
    r = one(f"SELECT TOP 1 CONVERT(varchar(20),SURFACE_LATITUDE)+','+CONVERT(varchar(20),SURFACE_LONGITUDE) FROM WELL_REF.well_ref.WELL_MASTER WHERE UWI14=?", u)
    log(f"  {u}: gold coords = {r}")

log("\n=== 3) does cat_well itself already have coords under a DIFFERENT source row for these? ===")
for u in held[:5]:
    n = one(f"SELECT COUNT(*) FROM file_catalog.cat_well WHERE LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),uwi),'-',''),' ',''),'/','')))+'00000000000000',14)=? AND surface_latitude IS NOT NULL", u)
    log(f"  {u}: cat_well rows WITH coords = {n}")

log("\n=== VERDICT ===")
log("  Best coord source wins: if FILE_WELL_HEADER (1) or gold (2) has coords for these")
log("  wells, backfill cat_well.surface_lat/lon from there -> they promote. If NONE have")
log("  coords, these wells genuinely have no coordinates anywhere and are CORRECTLY held")
log("  until a coordinate source is provided (a header CSV that includes THEM, or manual).")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

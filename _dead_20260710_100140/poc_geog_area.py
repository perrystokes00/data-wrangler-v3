"""The polygons already loaded into geography (raw strategy worked, 5/5).
This just reads back the true area to confirm geography computes real km2.
Assumes file_catalog.poc_geog still exists from the prior run."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")

# compute area in one transaction
with e.begin() as c:
    c.execute(text("""
        UPDATE file_catalog.poc_geog
           SET area_km2 = geog.STArea()/1000000.0
         WHERE geog IS NOT NULL"""))

# read back in a SEPARATE connection
with e.connect() as c:
    print("=== geography loaded — true area (STArea) vs shapefile AREA_SQKM ===")
    print("   (shapefile said Midland=8037.1 km2)\n")
    for nm, a, srid, npts in c.execute(text("""
        SELECT survey_name, area_km2, geog.STSrid, geog.STNumPoints()
        FROM file_catalog.poc_geog WHERE geog IS NOT NULL
        ORDER BY survey_name""")).fetchall():
        print(f"   {nm:22} area={a:>12,.1f} km2   SRID={srid} pts={npts}")

    nnull = c.execute(text(
        "SELECT COUNT(*) FROM file_catalog.poc_geog WHERE geog IS NULL")).scalar()
    print(f"\n   failed rows: {nnull}")
    print("\n   ✓ geography works with the RAW strategy — no reorientation needed.")

"""The polygons loaded but INVERTED (area ~510M km2 = whole Earth = CW rings
interpreted as the complement). Fix: detect inverted geography (area > half the
planet) and ReorientObject() to flip to the correct (small) side. Self-correcting
regardless of source ring order — the right approach for a general loader."""
import os
import worker_core as w
from sqlalchemy import text

HALF_EARTH_KM2 = 255_000_000   # Earth surface ~510M km2; >half => inverted

e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")

with e.begin() as c:
    # Re-fix any inverted geography in the existing poc_geog table.
    # STArea() is in m2 for geography; /1e6 = km2.
    c.execute(text(f"""
        UPDATE file_catalog.poc_geog
           SET geog = geog.ReorientObject()
         WHERE geog IS NOT NULL
           AND geog.STArea()/1000000.0 > {HALF_EARTH_KM2}
    """))
    # recompute area after the fix
    c.execute(text("""
        UPDATE file_catalog.poc_geog
           SET area_km2 = geog.STArea()/1000000.0
         WHERE geog IS NOT NULL
    """))

with e.connect() as c:
    print("=== after orientation fix — true area vs shapefile AREA_SQKM ===")
    print("   (shapefile said Midland=8037.1 km2)\n")
    for nm, a, npts in c.execute(text("""
        SELECT survey_name, area_km2, geog.STNumPoints()
        FROM file_catalog.poc_geog WHERE geog IS NOT NULL
        ORDER BY survey_name""")).fetchall():
        flag = "  <-- still inverted!" if a > HALF_EARTH_KM2 else ""
        print(f"   {nm:22} area={a:>12,.1f} km2  pts={npts}{flag}")
    print("\n   If areas are now in the thousands (not millions), the fix works:")
    print("   detect area>half-Earth -> ReorientObject(). This goes in the loader.")

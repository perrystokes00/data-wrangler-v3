"""eligible=0 but cat_land_tract has 30 rows. Are they PROMOTED=1 already,
or is TRACT_NAME blank (DBF column mismatch)?"""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== cat_land_tract: PROMOTED + TRACT_NAME state ===")
    for prom, cnt in c.execute(text("""
        SELECT PROMOTED, COUNT(*) FROM file_catalog.cat_land_tract
        GROUP BY PROMOTED""")).fetchall():
        print(f"   PROMOTED={prom}: {cnt} rows")
    nn = c.execute(text("""SELECT COUNT(*) FROM file_catalog.cat_land_tract
        WHERE NULLIF(LTRIM(RTRIM(TRACT_NAME)),'') IS NOT NULL""")).scalar()
    print(f"   rows with non-blank TRACT_NAME: {nn}")

    print("\n=== sample rows (what actually got captured) ===")
    for row in c.execute(text("""
        SELECT TOP 6 TRACT_NAME, LEASE_NUMBER, OPERATOR_NAME, PROVINCE_STATE,
               CASE WHEN SPATIAL_OUTLINE IS NULL THEN 'NULL'
                    ELSE CAST(LEN(SPATIAL_OUTLINE) AS varchar)+'ch' END, PROMOTED
        FROM file_catalog.cat_land_tract""")).fetchall():
        print("  ", tuple(str(x)[:22] for x in row))

    print("\n=== same for cat_pipeline ===")
    for row in c.execute(text("""
        SELECT TOP 4 PIPELINE_NAME, OPERATOR_NAME, COMMODITY,
               CASE WHEN SPATIAL_OUTLINE IS NULL THEN 'NULL'
                    ELSE CAST(LEN(SPATIAL_OUTLINE) AS varchar)+'ch' END, PROMOTED
        FROM file_catalog.cat_pipeline""")).fetchall():
        print("  ", tuple(str(x)[:22] for x in row))

    # what ARE the real DBF columns for these shapefiles?
    print("\n=== actual DBF columns ===")
    import geopandas as gpd, glob, os
    base = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training"
    for pat in ("Active_Leases_TX","blocks","Pipelines_TX"):
        hits = glob.glob(os.path.join(base,"**",pat+".shp"), recursive=True)
        if hits:
            g = gpd.read_file(hits[0])
            print(f"   {pat}: {[c for c in g.columns if c!='geometry']}")

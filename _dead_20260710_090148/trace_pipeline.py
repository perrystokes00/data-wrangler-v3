"""land tracts work (30 in dv), but pipelines captured 0 this run.
Pipelines_TX classified PIPELINE. Why 0 cat_pipeline rows?
Test capture_features_to_catalog on Pipelines_TX directly."""
import worker_core as w
from sqlalchemy import text
import glob, os
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")

# find Pipelines_TX
base = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training"
hits = glob.glob(os.path.join(base,"**","Pipelines_TX.shp"), recursive=True)
p = hits[0] if hits else None
print("Pipelines_TX:", p)

if p:
    import geopandas as gpd
    gdf = gpd.read_file(p)
    print(f"features: {len(gdf)}, geom types: {sorted(gdf.geom_type.unique())}")
    print(f"columns: {[c for c in gdf.columns if c!='geometry']}")
    print(f"PIPE_NAME sample: {list(gdf['PIPE_NAME'].head(3)) if 'PIPE_NAME' in gdf.columns else 'NO PIPE_NAME COL'}")

    # call the capture directly to surface any error
    try:
        from modules.shapefile_catalog import capture_features_to_catalog
    except ImportError:
        from shapefile_catalog import capture_features_to_catalog
    # get the inventory id for pipelines
    with e.connect() as c:
        inv = c.execute(text("""SELECT TOP 1 INVENTORY_ID FROM file_catalog.GLOBAL_FILE_CATALOG
            WHERE FILE_NAME LIKE 'Pipelines%'""")).scalar()
    print("inventory_id:", inv)
    r = capture_features_to_catalog(
        file_path=p, feature_category="PIPELINE", engine=e,
        well_info={"inventory_id": inv, "source_path": p})
    print("capture result:", r)

    with e.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM file_catalog.cat_pipeline")).scalar()
        print("cat_pipeline now:", n)

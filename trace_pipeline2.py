"""capture returns loaded:0 with no error on 10 valid features.
Instrument: build ONE pipeline rec exactly as capture_features does,
call capture() with logging, see why it writes nothing."""
import worker_core as w
from sqlalchemy import text
import glob, os
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
base = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training"
p = glob.glob(os.path.join(base,"**","Pipelines_TX.shp"), recursive=True)[0]

import geopandas as gpd
gdf = gpd.read_file(p)
row = gdf.iloc[0]

# build a rec like capture_features does
rec = {"PIPELINE_NAME": "Pipeline_1", "ACTIVE_IND":"Y",
       "ROW_CREATED_BY":"DataWrangler", "ROW_CREATED_DATE":"2026-07-01 12:00:00",
       "SPATIAL_OUTLINE": row.geometry.wkt,
       "OPERATOR_NAME": str(row.get("OPERATOR")),
       "COMMODITY": str(row.get("COMMODITY")),
       "PROVINCE_STATE": "TX",
       "LENGTH_KM": 123.4}

try:
    from modules.catalog_capture import capture
except ImportError:
    from catalog_capture import capture

with e.connect() as c:
    inv = c.execute(text("""SELECT TOP 1 INVENTORY_ID FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE FILE_NAME LIKE 'Pipelines%'""")).scalar()

print("cat_pipeline columns vs rec keys:")
with e.connect() as c:
    cols = [r[0] for r in c.execute(text("""SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME='cat_pipeline'""")).fetchall()]
print("  table cols:", cols)
print("  rec keys  :", list(rec.keys()))
print("  rec keys NOT in table:", [k for k in rec if k.upper() not in [c.upper() for c in cols]])

print("\ncalling capture() with logging:")
n = capture(e, "cat_pipeline", [rec], uwi="Pipeline_1",
            inventory_id=inv, source_path=p, source="SHAPEFILE",
            log=lambda *a: print("   LOG:", *a))
print("capture returned:", n)
with e.connect() as c:
    print("cat_pipeline now:", c.execute(text("SELECT COUNT(*) FROM file_catalog.cat_pipeline")).scalar())

"""Which 2 .shp files still write seismic headers? If they're the ones NAMED
seismic (Seismic_3D_Surveys, etc.), that's correct. If not, investigate."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== the remaining .shp seismic-header rows ===")
    for sn, fname, ft in c.execute(text("""
        SELECT sh.SURVEY_NAME, g.FILE_NAME, sh.SEIS_SET_TYPE
        FROM file_catalog.FILE_SEIS_HEADER sh
        JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID=sh.INVENTORY_ID
        WHERE LOWER(g.FILE_EXT)='.shp'""")).fetchall():
        print(f"   file={fname:35} survey='{sn}' type={ft}")

    print("\n=== the .json ones (also suspect) ===")
    for sn, fname in c.execute(text("""
        SELECT sh.SURVEY_NAME, g.FILE_NAME
        FROM file_catalog.FILE_SEIS_HEADER sh
        JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID=sh.INVENTORY_ID
        WHERE LOWER(g.FILE_EXT)='.json'""")).fetchall():
        print(f"   file={fname:35} survey='{sn}'")

    print("\n=== live classify of the 2 remaining shp ===")
    import sys, os; sys.path.insert(0, ".")
    from modules.shapefile_catalog import classify_shapefile
    base = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_shapefiles"
    for f in ["Seismic_2D_Lines_Permian.shp","Seismic_3D_Surveys.shp"]:
        p = os.path.join(base, f)
        if os.path.exists(p):
            cl = classify_shapefile(p)
            print(f"   {f:32} -> {cl.get('feature_type')}")

"""Are the bogus .shp seis rows OLD (survived, no reset) or NEW (regenerated
after reset despite the fix)? Check EXTRACTED_DATE + whether the shapefiles
now classify correctly."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== bogus .shp seis rows — when were they extracted? ===")
    for sn, ed in c.execute(text("""
        SELECT sh.SURVEY_NAME, sh.EXTRACTED_DATE
        FROM file_catalog.FILE_SEIS_HEADER sh
        JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID=sh.INVENTORY_ID
        WHERE LOWER(g.FILE_EXT)='.shp'""")).fetchall():
        print(f"   '{sn}'  extracted={ed}")

    print("\n=== current time for reference ===")
    print("   now:", c.execute(text("SELECT SYSUTCDATETIME()")).scalar())

    print("\n=== how does classify_shapefile classify these NOW? (live test) ===")
    import sys
    sys.path.insert(0, ".")
    try:
        try:
            from modules.shapefile_catalog import classify_shapefile
            print("   (imported from modules.shapefile_catalog)")
        except ImportError:
            from shapefile_catalog import classify_shapefile
            print("   (imported from shapefile_catalog - ROOT)")
        for p in [r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_shapefiles\Active_Leases_TX.shp",
                  r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_shapefiles\blocks\blocks.shp"]:
            import os
            if os.path.exists(p):
                cl = classify_shapefile(p)
                print(f"   {os.path.basename(p):25} -> feature_type={cl.get('feature_type')} "
                      f"target={cl.get('ppdm_target')}")
            else:
                print(f"   NOT FOUND: {p}")
    except Exception as ex:
        import traceback; traceback.print_exc()

    print("\n=== GLOBAL_FILE_CATALOG PROC_STATUS for the shapefiles (did they reprocess?) ===")
    for fn, ps, hx in c.execute(text("""
        SELECT FILE_NAME, COALESCE(PROC_STATUS,'(null)'),
               COALESCE(CAST(HEADER_EXTRACTED AS varchar(5)),'(null)')
        FROM file_catalog.GLOBAL_FILE_CATALOG WHERE LOWER(FILE_EXT)='.shp'""")).fetchall():
        print(f"   {fn[:35]:35} status={ps} hx={hx}")

"""FIELD per-feature: 0 rows in dv_field. Trace the chain:
1. Did Oil_Fields_USA classify as FIELD?
2. Did capture_features_to_catalog write per-feature rows to cat_field?
3. Did those rows have SPATIAL_OUTLINE?
4. Is promote_field finding them (PROMOTED=0)?"""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== 1. Oil_Fields_USA in GFC — classified how? ===")
    for fn, cat, ready, hx in c.execute(text("""
        SELECT FILE_NAME, COALESCE(CATALOG_TABLE,'(null)'),
               COALESCE(CATALOG_READINESS,'(null)'),
               COALESCE(CAST(HEADER_EXTRACTED AS varchar),'(null)')
        FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE FILE_NAME LIKE '%Oil_Fields%'""")).fetchall():
        print(f"   {fn}: CATALOG_TABLE={cat} readiness={ready} hx={hx}")

    print("\n=== 2/3. cat_field rows (per-feature capture)? ===")
    try:
        rows = c.execute(text("""
            SELECT FIELD_NAME, PROVINCE_STATE, FLUID_TYPE,
                   CASE WHEN SPATIAL_OUTLINE IS NULL THEN 'NULL'
                        ELSE CAST(LEN(SPATIAL_OUTLINE) AS varchar)+'ch' END,
                   COALESCE(CAST(PROMOTED AS varchar),'(null)')
            FROM file_catalog.cat_field ORDER BY FIELD_NAME""")).fetchall()
        if not rows:
            print("   (cat_field EMPTY — capture didn't write per-feature rows)")
        for fn, st, ft, outl, prom in rows:
            print(f"   {str(fn)[:20]:20} state={st} type={ft} outline={outl} promoted={prom}")
    except Exception as ex:
        print(f"   err: {str(ex)[:80]}")

    print("\n=== 4. dv_field total ===")
    print("   dv_field rows:", c.execute(text("SELECT COUNT(*) FROM dataview.dv_field")).scalar())
    print("   dv_field with geog:", c.execute(text("SELECT COUNT(*) FROM dataview.dv_field WHERE geog IS NOT NULL")).scalar())

    print("\n=== does cat_field have SPATIAL_OUTLINE column? ===")
    col = c.execute(text("""
        SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME='cat_field' AND COLUMN_NAME='SPATIAL_OUTLINE'""")).scalar()
    print(f"   SPATIAL_OUTLINE column exists: {bool(col)}")

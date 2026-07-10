"""Did the fast (multi-core off) run actually DO the work, or skip it?
Check: were the 2 seismic files extracted, do they have SURVEY_OUTLINE,
and did geography land in dv_seis_set."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== the 2 seismic shapefiles: were they extracted? ===")
    for fn, hx, ready, cat in c.execute(text("""
        SELECT FILE_NAME,
               COALESCE(CAST(HEADER_EXTRACTED AS varchar(5)),'(null)'),
               COALESCE(CATALOG_READINESS,'(null)'),
               COALESCE(FILE_TYPE_GROUP,'(null)')
        FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE LOWER(FILE_EXT)='.shp'
          AND (FILE_NAME LIKE '%Seismic%' OR FILE_NAME LIKE '%seis%')
        ORDER BY FILE_NAME""")).fetchall():
        print(f"   {fn:35} hx={hx} ready={ready} grp={cat}")

    print("\n=== FILE_SEIS_HEADER: do they have SURVEY_OUTLINE (geometry WKT)? ===")
    rows = c.execute(text("""
        SELECT sh.SURVEY_NAME, sh.SEIS_SET_TYPE,
               CASE WHEN sh.SURVEY_OUTLINE IS NULL THEN 'NULL'
                    ELSE CAST(LEN(sh.SURVEY_OUTLINE) AS varchar) + ' chars' END,
               g.FILE_NAME, g.FILE_EXT
        FROM file_catalog.FILE_SEIS_HEADER sh
        JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID=sh.INVENTORY_ID
        WHERE LOWER(g.FILE_EXT)='.shp'""")).fetchall()
    if not rows:
        print("   (no .shp rows in FILE_SEIS_HEADER — extraction didn't write them)")
    for sn, st, outlen, fn, ext in rows:
        print(f"   {sn:28} type={st} outline={outlen}  ({fn})")

    print("\n=== dv_seis_set: geography present? ===")
    for sn, area, srid in c.execute(text("""
        SELECT seis_set_name, geog.STArea()/1000000.0, geog.STSrid
        FROM dataview.dv_seis_set WHERE geog IS NOT NULL
        ORDER BY seis_set_name""")).fetchall():
        print(f"   {sn:28} area={area:,.1f} km2 SRID={srid}")
    total = c.execute(text("SELECT COUNT(*) FROM dataview.dv_seis_set")).scalar()
    withg = c.execute(text("SELECT COUNT(*) FROM dataview.dv_seis_set WHERE geog IS NOT NULL")).scalar()
    print(f"\n   dv_seis_set: {total} total, {withg} with geography")

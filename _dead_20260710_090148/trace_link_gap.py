"""DB was empty, so every well came from a document. Yet ~168 wells have no
FILE_WELL_HEADER link. Find WHERE the link is lost: do the well-bearing files
exist in the catalog, and do they have FILE_WELL_HEADER rows written?"""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as con:
    # 1. wells in cat_well / dv_well vs wells that have a FILE_WELL_HEADER row
    print("=== 1. link coverage ===")
    for schema, tbl, uwicol in [("dataview","dv_well","uwi"),
                                ("file_catalog","cat_well","UWI")]:
        try:
            tot = con.execute(text(f"SELECT COUNT(DISTINCT {uwicol}) FROM {schema}.{tbl} "
                f"WHERE NULLIF(LTRIM(RTRIM({uwicol})),'') IS NOT NULL")).scalar()
            linked = con.execute(text(f"""
                SELECT COUNT(DISTINCT t.{uwicol}) FROM {schema}.{tbl} t
                WHERE EXISTS (SELECT 1 FROM file_catalog.FILE_WELL_HEADER h
                              WHERE h.UWI = t.{uwicol}
                              AND NULLIF(LTRIM(RTRIM(h.UWI)),'') IS NOT NULL)""")).scalar()
            print(f"  {schema}.{tbl}: {linked}/{tot} distinct UWIs have a FILE_WELL_HEADER row")
        except Exception as ex:
            print(f"  {schema}.{tbl}: {str(ex)[:60]}")

    # 2. FILE_WELL_HEADER: how many rows, how many with UWI, how many with INVENTORY_ID
    print("\n=== 2. FILE_WELL_HEADER completeness ===")
    print("  total rows:", con.execute(text("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER")).scalar())
    print("  with UWI:", con.execute(text("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER WHERE NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL")).scalar())
    print("  with INVENTORY_ID:", con.execute(text("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER WHERE INVENTORY_ID IS NOT NULL")).scalar())

    # 3. GLOBAL_FILE_CATALOG: files that were classified as well-bearing but have NO FILE_WELL_HEADER row
    print("\n=== 3. well-bearing files missing a FILE_WELL_HEADER row ===")
    cols = [r[0].upper() for r in con.execute(text(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='GLOBAL_FILE_CATALOG'"))]
    print("  GFC has DOC_TYPE:", "DOC_TYPE" in cols, "| MATCHED_UWI:", "MATCHED_UWI" in cols)
    # files with a matched UWI but no header row
    if "MATCHED_UWI" in cols:
        n = con.execute(text("""
            SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
            WHERE NULLIF(LTRIM(RTRIM(g.MATCHED_UWI)),'') IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM file_catalog.FILE_WELL_HEADER h
                            WHERE h.INVENTORY_ID = g.INVENTORY_ID)""")).scalar()
        print(f"  files WITH a matched UWI but NO FILE_WELL_HEADER row: {n}")
    # doc types present
    if "DOC_TYPE" in cols:
        print("  --- DOC_TYPE distribution ---")
        for r in con.execute(text("SELECT TOP 15 DOC_TYPE, COUNT(*) n FROM file_catalog.GLOBAL_FILE_CATALOG GROUP BY DOC_TYPE ORDER BY n DESC")):
            print(f"      {r[0]!r}: {r[1]}")

    # 4. where do the 168 orphan wells' UWIs appear in the catalog at all?
    print("\n=== 4. sample orphan wells — do their UWIs appear ANYWHERE in the catalog? ===")
    orphans = con.execute(text("""
        SELECT TOP 5 d.uwi FROM dataview.dv_well d
        WHERE NOT EXISTS (SELECT 1 FROM file_catalog.FILE_WELL_HEADER h
                          WHERE h.UWI = d.uwi AND NULLIF(LTRIM(RTRIM(h.UWI)),'') IS NOT NULL)""")).fetchall()
    for (u,) in orphans:
        in_gfc = "n/a"
        if "MATCHED_UWI" in cols:
            in_gfc = con.execute(text("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE MATCHED_UWI = :u"), {"u": u}).scalar()
        in_catwell = con.execute(text("SELECT COUNT(*) FROM file_catalog.cat_well WHERE UWI = :u"), {"u": u}).scalar()
        print(f"  [{u}] — in GFC.MATCHED_UWI: {in_gfc} · in cat_well: {in_catwell}")

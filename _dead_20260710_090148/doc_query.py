"""Run the documents-map's EXACT query and isolate which filter zeroes it out."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
DOC_EXTS = ('.pdf', '.docx', '.doc', '.txt', '.rtf', '.md', '.html', '.htm',
            '.csv', '.xlsx', '.xls', '.xml', '.json', '.las', '.dlis', '.lis')
with e.connect() as c:
    # the join + UWI filter only (no ext filter)
    n_noext = c.execute(text("""
        SELECT COUNT(DISTINCT h.UWI) FROM file_catalog.GLOBAL_FILE_CATALOG g
          JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID = g.INVENTORY_ID
         WHERE NULLIF(LTRIM(RTRIM(h.UWI)),'') IS NOT NULL
    """)).scalar()
    print(f"wells with docs (UWI filter, NO ext filter): {n_noext}")

    # add the ext filter
    vals = ", ".join("'" + x + "'" for x in DOC_EXTS)
    n_ext = c.execute(text(f"""
        SELECT COUNT(DISTINCT h.UWI) FROM file_catalog.GLOBAL_FILE_CATALOG g
          JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID = g.INVENTORY_ID
         WHERE NULLIF(LTRIM(RTRIM(h.UWI)),'') IS NOT NULL
           AND LOWER(g.FILE_EXT) IN ({vals})
    """)).scalar()
    print(f"wells with docs (WITH ext filter on DOC_EXTS): {n_ext}")

    # what extensions do the joined files actually have?
    print("\nextensions of files that join to a well header:")
    for ext, n in c.execute(text("""
        SELECT LOWER(g.FILE_EXT), COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
          JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID = g.INVENTORY_ID
         GROUP BY LOWER(g.FILE_EXT) ORDER BY COUNT(*) DESC
    """)).fetchall():
        print(f"   {ext!r:12} {n}")

    # is the column actually named FILE_EXT?
    print("\nGFC columns containing 'EXT':")
    for (col,) in c.execute(text("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
         WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='GLOBAL_FILE_CATALOG'
           AND COLUMN_NAME LIKE '%EXT%'""")).fetchall():
        print(f"   {col}")

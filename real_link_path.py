"""FILE_WELL_HEADER is only written for LAS/DLIS/LIS. Non-log documents (scout
PDFs, CSV, shapefile) link wells via INVENTORY_ID on the promoted rows instead.
Check whether the orphan wells DO have an INVENTORY_ID path to a catalog file
via their detail rows (dv_well_* tables carry INVENTORY_ID per the promote design)."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as con:
    # Which dv_* tables carry INVENTORY_ID?
    inv_tables = [r[0] for r in con.execute(text("""
        SELECT t.name FROM sys.columns c JOIN sys.tables t ON t.object_id=c.object_id
        JOIN sys.schemas s ON s.schema_id=t.schema_id
        WHERE c.name='INVENTORY_ID' AND s.name='dataview' ORDER BY t.name"""))]
    print("dv_* tables with INVENTORY_ID:", inv_tables)

    # For a few orphan wells, do ANY of their detail rows carry an INVENTORY_ID
    # that resolves to a GLOBAL_FILE_CATALOG file?
    orphans = [r[0] for r in con.execute(text("""
        SELECT TOP 5 d.uwi FROM dataview.dv_well d
        WHERE NOT EXISTS (SELECT 1 FROM file_catalog.FILE_WELL_HEADER h
                          WHERE h.UWI=d.uwi AND NULLIF(LTRIM(RTRIM(h.UWI)),'') IS NOT NULL)"""))]
    print("\nsample orphan wells:", orphans)
    for u in orphans:
        found = []
        for t in inv_tables:
            try:
                n = con.execute(text(
                    f"SELECT COUNT(*) FROM dataview.{t} x "
                    f"JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID=x.INVENTORY_ID "
                    f"WHERE x.uwi=:u"), {"u": u}).scalar()
                if n:
                    found.append(f"{t}={n}")
            except Exception:
                pass
        print(f"  [{u}] catalog-linked detail rows: {found or 'NONE'}")

    # Also: does dv_well itself carry INVENTORY_ID?
    dvw_has_inv = con.execute(text("""
        SELECT COUNT(*) FROM sys.columns c JOIN sys.tables t ON t.object_id=c.object_id
        JOIN sys.schemas s ON s.schema_id=t.schema_id
        WHERE c.name='INVENTORY_ID' AND s.name='dataview' AND t.name='dv_well'""")).scalar()
    print(f"\ndv_well has INVENTORY_ID column: {bool(dvw_has_inv)}")

    # What documents produced the orphans? Check GLOBAL_FILE_CATALOG file types present
    print("\n=== all GLOBAL_FILE_CATALOG files by extension (what docs exist) ===")
    cols = [r[0].upper() for r in con.execute(text(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='GLOBAL_FILE_CATALOG'"))]
    extcol = next((c for c in ("FILE_EXT","EXTENSION","EXT") if c in cols), None)
    if extcol:
        for r in con.execute(text(f"SELECT {extcol}, COUNT(*) n FROM file_catalog.GLOBAL_FILE_CATALOG GROUP BY {extcol} ORDER BY n DESC")):
            print(f"    {r[0]!r}: {r[1]}")

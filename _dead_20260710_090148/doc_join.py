"""Diagnose why the documents map finds 0 wells. Tests each piece of its query:
FILE_WELL_HEADER rows, the INVENTORY_ID join to GLOBAL_FILE_CATALOG, and the
UWI/ext filters."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    fwh = c.execute(text("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER")).scalar()
    fwh_uwi = c.execute(text(
        "SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER "
        "WHERE NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL")).scalar()
    print(f"FILE_WELL_HEADER: {fwh} rows, {fwh_uwi} with non-empty UWI")

    # the join: how many FWH rows match a GFC row on INVENTORY_ID?
    joined = c.execute(text("""
        SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER h
          JOIN file_catalog.GLOBAL_FILE_CATALOG g ON h.INVENTORY_ID = g.INVENTORY_ID
    """)).scalar()
    print(f"FWH ⨝ GFC on INVENTORY_ID: {joined} matched rows")

    # sample INVENTORY_ID from each side — type/format mismatch?
    print("\nsample FWH.INVENTORY_ID:")
    for (v,) in c.execute(text("SELECT TOP 3 INVENTORY_ID FROM file_catalog.FILE_WELL_HEADER")).fetchall():
        print(f"   {v!r}")
    print("sample GFC.INVENTORY_ID:")
    for (v,) in c.execute(text("SELECT TOP 3 INVENTORY_ID FROM file_catalog.GLOBAL_FILE_CATALOG")).fetchall():
        print(f"   {v!r}")

    # column types
    print("\nINVENTORY_ID column types:")
    for tbl in ("FILE_WELL_HEADER", "GLOBAL_FILE_CATALOG"):
        r = c.execute(text("""
            SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME=:t AND COLUMN_NAME='INVENTORY_ID'
        """), {"t": tbl}).fetchone()
        print(f"   {tbl}: {r}")

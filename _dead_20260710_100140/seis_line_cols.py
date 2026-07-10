"""dv_seis_line columns — the EXISTING child table we should populate,
instead of creating a new one."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as con:
    print("=== dataview.dv_seis_line columns ===")
    for cn, dt, nul in con.execute(text("""
        SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME='dv_seis_line'
        ORDER BY ORDINAL_POSITION""")):
        print(f"   {cn} ({dt}) {'NULL' if nul=='YES' else 'NOT NULL'}")
    print()
    print("=== FILE_SEIS_HEADER columns (the source) ===")
    for cn, dt in con.execute(text("""
        SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='FILE_SEIS_HEADER'
        ORDER BY ORDINAL_POSITION""")):
        print(f"   {cn} ({dt})")

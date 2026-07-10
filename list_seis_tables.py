"""What seismic tables actually exist in the DB, and how many rows each?
Settles what we already have before adding anything."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as con:
    print("=== all tables with 'seis' in the name (any schema) ===")
    rows = con.execute(text("""
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_NAME LIKE '%SEIS%'
        ORDER BY TABLE_SCHEMA, TABLE_NAME""")).fetchall()
    for sch, tbl in rows:
        try:
            n = con.execute(text(f"SELECT COUNT(*) FROM [{sch}].[{tbl}]")).scalar()
        except Exception as ex:
            n = f"err: {str(ex)[:30]}"
        print(f"   {sch}.{tbl}: {n} rows")
    print()
    print("=== columns of dataview.dv_seis_set (the survey table) ===")
    cols = con.execute(text("""
        SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME='dv_seis_set'
        ORDER BY ORDINAL_POSITION""")).fetchall()
    for cn, dt in cols:
        print(f"   {cn} ({dt})")

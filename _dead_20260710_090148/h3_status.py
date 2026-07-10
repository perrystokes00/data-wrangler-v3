"""h3_status.py — is the H3 backfill running / done? py h3_status.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()
staging = cur.execute("SELECT OBJECT_ID('stg.dv_well_h3_stage')").fetchone()[0]
print("staging table present :", staging is not None, "(True = write phase, almost done)")
for col in ("h3_r4", "h3_r5", "h3_r6", "h3_r7"):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM dataview.dv_well WHERE {col} IS NOT NULL").fetchone()[0]
        print(f"dv_well {col} populated : {n:,}")
    except Exception as e:
        print(f"dv_well {col}: {e}")
tot = cur.execute("SELECT COUNT(*) FROM dataview.dv_well").fetchone()[0]
wc  = cur.execute("SELECT COUNT(*) FROM dataview.dv_well WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL").fetchone()[0]
print(f"dv_well total rows    : {tot:,}   (with coords: {wc:,})")

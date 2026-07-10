import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
ks = cur.execute(
    "SELECT COUNT(*) FROM WELL_REF.well_ref.well_master_gold WHERE uwi14 LIKE '15%'"
).fetchone()[0]
good = cur.execute(
    "SELECT COUNT(*) FROM WELL_REF.well_ref.well_master_gold "
    "WHERE uwi14 LIKE '15%' AND surface_latitude IS NOT NULL "
    "AND NOT (surface_latitude = 0 AND surface_longitude = 0)"
).fetchone()[0]
print(f"KS wells in gold : {ks:,}")
print(f"  with coords    : {good:,}")
print(f"  missing/(0,0)  : {ks - good:,}")

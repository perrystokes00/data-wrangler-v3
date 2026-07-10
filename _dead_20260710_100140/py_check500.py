import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
tot = cur.execute("SELECT COUNT(*) FROM dataview.dv_well").fetchone()[0]
crd = cur.execute(
    "SELECT COUNT(*) FROM dataview.dv_well WHERE surface_latitude IS NOT NULL "
    "AND NOT (surface_latitude=0 AND surface_longitude=0)").fetchone()[0]
cur2 = cur.execute("SELECT COUNT(*) FROM file_catalog.cat_well_log_curve").fetchone()[0]
print(f"dv_well: {tot:,}  |  with coords: {crd:,}  |  cat curves: {cur2:,}")

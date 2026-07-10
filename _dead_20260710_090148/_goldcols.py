import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
cols = [r[0] for r in cur.execute(
    "SELECT name FROM WELL_REF.sys.columns "
    "WHERE object_id=OBJECT_ID('WELL_REF.well_ref.well_master_gold') ORDER BY column_id")]
want = ["uwi14","api_10","surface_latitude","surface_longitude","well_name","operator_name",
        "county","province_state","country","primary_source","source_list","source_count",
        "quality_score","long_lat_source","built_at"]
print("gold has these of my insert cols :", [w for w in want if w in cols])
print("MISSING (I referenced, not real) :", [w for w in want if w not in cols])
print("\nall gold cols:", cols)

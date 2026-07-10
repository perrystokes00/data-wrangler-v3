import pyodbc
cur = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
print("gold uwi14 collation:", cur.execute(
    "SELECT collation_name FROM WELL_REF.sys.columns "
    "WHERE object_id=OBJECT_ID('WELL_REF.well_ref.well_master_gold') AND name='uwi14'").fetchone()[0])

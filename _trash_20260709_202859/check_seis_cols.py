import pyodbc
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
print("FILE_SEIS_HEADER columns:")
try:
    for r in c.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='FILE_SEIS_HEADER' ORDER BY ORDINAL_POSITION").fetchall():
        print(f"   {r[0]:30} {r[1]}")
except Exception as e:
    print("  ", e)
print("\ndv_seis_set columns:")
try:
    for r in c.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME='dv_seis_set' ORDER BY ORDINAL_POSITION").fetchall():
        print(f"   {r[0]:30} {r[1]}")
except Exception as e:
    print("  ", e)

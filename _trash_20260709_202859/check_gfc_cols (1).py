"""check_gfc_cols.py — does GLOBAL_FILE_CATALOG carry a well name / line, or must we
join FILE_WELL_HEADER / FILE_SEIS_HEADER to get them for the grid? py check_gfc_cols.py"""
import pyodbc
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
cols = [r[0] for r in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='GLOBAL_FILE_CATALOG' ORDER BY ORDINAL_POSITION").fetchall()]
print("GLOBAL_FILE_CATALOG columns of interest:")
for want in ("WELL_NAME","LINE_NAME","MATCHED_UWI","UWI14","SURVEY_NAME","FILE_NAME"):
    print(f"   {want:14} {'YES' if any(x.upper()==want for x in cols) else 'no'}")
print("\nFILE_WELL_HEADER has WELL_NAME:", any(r[0].upper()=='WELL_NAME' for r in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='FILE_WELL_HEADER'").fetchall()))
print("FILE_SEIS_HEADER has LINE_NAME:", any(r[0].upper()=='LINE_NAME' for r in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='FILE_SEIS_HEADER'").fetchall()))

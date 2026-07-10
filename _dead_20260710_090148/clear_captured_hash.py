"""clear_captured_hash.py — clear the wrongly-stamped CAPTURED_HASH on .las files so
capture re-selects them (the fingerprint stamp had marked all selected files, not
just captured ones). py clear_captured_hash.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
n = c.execute("UPDATE file_catalog.GLOBAL_FILE_CATALOG SET CAPTURED_HASH=NULL "
              "WHERE LOWER(FILE_EXT)='.las'").rowcount
print(f"cleared CAPTURED_HASH on {n} .las file(s)")
print("now run the pipeline (or run_load.py) — capture will re-select them")

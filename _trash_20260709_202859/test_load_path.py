"""test_load_path.py — run the FULL run_bcp_capture on 60 real files (blank UWI,
fresh-scan style) and see how many cat_well rows actually land. Isolates the DB
load. py test_load_path.py"""
import sys, os, glob
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pyodbc
from bcp_capture import run_bcp_capture

CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
ODBC = ("DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\\SQLEXPRESS;"
        "DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")

FOLDER = r"C:\Users\perry\OneDrive\Documents\KSGS\LAS_Files\_selected"
files = glob.glob(os.path.join(FOLDER, "*.las"))[:60]

# build recs the way _stage_capture does — blank MATCHED_UWI (fresh scan), unique INVENTORY_ID
recs = [{"FILE_PATH": fp, "MATCHED_UWI": "", "INVENTORY_ID": f"TEST{ i }"}
        for i, fp in enumerate(files)]

c = pyodbc.connect(CONN, autocommit=True).cursor()
before = c.execute("SELECT COUNT(*) FROM file_catalog.cat_well WHERE INVENTORY_ID LIKE 'TEST%'").fetchone()[0]

print(f"feeding {len(recs)} files (blank MATCHED_UWI) through run_bcp_capture…\n")
res = run_bcp_capture(recs, conn_str=ODBC, workers=6, log=print)
print("\nrun_bcp_capture returned:", res)

after = c.execute("SELECT COUNT(*) FROM file_catalog.cat_well WHERE INVENTORY_ID LIKE 'TEST%'").fetchone()[0]
print(f"\ncat_well TEST rows: before={before} after={after} (delta={after-before})")
print(f"=> expected 60. If delta==60, the load works and the pipeline SELECTION is")
print(f"   the culprit. If delta<60, _load_table is dropping rows.")

# cleanup
c.execute("DELETE FROM file_catalog.cat_well WHERE INVENTORY_ID LIKE 'TEST%'")
c.execute("DELETE FROM file_catalog.cat_well_log WHERE INVENTORY_ID LIKE 'TEST%'")
c.execute("DELETE FROM file_catalog.cat_well_log_curve WHERE INVENTORY_ID LIKE 'TEST%'")
c.execute("DELETE FROM file_catalog.FILE_WELL_HEADER WHERE INVENTORY_ID LIKE 'TEST%'")
print("(cleaned up TEST rows)")

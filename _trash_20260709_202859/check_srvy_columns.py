"""check_srvy_columns.py — confirm the actual column names of cat_well_dir_srvy_sta so we
map the loader's dict keys correctly. py check_srvy_columns.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\srvy_columns.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
log("=== cat_well_dir_srvy_sta columns ===")
for r in c.execute("SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='cat_well_dir_srvy_sta' ORDER BY ORDINAL_POSITION").fetchall():
    log(f"  {r[0]:20} {r[1]}")
log("\n=== the loader writes these keys (from survey_loader.py) ===")
loader_keys = ["dir_srvy_id","survey_id","station_id","station_num","station_md",
               "inclination","azimuth","station_tvd","ns_deviation","ew_deviation",
               "dogleg_severity","depth_ouom","active_ind"]
cols = {r[0].lower() for r in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='cat_well_dir_srvy_sta'").fetchall()}
for k in loader_keys:
    log(f"  loader key '{k}': {'MATCHES column' if k.lower() in cols else 'NO COLUMN -> writes NULL'}")
log("\n=== so the correct mapping (loader key -> real column) ===")
log("  need to know real columns for: md, incl, azim, tvd, ns, ew, dls")
for want in ("md","incl","azim","tvd","ns_offset","ew_offset","dls","measured_depth","inclination","azimuth"):
    log(f"    column '{want}' exists: {want in cols}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

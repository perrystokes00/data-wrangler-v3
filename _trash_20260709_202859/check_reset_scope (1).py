"""check_reset_scope.py — what survives your reset? Shows current row counts for
the reference/lookup tables vs the data tables, so you know if a reset leaves
dv_r_* intact (then no reseed needed) or wipes them. py check_reset_scope.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
def n(t):
    try: return c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    except Exception as e: return f"(err {str(e)[:30]})"

print("REFERENCE / LOOKUP (should survive a data-only reset):")
for t in ("dataview.dv_r_uom","dataview.dv_r_source","dataview.dv_r_well_type",
          "dataview.dv_r_well_status","dataview.dv_business_associate","dataview.dv_field"):
    print(f"  {t:34} {n(t)}")
print("\nDATA (cleared by reset):")
for t in ("dataview.dv_well","dataview.dv_well_log","dataview.dv_well_log_curve",
          "file_catalog.cat_well","file_catalog.cat_well_log_curve",
          "file_catalog.GLOBAL_FILE_CATALOG","file_catalog.FILE_WELL_HEADER"):
    print(f"  {t:34} {n(t)}")

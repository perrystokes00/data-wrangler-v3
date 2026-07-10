"""diag_deep_promote.py — the loaders wrote rows to cat_* (proven). Did those rows
(a) land in cat_*, and (b) get promoted to dv_*? Checks the ANADARKO 1H well across
the deep-data tables in BOTH cat_ (catalog staging) and dv_ (promoted). py diag_deep_promote.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
UWI = "42317123450000"

pairs = [
    ("formation tops",  "cat_well_formation_top", "dv_well_formation_top"),
    ("dir survey hdr",  "cat_well_dir_srvy_hdr",  "dv_well_dir_srvy_hdr"),
    ("dir survey sta",  "cat_well_dir_srvy_sta",  "dv_well_dir_srvy_sta"),
    ("completions",     "cat_well_completion",    "dv_well_completion"),
    ("production vol",  "cat_prod_volume",        "dv_prod_volume"),
]
def cnt(schema, tbl, uwicol="uwi"):
    try:
        return c.execute(f"SELECT COUNT(*) FROM {schema}.{tbl} WHERE {uwicol}=?", UWI).fetchone()[0]
    except Exception as e:
        return f"ERR({str(e)[:40]})"

print(f"=== deep data for {UWI}: cat_ (staged) vs dv_ (promoted) ===\n")
print(f"  {'domain':18} {'cat_ (staged)':>14}  {'dv_ (promoted)':>15}")
print(f"  {'-'*18} {'-'*14}  {'-'*15}")
for label, cat, dv in pairs:
    # cat_ tables use UWI (upper) per catalog_capture; dv_ use uwi (lower)
    cc = cnt("file_catalog", cat, "UWI")
    dd = cnt("dataview", dv, "uwi")
    print(f"  {label:18} {str(cc):>14}  {str(dd):>15}")

print("\n=== is this well even in the catalog with a resolved UWI? ===")
for col in ("UWI14","MATCHED_UWI"):
    try:
        n = c.execute(f"SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE {col}=?", UWI).fetchone()[0]
        print(f"   GLOBAL_FILE_CATALOG.{col}={UWI}: {n} file(s)")
    except Exception as e:
        print(f"   {col}: ERR {str(e)[:50]}")

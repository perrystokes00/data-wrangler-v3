"""diag_held_refs.py — the deep rows are HELD on unresolved reference FKs: source,
depth_ouom, volume_ouom, rate_ouom, curve_unit. Find the exact values in cat_* that
aren't in the dv_r_* reference tables, so we can seed them. py diag_held_refs.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

def distinct(schema, tbl, col):
    try:
        return [r[0] for r in c.execute(
            f"SELECT DISTINCT {col} FROM {schema}.{tbl} WHERE {col} IS NOT NULL").fetchall()]
    except Exception as e:
        return [f"ERR {str(e)[:40]}"]

print("=== SOURCE values in cat_ tables vs dv_r_source ===")
for t in ("cat_well_dir_srvy_hdr","cat_well_formation_top","cat_prod_volume","cat_well_log_curve"):
    vals = distinct("file_catalog", t, "SOURCE")
    print(f"  {t}.SOURCE = {vals}")
print("  dv_r_source has:", distinct("dataview","dv_r_source","source"))

print("\n=== UOM values (depth_ouom / rate_ouom / volume_ouom / curve_unit) ===")
for t, col in (("cat_well_formation_top","DEPTH_OUOM"),
               ("cat_well_dir_srvy_sta","DEPTH_OUOM"),
               ("cat_prod_volume","VOLUME_OUOM"),
               ("cat_prod_volume","RATE_OUOM"),
               ("cat_well_log_curve","CURVE_UNIT"),
               ("cat_well_log_curve","DEPTH_OUOM")):
    print(f"  {t}.{col} = {distinct('file_catalog', t, col)}")
print("  dv_r_uom has:", distinct("dataview","dv_r_uom","uom_id")[:20])

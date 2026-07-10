"""pipeline_status.py — compact one-shot state of the loader after a run.
Prints ~12 lines you can paste as text. py pipeline_status.py"""
import os, pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()
def f(q, d="?"):
    try: return cur.execute(q).fetchone()[0]
    except Exception: return d

REF = "WELL_REF.well_ref.well_master_gold"
CWN = ("LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(w.UWI)),'-',''),' ',''),"
       "'/',''),'.',''),'_','') + '00000000000000', 14)")
LAS = "FILE_EXT IN ('.las','.dlis','.lis','.dlf','.dis')"

print("=== PIPELINE STATUS ===")
print(f"LAS files cataloged     : {f(f'SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE {LAS}')}")
print(f"FILE_WELL_HEADER wells  : {f('SELECT COUNT(DISTINCT UWI14) FROM file_catalog.FILE_WELL_HEADER WHERE UWI14 IS NOT NULL')}")
print(f"cat_well total / held   : {f('SELECT COUNT(*) FROM file_catalog.cat_well')} / "
      f"{f('SELECT COUNT(*) FROM file_catalog.cat_well WHERE ISNULL(PROMOTED,0)=0')}")
print(f"dv_well total           : {f('SELECT COUNT(*) FROM dataview.dv_well')}")
print(f"dv_well with real coords: {f('SELECT COUNT(*) FROM dataview.dv_well WHERE surface_latitude IS NOT NULL AND NOT(surface_latitude=0 AND surface_longitude=0)')}")

held_nocoord = f("SELECT COUNT(*) FROM file_catalog.cat_well w WHERE ISNULL(PROMOTED,0)=0 "
                 "AND (SURFACE_LATITUDE IS NULL OR SURFACE_LONGITUDE IS NULL "
                 "OR (SURFACE_LATITUDE=0 AND SURFACE_LONGITUDE=0))")
print(f"cat_well held: no coords: {held_nocoord}")

# of those held-no-coord, how many could gold fill? how many ks_wells could?
gold_fill = f(f"SELECT COUNT(*) FROM file_catalog.cat_well w JOIN {REF} g ON g.uwi14={CWN} "
              f"WHERE ISNULL(w.PROMOTED,0)=0 AND (w.SURFACE_LATITUDE IS NULL OR w.SURFACE_LONGITUDE IS NULL "
              f"OR (w.SURFACE_LATITUDE=0 AND w.SURFACE_LONGITUDE=0)) "
              f"AND g.surface_latitude IS NOT NULL AND NOT(g.surface_latitude=0 AND g.surface_longitude=0)")
print(f"  of those, gold can fill: {gold_fill}")

print(f"cat_well_log_curve held : {f('SELECT COUNT(*) FROM file_catalog.cat_well_log_curve WHERE ISNULL(PROMOTED,0)=0')}")
miss_uom = f("SELECT COUNT(DISTINCT LTRIM(RTRIM(curve_unit))) FROM file_catalog.cat_well_log_curve m "
             "WHERE NULLIF(LTRIM(RTRIM(curve_unit)),'') IS NOT NULL AND NOT EXISTS "
             "(SELECT 1 FROM dataview.dv_r_uom r WHERE UPPER(RTRIM(r.uom_code))=UPPER(RTRIM(m.curve_unit)))")
print(f"missing UOM codes       : {miss_uom}")

# patch deployment
prom = "promote_catalog.py"
patch = ("_fill_cat_coords_from_gold" in open(prom, encoding="utf-8", errors="replace").read()
         if os.path.exists(prom) else "run in app folder")
print(f"pre-gate coord patch    : {patch}")
print("\n(paste these lines)")

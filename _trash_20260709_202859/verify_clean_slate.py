"""verify_clean_slate.py — after clicking 'Clear catalog & data rows', confirm the
slate is actually clean before the end-to-end run: cat_* empty, dv_* empty (catalog-
derived), CAPTURED_HASH/VAULTED_AT/PROMOTED_AT reset, inventory still present.
Read-only. py verify_clean_slate.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\clean_slate.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:35]}"

log("=== inventory (should still be present after clear) ===")
inv = one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG")
log(f"  GLOBAL_FILE_CATALOG rows: {inv}   {'OK — inventory kept' if isinstance(inv,int) and inv>0 else 'EMPTY — you cleared inventory too (re-scan needed)'}")

log("\n=== stamps (should all be 0 after a clean clear) ===")
for col in ("CAPTURED_HASH", "VAULTED_AT", "PROMOTED_AT"):
    n = one(f"SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE {col} IS NOT NULL")
    log(f"  {col:14} still set: {n}   {'OK' if n==0 else '<-- NOT reset (stamp patch not applied?)'}")

log("\n=== cat_* mirrors (should be 0 or near-0 after clear) ===")
for t in ("cat_well","cat_well_log","cat_well_log_curve","cat_well_formation_top",
          "cat_prod_volume","cat_well_completion","cat_well_dir_srvy_hdr","cat_well_dir_srvy_sta"):
    log(f"  {t:26}: {one(f'SELECT COUNT(*) FROM file_catalog.{t}')}")

log("\n=== dv_* catalog-derived (should be 0 after clear with do_dv=True) ===")
for t in ("dv_well","dv_well_log","dv_well_log_curve","dv_well_formation_top",
          "dv_prod_volume","dv_well_completion","dv_seis_set"):
    log(f"  {t:26}: {one(f'SELECT COUNT(*) FROM dataview.{t}')}")

log("\n=== FILE_WELL_HEADER / FILE_SEIS_HEADER ===")
log(f"  FILE_WELL_HEADER: {one('SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER')}")
log(f"  FILE_SEIS_HEADER: {one('SELECT COUNT(*) FROM file_catalog.FILE_SEIS_HEADER')}")

log("\n=== reference tables (should be KEPT — seeded codes) ===")
for t in ("dv_r_uom","dv_r_source"):
    log(f"  {t:14}: {one(f'SELECT COUNT(*) FROM dataview.{t}')}   (should be >0 — seeds preserved)")

log("\n=== verdict ===")
stamps0 = all(one(f"SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE {c2} IS NOT NULL")==0
              for c2 in ("CAPTURED_HASH","VAULTED_AT","PROMOTED_AT"))
catw = one("SELECT COUNT(*) FROM file_catalog.cat_well")
dvw  = one("SELECT COUNT(*) FROM dataview.dv_well")
if isinstance(inv,int) and inv>0 and stamps0 and catw==0:
    log("  CLEAN — inventory present, stamps reset, cat_well empty. Ready for end-to-end.")
else:
    log("  NOT fully clean — see above. If stamps still set, the clear-stamp patch may")
    log("  not be deployed; run reset_capture_stamps.py --apply before the run.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT)

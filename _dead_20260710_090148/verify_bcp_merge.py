"""verify_bcp_merge.py — after the merge + a LAS crawl and a SEG-Y crawl, confirm BOTH
features work: LAS loaded (nested-pool path didn't crash) and SEG-Y has SURVEY_OUTLINE
populated. py verify_bcp_merge.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\bcp_merge_verify.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:45]}"

log("=== 1) nested-pool fix: did LAS load without crashing? ===")
log("  dv_well_log rows: " + str(one("SELECT COUNT(*) FROM dataview.dv_well_log")))
log("  dv_well_log_curve rows: " + str(one("SELECT COUNT(*) FROM dataview.dv_well_log_curve")))
log("  (if >0 after a LAS crawl, the nested-pool parse path worked)")

log("\n=== 2) survey outline: is SURVEY_OUTLINE populated for SEG-Y? ===")
# check the cat_ and dv_ seismic header tables
for tbl in ("file_catalog.FILE_SEIS_HEADER","file_catalog.cat_seis_header","dataview.dv_seis_header"):
    try:
        tot = one(f"SELECT COUNT(*) FROM {tbl}")
        if isinstance(tot,int):
            filled = one(f"SELECT COUNT(*) FROM {tbl} WHERE SURVEY_OUTLINE IS NOT NULL")
            log(f"  {tbl}: {tot} rows, {filled} with SURVEY_OUTLINE")
    except Exception as e:
        log(f"  {tbl}: {str(e)[:50]}")

log("\n=== 3) sanity: is modules.bcp_capture importable (the shim)? ===")
import sys
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP,"modules"))
try:
    import importlib
    m = importlib.import_module("modules.bcp_capture")
    has_run = hasattr(m, "run_bcp_capture")
    log(f"  modules.bcp_capture imports OK, has run_bcp_capture: {has_run}")
    import bcp_capture as rootbcp
    log(f"  root bcp_capture imports OK, has run_bcp_capture: {hasattr(rootbcp,'run_bcp_capture')}")
    log(f"  shim points to same object: {m.run_bcp_capture is rootbcp.run_bcp_capture}")
except Exception as e:
    log(f"  import error: {str(e)[:100]}")

log("\n=== VERDICT ===")
log("  LAS rows >0 = nested-pool path OK. SURVEY_OUTLINE filled = outline OK.")
log("  shim 'same object' True = the merge unified both import styles correctly.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

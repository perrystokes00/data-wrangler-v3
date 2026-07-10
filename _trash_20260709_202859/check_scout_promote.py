"""check_scout_promote.py — the scout ticket isn't promoting. Trace it: did it resolve a
UWI, capture to cat_*, and what's in dv_* for it. py check_scout_promote.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\scout_promote.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== the scout ticket file in the catalog ===")
r = c.execute("""SELECT FILE_NAME, INVENTORY_ID, MATCHED_UWI, HEADER_EXTRACTED,
    CATALOG_READINESS, CAPTURED_HASH, PROMOTED_AT
    FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_NAME LIKE '%scout_synth%'""").fetchone()
if not r:
    log("  no scout_synth file in catalog — was it crawled?");
    open(OUT,"w").write("\n".join(L)); print("\n".join(L)); raise SystemExit
fn, inv, muwi, hx, ready, caph, prom = r
log(f"  {fn}")
log(f"  inventory_id: {inv}")
log(f"  matched_uwi:  {muwi!r}")
log(f"  extracted:    {hx}   readiness: {ready}   captured_hash: {'set' if caph else 'null'}   promoted_at: {prom}")

# FILE_WELL_HEADER — what did the header parse give?
log("\n=== FILE_WELL_HEADER (what the scout header parsed) ===")
h = c.execute("SELECT WELL_NAME, UWI, REPORT_TYPE FROM file_catalog.FILE_WELL_HEADER WHERE INVENTORY_ID=?", inv).fetchone()
if h: log(f"  well_name={h[0]!r} uwi={h[1]!r} type={h[2]!r}")
else: log("  no FILE_WELL_HEADER row")

log("\n=== cat_* (staged) for this file ===")
for t in ("cat_well","cat_well_formation_top","cat_well_dir_srvy_sta","cat_well_dst","cat_well_completion"):
    log(f"  {t}: " + str(one(f"SELECT COUNT(*) FROM file_catalog.{t} WHERE INVENTORY_ID=?", inv)))

log("\n=== dv_* (promoted) for this file ===")
for t in ("dv_well","dv_well_formation_top","dv_well_dir_srvy_sta","dv_well_dst","dv_well_completion"):
    log(f"  {t}: " + str(one(f"SELECT COUNT(*) FROM dataview.{t} WHERE INVENTORY_ID=?", inv)))

log("\n=== does the resolved UWI have coords? (promote gate) ===")
if muwi:
    norm="".join(ch for ch in str(muwi) if ch.isdigit()).ljust(14,"0")[:14]
    w = c.execute("SELECT well_name, surface_latitude FROM dataview.dv_well WHERE uwi=?", norm).fetchone()
    log(f"  {norm}: " + (f"{w[0]} lat={w[1]}" if w else "NOT in dv_well"))

log("\n=== VERDICT ===")
log("  matched_uwi None/blank -> header still not resolving; check FILE_WELL_HEADER uwi.")
log("  cat_* has rows but dv_* empty -> promote gate held it (coords? readiness?).")
log("  both empty but extracted=Y -> scout detail didn't capture (load_scout path).")
log("  captured_hash set + all empty -> stamp trap; reset + re-run.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

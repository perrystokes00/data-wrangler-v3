"""diag_h3.py — run_h3 read 655 coords but updated 0 and grid=0 cells. Find why:
are h3 columns populated, and does the uwi join work? py diag_h3.py"""
import pyodbc, os
OUT=r"C:\Bulk\reports\h3_diag.txt"
os.makedirs(os.path.dirname(OUT),exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c=pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:50]}"

log("=== dv_well H3 state ===")
log("  total wells: " + str(one("SELECT COUNT(*) FROM dataview.dv_well")))
log("  with coords: " + str(one("SELECT COUNT(*) FROM dataview.dv_well WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL")))
log("  h3_r5 populated: " + str(one("SELECT COUNT(*) FROM dataview.dv_well WHERE h3_r5 IS NOT NULL")))
log("  h3_r5 NULL (but has coords): " + str(one("SELECT COUNT(*) FROM dataview.dv_well WHERE h3_r5 IS NULL AND surface_latitude IS NOT NULL")))

log("\n=== sample h3 values (are they real or blank?) ===")
try:
    for r in c.execute("SELECT TOP 5 uwi, surface_latitude, surface_longitude, h3_r5 FROM dataview.dv_well WHERE surface_latitude IS NOT NULL").fetchall():
        log(f"  uwi='{r[0]}' lat={r[1]} lon={r[2]} h3_r5={r[3]!r}")
except Exception as e:
    log("  err: "+str(e)[:60])

log("\n=== does the staging table still exist? (post-run) ===")
log("  stg.dv_well_h3_stage exists: " + str(one("SELECT COUNT(*) FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE s.name='stg' AND t.name='dv_well_h3_stage'")))

log("\n=== uwi format check (char(14) trailing-space join issue?) ===")
try:
    r = c.execute("SELECT TOP 3 '['+uwi+']' , LEN(uwi), DATALENGTH(uwi) FROM dataview.dv_well WHERE surface_latitude IS NOT NULL").fetchall()
    for x in r: log(f"  {x[0]}  LEN={x[1]} DATALENGTH={x[2]}")
except Exception as e:
    log("  err: "+str(e)[:60])

log("\n=== VERDICT ===")
log("  If h3_r5 is ALREADY populated on all 655: backfill correctly updated 0 (nothing")
log("     to do) — but then grid=0 is the real bug (density query not finding them).")
log("  If h3_r5 is NULL on wells with coords: the UPDATE JOIN failed — likely uwi")
log("     char(14) trailing-space or format mismatch between staging and dv_well.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

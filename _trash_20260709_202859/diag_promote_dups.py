"""diag_promote_dups.py — the 'other' held rows are eligible (well+codes OK) but not
clearing. Run promote and watch tops/prod specifically: eligible? moved? cleared?
Commits (real promote). writes to file. py diag_promote_dups.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\promote_dups.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
conn = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
conn.autocommit=False
cur = conn.cursor()

def held(t):
    return cur.execute(f"SELECT COUNT(*) FROM file_catalog.{t} WHERE PROMOTED=0").fetchone()[0]

log("BEFORE:")
for t in ("cat_well_formation_top","cat_prod_volume","cat_well_dir_srvy_hdr"):
    log(f"  {t} held: {held(t)}")

log("\nrunning promote (watch formation_top / prod_volume lines)...\n")
try:
    import promote_catalog as pc
    pc.run_promote(cur, None, True, log=log)
    conn.commit()
    log("\n=== committed ===")
except Exception as e:
    conn.rollback()
    import traceback
    log("FAILED, rolled back:", str(e)[:120])
    log(traceback.format_exc()[-400:])
    open(OUT,"w",encoding="utf-8").write("\n".join(L)); raise SystemExit

log("\nAFTER:")
for t in ("cat_well_formation_top","cat_prod_volume","cat_well_dir_srvy_hdr"):
    log(f"  {t} held: {held(t)}")
conn.close()
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

"""check_las_eligible_now.py — after reset+recrawl, are the LAS files NOW eligible for
capture, or still blocked? Re-checks all four capture-stage filters + shows the actual
CAPTURED_HASH vs FILE_HASH. writes to file. py check_las_eligible_now.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\las_eligible.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

log("=== LAS capture eligibility RIGHT NOW ===")
rows = c.execute("""SELECT FILE_NAME, CATALOG_READINESS, DUPLICATE_GROUP,
    CAPTURED_HASH, FILE_HASH, FLAG_DELETE, MATCHED_UWI
    FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' ORDER BY FILE_NAME""").fetchall()
elig=blocked=0
for r in rows:
    fn,ready,dup,chash,fhash,fdel,uwi = r
    reasons=[]
    if dup is not None: reasons.append("DUP_GROUP")
    if ready in ("SKIPPED","CATALOGED"): reasons.append(f"READY={ready}")
    if chash is not None and chash==fhash: reasons.append("HASH_MATCH")
    if fdel=="Y": reasons.append("FLAG_DEL")
    if reasons: blocked+=1
    else: elig+=1
    log(f"   {fn}: {'ELIGIBLE' if not reasons else '|'.join(reasons)}  chash={'set' if chash else 'null'}")
log(f"\n   ELIGIBLE now: {elig}   BLOCKED: {blocked}")

log("\n=== did the LAS write cat_well / curves this time? ===")
for t in ("cat_well","cat_well_log","cat_well_log_curve"):
    n = c.execute(f"SELECT COUNT(*) FROM file_catalog.{t}").fetchone()[0]
    fromlas = ""
    if t=="cat_well":
        fromlas = c.execute("SELECT COUNT(*) FROM file_catalog.cat_well WHERE SOURCE='LAS_HEADER'").fetchone()[0]
        fromlas = f" (LAS_HEADER: {fromlas})"
    log(f"   {t}: {n}{fromlas}")

log("\n=== are the LAS wells in dv_well now? ===")
n = c.execute("SELECT COUNT(*) FROM dataview.dv_well").fetchone()[0]
log(f"   dv_well: {n}")
# sample: is 17031101760000 in dv_well?
for u in ("17031101760000","38105100680000","42475100200000"):
    got = c.execute("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=?", u).fetchone()[0]
    log(f"   dv_well has {u}: {'YES' if got else 'no'}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

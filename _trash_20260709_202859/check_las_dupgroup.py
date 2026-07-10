"""check_las_dupgroup.py — are the LAS files excluded from capture by DUPLICATE_GROUP
or CATALOG_READINESS or CAPTURED_HASH? These are the capture-stage WHERE filters.
writes to file. py check_las_dupgroup.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\las_dupgroup.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

log("=== the 20 LAS files vs the capture-stage WHERE filters ===")
log("(capture needs: DUPLICATE_GROUP NULL, READINESS not in SKIPPED/CATALOGED, CAPTURED_HASH null-or-changed, FLAG_DELETE<>Y)\n")
try:
    rows = c.execute("""SELECT FILE_NAME, MATCHED_UWI, CATALOG_READINESS, DUPLICATE_GROUP,
        CAPTURED_HASH, FILE_HASH, FLAG_DELETE, HEADER_EXTRACTED
        FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las'""").fetchall()
    excl_dup = excl_ready = excl_hash = excl_del = eligible = 0
    for r in rows:
        fn, uwi, ready, dup, chash, fhash, fdel, hext = r
        reasons = []
        if dup is not None: reasons.append("DUPLICATE_GROUP set"); excl_dup+=1
        if ready in ("SKIPPED","CATALOGED"): reasons.append(f"readiness={ready}"); excl_ready+=1
        if chash is not None and chash == fhash: reasons.append("CAPTURED_HASH==FILE_HASH (already captured)"); excl_hash+=1
        if fdel == "Y": reasons.append("FLAG_DELETE=Y"); excl_del+=1
        if not reasons: eligible+=1
        tag = "ELIGIBLE" if not reasons else " | ".join(reasons)
        log(f"   {fn}: {tag}")
    log(f"\n=== summary ===")
    log(f"   excluded by DUPLICATE_GROUP: {excl_dup}")
    log(f"   excluded by READINESS (SKIPPED/CATALOGED): {excl_ready}")
    log(f"   excluded by CAPTURED_HASH match: {excl_hash}")
    log(f"   excluded by FLAG_DELETE: {excl_del}")
    log(f"   ELIGIBLE for capture: {eligible}")
except Exception as e:
    log("err:", str(e)[:100])

log("\n=== DUPLICATE_GROUP distribution across LAS ===")
try:
    for r in c.execute("""SELECT CASE WHEN DUPLICATE_GROUP IS NULL THEN '(null)' ELSE 'set' END, COUNT(*)
        FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' GROUP BY CASE WHEN DUPLICATE_GROUP IS NULL THEN '(null)' ELSE 'set' END""").fetchall():
        log(f"   DUPLICATE_GROUP {r[0]}: {r[1]}")
except Exception as e:
    log("   err:", str(e)[:60])
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

"""diag_capture_nothing.py — 9 PDFs extracted (READY, UWI resolved) but cat_well=0. Capture
wrote nothing. Find why: check readiness gate, and run the capture path on ONE file to see
what it returns. py diag_capture_nothing.py"""
import pyodbc, os, sys, traceback
OUT = r"C:\Bulk\reports\capture_nothing.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== the capture SELECT gate: which files qualify for capture? ===")
# mirror the capture WHERE from pipeline_run: MATCHED_UWI present, readiness not SKIPPED/CATALOGED, not dup
rows = c.execute("""SELECT FILE_NAME, MATCHED_UWI, CATALOG_READINESS, CAPTURED_HASH, FILE_HASH,
    DUPLICATE_GROUP, HEADER_EXTRACTED
    FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.pdf' ORDER BY FILE_NAME""").fetchall()
for r in rows:
    fn, muwi, ready, caph, fh, dup, hx = r
    # would the capture gate include this file?
    qualifies = (muwi and str(muwi).strip() and ready not in ('SKIPPED','CATALOGED')
                 and dup is None and (caph is None or caph != fh))
    log(f"  {fn}: uwi={'Y' if muwi else 'N'} ready={ready} extracted={hx} "
        f"captured_hash={'set' if caph else 'null'} dup={dup} -> capture_gate={'PASS' if qualifies else 'SKIP'}")

log("\n=== summary ===")
log("  cat_well rows: " + str(one("SELECT COUNT(*) FROM file_catalog.cat_well")))
log("  files with MATCHED_UWI set: " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.pdf' AND MATCHED_UWI IS NOT NULL AND LTRIM(RTRIM(MATCHED_UWI))<>''")))
log("  files at readiness READY: " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.pdf' AND CATALOG_READINESS='READY'")))
log("  files with CAPTURED_HASH already set: " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.pdf' AND CAPTURED_HASH IS NOT NULL")))

log("\n=== KEY QUESTION ===")
log("  If most show capture_gate=SKIP due to CAPTURED_HASH already set -> they were")
log("  'already captured' (stamped) but cat_well is empty = the stamp-without-rows bug")
log("  again, OR capture ran, found no DETAIL rows (these report types may extract a")
log("  header but no detail table), stamped, and moved on. cat_well only gets a row if")
log("  the handler writes a well header. Which handlers write cat_well for these types?")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

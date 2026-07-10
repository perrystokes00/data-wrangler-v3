"""check_crawl_scope.py — crawl set to ...\\sample_pdfs but report shows LAS/SEGY. Are
those files' paths under sample_pdfs (crawl scanned wide) or elsewhere (old inventory
from prior crawls still in the catalog)? py check_crawl_scope.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\crawl_scope.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== where do the LAS/SEGY files actually live? (FILE_PATH) ===")
for ext in (".las",".segy",".sgy",".dlis",".lis"):
    rows = c.execute("SELECT TOP 2 FILE_PATH FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT=?", ext).fetchall()
    for r in rows:
        log(f"  {ext}: {r[0]}")

log("\n=== do their paths contain 'sample_pdfs'? ===")
n_in = one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT IN ('.las','.segy','.sgy','.dlis','.lis') AND FILE_PATH LIKE '%sample_pdfs%'")
n_out = one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT IN ('.las','.segy','.sgy','.dlis','.lis') AND FILE_PATH NOT LIKE '%sample_pdfs%'")
log(f"  LAS/SEGY/etc UNDER sample_pdfs: {n_in}")
log(f"  LAS/SEGY/etc OUTSIDE sample_pdfs: {n_out}")

log("\n=== distinct ROOT_PATH values (what folders have been crawled) ===")
try:
    for r in c.execute("SELECT ROOT_PATH, COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG GROUP BY ROOT_PATH ORDER BY COUNT(*) DESC").fetchall():
        log(f"  {r[1]:5}  {r[0]}")
except Exception as e:
    log("  ROOT_PATH err (col exists?): " + str(e)[:60])

log("\n=== SCAN_DATE: are the LAS/SEGY from an OLD scan vs the PDFs from a new one? ===")
for ext in (".pdf",".las",".segy"):
    r = c.execute("SELECT MIN(SCAN_DATE), MAX(SCAN_DATE), COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT=?", ext).fetchone()
    log(f"  {ext}: scan min={r[0]} max={r[1]} count={r[2]}")

log("\n=== VERDICT ===")
log("  If LAS/SEGY are OUTSIDE sample_pdfs: they're leftover inventory from earlier")
log("  crawls — the report shows the whole GLOBAL_FILE_CATALOG, not just this folder.")
log("  A Clear catalog (or a scoped re-scan) removes them. If they're UNDER sample_pdfs,")
log("  the files were actually copied there and the crawl correctly found them.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

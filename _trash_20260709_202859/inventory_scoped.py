"""inventory_scoped.py — a CLEAN inventory of just the folder you're crawling now, two ways:
(1) what's physically in the folder on disk, (2) what the catalog holds for that folder.
Doesn't change anything. py inventory_scoped.py --dir "C:\\...\\sample_pdfs" """
import sys, os, glob, pyodbc
OUT = r"C:\Bulk\reports\inventory_scoped.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

d = None
if "--dir" in sys.argv:
    d = sys.argv[sys.argv.index("--dir")+1]
else:
    d = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs"
log(f"folder: {d}")

# 1) what's ON DISK in that folder (recursive)
log("\n=== 1) files physically in the folder (on disk) ===")
from collections import Counter
disk = glob.glob(os.path.join(d, "**", "*.*"), recursive=True)
disk = [f for f in disk if os.path.isfile(f)]
by_ext = Counter(os.path.splitext(f)[1].lower() for f in disk)
for ext, n in sorted(by_ext.items(), key=lambda x: -x[1]):
    log(f"  {ext or '(none)':8}: {n}")
log(f"  TOTAL on disk: {len(disk)}")

# 2) what the CATALOG holds for that folder path
log("\n=== 2) catalog rows whose FILE_PATH is under this folder ===")
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
# use the folder leaf as the LIKE pattern (robust to OneDrive path variants)
leaf = os.path.basename(d.rstrip("\\/"))
like = f"%{leaf}%"
try:
    rows = c.execute("""SELECT FILE_EXT, COUNT(*),
        SUM(CASE WHEN HEADER_EXTRACTED='Y' THEN 1 ELSE 0 END),
        SUM(CASE WHEN CATALOG_READINESS='CATALOGED' THEN 1 ELSE 0 END)
        FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE FILE_PATH LIKE ? GROUP BY FILE_EXT ORDER BY FILE_EXT""", like).fetchall()
    log(f"  (matching FILE_PATH LIKE '{like}')")
    log(f"  {'ext':8} {'total':>6} {'extracted':>10} {'cataloged':>10}")
    tot=0
    for r in rows:
        log(f"  {r[0] or '(none)':8} {r[1]:>6} {r[2]:>10} {r[3]:>10}")
        tot+=r[1]
    log(f"  TOTAL in catalog for this folder: {tot}")
except Exception as e:
    log("  catalog query err: " + str(e)[:80])

# 3) what's in the catalog but NOT this folder (the 'why is LAS/SEGY showing' leftovers)
log("\n=== 3) catalog rows NOT under this folder (leftover from other crawls) ===")
try:
    rows = c.execute("""SELECT FILE_EXT, COUNT(*)
        FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE FILE_PATH NOT LIKE ? GROUP BY FILE_EXT ORDER BY COUNT(*) DESC""", like).fetchall()
    tot=0
    for r in rows:
        log(f"  {r[0] or '(none)':8}: {r[1]}")
        tot+=r[1]
    log(f"  TOTAL leftover (other folders): {tot}")
    log("  -> these are why the report shows LAS/SEGY. Clear catalog to remove them.")
except Exception as e:
    log("  err: " + str(e)[:60])

open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

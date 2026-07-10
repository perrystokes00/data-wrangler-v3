r"""
backfill_matched_uwi.py — set GLOBAL_FILE_CATALOG.MATCHED_UWI for well-log files
(LAS/LIS/DLIS) that resolved a UWI at capture but never wrote it back to the catalog row.

Why: the fast-path resolves each log's UWI from its header and writes FILE_WELL_HEADER,
but leaves GLOBAL_FILE_CATALOG.MATCHED_UWI blank. The map's v_well_documents view keys
on MATCHED_UWI (GROUP BY, requires non-null), so these wells never show as
'wells with documents' even though their logs promoted. This copies the resolved UWI
from FILE_WELL_HEADER.UWI onto the blank catalog rows (set-based JOIN, not per-row).

SEISMIC (SEG-Y) is intentionally NOT touched: FILE_SEIS_HEADER has no UWI (only
SURVEY_NAME) — seismic maps to surveys (dv_seis_set), a separate map layer, not wells.

  py backfill_matched_uwi.py            # preview (counts, no change)
  py backfill_matched_uwi.py --apply    # write MATCHED_UWI + refresh well_documents table
"""
import sys, pyodbc, os
OUT = r"C:\Bulk\reports\backfill_muwi.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

apply = "--apply" in sys.argv
conn = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
conn.autocommit = not apply
c = conn.cursor()

# which log rows are eligible: blank MATCHED_UWI + a usable FILE_WELL_HEADER.UWI
SEL = """
SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID = g.INVENTORY_ID
WHERE g.FILE_EXT IN ('.las','.lis','.dlis')
  AND NULLIF(LTRIM(RTRIM(g.MATCHED_UWI)),'') IS NULL
  AND NULLIF(LTRIM(RTRIM(h.UWI)),'') IS NOT NULL
"""
n = c.execute(SEL).fetchone()[0]
log(f"well-log rows eligible for MATCHED_UWI backfill: {n}")

if not apply:
    log("\n(preview) re-run with --apply to backfill MATCHED_UWI and refresh well_documents.")
    conn.rollback()
    open(OUT,"w",encoding="utf-8").write("\n".join(L)); print("\n".join(L)); sys.exit()

# set-based update: copy the header UWI onto the blank catalog rows. If multiple headers
# per inventory (shouldn't happen for logs), take MAX to be deterministic.
UPD = """
;WITH src AS (
    SELECT g.INVENTORY_ID, MAX(LTRIM(RTRIM(h.UWI))) AS uwi
    FROM file_catalog.GLOBAL_FILE_CATALOG g
    JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID = g.INVENTORY_ID
    WHERE g.FILE_EXT IN ('.las','.lis','.dlis')
      AND NULLIF(LTRIM(RTRIM(g.MATCHED_UWI)),'') IS NULL
      AND NULLIF(LTRIM(RTRIM(h.UWI)),'') IS NOT NULL
    GROUP BY g.INVENTORY_ID
)
UPDATE g SET g.MATCHED_UWI = src.uwi
FROM file_catalog.GLOBAL_FILE_CATALOG g
JOIN src ON src.INVENTORY_ID = g.INVENTORY_ID
"""
c.execute(UPD)
updated = c.rowcount
conn.commit()
log(f"backfilled MATCHED_UWI on {updated} well-log catalog row(s)")

# refresh the materialized well_documents table from the (live) view so the map updates
try:
    c.execute("IF OBJECT_ID('dataview.well_documents','U') IS NOT NULL TRUNCATE TABLE dataview.well_documents")
    # column list must match; insert from the view
    cols = [r[0] for r in c.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME='well_documents' ORDER BY ORDINAL_POSITION").fetchall()]
    collist = ", ".join(f"[{x}]" for x in cols)
    c.execute(f"INSERT INTO dataview.well_documents ({collist}) SELECT {collist} FROM dataview.v_well_documents")
    conn.commit()
    log(f"refreshed dataview.well_documents ({c.execute('SELECT COUNT(*) FROM dataview.well_documents').fetchone()[0]} rows)")
except Exception as e:
    log(f"(well_documents refresh skipped: {str(e)[:120]})")
    log(" -> if the column lists differ, tell me and I'll match the rebuild exactly.")

# verify the LAS wells now appear
log("\nverify — LAS wells now in v_well_documents:")
for u in ("17031100350000","38105100680000","42475100200000"):
    r = c.execute("SELECT doc_count, log_count, doc_types FROM dataview.v_well_documents WHERE uwi=?", u).fetchone()
    log(f"  {u}: {'doc_count='+str(r[0])+' log_count='+str(r[1])+' types='+str(r[2]) if r else 'still absent'}")

open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L))
print("\n>>> written to",OUT)

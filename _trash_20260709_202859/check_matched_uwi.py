"""check_matched_uwi.py — the v_well_documents view groups by MATCHED_UWI and requires it
non-null. Do LAS/SEGY have MATCHED_UWI set, or is it blank (so they're excluded)?
py check_matched_uwi.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\matched_uwi.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== MATCHED_UWI populated vs blank, by extension ===")
for r in c.execute("""SELECT FILE_EXT,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(MATCHED_UWI)),'') IS NOT NULL THEN 1 ELSE 0 END) AS has_uwi,
    SUM(CASE WHEN NULLIF(LTRIM(RTRIM(MATCHED_UWI)),'') IS NULL THEN 1 ELSE 0 END) AS blank,
    COUNT(*) AS total
    FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE FILE_EXT IN ('.las','.lis','.dlis','.segy','.sgy','.pdf','.xlsx')
    GROUP BY FILE_EXT ORDER BY FILE_EXT""").fetchall():
    flag = "  <-- BLANK = excluded from map docs" if r[2] and r[2]==r[3] else ""
    log(f"  {r[0]:7} has_uwi={r[1]:4} blank={r[2]:4} total={r[3]}{flag}")

log("\n=== are the LAS wells in the view at all? ===")
for u in ("17031100350000","38105100680000","42475100200000"):
    dv = one("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=?", u)
    vw = one("SELECT doc_count FROM dataview.v_well_documents WHERE uwi=?", u)
    tbl = one("SELECT doc_count FROM dataview.well_documents WHERE uwi=?", u)
    log(f"  {u}: dv_well={dv}  v_well_documents.doc_count={vw}  well_documents(table).doc_count={tbl}")

log("\n=== VERDICT ===")
log("  If LAS/SEGY show blank MATCHED_UWI: the view (GROUP BY MATCHED_UWI, requires")
log("  non-null) EXCLUDES them -> not on map as documents, even though FILE_TYPE_GROUP")
log("  is correct. Fix options:")
log("   A) backfill MATCHED_UWI on las/segy rows from their promoted well UWI, OR")
log("   B) change the view to fall back to the header UWI (FILE_WELL_HEADER/FILE_SEIS_HEADER)")
log("      when MATCHED_UWI is blank.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

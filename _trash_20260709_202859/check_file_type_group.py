"""check_file_type_group.py — the map's v_well_documents counts logs/seismic via
GLOBAL_FILE_CATALOG.FILE_TYPE_GROUP. Is it NULL for LAS/SEGY (so they don't count)?
Show FILE_TYPE_GROUP by extension. py check_file_type_group.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\file_type_group.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

log("=== FILE_TYPE_GROUP by extension (what's set vs null) ===")
try:
    for r in c.execute("""SELECT FILE_EXT, FILE_TYPE_GROUP, COUNT(*)
        FROM file_catalog.GLOBAL_FILE_CATALOG
        GROUP BY FILE_EXT, FILE_TYPE_GROUP ORDER BY FILE_EXT""").fetchall():
        log(f"  {r[0] or '(none)':8} FILE_TYPE_GROUP={r[1]!r:16} count={r[2]}")
except Exception as e:
    log("  err (column exists?):", str(e)[:80])

log("\n=== specifically: LAS / LIS / DLIS / SEGY ===")
for ext in (".las",".lis",".dlis",".segy",".sgy"):
    tot = c.execute("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT=?", ext).fetchone()[0]
    nullftg = c.execute("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT=? AND (FILE_TYPE_GROUP IS NULL OR LTRIM(RTRIM(FILE_TYPE_GROUP))='')", ext).fetchone()[0]
    if tot:
        log(f"  {ext}: {tot} files, {nullftg} with NULL/blank FILE_TYPE_GROUP")

log("\n=== what FILE_TYPE_GROUP do working docs (pdf/xlsx) use? (the correct values) ===")
for r in c.execute("""SELECT FILE_TYPE_GROUP, COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE FILE_TYPE_GROUP IS NOT NULL GROUP BY FILE_TYPE_GROUP ORDER BY FILE_TYPE_GROUP""").fetchall():
    log(f"  {r[0]!r}: {r[1]}")

log("\n=== VERDICT ===")
log("  The view counts 'Well Log' and 'Seismic' correctly, but only if FILE_TYPE_GROUP")
log("  is set. If LAS/SEGY show NULL above, the fast-paths never set it -> they don't")
log("  count as documents on the map. Fix = set FILE_TYPE_GROUP='Well Log' for las/lis/")
log("  dlis and 'Seismic' for segy (in the fast-path, or a post-capture UPDATE).")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

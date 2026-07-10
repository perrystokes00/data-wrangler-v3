"""clear_seismic.py — delete loaded seismic (FILE_SEIS_HEADER + dv_seis_set) and
reset the SEG-Y catalog flags so a re-run recaptures them WITH convex-hull outlines.
py clear_seismic.py            (preview)
py clear_seismic.py --apply    (delete)"""
import sys, pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]
APPLY = "--apply" in sys.argv

print("=== current seismic state ===")
print("  FILE_SEIS_HEADER rows        :", f("SELECT COUNT(*) FROM file_catalog.FILE_SEIS_HEADER"))
print("  ...with SURVEY_OUTLINE (hull):", f("SELECT COUNT(*) FROM file_catalog.FILE_SEIS_HEADER WHERE SURVEY_OUTLINE IS NOT NULL"))
print("  dv_seis_set rows             :", f("SELECT COUNT(*) FROM dataview.dv_seis_set"))
segy = f("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
           WHERE LOWER(FILE_EXT) IN ('.segy','.sgy','.seg')""")
print("  .segy/.sgy/.seg in catalog   :", segy)

if not APPLY:
    print("\n(preview only) add --apply to delete + reset for re-capture")
    sys.exit(0)

# 1) drop promoted seismic sets
n1 = c.execute("DELETE FROM dataview.dv_seis_set").rowcount
# 2) drop the captured headers
n2 = c.execute("DELETE FROM file_catalog.FILE_SEIS_HEADER").rowcount
# 3) reset catalog flags on SEG-Y files so capture re-selects them
n3 = c.execute("""
    UPDATE file_catalog.GLOBAL_FILE_CATALOG
    SET CAPTURED_HASH = NULL,
        HEADER_EXTRACTED = 'N',
        CATALOG_READINESS = NULL,
        PROMOTED_AT = NULL,
        ROW_CHANGED_DATE = GETUTCDATE()
    WHERE LOWER(FILE_EXT) IN ('.segy','.sgy','.seg')""").rowcount

print(f"\ndeleted dv_seis_set={n1}, FILE_SEIS_HEADER={n2}, reset {n3} SEG-Y catalog row(s)")
print("now re-run the pipeline (capture on) — SEG-Y recaptures WITH hull outlines.")

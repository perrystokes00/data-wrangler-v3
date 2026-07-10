"""fix_matched_uwi.py — the LAS headers hold valid UWI14 (402) but GLOBAL_FILE_CATALOG
.MATCHED_UWI is empty, so triage tiered them NEEDS_UWI and capture skipped them. Copy
UWI14 from FILE_WELL_HEADER up to MATCHED_UWI + fix CATALOG_READINESS, so capture/promote
can pick them up. py fix_matched_uwi.py [--apply]"""
import sys, pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
APPLY = "--apply" in sys.argv

# how many would be fixed?
n = c.execute("""
    SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
    JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID = g.INVENTORY_ID
    WHERE h.UWI14 IS NOT NULL AND (g.MATCHED_UWI IS NULL OR g.MATCHED_UWI='')""").fetchone()[0]
print(f"{n} catalog row(s) have a header UWI14 but no MATCHED_UWI")

if not APPLY:
    print("add --apply to copy UWI14 -> MATCHED_UWI and clear NEEDS_UWI"); sys.exit(0)

nr = c.execute("""
    UPDATE g SET g.MATCHED_UWI = h.UWI14,
                 g.CATALOG_READINESS = CASE WHEN g.CATALOG_READINESS='NEEDS_UWI'
                                            THEN 'READY' ELSE g.CATALOG_READINESS END
    FROM file_catalog.GLOBAL_FILE_CATALOG g
    JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID = g.INVENTORY_ID
    WHERE h.UWI14 IS NOT NULL AND (g.MATCHED_UWI IS NULL OR g.MATCHED_UWI='')""").rowcount
print(f"updated {nr} row(s): MATCHED_UWI set, NEEDS_UWI -> READY")
print("now re-run capture+promote (run_load.py, or repromote2.py if headers already captured)")

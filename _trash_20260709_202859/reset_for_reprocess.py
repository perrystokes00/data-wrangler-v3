r"""
reset_for_reprocess.py — reset catalog file state after an aborted run so the next
pipeline run reprocesses them cleanly.

  py reset_for_reprocess.py                          # preview: what's in scope
  py reset_for_reprocess.py --apply                  # reset ALL files to pending
  py reset_for_reprocess.py --folder "C:\...\_selected_500" --apply
  py reset_for_reprocess.py --folder "..." --apply --purge   # also delete their captured rows
  py reset_for_reprocess.py --stuck --apply          # only files marked extracted but NOT captured

State reset: HEADER_EXTRACTED -> 'N', CATALOG_READINESS -> NULL (re-extract/triage/
capture). --purge also clears cat_*/FILE_WELL_HEADER rows for those files so capture
re-writes from scratch.
"""
import sys, pyodbc
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
cn = pyodbc.connect(CONN, autocommit=True)
cur = cn.cursor()

GFC = "file_catalog.GLOBAL_FILE_CATALOG"
folder = sys.argv[sys.argv.index("--folder") + 1] if "--folder" in sys.argv else None

where, params = "1=1", []
if folder:
    where = "FILE_PATH LIKE ?"
    params = [folder.rstrip("\\/") + "%"]
elif "--stuck" in sys.argv:
    # files marked extracted but with no captured well rows (aborted mid-capture)
    where = ("HEADER_EXTRACTED='Y' AND INVENTORY_ID NOT IN "
             "(SELECT INVENTORY_ID FROM file_catalog.cat_well WHERE INVENTORY_ID IS NOT NULL)")

iids = [r[0] for r in cur.execute(
    f"SELECT INVENTORY_ID FROM {GFC} WHERE {where} AND ISNULL(FLAG_DELETE,'N')<>'Y'",
    *params).fetchall()]
print(f"{len(iids):,} file(s) in scope")

if "--apply" not in sys.argv:
    print("\n[dry run] --apply to reset to pending "
          "(+ --purge to also clear captured/header rows).")
    sys.exit(0)

n = cur.execute(
    f"UPDATE {GFC} SET HEADER_EXTRACTED='N', CATALOG_READINESS=NULL, "
    f"ROW_CHANGED_DATE=GETUTCDATE() WHERE {where} AND ISNULL(FLAG_DELETE,'N')<>'Y'",
    *params).rowcount
print(f"reset {n:,} file(s) to pending")

if "--purge" in sys.argv and iids:
    total = 0
    for t in ("cat_well_log_curve", "cat_well_log", "cat_well", "FILE_WELL_HEADER"):
        if not cur.execute("SELECT OBJECT_ID('file_catalog." + t + "')").fetchone()[0]:
            continue
        d = 0
        for i in range(0, len(iids), 1000):
            blk = ",".join(str(int(x)) for x in iids[i:i+1000] if x is not None)
            if blk:
                d += cur.execute(
                    f"DELETE FROM file_catalog.{t} WHERE INVENTORY_ID IN ({blk})").rowcount or 0
        print(f"  purged {d:,} row(s) from {t}")
        total += d
    print(f"purged {total:,} captured/header row(s)")

print("\nnow re-run the pipeline — these files reprocess from scratch.")

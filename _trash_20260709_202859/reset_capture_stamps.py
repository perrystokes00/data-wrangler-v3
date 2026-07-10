r"""
reset_capture_stamps.py — clear stale CAPTURED_HASH (and optionally VAULTED_AT/
PROMOTED_AT) on GLOBAL_FILE_CATALOG so files re-capture on the next pipeline run.

Why: the capture stage skips any file whose CAPTURED_HASH == FILE_HASH ("already
captured"). If you cleared the catalog's cat_*/dv_* rows but the CAPTURED_HASH stamps
survived, capture wrongly believes the files are done and skips them — so LAS (and any
other) files get marked extracted but write no cat_well/curves. This nulls the stamps
so a re-crawl actually re-captures.

  py reset_capture_stamps.py                     # preview counts
  py reset_capture_stamps.py --apply             # clear CAPTURED_HASH for ALL files
  py reset_capture_stamps.py --apply --ext .las  # only .las
  py reset_capture_stamps.py --apply --all-stamps# also clear VAULTED_AT + PROMOTED_AT
"""
import sys, pyodbc

def main():
    apply = "--apply" in sys.argv
    ext = None
    if "--ext" in sys.argv:
        ext = sys.argv[sys.argv.index("--ext")+1].lower()
        if not ext.startswith("."):
            ext = "." + ext
    all_stamps = "--all-stamps" in sys.argv

    conn = pyodbc.connect(
        r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
    conn.autocommit = not apply
    cur = conn.cursor()

    where = "WHERE CAPTURED_HASH IS NOT NULL"
    params = []
    if ext:
        where += " AND LOWER(FILE_EXT) = ?"
        params.append(ext)

    n = cur.execute(f"SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG {where}",
                    *params).fetchone()[0]
    print(f"files with a CAPTURED_HASH stamp{' (.'+ext.lstrip('.')+')' if ext else ''}: {n}")

    if not apply:
        print("\n(preview) re-run with --apply to clear the stamp so these re-capture.")
        return

    sets = ["CAPTURED_HASH = NULL"]
    if all_stamps:
        sets += ["VAULTED_AT = NULL", "PROMOTED_AT = NULL"]
    cur.execute(f"UPDATE file_catalog.GLOBAL_FILE_CATALOG SET {', '.join(sets)} {where}",
                *params)
    cleared = cur.rowcount or 0
    conn.commit()
    print(f"cleared stamps on {cleared} file(s): {', '.join(sets)}")
    print("now re-run the pipeline (Capture ON) — these files will re-capture.")


if __name__ == "__main__":
    main()

"""Show the FULL PATHS of skipped files for a given extension, so we can tell
expected-empty from should-have-loaded. Usage: py skip_detail.py .pdf"""
import sys
import worker_core as w
from sqlalchemy import text
ext = (sys.argv[1] if len(sys.argv) > 1 else ".pdf").lower()
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    rows = c.execute(text("""
        SELECT FILE_PATH FROM file_catalog.GLOBAL_FILE_CATALOG
         WHERE PROC_STATUS='done' AND ISNULL(PROC_ROWS,0)=0
           AND LOWER(FILE_EXT)=:x ORDER BY FILE_PATH
    """), {"x": ext}).fetchall()
    print(f"{len(rows)} skipped {ext} files:\n")
    for (p,) in rows:
        print(" ", p)

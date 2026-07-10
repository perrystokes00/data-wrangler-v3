"""Show the full error list with file paths and messages."""
import worker_core as w
from sqlalchemy import text

e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    rows = c.execute(text("""
        SELECT FILE_PATH, FILE_EXT, PROC_ERROR, PROC_ATTEMPTS
          FROM file_catalog.GLOBAL_FILE_CATALOG
         WHERE PROC_STATUS = 'error'
         ORDER BY FILE_EXT, FILE_PATH
    """)).fetchall()

print(f"{len(rows)} file(s) in error state:\n")
for path, ext, err, attempts in rows:
    print(f"[{ext}]  attempts={attempts}")
    print(f"  path:  {path}")
    print(f"  error: {err}")
    print()

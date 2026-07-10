"""List the files that errored with a UWI message, so we can eyeball them."""
import worker_core as w
from sqlalchemy import text

e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    rows = c.execute(text("""
        SELECT FILE_PATH, FILE_EXT, PROC_ERROR
          FROM file_catalog.GLOBAL_FILE_CATALOG
         WHERE PROC_STATUS = 'error'
           AND (PROC_ERROR LIKE '%UWI%')
         ORDER BY FILE_PATH
    """)).fetchall()

print(f"{len(rows)} files errored on a UWI message:\n")
for path, ext, err in rows:
    print(path)

# also show the parent folders, in case they cluster in one place
from collections import Counter
import os
folders = Counter(os.path.dirname(p) for p, _, _ in rows)
print("\n── by folder ──")
for folder, n in folders.most_common():
    print(f"  {n:4}  {folder}")

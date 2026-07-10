"""Dump the raw DLIS/LIS filenames so we can design real well-name extraction."""
import os
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    rows = c.execute(text(
        "SELECT DISTINCT FILE_PATH FROM file_catalog.GLOBAL_FILE_CATALOG "
        "WHERE LOWER(FILE_EXT) IN ('.dlis','.lis') ORDER BY FILE_PATH")).fetchall()
print(f"{len(rows)} DLIS/LIS files — raw filenames:\n")
for (p,) in rows:
    print(" ", os.path.basename(p or ""))

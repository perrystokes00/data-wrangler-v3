import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    rows = c.execute(text(
        "SELECT FILE_EXT, PROC_ERROR, COUNT(*) n "
        "FROM file_catalog.GLOBAL_FILE_CATALOG "
        "WHERE PROC_STATUS='error' GROUP BY FILE_EXT, PROC_ERROR")).fetchall()
    for ext, err, n in rows:
        print(f"{ext}  ×{n}  {(err or '')[:150]}")

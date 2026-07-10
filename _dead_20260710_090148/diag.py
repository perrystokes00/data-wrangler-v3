import worker_core as wc
from sqlalchemy import text

e = wc.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("connected to DB:", c.execute(text("SELECT DB_NAME()")).scalar())
    print("engine url:", repr(e.url))
    cols = [r[0] for r in c.execute(text(
        "SELECT name FROM sys.columns "
        "WHERE object_id = OBJECT_ID('file_catalog.GLOBAL_FILE_CATALOG') "
        "AND name LIKE 'PROC[_]%'")).fetchall()]
    print("PROC_ columns seen:", cols)
    try:
        c.execute(text("SELECT TOP 1 PROC_STATUS FROM file_catalog.GLOBAL_FILE_CATALOG")).fetchall()
        print("direct SELECT PROC_STATUS: OK")
    except Exception as ex:
        print("direct SELECT FAILED:", type(ex).__name__, str(ex)[:150])

"""Break down what got skipped — by extension, so we can tell expected skips
(no handler, nothing to load) from anything that shouldn't be skipped."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    # done rows with 0 rows_written are effectively the "skips" (processed but
    # nothing loaded). Group by extension.
    print("── files that produced 0 rows (the 'skips'), by extension ──")
    rows = c.execute(text("""
        SELECT LOWER(FILE_EXT) ext, COUNT(*) n
          FROM file_catalog.GLOBAL_FILE_CATALOG
         WHERE PROC_STATUS='done' AND ISNULL(PROC_ROWS,0)=0
         GROUP BY LOWER(FILE_EXT)
         ORDER BY n DESC
    """)).fetchall()
    tot = 0
    for ext, n in rows:
        print(f"  {ext or '(none)':12} {n:>5}")
        tot += n
    print(f"  {'TOTAL':12} {tot:>5}")

    print("\n── for comparison: files that DID load rows, by extension ──")
    for ext, n, r in c.execute(text("""
        SELECT LOWER(FILE_EXT) ext, COUNT(*) n, SUM(PROC_ROWS) r
          FROM file_catalog.GLOBAL_FILE_CATALOG
         WHERE PROC_STATUS='done' AND ISNULL(PROC_ROWS,0)>0
         GROUP BY LOWER(FILE_EXT) ORDER BY n DESC
    """)).fetchall():
        print(f"  {ext or '(none)':12} {n:>5} files  {r:>7,} rows")

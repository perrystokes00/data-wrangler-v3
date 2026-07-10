"""Why won't the regular pipeline pick up the 'pending' files? It selects
WHERE (HEADER_EXTRACTED IS NULL OR ='N') AND DUPLICATE_GROUP IS NULL.
Show the real values of those columns so we see what's blocking it."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== HEADER_EXTRACTED distribution ===")
    for v, n in c.execute(text("""
        SELECT COALESCE(CAST(HEADER_EXTRACTED AS varchar(10)),'(null)') hx,
               COUNT(*) n FROM file_catalog.GLOBAL_FILE_CATALOG
        GROUP BY HEADER_EXTRACTED ORDER BY n DESC""")).fetchall():
        print(f"   HEADER_EXTRACTED={v:12} {n:,}")

    print("\n=== DUPLICATE_GROUP: how many are non-null (skipped by extract)? ===")
    for v, n in c.execute(text("""
        SELECT CASE WHEN DUPLICATE_GROUP IS NULL THEN '(null - eligible)'
                    ELSE '(has dup group - SKIPPED)' END g, COUNT(*) n
        FROM file_catalog.GLOBAL_FILE_CATALOG GROUP BY
        CASE WHEN DUPLICATE_GROUP IS NULL THEN '(null - eligible)'
             ELSE '(has dup group - SKIPPED)' END""")).fetchall():
        print(f"   {v:30} {n:,}")

    print("\n=== what the regular pipeline's extract query would actually find ===")
    n = c.execute(text("""
        SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE (HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED='N')
          AND ISNULL(HEADER_EXTRACTED,'') <> 'S'
          AND DUPLICATE_GROUP IS NULL""")).scalar()
    print(f"   extract-eligible rows: {n:,}")
    print("   (if 0, the regular pipeline thinks everything's done — that's why")
    print("    'run again' does nothing. The pool marked them done via a")
    print("    different column than the regular pipeline reads.)")

    print("\n=== PROC_STATUS vs HEADER_EXTRACTED cross-check ===")
    for ps, hx, n in c.execute(text("""
        SELECT COALESCE(PROC_STATUS,'(null)') ps,
               COALESCE(CAST(HEADER_EXTRACTED AS varchar(10)),'(null)') hx,
               COUNT(*) n FROM file_catalog.GLOBAL_FILE_CATALOG
        GROUP BY PROC_STATUS, HEADER_EXTRACTED ORDER BY n DESC""")).fetchall():
        print(f"   PROC_STATUS={ps:10} HEADER_EXTRACTED={hx:10} {n:,}")

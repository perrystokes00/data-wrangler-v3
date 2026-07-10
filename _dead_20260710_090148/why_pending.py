"""Why are files 'pending'? Show the queue state and per-extension processing
status so we can see whether the regular pipeline genuinely skipped files or
just counts differently than the pool."""
import worker_core as w
from sqlalchemy import text

e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== queue status (PROC_STATUS in GLOBAL_FILE_CATALOG) ===")
    try:
        rows = c.execute(text("""
            SELECT COALESCE(PROC_STATUS,'(null)') AS status, COUNT(*) n
              FROM file_catalog.GLOBAL_FILE_CATALOG
             GROUP BY PROC_STATUS ORDER BY n DESC""")).fetchall()
        for s, n in rows:
            print(f"   {s:20} {n:,}")
    except Exception as ex:
        print("   ", ex)

    print("\n=== by extension: inventoried vs header-extracted ===")
    try:
        rows = c.execute(text("""
            SELECT LOWER(FILE_EXT) ext, COUNT(*) inv,
                   SUM(CASE WHEN HEADER_EXTRACTED=1 THEN 1 ELSE 0 END) extracted,
                   SUM(CASE WHEN COALESCE(PROC_STATUS,'pending')='pending'
                            THEN 1 ELSE 0 END) pending
              FROM file_catalog.GLOBAL_FILE_CATALOG
             GROUP BY LOWER(FILE_EXT) ORDER BY inv DESC""")).fetchall()
        print(f"   {'ext':10} {'inv':>6} {'extracted':>10} {'pending':>8}")
        for ext, inv, ext2, pend in rows:
            print(f"   {ext or '(none)':10} {inv:>6} {ext2 or 0:>10} {pend or 0:>8}")
    except Exception as ex:
        print("   ", ex)

    print("\n=== total inventory ===")
    n = c.execute(text(
        "SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG")).scalar()
    print(f"   {n:,} files in GLOBAL_FILE_CATALOG")

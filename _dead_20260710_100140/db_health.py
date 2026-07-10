"""Check catalog table sizes + fragmentation — diagnose the slowdown."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("── row counts in catalog tables ──")
    for t in ("GLOBAL_FILE_CATALOG","cat_well","cat_well_log",
              "cat_well_log_curve","cat_well_formation_top",
              "cat_well_dir_srvy_sta","dv_seis_set"):
        try:
            n = c.execute(text(f"SELECT COUNT(*) FROM file_catalog.{t}")).scalar()
            print(f"  {t:28} {n:>10,}")
        except Exception as ex:
            print(f"  {t:28} (err: {ex})")

    print("\n── table sizes (MB) + fragmentation ──")
    rows = c.execute(text("""
        SELECT OBJECT_NAME(ips.object_id) AS tbl,
               ips.avg_fragmentation_in_percent AS frag,
               ips.page_count * 8.0 / 1024 AS mb
          FROM sys.dm_db_index_physical_stats(DB_ID(),NULL,NULL,NULL,'LIMITED') ips
         WHERE ips.page_count > 100
         ORDER BY ips.page_count DESC
    """)).fetchall()
    for tbl, frag, mb in rows[:15]:
        print(f"  {str(tbl):28} {mb:8.1f} MB  frag={frag:5.1f}%")

    # transaction log size
    print("\n── DB file sizes ──")
    for name, mb in c.execute(text("""
        SELECT name, size*8.0/1024 FROM sys.database_files
    """)).fetchall():
        print(f"  {name:28} {mb:8.1f} MB")

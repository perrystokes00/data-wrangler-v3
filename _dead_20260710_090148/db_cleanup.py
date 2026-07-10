"""Reclaim the bloated test DB: truncate mirror tables, rebuild fragmented
indexes, shrink the 25GB log. Test-DB (DataView_Demo) only — never prod.

Run this with the pool STOPPED.
"""
import worker_core as w
from sqlalchemy import text

MIRRORS = ["cat_well","cat_well_log","cat_well_log_curve","cat_well_formation_top",
           "cat_well_dir_srvy_hdr","cat_well_dir_srvy_sta","cat_well_completion",
           "cat_well_core","cat_well_core_sample","cat_well_dst","cat_prod_entity",
           "cat_prod_volume","cat_well_petro_interp","cat_well_petro_zone",
           "cat_well_stimulation","FILE_SEIS_HEADER"]

e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")

# 1) truncate mirrors (clears the churn; keeps GLOBAL_FILE_CATALOG queue)
with e.begin() as c:
    for t in MIRRORS:
        try:
            c.execute(text(f"TRUNCATE TABLE file_catalog.{t}"))
            print(f"  truncated {t}")
        except Exception as ex:
            print(f"  skip {t} ({str(ex)[:60]})")

# 2) rebuild indexes on the hot tables (defragment). autocommit for DDL.
raw = e.raw_connection()
try:
    raw.autocommit = True
    cur = raw.cursor()
    for t in ["GLOBAL_FILE_CATALOG"] + MIRRORS:
        try:
            cur.execute(f"ALTER INDEX ALL ON file_catalog.{t} REBUILD")
            print(f"  rebuilt indexes on {t}")
        except Exception as ex:
            print(f"  skip rebuild {t} ({str(ex)[:50]})")
finally:
    raw.close()

# 3) shrink the log. switch to SIMPLE recovery first so it can actually shrink,
#    then shrink the logical log file.
raw = e.raw_connection()
try:
    raw.autocommit = True
    cur = raw.cursor()
    cur.execute("ALTER DATABASE DataView_Demo SET RECOVERY SIMPLE")
    print("  recovery model → SIMPLE")
    # find the log file logical name
    cur.execute("SELECT name FROM sys.database_files WHERE type_desc='LOG'")
    logname = cur.fetchone()[0]
    cur.execute(f"DBCC SHRINKFILE (N'{logname}', 512)")
    print(f"  shrank log '{logname}' toward 512 MB")
finally:
    raw.close()

print("\ncleanup done — re-check with db_health.py")

"""Rebuild indexes on GLOBAL_FILE_CATALOG (still 98.8% fragmented). This is the
hot table — every claim_batch and status write hits it. autocommit, no txn."""
import pyodbc

cs = ("DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost\\SQLEXPRESS;"
      "DATABASE=DataView_Demo;Trusted_Connection=yes;")
conn = pyodbc.connect(cs, autocommit=True)
cur = conn.cursor()

GFC = "file_catalog.GLOBAL_FILE_CATALOG"

# show indexes + fragmentation before
print("── before ──")
cur.execute("""
    SELECT i.name, ips.avg_fragmentation_in_percent, ips.page_count
      FROM sys.dm_db_index_physical_stats(DB_ID(),
             OBJECT_ID('file_catalog.GLOBAL_FILE_CATALOG'),NULL,NULL,'LIMITED') ips
      JOIN sys.indexes i ON i.object_id=ips.object_id AND i.index_id=ips.index_id
     WHERE ips.page_count > 50
""")
for name, frag, pages in cur.fetchall():
    print(f"  {str(name):30} frag={frag:5.1f}%  pages={pages}")

# does it even have a clustered index? if it's a HEAP, REBUILD won't help —
# heaps fragment and need ALTER TABLE ... REBUILD instead.
cur.execute("""
    SELECT type_desc FROM sys.indexes
     WHERE object_id=OBJECT_ID('file_catalog.GLOBAL_FILE_CATALOG')
""")
types = [r[0] for r in cur.fetchall()]
print(f"\n  index types present: {types}")

if "CLUSTERED" not in types:
    # HEAP table — rebuild the heap itself to compact it
    print("  → HEAP table; running ALTER TABLE REBUILD")
    cur.execute(f"ALTER TABLE {GFC} REBUILD")
else:
    cur.execute(f"ALTER INDEX ALL ON {GFC} REBUILD")
print("  rebuilt.")

# also rebuild nonclustered indexes explicitly
cur.execute(f"ALTER INDEX ALL ON {GFC} REBUILD")

print("\n── after ──")
cur.execute("""
    SELECT i.name, ips.avg_fragmentation_in_percent, ips.page_count
      FROM sys.dm_db_index_physical_stats(DB_ID(),
             OBJECT_ID('file_catalog.GLOBAL_FILE_CATALOG'),NULL,NULL,'LIMITED') ips
      JOIN sys.indexes i ON i.object_id=ips.object_id AND i.index_id=ips.index_id
     WHERE ips.page_count > 50
""")
for name, frag, pages in cur.fetchall():
    print(f"  {str(name):30} frag={frag:5.1f}%  pages={pages}")
conn.close()

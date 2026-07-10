"""
delete_ks_no_docs.py — delete Kansas wells (uwi starts with '15') from dataview.dv_well
that have NO associated document (no GLOBAL_FILE_CATALOG row with matching UWI14).

  py delete_ks_no_docs.py              # PREVIEW only (counts + child rows), no changes
  py delete_ks_no_docs.py --apply      # back up + delete the childless ones
  py delete_ks_no_docs.py --apply --cascade   # also delete their child rows first

Backs up the to-delete wells to stg.dv_well_ks_nodoc_bak before deleting.
"""
import sys, pyodbc
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
c = pyodbc.connect(CONN, autocommit=True)
cur = c.cursor()
scalar = lambda q: cur.execute(q).fetchone()[0]

# Kansas + no associated document
PRED = ("LEFT(w.uwi,2) = '15' AND NOT EXISTS ("
        "SELECT 1 FROM file_catalog.GLOBAL_FILE_CATALOG g WHERE g.UWI14 = w.uwi)")

tot = scalar("SELECT COUNT(*) FROM dataview.dv_well w WHERE LEFT(w.uwi,2)='15'")
nod = scalar(f"SELECT COUNT(*) FROM dataview.dv_well w WHERE {PRED}")
print(f"Kansas wells (uwi '15…')          : {tot:,}")
print(f"  with a document      (keep)     : {tot - nod:,}")
print(f"  WITHOUT a document   (delete)   : {nod:,}")

# FK children of dv_well and how many rows tie to the to-delete wells
fks = cur.execute("""
  SELECT OBJECT_SCHEMA_NAME(fk.parent_object_id) AS sch,
         OBJECT_NAME(fk.parent_object_id)        AS tbl,
         cp.name AS child_col, cr.name AS ref_col
  FROM sys.foreign_keys fk
  JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
  JOIN sys.columns cp ON cp.object_id=fkc.parent_object_id AND cp.column_id=fkc.parent_column_id
  JOIN sys.columns cr ON cr.object_id=fkc.referenced_object_id AND cr.column_id=fkc.referenced_column_id
  WHERE fk.referenced_object_id = OBJECT_ID('dataview.dv_well')""").fetchall()

print("\nchild tables (FK -> dv_well) with rows tied to the to-delete wells:")
child_deletes, blocking = [], 0
for r in fks:
    n = scalar(f"SELECT COUNT(*) FROM [{r.sch}].[{r.tbl}] ch WHERE ch.[{r.child_col}] "
               f"IN (SELECT w.[{r.ref_col}] FROM dataview.dv_well w WHERE {PRED})")
    print(f"  {r.sch}.{r.tbl}.{r.child_col} -> {n:,}")
    if n:
        blocking += n
        child_deletes.append((r.sch, r.tbl, r.child_col, r.ref_col))
if not fks:
    print("  (no FK constraints reference dv_well)")

apply   = "--apply" in sys.argv
cascade = "--cascade" in sys.argv

if not apply:
    print(f"\n[dry run] would delete {nod:,} wells; {blocking:,} child row(s) reference them.")
    if blocking and not cascade:
        print("  -> those wells are blocked by children; add --cascade to remove children too.")
    print("  add --apply to proceed (backs up first).")
    sys.exit(0)

# backup
cur.execute("IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg')")
cur.execute("IF OBJECT_ID('stg.dv_well_ks_nodoc_bak') IS NOT NULL DROP TABLE stg.dv_well_ks_nodoc_bak")
b = cur.execute(f"SELECT w.* INTO stg.dv_well_ks_nodoc_bak "
                f"FROM dataview.dv_well w WHERE {PRED}").rowcount
print(f"\nbacked up {b:,} rows -> stg.dv_well_ks_nodoc_bak")

if blocking and not cascade:
    print(f"ABORT: {blocking:,} child row(s) would block the delete. "
          "Re-run with --apply --cascade to remove children first.")
    sys.exit(1)

if cascade:
    for sch, tbl, col, ref in child_deletes:
        n = cur.execute(f"DELETE ch FROM [{sch}].[{tbl}] ch WHERE ch.[{col}] "
                        f"IN (SELECT w.[{ref}] FROM dataview.dv_well w WHERE {PRED})").rowcount
        print(f"  deleted {n:,} from {sch}.{tbl}")

deleted = cur.execute(f"DELETE w FROM dataview.dv_well w WHERE {PRED}").rowcount
print(f"deleted {deleted:,} Kansas wells without documents")
print("(restore if needed: INSERT INTO dataview.dv_well SELECT * FROM stg.dv_well_ks_nodoc_bak)")

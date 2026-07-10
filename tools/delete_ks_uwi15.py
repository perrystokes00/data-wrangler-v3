"""
delete_ks_uwi15.py — delete all Kansas wells whose uwi starts with '15' from
dataview.dv_well.

  py delete_ks_uwi15.py                    # PREVIEW (counts + child rows)
  py delete_ks_uwi15.py --apply            # back up + delete childless ones
  py delete_ks_uwi15.py --apply --cascade  # also delete their child rows first

Backs up deleted wells to stg.dv_well_ks15_bak before deleting.
"""
import sys, pyodbc
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
cur = pyodbc.connect(CONN, autocommit=True).cursor()
scalar = lambda q: cur.execute(q).fetchone()[0]

PRED = "LEFT(w.uwi,2) = '15'"

n = scalar(f"SELECT COUNT(*) FROM dataview.dv_well w WHERE {PRED}")
print(f"Kansas wells (uwi '15…') to delete: {n:,}")

fks = cur.execute("""
  SELECT OBJECT_SCHEMA_NAME(fk.parent_object_id) AS sch,
         OBJECT_NAME(fk.parent_object_id)        AS tbl,
         cp.name AS child_col, cr.name AS ref_col
  FROM sys.foreign_keys fk
  JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
  JOIN sys.columns cp ON cp.object_id=fkc.parent_object_id AND cp.column_id=fkc.parent_column_id
  JOIN sys.columns cr ON cr.object_id=fkc.referenced_object_id AND cr.column_id=fkc.referenced_column_id
  WHERE fk.referenced_object_id = OBJECT_ID('dataview.dv_well')""").fetchall()

print("\nchild tables (FK -> dv_well) with rows tied to these wells:")
child_deletes, blocking = [], 0
for r in fks:
    m = scalar(f"SELECT COUNT(*) FROM [{r.sch}].[{r.tbl}] ch WHERE ch.[{r.child_col}] "
               f"IN (SELECT w.[{r.ref_col}] FROM dataview.dv_well w WHERE {PRED})")
    print(f"  {r.sch}.{r.tbl}.{r.child_col} -> {m:,}")
    if m:
        blocking += m
        child_deletes.append((r.sch, r.tbl, r.child_col, r.ref_col))
if not fks:
    print("  (no FK constraints reference dv_well)")

apply, cascade = "--apply" in sys.argv, "--cascade" in sys.argv
if not apply:
    print(f"\n[dry run] would delete {n:,} wells; {blocking:,} child row(s) reference them.")
    if blocking:
        print("  -> add --apply --cascade to remove their children too.")
    print("  add --apply to proceed (backs up first).")
    sys.exit(0)

cur.execute("IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg')")
cur.execute("IF OBJECT_ID('stg.dv_well_ks15_bak') IS NOT NULL DROP TABLE stg.dv_well_ks15_bak")
b = cur.execute(f"SELECT w.* INTO stg.dv_well_ks15_bak "
                f"FROM dataview.dv_well w WHERE {PRED}").rowcount
print(f"\nbacked up {b:,} rows -> stg.dv_well_ks15_bak")

if blocking and not cascade:
    print(f"ABORT: {blocking:,} child row(s) would block the delete. "
          "Re-run with --apply --cascade."); sys.exit(1)

if cascade:
    for sch, tbl, col, ref in child_deletes:
        d = cur.execute(f"DELETE ch FROM [{sch}].[{tbl}] ch WHERE ch.[{col}] "
                        f"IN (SELECT w.[{ref}] FROM dataview.dv_well w WHERE {PRED})").rowcount
        print(f"  deleted {d:,} from {sch}.{tbl}")

deleted = cur.execute(f"DELETE w FROM dataview.dv_well w WHERE {PRED}").rowcount
print(f"deleted {deleted:,} Kansas wells (uwi '15…')")
print("(restore: INSERT INTO dataview.dv_well SELECT * FROM stg.dv_well_ks15_bak)")

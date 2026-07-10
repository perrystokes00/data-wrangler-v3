"""find_uom_ref.py — locate the real UOM reference table + key column that promote
checks curve_unit/depth_ouom against. py find_uom_ref.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()

print("=== dv_r_* / uom / unit reference tables ===")
for r in cur.execute("""
    SELECT s.name sch, t.name tbl, SUM(p.rows) rows
    FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
    JOIN sys.partitions p ON p.object_id=t.object_id AND p.index_id IN (0,1)
    WHERE t.name LIKE 'dv_r%' OR t.name LIKE '%uom%' OR t.name LIKE '%unit%'
    GROUP BY s.name, t.name ORDER BY t.name""").fetchall():
    print(f"  {r.sch}.{r.tbl}: {r.rows:,}")

print("\n=== columns of any uom/unit ref table (find the key column) ===")
for r in cur.execute("""
    SELECT s.name sch, t.name tbl FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id=t.schema_id
    WHERE t.name LIKE '%uom%' OR t.name LIKE '%unit%'""").fetchall():
    full = f"{r.sch}.{r.tbl}"
    cols = [x[0] for x in cur.execute(
        "SELECT name FROM sys.columns WHERE object_id=OBJECT_ID(?) ORDER BY column_id", full).fetchall()]
    print(f"  {full}: {cols}")
    # peek a couple rows
    try:
        for row in cur.execute(f"SELECT TOP 3 * FROM {full}").fetchall():
            print("     ", tuple(row))
    except Exception as e:
        print("     ", str(e)[:60])

# how does promote resolve the FK? look at the actual FK on dv_well_log_curve
print("\n=== FK from dv_well_log_curve on a *_uom/*_unit column (what it references) ===")
for r in cur.execute("""
    SELECT fk.name, cpar.name AS child_col, OBJECT_SCHEMA_NAME(fk.referenced_object_id)+'.'
           +OBJECT_NAME(fk.referenced_object_id) AS ref_tbl, cref.name AS ref_col
    FROM sys.foreign_keys fk
    JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id
    JOIN sys.columns cpar ON cpar.object_id=fkc.parent_object_id AND cpar.column_id=fkc.parent_column_id
    JOIN sys.columns cref ON cref.object_id=fkc.referenced_object_id AND cref.column_id=fkc.referenced_column_id
    WHERE fk.parent_object_id=OBJECT_ID('dataview.dv_well_log_curve')
      AND (cpar.name LIKE '%uom%' OR cpar.name LIKE '%unit%')""").fetchall():
    print(f"  {r.child_col} -> {r.ref_tbl}.{r.ref_col}  ({r.name})")

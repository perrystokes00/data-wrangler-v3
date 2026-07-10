"""scan_uwi_deps.py — what depends on dv_well.uwi (and cat_well.uwi) before we
alter the type. Lists PK/unique/indexes/FKs/computed cols/defaults that reference
the column, so the migration can drop -> alter -> recreate safely. py scan_uwi_deps.py"""
import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

def report(schema, table, col):
    full = f"{schema}.{table}"
    oid = cur.execute("SELECT OBJECT_ID(?)", full).fetchone()[0]
    if not oid:
        print(f"\n=== {full}: NOT FOUND ==="); return
    print(f"\n=== {full}.{col} ===")
    t = cur.execute("""SELECT ty.name, c.max_length, c.is_nullable
        FROM sys.columns c JOIN sys.types ty ON ty.user_type_id=c.user_type_id
        WHERE c.object_id=? AND c.name=?""", oid, col).fetchone()
    print(f"  current type: {t[0]}({t[1]}) {'NULL' if t[2] else 'NOT NULL'}")

    print("  indexes on this column:")
    for r in cur.execute("""
        SELECT i.name, i.type_desc, i.is_primary_key, i.is_unique
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
        JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
        WHERE i.object_id=? AND c.name=?""", oid, col).fetchall():
        tag = "PK" if r[2] else ("UNIQUE" if r[3] else "")
        print(f"    {r[0]}  {r[1]} {tag}")

    print("  FKs referencing this column (child -> here):")
    for r in cur.execute("""
        SELECT fk.name, OBJECT_SCHEMA_NAME(fk.parent_object_id),
               OBJECT_NAME(fk.parent_object_id), pc.name
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id
        JOIN sys.columns rc ON rc.object_id=fkc.referenced_object_id AND rc.column_id=fkc.referenced_column_id
        JOIN sys.columns pc ON pc.object_id=fkc.parent_object_id AND pc.column_id=fkc.parent_column_id
        WHERE fkc.referenced_object_id=? AND rc.name=?""", oid, col).fetchall():
        print(f"    {r[0]}: {r[1]}.{r[2]}.{r[3]}")

    print("  FKs ON this column (here -> parent):")
    for r in cur.execute("""
        SELECT fk.name, OBJECT_SCHEMA_NAME(fk.referenced_object_id),
               OBJECT_NAME(fk.referenced_object_id)
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id
        JOIN sys.columns pc ON pc.object_id=fkc.parent_object_id AND pc.column_id=fkc.parent_column_id
        WHERE fkc.parent_object_id=? AND pc.name=?""", oid, col).fetchall():
        print(f"    {r[0]} -> {r[1]}.{r[2]}")

    d = cur.execute("""SELECT dc.name FROM sys.default_constraints dc
        JOIN sys.columns c ON c.default_object_id=dc.object_id
        WHERE c.object_id=? AND c.name=?""", oid, col).fetchall()
    print("  default constraints:", [r[0] for r in d] or "none")

for sch, tbl, col in (("dataview","dv_well","uwi"),
                      ("file_catalog","cat_well","uwi"),
                      ("dataview","dv_well_log","uwi"),
                      ("dataview","dv_well_log_curve","uwi")):
    report(sch, tbl, col)

"""show_cat_schema.py — dump the cat_* table schemas the BCP capture must match:
columns + types + identity + PK. py show_cat_schema.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()

for t in ("cat_well", "cat_well_log", "cat_well_log_curve"):
    full = f"file_catalog.{t}"
    oid = cur.execute("SELECT OBJECT_ID(?)", full).fetchone()[0]
    if not oid:
        print(f"\n=== {full}: NOT FOUND ==="); continue
    print(f"\n=== {full} ===")
    rows = cur.execute("""
        SELECT c.name, ty.name typ, c.max_length, c.is_nullable, c.is_identity
        FROM sys.columns c JOIN sys.types ty ON ty.user_type_id=c.user_type_id
        WHERE c.object_id=? ORDER BY c.column_id""", oid).fetchall()
    for r in rows:
        ml = "" if r.max_length in (-1, 0) else f"({r.max_length})"
        tag = "  IDENTITY" if r.is_identity else ""
        nul = "" if r.is_nullable else "  NOT NULL"
        print(f"  {r.name:26} {r.typ}{ml}{nul}{tag}")
    pk = cur.execute("""
        SELECT c.name FROM sys.key_constraints k
        JOIN sys.index_columns ic ON ic.object_id=k.parent_object_id AND ic.index_id=k.unique_index_id
        JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
        WHERE k.parent_object_id=? AND k.type='PK' ORDER BY ic.key_ordinal""", oid).fetchall()
    print(f"  PK: {', '.join(r[0] for r in pk) or '(none)'}")

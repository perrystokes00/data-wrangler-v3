"""check_uwi_types.py — why the gold-enrich join scans 3.5M rows: compare the
join-key types. py check_uwi_types.py"""
import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

def coltype(db, sch, tbl, col):
    r = cur.execute(f"""
        SELECT ty.name, c.max_length
        FROM {db}.sys.columns c
        JOIN {db}.sys.types ty ON ty.user_type_id=c.user_type_id
        WHERE c.object_id = OBJECT_ID('{db}.{sch}.{tbl}') AND c.name = ?""", col).fetchone()
    return f"{r[0]}({r[1]})" if r else "MISSING"

print("dv_well.uwi              :", coltype("DataView_Demo", "dataview", "dv_well", "uwi"))
print("gold.uwi14               :", coltype("WELL_REF", "well_ref", "well_master_gold", "uwi14"))
print("FILE_WELL_HEADER.UWI14   :", coltype("DataView_Demo", "file_catalog", "FILE_WELL_HEADER", "UWI14"))

# is gold.uwi14 the PK / indexed?
idx = cur.execute("""
    SELECT i.name, i.type_desc FROM WELL_REF.sys.indexes i
    WHERE i.object_id = OBJECT_ID('WELL_REF.well_ref.well_master_gold')
      AND i.index_id > 0""").fetchall()
print("\ngold indexes:", [(r[0], r[1]) for r in idx] or "NONE")

"""diag_ref_cols.py — get the real column names + values of dv_r_source and dv_r_uom
so we can seed the missing SOURCE and UOM codes. writes to file. py diag_ref_cols.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\ref_cols.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

for tbl in ("dv_r_source","dv_r_uom"):
    cols=[(r[0],r[1]) for r in c.execute("SELECT COLUMN_NAME,DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME=? ORDER BY ORDINAL_POSITION",tbl).fetchall()]
    log(f"\n=== {tbl} columns ===")
    for cn,dt in cols: log(f"   {cn} ({dt})")
    # dump a few rows
    try:
        colnames=[x[0] for x in cols]
        log(f"   sample rows:")
        for r in c.execute(f"SELECT TOP 8 * FROM dataview.{tbl}").fetchall():
            log("     "+str(tuple(r)))
    except Exception as e:
        log("   sample err:",e)

open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

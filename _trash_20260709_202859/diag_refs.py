"""diag_refs.py — exactly why curves are held: are the ref tables seeded, and do
the held rows' codes match? py diag_refs.py"""
import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

def show(t):
    try:
        n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        cols = [r[0] for r in cur.execute(
            "SELECT c.name FROM sys.columns c WHERE c.object_id=OBJECT_ID(?)", t).fetchall()]
        print(f"\n{t}: {n} rows | cols: {cols}")
        if n:
            for r in cur.execute(f"SELECT TOP 8 * FROM {t}").fetchall():
                print("   ", tuple(r))
    except Exception as e:
        print(f"\n{t}: ERROR {str(e)[:80]}")

show("dataview.dv_r_uom")
show("dataview.dv_r_source")

print("\n--- what the held curves actually carry ---")
for col in ("source", "curve_unit", "depth_ouom"):
    try:
        vals = [r[0] for r in cur.execute(
            f"SELECT DISTINCT TOP 12 {col} FROM file_catalog.cat_well_log_curve "
            f"WHERE {col} IS NOT NULL").fetchall()]
        print(f"  cat_well_log_curve.{col}: {vals}")
    except Exception as e:
        print(f"  {col}: {str(e)[:60]}")

"""h3_diag.py — why is the read hanging? checks blocking + times the raw read.
py h3_diag.py"""
import pyodbc, time
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()

print("=== active sessions on DataView_Demo (blocking?) ===")
rows = cur.execute("""
    SELECT r.session_id, r.status, r.blocking_session_id, r.wait_type,
           r.command, SUBSTRING(t.text,1,60) AS sql_txt
    FROM sys.dm_exec_requests r
    OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) t
    WHERE r.database_id = DB_ID('DataView_Demo')""").fetchall()
for r in rows:
    print(f"  sid {r.session_id} status={r.status} blocked_by={r.blocking_session_id} "
          f"wait={r.wait_type} :: {(r.sql_txt or '').strip()}")
if not rows:
    print("  (no active requests — nothing blocking)")

print("\n=== time the exact read run_h3 does ===")
t0 = time.time()
n = cur.execute(
    "SELECT COUNT(*) FROM dataview.dv_well t "
    "WHERE t.surface_latitude IS NOT NULL AND t.surface_longitude IS NOT NULL").fetchone()[0]
print(f"  count read: {n:,} rows in {time.time()-t0:.1f}s")
t0 = time.time()
cur.execute("SELECT TOP 100 t.uwi, t.surface_latitude, t.surface_longitude "
            "FROM dataview.dv_well t "
            "WHERE t.surface_latitude IS NOT NULL AND t.surface_longitude IS NOT NULL").fetchall()
print(f"  top-100 read: {time.time()-t0:.1f}s")

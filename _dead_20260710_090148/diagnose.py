"""diagnose.py — why nothing is moving: blockers, funnel, running processes.
py diagnose.py"""
import subprocess, pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: cur.execute(q).fetchone()[0]

print("=== DB sessions (blocking / open transaction / python) ===")
rows = cur.execute("""
    SELECT s.session_id, s.status, ISNULL(r.blocking_session_id,0),
           s.open_transaction_count, ISNULL(r.wait_type,''), ISNULL(s.program_name,'')
    FROM sys.dm_exec_sessions s
    LEFT JOIN sys.dm_exec_requests r ON r.session_id=s.session_id
    WHERE s.is_user_process=1 AND s.session_id<>@@SPID
      AND (ISNULL(r.blocking_session_id,0)>0 OR s.open_transaction_count>0
           OR s.program_name LIKE '%python%')""").fetchall()
for r in rows:
    print(f"  spid {r[0]:<5} status={r[1]:<10} blocked_by={r[2]:<5} "
          f"opentran={r[3]} wait={r[4]:<18} {r[5][:40]}")
print("  (none)" if not rows else "")

print("=== funnel ===")
print("  catalogued :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG "
                          "WHERE ISNULL(FLAG_DELETE,'N')<>'Y' AND DUPLICATE_GROUP IS NULL"))
print("  pending    :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG "
                          "WHERE (HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED='N') "
                          "AND DUPLICATE_GROUP IS NULL AND ISNULL(FLAG_DELETE,'N')<>'Y'"))
print("  captured   :", f("SELECT COUNT(DISTINCT INVENTORY_ID) FROM file_catalog.cat_well "
                          "WHERE INVENTORY_ID IS NOT NULL"))
print("  promoted   :", f("SELECT COUNT(*) FROM dataview.dv_well"))

print("=== running pipeline process(es) ===")
ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
      "'pipeline_proc_runner|pipeline_run' } | ForEach-Object { $_.ProcessId }")
out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                     capture_output=True, text=True).stdout
print("  running pids:", [x for x in out.split() if x.isdigit()] or "none")

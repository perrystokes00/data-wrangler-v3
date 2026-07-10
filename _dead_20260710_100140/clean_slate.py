"""clean_slate.py — kill ALL running pipeline processes + their open-transaction DB
sessions, then reset stuck files. Use when multiple runs overlapped. py clean_slate.py"""
import subprocess, pyodbc

# 1) kill every python process running the pipeline runner
ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
      "'pipeline_proc_runner|pipeline_run' } | ForEach-Object { Write-Output $_.ProcessId; "
      "Stop-Process -Id $_.ProcessId -Force }")
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, text=True)
print("killed pipeline pids:", [x for x in (r.stdout or "").split() if x.isdigit()] or "none")

# 2) kill leftover python DB sessions with an open transaction
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
for row in cur.execute(
        "SELECT session_id FROM sys.dm_exec_sessions "
        "WHERE is_user_process=1 AND session_id<>@@SPID "
        "AND program_name LIKE '%python%' AND open_transaction_count>0").fetchall():
    try:
        cur.execute(f"KILL {row[0]}"); print("killed db session", row[0])
    except Exception as e:
        print("  session", row[0], ":", str(e)[:80])

# 3) reset stuck files
n = cur.execute("""UPDATE file_catalog.GLOBAL_FILE_CATALOG
    SET HEADER_EXTRACTED='N', CATALOG_READINESS=NULL, ROW_CHANGED_DATE=GETUTCDATE()
    WHERE HEADER_EXTRACTED='Y' AND INVENTORY_ID NOT IN
    (SELECT INVENTORY_ID FROM file_catalog.cat_well WHERE INVENTORY_ID IS NOT NULL)""").rowcount
print(f"reset {n} stuck file(s) to pending")
print("\nclean. run ONE pipeline: multi-core ON, batch mode OFF.")

"""kill_now.py — kill the specific stuck pipeline PID + its open-tran sessions.
py kill_now.py"""
import subprocess, pyodbc, time

# kill the running pipeline pid(s) by name+cmdline, hard
ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
      "'pipeline_proc_runner|pipeline_run' } | ForEach-Object { "
      "Write-Output $_.ProcessId; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
print("killed pids:", [x for x in (r.stdout or "").split() if x.isdigit()] or "none")
time.sleep(1)

cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

# kill ALL python sessions except this one (they're orphaned pipeline connections)
killed = 0
for row in cur.execute(
        "SELECT session_id FROM sys.dm_exec_sessions "
        "WHERE is_user_process=1 AND session_id<>@@SPID "
        "AND program_name LIKE '%python%'").fetchall():
    try:
        cur.execute(f"KILL {row[0]}"); killed += 1
    except Exception as e:
        print("  session", row[0], ":", str(e)[:60])
print(f"killed {killed} python db session(s)")

n = cur.execute("""UPDATE file_catalog.GLOBAL_FILE_CATALOG
    SET HEADER_EXTRACTED='N', CATALOG_READINESS=NULL, ROW_CHANGED_DATE=GETUTCDATE()
    WHERE HEADER_EXTRACTED='Y' AND INVENTORY_ID NOT IN
    (SELECT INVENTORY_ID FROM file_catalog.cat_well WHERE INVENTORY_ID IS NOT NULL)""").rowcount
print(f"reset {n} stuck file(s)")
print("\nnow: DO NOT start a run from the app yet — run diagnose.py first to confirm clean.")

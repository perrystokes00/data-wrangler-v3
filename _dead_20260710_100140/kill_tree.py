"""kill_tree.py — kill the Streamlit app (app_v3.py) and its ENTIRE child-process
tree from the top, so nested children can't respawn. Then clear DB sessions +
reset stuck files. py kill_tree.py"""
import subprocess, time, pyodbc

# 1) find the streamlit app process (the root of the tree)
find = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
        "'streamlit.*run.*app_v3|streamlit\\.exe run' } | ForEach-Object { $_.ProcessId }")
r = subprocess.run(["powershell","-NoProfile","-Command",find], capture_output=True, text=True)
roots = [x for x in (r.stdout or "").split() if x.isdigit()]
print("streamlit app root pid(s):", roots or "none found")

# 2) taskkill /T kills the whole tree (process + all descendants)
for pid in roots:
    k = subprocess.run(["taskkill","/F","/T","/PID",pid], capture_output=True, text=True)
    print(f"  killed tree under {pid}: {(k.stdout or k.stderr).strip()[:80]}")

# 3) sweep any remaining pipeline/python runners not under that tree
sweep = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
         "'pipeline_proc_runner|pipeline_run\\.py' } | ForEach-Object { "
         "Write-Output $_.ProcessId; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
s = subprocess.run(["powershell","-NoProfile","-Command",sweep], capture_output=True, text=True)
print("swept runner pid(s):", [x for x in (s.stdout or "").split() if x.isdigit()] or "none")
time.sleep(1)

# 4) clear orphaned python DB sessions + reset stuck files
cur = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
n = 0
for row in cur.execute("SELECT session_id FROM sys.dm_exec_sessions WHERE is_user_process=1 "
                       "AND session_id<>@@SPID AND program_name LIKE '%python%'").fetchall():
    try: cur.execute(f"KILL {row[0]}"); n += 1
    except Exception: pass
print(f"cleared {n} DB session(s)")
nr = cur.execute("""UPDATE file_catalog.GLOBAL_FILE_CATALOG
    SET HEADER_EXTRACTED='N', CATALOG_READINESS=NULL, ROW_CHANGED_DATE=GETUTCDATE()
    WHERE HEADER_EXTRACTED='Y' AND INVENTORY_ID NOT IN
    (SELECT INVENTORY_ID FROM file_catalog.cat_well WHERE INVENTORY_ID IS NOT NULL)""").rowcount
print(f"reset {nr} stuck file(s)")
print("\nTREE KILLED. verify: py clear_stuck_state.py  (should show pids: none)")

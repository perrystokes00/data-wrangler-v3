"""kill_app.py — find and kill the Streamlit APP (the parent that respawns runners),
plus any pipeline runner children, then clear DB sessions. The app is what keeps
relaunching; kill it and the respawns stop. py kill_app.py"""
import subprocess, time, pyodbc

# 1) show the full tree first (python + streamlit), so we see the app
show = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|streamlit' } "
        "| ForEach-Object { \"{0} | ppid {1} | {2}\" -f $_.ProcessId, $_.ParentProcessId, $_.CommandLine }")
r = subprocess.run(["powershell","-NoProfile","-Command",show], capture_output=True, text=True)
print("=== python/streamlit processes ===")
for ln in (r.stdout or "").splitlines():
    if ln.strip() and "kill_app" not in ln:
        print(" ", ln.strip()[:160])

# 2) kill anything running streamlit OR the pipeline runner OR the app entry script
#    (adjust 'app.py'/'main.py' if your Streamlit entry file has a different name)
kill = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
        "'streamlit run|streamlit\\.web|pipeline_proc_runner|pipeline_run\\.py|app\\.py' } "
        "| ForEach-Object { Write-Output $_.ProcessId; "
        "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
k = subprocess.run(["powershell","-NoProfile","-Command",kill], capture_output=True, text=True)
print("\nkilled:", [x for x in (k.stdout or "").split() if x.isdigit()] or "none")
time.sleep(1)

# 3) clear orphaned python DB sessions
cur = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
n = 0
for row in cur.execute("SELECT session_id FROM sys.dm_exec_sessions WHERE is_user_process=1 "
                       "AND session_id<>@@SPID AND program_name LIKE '%python%'").fetchall():
    try: cur.execute(f"KILL {row[0]}"); n += 1
    except Exception: pass
print(f"cleared {n} orphaned DB session(s)")
print("\nnow run: py check_after_ui.py  — should show pids: none and STAY none")

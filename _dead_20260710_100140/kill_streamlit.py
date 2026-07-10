"""kill_streamlit.py — kill the streamlit SERVER (app_v3.py) itself, hard, by its
own pid and any parent, so it stops relaunching children. Loops until gone.
py kill_streamlit.py"""
import subprocess, time

def find():
    q = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
         "'app_v3|streamlit' -and $_.CommandLine -notmatch 'kill_streamlit' } | "
         "ForEach-Object { $_.ProcessId }")
    r = subprocess.run(["powershell","-NoProfile","-Command",q], capture_output=True, text=True)
    return [x for x in (r.stdout or "").split() if x.isdigit()]

for attempt in range(6):
    pids = find()
    if not pids:
        print("all streamlit/app processes gone."); break
    print(f"attempt {attempt+1}: killing {pids}")
    for pid in pids:
        subprocess.run(["taskkill","/F","/T","/PID",pid], capture_output=True, text=True)
    time.sleep(1.5)
else:
    print("still alive after 6 tries — pids:", find())
    print("If it keeps respawning, the terminal that launched 'streamlit run app_v3.py'")
    print("is auto-restarting it. Close THAT terminal window (Ctrl-C in it, or close it).")

# final DB session sweep
import pyodbc
cur = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
for row in cur.execute("SELECT session_id FROM sys.dm_exec_sessions WHERE is_user_process=1 "
                       "AND session_id<>@@SPID AND program_name LIKE '%python%'").fetchall():
    try: cur.execute(f"KILL {row[0]}")
    except Exception: pass
print("cleared DB sessions. verify: py clear_stuck_state.py")

import subprocess, pyodbc
ps = (r"Get-CimInstance Win32_Process | "
      r"Where-Object { $_.CommandLine -match 'pipeline_proc_runner|pipeline_run' } | "
      r"ForEach-Object { Write-Output $_.ProcessId; Stop-Process -Id $_.ProcessId -Force }")
r = subprocess.run(["powershell","-NoProfile","-Command",ps], capture_output=True, text=True)
print("killed:", [x for x in (r.stdout or "").split() if x.isdigit()] or "none")
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
for row in cur.execute("SELECT session_id FROM sys.dm_exec_sessions WHERE is_user_process=1 "
                       "AND session_id<>@@SPID AND open_transaction_count>0 "
                       "AND program_name LIKE '%python%'").fetchall():
    try: cur.execute(f"KILL {row[0]}"); print("killed db session", row[0])
    except Exception as e: print(row[0], e)
print("done")

"""clear_stuck_state.py — is the '400 extracted not captured' a NEW failure or old
residue? Show state + any running process, then (with --reset) clear the stuck
files so the next run is clean. py clear_stuck_state.py [--reset]"""
import sys, subprocess, pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]

print("=== current state ===")
print("  GLOBAL_FILE_CATALOG      :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG"))
print("  HEADER_EXTRACTED='Y'     :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE HEADER_EXTRACTED='Y'"))
print("  cat_well                 :", f("SELECT COUNT(*) FROM file_catalog.cat_well"))
print("  extracted-not-captured   :", f("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
       WHERE HEADER_EXTRACTED='Y' AND NOT EXISTS
       (SELECT 1 FROM file_catalog.cat_well w WHERE w.INVENTORY_ID=g.INVENTORY_ID)"""))
print("  dv_well                  :", f("SELECT COUNT(*) FROM dataview.dv_well"))

ps=("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
    "'pipeline_proc_runner|pipeline_run|streamlit' } | ForEach-Object { $_.ProcessId }")
out=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True).stdout
pids=[x for x in out.split() if x.isdigit()]
print("\n  running pipeline/app pids:", pids or "none")
print("  => this is",
      "a LIVE run still in progress" if pids else "OLD RESIDUE (no run active)")

if "--reset" in sys.argv:
    n = c.execute("""UPDATE file_catalog.GLOBAL_FILE_CATALOG
        SET HEADER_EXTRACTED='N', CATALOG_READINESS=NULL, ROW_CHANGED_DATE=GETUTCDATE()
        WHERE HEADER_EXTRACTED='Y' AND INVENTORY_ID NOT IN
        (SELECT INVENTORY_ID FROM file_catalog.cat_well WHERE INVENTORY_ID IS NOT NULL)""").rowcount
    print(f"\n  reset {n} stuck file(s) to pending")
else:
    print("\n  add --reset to clear the stuck files")

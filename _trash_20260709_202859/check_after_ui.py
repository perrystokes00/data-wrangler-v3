"""check_after_ui.py — real DB state after the UI run + WHY files are 'extracted
not captured'. py check_after_ui.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]

print("=== data tables ===")
for t in ("file_catalog.GLOBAL_FILE_CATALOG","file_catalog.cat_well",
          "file_catalog.cat_well_log_curve","file_catalog.FILE_WELL_HEADER",
          "dataview.dv_well","dataview.dv_well_log_curve"):
    print(f"  {t:36} {f('SELECT COUNT(*) FROM '+t)}")

print("\n=== catalog state breakdown ===")
print("  HEADER_EXTRACTED='Y'      :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE HEADER_EXTRACTED='Y'"))
print("  has MATCHED_UWI           :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE MATCHED_UWI IS NOT NULL"))
print("  .las files                :", f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE LOWER(FILE_EXT)='.las'"))
print("  extracted-not-captured    :", f("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
       WHERE HEADER_EXTRACTED='Y' AND NOT EXISTS
       (SELECT 1 FROM file_catalog.cat_well w WHERE w.INVENTORY_ID=g.INVENTORY_ID)"""))

print("\n=== is a pipeline process still running? (UI may auto-respawn) ===")
import subprocess
ps=("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "
    "'pipeline_proc_runner|pipeline_run|streamlit' } | ForEach-Object { $_.ProcessId }")
out=subprocess.run(["powershell","-NoProfile","-Command",ps],capture_output=True,text=True).stdout
print("  pids:", [x for x in out.split() if x.isdigit()] or "none")

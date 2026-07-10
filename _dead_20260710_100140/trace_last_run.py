"""trace_last_run.py — read the MOST RECENT pipeline log and show exactly what the
capture stage did, plus the live DB state. No theories — just what happened.
py trace_last_run.py"""
import os, glob, pyodbc

# 1) find the newest pipeline log
RPT = r"C:\Bulk\reports"
logs = sorted(glob.glob(os.path.join(RPT, "pipeline_*.log")) +
              glob.glob(os.path.join(RPT, "_run_console.log")) +
              glob.glob(os.path.join(RPT, "run_*.md")),
              key=os.path.getmtime, reverse=True)
if logs:
    newest = logs[0]
    print(f"=== newest log: {os.path.basename(newest)} ({os.path.getmtime(newest)}) ===")
    txt = open(newest, encoding="utf-8", errors="replace").read()
    # show only the capture-relevant lines
    for ln in txt.splitlines():
        if any(k in ln.lower() for k in ("capture", "cat_well", "document(s)", "bcp",
                                          "select", "skip", "las fast", "error", "held")):
            print("   ", ln[:120])
else:
    print("no pipeline logs found in", RPT)

# 2) live DB state right now
print("\n=== DB state right now ===")
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]
T = "file_catalog.GLOBAL_FILE_CATALOG"
print("  .las total                   :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las'"))
print("  .las CAPTURED_HASH set       :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las' AND CAPTURED_HASH IS NOT NULL"))
print("  .las DUPLICATE_GROUP set     :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las' AND DUPLICATE_GROUP IS NOT NULL"))
print("  cat_well rows                :", f("SELECT COUNT(*) FROM file_catalog.cat_well"))
print("  what capture WOULD select now:", f(f"""SELECT COUNT(*) FROM {T} g WHERE LOWER(g.FILE_EXT)='.las'
    AND ISNULL(g.FLAG_DELETE,'N')<>'Y'
    AND ISNULL(g.CATALOG_READINESS,'') NOT IN ('SKIPPED','CATALOGED')
    AND g.DUPLICATE_GROUP IS NULL
    AND (g.CAPTURED_HASH IS NULL OR g.CAPTURED_HASH <> g.FILE_HASH)"""))

# 3) which pipeline_run.py is the app actually importing?
import importlib.util
for cand in ("pipeline_run.py", "modules/pipeline_run.py"):
    if os.path.exists(cand):
        s = open(cand, encoding="utf-8", errors="ignore").read()
        print(f"\n  {cand}: cap_invs-fix={'_sel_invs' in s and '#cap_real' in s} · mtime={os.path.getmtime(cand)}")

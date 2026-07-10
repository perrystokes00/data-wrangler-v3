"""read_run_full.py — dump the FULL capture + extract stage from the newest run log,
verbatim, so we see exactly what happened this run. py read_run_full.py"""
import os, glob
RPT = r"C:\Bulk\reports"
logs = sorted(glob.glob(os.path.join(RPT, "pipeline_*.log")),
              key=os.path.getmtime, reverse=True)
if not logs:
    print("no pipeline_*.log in", RPT); raise SystemExit
newest = logs[0]
print(f"=== {os.path.basename(newest)} ===\n")
txt = open(newest, encoding="utf-8", errors="replace").read()
lines = txt.splitlines()
# print extract + capture stages in full (from [extract] to end of [capture])
grab = False
for ln in lines:
    L = ln.strip()
    if L.startswith("[extract]") or L.startswith("[scan]"):
        grab = True
    if grab:
        print(ln[:140])
    if L.startswith("[promote]") and "starting" in L:
        break

"""which_log.py — list all recent pipeline logs with timestamps + their capture
result, so we can tell WHICH run each was (FCP vs headless) and whether any FCP run
actually captured. py which_log.py"""
import os, glob, datetime
RPT = r"C:\Bulk\reports"
logs = glob.glob(os.path.join(RPT, "pipeline_*.log")) + \
       glob.glob(os.path.join(RPT, "_run_console.log")) + \
       glob.glob(os.path.join(RPT, "run_*.md"))
logs = sorted(logs, key=os.path.getmtime, reverse=True)[:12]

for p in logs:
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%H:%M:%S")
    txt = open(p, encoding="utf-8", errors="replace").read()
    # extract the capture verdict + the crawl root (tells us which folder = which run)
    cap = "?"
    root = "?"
    for ln in txt.splitlines():
        if "captured" in ln and "row(s) from" in ln and "file(s)" in ln:
            cap = ln.strip()[:70]
        if "walking" in ln:
            root = ln.split("walking",1)[1].strip()[:60]
        if "no new or changed" in ln:
            cap = "SKIPPED (no new files)"
    print(f"{mt}  {os.path.basename(p):32}")
    print(f"         root: {root}")
    print(f"         cap : {cap}")
    print()

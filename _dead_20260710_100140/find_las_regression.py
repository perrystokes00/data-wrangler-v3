"""find_las_regression.py — find what changed in the LAS capture path. Lists pipeline_run.py
+ its backups with timestamps, and greps each for the '.las' skip and the capture gate,
so we can see exactly which version broke LAS. Read-only. py find_las_regression.py"""
import os, glob, datetime
OUT = r"C:\Bulk\reports\las_regression.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

here = os.getcwd()
log("=== pipeline_run.py and all its backups (newest first) ===")
cands = []
for pat in ("pipeline_run.py", "pipeline_run.py.*", "pipeline_run*.bak", "pipeline_run*.py"):
    cands += glob.glob(os.path.join(here, pat))
cands = sorted(set(cands), key=lambda p: os.path.getmtime(p), reverse=True)
for p in cands:
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
    log(f"   {mt}  {os.path.basename(p)}  ({os.path.getsize(p)} bytes)")

log("\n=== in each, the LAS-relevant lines (skip in extract + capture gate) ===")
for p in cands:
    log(f"\n--- {os.path.basename(p)} ---")
    try:
        s = open(p, encoding="utf-8", errors="replace").read()
        lines = s.splitlines()
        for i, ln in enumerate(lines):
            low = ln.lower()
            if ("<> '.las'" in low or "!= '.las'" in low or "skip .las" in low
                    or "_e in sp_exts" in low or "fields.get(\"uwi\")" in ln
                    or "do_cap and" in low or "sp_exts or" in low):
                log(f"   {i+1}: {ln.strip()[:110]}")
    except Exception as e:
        log(f"   read err: {e}")

# also check which capture path the app actually runs (parallel vs single-pass vs sequential)
log("\n=== which capture stages exist in current pipeline_run.py ===")
try:
    s = open(os.path.join(here,"pipeline_run.py"), encoding="utf-8").read()
    for fn in ("_stage_capture", "_stage_extract_capture", "_capture_proc_one",
               "_extract_capture_proc", "def run_pipeline"):
        log(f"   {fn}: {'present' if 'def '+fn.split()[-1] in s or fn in s else 'ABSENT'}")
    # how does run_pipeline choose the capture stage?
    import re
    for m in re.finditer(r".*(single_pass|_stage_extract_capture|_stage_capture|parse_mode).*", s):
        t = m.group(0).strip()
        if "def " not in t and len(t) < 120:
            log(f"     · {t}")
except Exception as e:
    log(f"   err: {e}")

open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

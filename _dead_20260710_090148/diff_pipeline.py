"""diff_pipeline.py — show exactly what changed between pipeline_run.py and its most
recent .bak (the last patch, which is the regression suspect). Focuses on LAS/capture
regions. Read-only. py diff_pipeline.py"""
import os, difflib
OUT = r"C:\Bulk\reports\pipeline_diff.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

here=os.getcwd()
cur = os.path.join(here,"pipeline_run.py")
bak = os.path.join(here,"pipeline_run.py.bak")
if not os.path.exists(bak):
    log("no pipeline_run.py.bak"); open(OUT,"w").write("\n".join(L)); raise SystemExit

a = open(bak, encoding="utf-8", errors="replace").read().splitlines()
b = open(cur, encoding="utf-8", errors="replace").read().splitlines()
log(f"=== diff: pipeline_run.py.bak ({len(a)} lines) -> pipeline_run.py ({len(b)} lines) ===")
log("(- = removed/old, + = added/new)\n")

diff = list(difflib.unified_diff(a, b, lineterm="", n=2))
# print the whole unified diff (it's the last patch only, should be compact)
for d in diff:
    if d.startswith("+++") or d.startswith("---") or d.startswith("@@"):
        log(d)
    elif d.startswith("+"):
        log("  NEW " + d[1:].strip()[:120])
    elif d.startswith("-"):
        log("  OLD " + d[1:].strip()[:120])

# also flag any change touching las / capture / process_file / gate
log("\n=== changed lines mentioning las/capture/process_file/uwi/gate ===")
for d in diff:
    if d[:1] in "+-" and not d.startswith(("+++","---")):
        low = d.lower()
        if any(k in low for k in ("las","capture","process_file","uwi","sp_exts","do_cap","_do_","header")):
            log(f"   {d[:1]} {d[1:].strip()[:120]}")

open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

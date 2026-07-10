"""diff_bcp_full.py — full hunk-by-hunk diff of root vs modules\ bcp_capture.py, so we can
decide which version's logic wins for each difference. Writes a clean diff to a file you
can paste. py diff_bcp_full.py"""
import os, difflib
ROOT = os.getcwd()
OUT = r"C:\Bulk\reports\bcp_diff.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
rp = os.path.join(ROOT, "bcp_capture.py")
mp = os.path.join(ROOT, "modules", "bcp_capture.py")
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

if not (os.path.exists(rp) and os.path.exists(mp)):
    log(f"missing: root={os.path.exists(rp)} modules={os.path.exists(mp)}")
    open(OUT,"w").write("\n".join(L)); raise SystemExit

a = open(rp,encoding="utf-8",errors="replace").read().splitlines()
b = open(mp,encoding="utf-8",errors="replace").read().splitlines()
log(f"root: {len(a)} lines   modules: {len(b)} lines\n")

# unified diff with generous context so we understand each hunk
diff = list(difflib.unified_diff(a, b, "ROOT", "MODULES", lineterm="", n=4))
log(f"=== full unified diff ({len([d for d in diff if d.startswith('@@')])} hunks) ===")
for line in diff:
    log(line)

# also: which key functions/markers exist in each (so we spot the nested-pool fix etc.)
log("\n=== key markers per copy ===")
markers = ["ProcessPoolExecutor","ThreadPoolExecutor","nested","_in_child","daemon",
           "def run_bcp_capture","def capture","DEV_CONN","DataView_Demo","int(INVENTORY_ID)",
           "SHA1","convex hull","survey outline","_done","_d "]
for mk in markers:
    ra = sum(1 for ln in a if mk in ln)
    rb = sum(1 for ln in b if mk in ln)
    if ra or rb:
        flag = "  <-- DIFFERS" if ra != rb else ""
        log(f"  '{mk}': root={ra} modules={rb}{flag}")

open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)[:3000]); print("\n... (full diff written to",OUT,")")

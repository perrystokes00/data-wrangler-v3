r"""
check_module_dupes.py — for files that exist in BOTH repo-root and modules\, determine
which copy your app ACTUALLY imports, and whether the two copies differ. This matters:
if you patch one but the app loads the other, the fix silently does nothing.

Read-only. py check_module_dupes.py
"""
import os, sys, hashlib, ast, re
ROOT = os.getcwd()
OUT = os.path.join(ROOT, "module_dupes.txt")
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

def sha(p):
    try: return hashlib.sha1(open(p,"rb").read()).hexdigest()[:12]
    except Exception: return "??"

# files present in both root and modules\
dupes = []
for fn in os.listdir(ROOT):
    if fn.endswith(".py"):
        m = os.path.join(ROOT, "modules", fn)
        if os.path.exists(m):
            dupes.append(fn)

log(f"files in BOTH root and modules\\ : {len(dupes)}\n")

# how does the app import them? scan for 'import X' vs 'from modules.X' vs 'import modules.X'
appfiles = []
for dp,dns,fns in os.walk(ROOT):
    if any(s in dp for s in (".git","venv","__pycache__","download","_archive","backup","_scratch",".vs")): continue
    for fn in fns:
        if fn.endswith(".py"): appfiles.append(os.path.join(dp,fn))
text = {}
for p in appfiles:
    try: text[p]=open(p,encoding="utf-8",errors="replace").read()
    except Exception: text[p]=""

for fn in sorted(dupes):
    stem = fn[:-3]
    root_p = os.path.join(ROOT, fn)
    mod_p  = os.path.join(ROOT, "modules", fn)
    same = sha(root_p) == sha(mod_p)
    # count import styles across the app
    n_bare = n_mod = 0
    for p,txt in text.items():
        if re.search(rf'(?<!\.)\bimport\s+{stem}\b', txt) or re.search(rf'\bfrom\s+{stem}\s+import', txt):
            n_bare += 1
        if re.search(rf'\bfrom\s+modules\.{stem}\s+import', txt) or re.search(rf'\bimport\s+modules\.{stem}\b', txt):
            n_mod += 1
    log(f"  {fn}")
    log(f"     identical: {same}   root sha={sha(root_p)}  modules sha={sha(mod_p)}")
    log(f"     imported as bare '{stem}': {n_bare} file(s)   as 'modules.{stem}': {n_mod} file(s)")
    if not same:
        log(f"     ^^ DIFFERENT CONTENT — patching the wrong one silently fails. Reconcile!")
    log("")

log("=== how to read ===")
log("  identical=True: harmless duplication; keep the one your imports use, delete other.")
log("  identical=False: the copies have DIVERGED. Whichever import style dominates is the")
log("     live one — the other is stale. Today's patches must target the LIVE copy.")
log("  If both import styles are used (bare AND modules.), you have a split — unify them.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

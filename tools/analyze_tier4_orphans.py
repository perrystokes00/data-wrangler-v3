r"""
analyze_tier4_orphans.py — fresh orphan analysis for Tier 4. An orphan = not imported by
anything reachable from app_v3.py AND its name never appears as a string. But many orphans
are scripts you RUN BY HAND (not dead). This sorts them:

  DEAD-ish   : not imported, no string ref, name doesn't look like a runnable tool
  RUNNABLE   : has `if __name__ == "__main__"` or argparse -> you probably run it directly
  Either way Tier 4 MOVES to _dead\ (not delete), so runnables are recoverable.

Read-only analysis. Writes a categorized list. py analyze_tier4_orphans.py
"""
import os, ast, re
from collections import deque
ROOT=os.getcwd()
OUT=r"C:\Bulk\reports\tier4_orphans.txt"
os.makedirs(os.path.dirname(OUT),exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

SKIP=("venv",".git","__pycache__","download","_trash","_archive",".vs","_dead","modules\\__pycache__")
allpy=[]
for dp,dns,fns in os.walk(ROOT):
    if any(s in dp for s in SKIP):
        dns[:]=[d for d in dns if d not in ("venv",".git","__pycache__","download",".vs") and not d.startswith("_trash") and not d.startswith("_dead") and not d.startswith("_archive")]
        continue
    for fn in fns:
        if fn.endswith(".py"): allpy.append(os.path.join(dp,fn))

# build import graph
name2file={}
for p in allpy:
    stem=os.path.splitext(os.path.basename(p))[0]
    name2file.setdefault(stem,p)
    rel=os.path.relpath(p,ROOT).replace("\\","/")
    name2file.setdefault(".".join(os.path.splitext(rel)[0].split("/")[-2:]),p)

imports_of={}
text={}
for p in allpy:
    try: src=open(p,encoding="utf-8",errors="replace").read()
    except: src=""
    text[p]=src
    deps=set()
    try:
        for node in ast.walk(ast.parse(src)):
            if isinstance(node,ast.Import):
                for a in node.names: deps.add(a.name.split(".")[-1])
            elif isinstance(node,ast.ImportFrom):
                if node.module: deps.add(node.module.split(".")[-1])
    except: pass
    imports_of[p]={name2file[d] for d in deps if d in name2file}

# reachable from app_v3 + page_* (real entries)
entries=[p for p in allpy if os.path.basename(p)=="app_v3.py" and os.sep not in os.path.relpath(p,ROOT)]
entries+=[p for p in allpy if os.path.basename(p).startswith("page_") and "\\" not in os.path.relpath(p,ROOT).replace("/","\\")[:-len(os.path.basename(p))]]
reach=set(); q=deque(entries)
while q:
    f=q.popleft()
    if f in reach: continue
    reach.add(f)
    for d in imports_of.get(f,()): q.append(d)

big=" ".join(text.values())
def strref(stem, self_p):
    pat=re.compile(rf'["\'.]{re.escape(stem)}["\'.]')
    for p,t in text.items():
        if p!=self_p and pat.search(t): return True
    return False

dead=[]; runnable=[]
for p in allpy:
    if p in reach: continue
    stem=os.path.splitext(os.path.basename(p))[0]
    if strref(stem,p): continue  # referenced by name somewhere -> skip (dynamic)
    src=text[p]
    is_runnable = '__main__' in src or 'argparse' in src or 'sys.argv' in src
    (runnable if is_runnable else dead).append(os.path.relpath(p,ROOT))

log(f"orphans found: {len(dead)+len(runnable)}  (dead-ish {len(dead)}, runnable-scripts {len(runnable)})\n")
log("=== RUNNABLE scripts (you likely run these by hand — move to _dead\\ but easy to restore) ===")
for p in sorted(runnable): log(f"  {p}")
log("\n=== DEAD-ish (no imports, no string ref, not obviously runnable) ===")
for p in sorted(dead): log(f"  {p}")
log("\n=== NOTE ===")
log("  Tier 4 MOVES all of these to _dead\\ (not delete). Runnables are recoverable if")
log("  you find you need one. After moving: run the app + a pipeline; if all good, the")
log("  _dead\\ folder can be deleted (or kept zipped as an archive).")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)[:2000]); print("\n... full list in",OUT," (",len(dead)+len(runnable),"files )")

r"""
cleanup_tier4_orphans.py — Tier 4: quarantine orphan files (not imported anywhere, name
never referenced) by MOVING them to _dead\. Self-contained: does the analysis internally
(fresh, not a stale list), so no upload round-trip needed.

Conservative by default: moves only DEAD-ish orphans (no __main__/argparse/sys.argv), and
LEAVES runnable scripts in place (you may run those by hand). Use --include-runnable to
also move the runnable scripts.

PREVIEW by default. --apply moves to _dead_<ts>\. Nothing is deleted; fully recoverable.
  py cleanup_tier4_orphans.py                      # preview (dead-ish only)
  py cleanup_tier4_orphans.py --apply              # move dead-ish to _dead_<ts>
  py cleanup_tier4_orphans.py --include-runnable --apply   # also move runnable scripts
"""
import os, ast, re, sys, shutil, time
from collections import deque
ROOT=os.getcwd()
APPLY="--apply" in sys.argv
INCL_RUN="--include-runnable" in sys.argv

SKIPTOP={"venv",".venv",".git","__pycache__","download",".vs"}
def skipdir(dp):
    parts=os.path.relpath(dp,ROOT).split(os.sep)
    return (parts and (parts[0] in SKIPTOP or parts[0].startswith("_trash")
            or parts[0].startswith("_dead") or parts[0].startswith("_archive")))

allpy=[]
for dp,dns,fns in os.walk(ROOT):
    if skipdir(dp):
        dns[:]=[]; continue
    dns[:]=[d for d in dns if d not in SKIPTOP and not d.startswith(("_trash","_dead","_archive"))]
    for fn in fns:
        if fn.endswith(".py"): allpy.append(os.path.join(dp,fn))

name2file={}
for p in allpy:
    stem=os.path.splitext(os.path.basename(p))[0]
    name2file.setdefault(stem,p)

text={}; imports_of={}
for p in allpy:
    try: src=open(p,encoding="utf-8",errors="replace").read()
    except: src=""
    text[p]=src
    deps=set()
    try:
        for n in ast.walk(ast.parse(src)):
            if isinstance(n,ast.Import):
                for a in n.names: deps.add(a.name.split(".")[-1])
            elif isinstance(n,ast.ImportFrom):
                if n.module: deps.add(n.module.split(".")[-1])
    except: pass
    imports_of[p]={name2file[d] for d in deps if d in name2file}

# entries: root app_v3.py + all page_*.py (root-level)
entries=[]
for p in allpy:
    rel=os.path.relpath(p,ROOT); b=os.path.basename(p)
    if os.sep not in rel and (b=="app_v3.py" or b.startswith("page_")):
        entries.append(p)
reach=set(); q=deque(entries)
while q:
    f=q.popleft()
    if f in reach: continue
    reach.add(f)
    for d in imports_of.get(f,()): q.append(d)

allsrc=" ".join(text.values())
def strref(stem,self_p):
    pat=re.compile(rf'["\'.]{re.escape(stem)}["\'.]')
    for p,t in text.items():
        if p!=self_p and pat.search(t): return True
    return False

dead=[]; runnable=[]
PROTECT={"app_v3.py","vault_copy.py"}
for p in allpy:
    b=os.path.basename(p)
    if b in PROTECT: continue
    if p in reach: continue
    stem=os.path.splitext(b)[0]
    if strref(stem,p): continue
    src=text[p]
    (runnable if ("__main__" in src or "argparse" in src or "sys.argv" in src) else dead).append(p)

move=dead + (runnable if INCL_RUN else [])
print(f"{'APPLY' if APPLY else 'PREVIEW'} — Tier 4 orphan quarantine")
print(f"  dead-ish orphans: {len(dead)}")
print(f"  runnable scripts: {len(runnable)}  ({'INCLUDED' if INCL_RUN else 'left in place'})")
print(f"  -> will move: {len(move)} file(s)\n")

# show a sample so you can eyeball
print("first 40 to move:")
for p in sorted(move)[:40]:
    print(f"   {os.path.relpath(p,ROOT)}")
if len(move)>40: print(f"   ... and {len(move)-40} more")

if not INCL_RUN and runnable:
    print(f"\nrunnable scripts LEFT IN PLACE (re-run with --include-runnable to move them):")
    for p in sorted(runnable)[:15]:
        print(f"   {os.path.relpath(p,ROOT)}")
    if len(runnable)>15: print(f"   ... and {len(runnable)-15} more")

if not APPLY:
    print("\n(preview) re-run with --apply to move to _dead_<ts>\\")
    sys.exit()

dead_dir=os.path.join(ROOT,"_dead_"+time.strftime("%Y%m%d_%H%M%S"))
os.makedirs(dead_dir,exist_ok=True)
moved=0
for p in move:
    try:
        dest=os.path.join(dead_dir, os.path.relpath(p,ROOT).replace(os.sep,"__"))
        shutil.move(p,dest); moved+=1
    except Exception as e:
        print(f"  skip {os.path.relpath(p,ROOT)}: {e}")
print(f"\nmoved {moved} file(s) to {dead_dir}")
print("RESTART Streamlit, click every page, run a full pipeline.")
print("If all good, delete (or zip) the _dead_ folder. If a page breaks, the file it")
print("needed is in there — move it back.")

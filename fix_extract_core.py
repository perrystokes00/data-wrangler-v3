r"""
fix_extract_core.py — relocate shared modules that were mis-sorted into tools/ but are
imported by the app via bare `import X` / `from X import ...`, then rewrite those imports
to the package path (works in ProcessPoolExecutor workers too).

  py fix_extract_core.py            # DRY RUN
  py fix_extract_core.py --apply

Also REPORTS any other flat (non-package) imports inside dataview/ that resolve to a
tools/ or root module — i.e. the next thing that would throw "No module named X".
"""
import os, re, sys, ast, subprocess

APPLY = "--apply" in sys.argv
ROOT  = os.getcwd()
def git(*a): return subprocess.run(["git", *a], capture_output=True, text=True)

# shared module short-name -> correct package home (extend if the report below finds more)
MOVE_TO = {
    "extract_core":         "dataview/file_catalog/extract_core.py",
    "extract_by_list":      "dataview/file_catalog/extract_by_list.py",
    "extract_matched_wells":"dataview/file_catalog/extract_matched_wells.py",
    "page_run":             "dataview/file_catalog/page_run.py",
    "clear_catalog":        "dataview/file_catalog/clear_catalog.py",
    "prep_rrc_texas":       "dataview/import_data/prep_rrc_texas.py",
    "dv_table_loader":      "dataview/mapping/dv_table_loader.py",
}
def dotted(dst): return dst[:-3].replace("/", ".")   # dataview/file_catalog/x.py -> dataview.file_catalog.x

SKIP = {"venv",".venv",".git","__pycache__","_refactor_quarantine","schema_registry"}
def skip(dp):
    p = os.path.relpath(dp, ROOT).split(os.sep)
    return bool(p) and (p[0] in SKIP or p[0].startswith(("_dead","_trash","_archive")))

def walk_py():
    for dp,dns,fns in os.walk(ROOT):
        if skip(dp): dns[:]=[]; continue
        dns[:]=[d for d in dns if not skip(os.path.join(dp,d))]
        for fn in fns:
            if fn.endswith(".py"): yield os.path.join(dp, fn)

def find(base):
    for p in walk_py():
        if os.path.basename(p) == base: return os.path.relpath(p, ROOT)
    return None

# only move the ones actually present + actually imported somewhere in dataview/
REMAP = {}          # name -> dotted target
moves = {}          # current_relpath -> target_relpath
for name, dst in MOVE_TO.items():
    cur = find(name + ".py")
    if cur and cur.replace(os.sep,"/") != dst:
        moves[cur] = dst
        REMAP[name] = dotted(dst)
    elif cur:                              # already at target
        REMAP[name] = dotted(dst)

# setup_database was relocated to dataview/core/ by the earlier fix; here we only
# rewrite any surviving FLAT `import setup_database` / `from setup_database import`.
if os.path.exists(os.path.join(ROOT, "dataview", "core", "setup_database.py")):
    REMAP["setup_database"] = "dataview.core.setup_database"

def rewrite(src):
    out, hits = src, []
    for name, tgt in REMAP.items():
        pkg = tgt.rsplit(".",1)[0]
        p1 = rf"(?m)^(\s*)import\s+{re.escape(name)}\b(?!\.)"
        o2 = re.sub(p1, rf"\1from {pkg} import {name}", out)
        if o2!=out: hits.append(f"import {name} -> from {pkg} import {name}"); out=o2
        p2 = rf"(?m)^(\s*)from\s+{re.escape(name)}\s+import"
        o2 = re.sub(p2, rf"\1from {tgt} import", out)
        if o2!=out: hits.append(f"from {name} import ... -> from {tgt} import ..."); out=o2
        for q in ('"',"'"):
            s=f'import_module({q}{name}{q})'; t=f'import_module({q}{tgt}{q})'
            if s in out: out=out.replace(s,t); hits.append(f"import_module {name} -> {tgt}")
    return out, hits

print(f"{'APPLY' if APPLY else 'DRY RUN'} — relocate + fix flat imports\n")
print("STEP 1 — move shared modules into the package:")
for cur,dst in moves.items(): print(f"   git mv {cur}  ->  {dst}")
if not moves: print("   (nothing to move — already in place)")
print()

print("STEP 2 — rewrite bare imports:")
targets=[]
for p in walk_py():
    try: src=open(p,encoding="utf-8",errors="replace").read()
    except OSError: continue
    _,hits=rewrite(src)
    if hits: targets.append((os.path.relpath(p,ROOT),hits))
for rel,hits in sorted(targets):
    print(f"   {rel}")
    for h in sorted(set(hits)): print(f"        {h}")
print(f"   {len(targets)} files to rewrite.\n")

# STEP 3 — report OTHER flat stranded imports inside dataview/ (next breakages)
print("STEP 3 — other flat imports in dataview/ that resolve to tools/ or root (potential next errors):")
import sys as _sys
stdlib = set(getattr(_sys,"stdlib_module_names",())) | {
    "pandas","numpy","streamlit","folium","geopandas","shapely","pyproj","lasio","sqlalchemy",
    "pyodbc","snowflake","h3","requests","dateutil","PIL","matplotlib","plotly","openpyxl","docx"}
pkg_tops = {"dataview","tools","modules"}
imp_re = re.compile(r"(?m)^\s*(?:import\s+([a-z_][\w]*)|from\s+([a-z_][\w]*)\s+import)")
# index of where flat modules live
flat_home = {}
for p in walk_py():
    rel = os.path.relpath(p, ROOT); top = rel.split(os.sep)[0]
    if "/" not in rel.replace(os.sep,"/") or top in ("tools",):
        flat_home[os.path.basename(p)[:-3]] = rel
seen=set()
for p in walk_py():
    rel=os.path.relpath(p,ROOT)
    if rel.split(os.sep)[0]!="dataview": continue
    try: src=open(p,encoding="utf-8",errors="replace").read()
    except OSError: continue
    for m in imp_re.finditer(src):
        name=m.group(1) or m.group(2)
        if not name or name in stdlib or name in pkg_tops or name in REMAP: continue
        if name in flat_home and name not in seen:
            seen.add(name)
            print(f"   {name:24s} lives at {flat_home[name]}  (imported flat inside dataview/)")
if not seen: print("   (none — good)")

if not APPLY:
    print("\n(DRY RUN) nothing changed. Review, then --apply."); sys.exit()

print("\n--- APPLYING ---")
for cur,dst in moves.items():
    os.makedirs(os.path.join(ROOT,os.path.dirname(dst)),exist_ok=True)
    r=git("mv",cur,dst)
    print(("  moved  " if r.returncode==0 else "  MV FAIL ")+f"{cur} -> {dst}"+("" if r.returncode==0 else "  "+r.stderr.strip()))
changed=0
for p in walk_py():
    src=open(p,encoding="utf-8",errors="replace").read()
    new,hits=rewrite(src)
    if new!=src:
        try: ast.parse(new)
        except SyntaxError as e: print(f"  WARN skip {os.path.relpath(p,ROOT)}: {e}"); continue
        open(p,"w",encoding="utf-8").write(new); changed+=1
print(f"\nrewrote {changed} files. Restart Streamlit and retry the File Catalog.")

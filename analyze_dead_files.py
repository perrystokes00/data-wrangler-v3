r"""
analyze_dead_files.py — find likely-dead / orphaned / duplicate-version files in the repo
by building the import + reference graph from the app entry point(s).

METHOD (static, read-only — never deletes):
  1. Parse every .py file's imports (ast) to build a module dependency graph.
  2. BFS from entry points (app_v3.py + any streamlit pages) to find REACHABLE modules.
  3. Also scan ALL files for STRING references to module/file names (catches importlib,
     st.Page("x.py"), __import__, exec, config-driven loads that ast import-parsing misses).
  4. Classify each .py:  ACTIVE (reachable) / STRING-REFED (named somewhere) /
     ORPHAN (no import, no string ref) / VERSION-DUP (looks like an old copy).
  5. Flag likely old versions by name (_v1/_v2/_old/_bak/_copy/ (1)/ - Copy).

OUTPUT: a ranked report. Review ORPHAN + VERSION-DUP by hand before deleting anything.

  py analyze_dead_files.py                      # analyze cwd
  py analyze_dead_files.py --root "C:\path"     # analyze a specific root
  py analyze_dead_files.py --entry app_v3.py    # set entry point(s), comma-sep
"""
import os, sys, ast, re, fnmatch
from collections import defaultdict, deque

def arg(k, d=None):
    return sys.argv[sys.argv.index(k)+1] if k in sys.argv else d

ROOT   = arg("--root", os.getcwd())
ENTRIES = arg("--entry", "app_v3.py").split(",")
OUT = os.path.join(ROOT, "dead_file_report.txt")

SKIP_DIRS = {".git","venv",".venv","__pycache__","node_modules",".idea",".vscode",
             "_trash","dist","build",".pytest_cache"}

# ---- collect all .py files ----
pyfiles = {}   # module-ish path -> abs path
allpy = []
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith("_trash")]
    for fn in fns:
        if fn.endswith(".py"):
            full = os.path.join(dp, fn)
            allpy.append(full)

def mod_names_for(path):
    """Possible import names for a file: bare stem, and modules.stem, pkg.stem."""
    rel = os.path.relpath(path, ROOT).replace("\\","/")
    stem = os.path.splitext(os.path.basename(path))[0]
    names = {stem}
    parts = os.path.splitext(rel)[0].split("/")
    names.add(".".join(parts))
    if len(parts) > 1:
        names.add(".".join(parts[-2:]))
    return names, stem

# map every importable name -> file
name_to_file = {}
for p in allpy:
    names, stem = mod_names_for(p)
    for n in names:
        name_to_file.setdefault(n, p)

# ---- parse imports per file ----
imports_of = defaultdict(set)   # file -> set(files it imports, resolved)
parse_err = {}
for p in allpy:
    try:
        tree = ast.parse(open(p, encoding="utf-8", errors="replace").read())
    except Exception as e:
        parse_err[p] = str(e)[:80]; continue
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names: mods.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module: mods.add(node.module)
            # from . import X  -> also consider X
            for a in node.names:
                if node.module: mods.add(node.module + "." + a.name)
                else: mods.add(a.name)
    for m in mods:
        # resolve to a local file if possible (try full, then last segment)
        for cand in (m, m.split(".")[-1], ".".join(m.split(".")[-2:])):
            if cand in name_to_file:
                imports_of[p].add(name_to_file[cand]); break

# ---- BFS reachable from entries ----
entry_files = []
for e in ENTRIES:
    e = e.strip()
    cand = os.path.join(ROOT, e)
    if os.path.exists(cand): entry_files.append(cand)
    elif e in name_to_file: entry_files.append(name_to_file[e])
# also treat any file that looks like a streamlit page as a secondary entry
for p in allpy:
    b = os.path.basename(p)
    if b.startswith("page_") or b.startswith("pages"):
        entry_files.append(p)

reachable = set()
q = deque(entry_files)
while q:
    f = q.popleft()
    if f in reachable: continue
    reachable.add(f)
    for dep in imports_of.get(f, ()):
        if dep not in reachable: q.append(dep)

# ---- string-reference scan (catches dynamic loads) ----
# does ANY file mention this file's stem as a string / dotted name?
all_text = {}
for p in allpy:
    try: all_text[p] = open(p, encoding="utf-8", errors="replace").read()
    except Exception: all_text[p] = ""
big = "\n".join(all_text.values())

def string_refed(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    # look for the stem as a quoted string or dotted module, excluding its own file
    pat = re.compile(r'["\'.]' + re.escape(stem) + r'["\'.]')
    for q, txt in all_text.items():
        if q == path: continue
        if pat.search(txt): return True
    return False

# ---- version-dup heuristics ----
VER_PATTERNS = ["*_v[0-9]*.py","*_old*.py","*_bak*.py","*_backup*.py","*_copy*.py",
                "*(1)*.py","* - Copy*.py","*_orig*.py","*_prev*.py","*_deprecated*.py",
                "*_test.py","*_tmp*.py","*_new.py","*_final*.py"]
def looks_like_version(path):
    b = os.path.basename(path).lower()
    return any(fnmatch.fnmatch(b, pat.lower()) for pat in VER_PATTERNS)

# group files with same "base name" ignoring version suffix, to spot dup families
def base_key(path):
    b = os.path.splitext(os.path.basename(path))[0].lower()
    b = re.sub(r'[_ -]*(v\d+|old|bak|backup|copy|orig|prev|new|final|deprecated|\(\d+\))$','',b)
    return b
families = defaultdict(list)
for p in allpy:
    families[base_key(p)].append(p)

# ---- classify ----
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

active, orphan, strref, verdup = [], [], [], []
for p in allpy:
    if p in entry_files:
        active.append(p); continue
    is_reach = p in reachable
    is_str = string_refed(p)
    is_ver = looks_like_version(p)
    if is_reach:
        active.append(p)
    elif is_str:
        strref.append(p)
    elif is_ver:
        verdup.append(p)
    else:
        orphan.append(p)

log(f"repo: {ROOT}")
log(f"entry points: {[os.path.relpath(e,ROOT) for e in entry_files][:8]}")
log(f"total .py files: {len(allpy)}")
log(f"  ACTIVE (reachable by import from entry): {len(active)}")
log(f"  STRING-REFED (named somewhere — likely dynamic load): {len(strref)}")
log(f"  VERSION-DUP (name looks like an old copy): {len(verdup)}")
log(f"  ORPHAN (no import, no string ref): {len(orphan)}")
if parse_err:
    log(f"  (parse errors in {len(parse_err)} files — couldn't analyze those)")

log("\n=== VERSION-DUP families (multiple files, same base name) ===")
for base, group in sorted(families.items()):
    if len(group) > 1:
        log(f"  '{base}': " + ", ".join(os.path.relpath(g,ROOT) for g in sorted(group)))
        for g in group:
            tag = "ACTIVE" if g in reachable or g in entry_files else ("str-ref" if string_refed(g) else "unused")
            log(f"       {tag:8} {os.path.relpath(g,ROOT)}")

log("\n=== ORPHANS (strongest dead-file candidates — review before deleting) ===")
for p in sorted(orphan):
    log(f"  {os.path.relpath(p, ROOT)}")

log("\n=== VERSION-DUP (name suggests old copy, not reachable) ===")
for p in sorted(verdup):
    log(f"  {os.path.relpath(p, ROOT)}")

log("\n=== STRING-REFED (reached only by name — verify these are real dynamic loads) ===")
for p in sorted(strref):
    log(f"  {os.path.relpath(p, ROOT)}")

log("\n=== NOTES ===")
log("  ORPHAN = not imported anywhere AND its name never appears as a string. Safest to")
log("           remove, but eyeball each (could be a script you run directly, or an entry).")
log("  VERSION-DUP = looks like foo_v2 / foo_old / foo (1); check against the ACTIVE one.")
log("  STRING-REFED = something mentions its name in a string — could be importlib/st.Page")
log("           dynamic loading. Do NOT delete without confirming.")
log("  Static analysis can't see every dynamic import — treat this as a REVIEW LIST.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

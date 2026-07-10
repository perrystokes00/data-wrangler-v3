r"""
cleanup_tier2_junk.py — Tier 2: remove the pure-junk folders/files that are clearly not
source. PREVIEWS by default; --apply moves to a timestamped _trash_ folder (recoverable),
--hard permanently deletes. Read the preview before applying.

Targets (all confirmed junk from the dead-file analysis):
  download\              — downloaded copy of AI output paths (download\mnt\user-data\...)
  .vs\                   — Visual Studio cache (never belongs in a repo)
  _archive_20260703_*\   — already-archived diagnostics (dated folders)
  __pycache__\           — Python bytecode cache (anywhere)
  *.bak, *.bak_*         — patch backups (after you've confirmed patches work)
  _trash_*\              — earlier trash folders from cleanup runs

Does NOT touch: venv, .git, modules, your source .py, sql, docs, data dirs.
  py cleanup_tier2_junk.py            # preview
  py cleanup_tier2_junk.py --apply    # move to _trash_<ts>
  py cleanup_tier2_junk.py --apply --hard   # permanent delete
"""
import os, sys, shutil, time, fnmatch

APPLY = "--apply" in sys.argv
HARD  = "--hard" in sys.argv
ROOT  = os.getcwd()

# top-level junk folders (exact or glob)
JUNK_DIR_GLOBS = ["download", ".vs", "_archive_20260703_*", "_trash_2*"]
# junk files anywhere (but not under venv/.git)
JUNK_FILE_GLOBS = ["*.bak", "*.bak_*"]
# __pycache__ dirs anywhere
PYCACHE = "__pycache__"

PROTECT_DIRS = {"venv", ".venv", ".git", "modules"}

def under_protected(path):
    parts = os.path.relpath(path, ROOT).split(os.sep)
    return any(p in PROTECT_DIRS for p in parts[:-1]) or (parts and parts[0] in {"venv",".venv",".git"})

targets = []

# 1) top-level junk dirs
for entry in os.listdir(ROOT):
    full = os.path.join(ROOT, entry)
    if os.path.isdir(full):
        if any(fnmatch.fnmatch(entry, g) for g in JUNK_DIR_GLOBS):
            targets.append(("dir", full))

# 2) __pycache__ anywhere (except under venv/.git)
for dp, dns, fns in os.walk(ROOT):
    if any(seg in dp for seg in (os.sep+"venv", os.sep+".git", os.sep+".venv")):
        dns[:] = []; continue
    if PYCACHE in dns:
        targets.append(("dir", os.path.join(dp, PYCACHE)))
        dns.remove(PYCACHE)

# 3) .bak files anywhere (except protected)
for dp, dns, fns in os.walk(ROOT):
    if any(seg in dp for seg in (os.sep+"venv", os.sep+".git", os.sep+".venv")):
        dns[:] = []; continue
    for fn in fns:
        if any(fnmatch.fnmatch(fn, g) for g in JUNK_FILE_GLOBS):
            targets.append(("file", os.path.join(dp, fn)))

# de-dup and size
seen=set(); uniq=[]
for kind,p in targets:
    if p in seen: continue
    seen.add(p); uniq.append((kind,p))

def dsize(p):
    if os.path.isfile(p): return os.path.getsize(p)
    t=0
    for dp,_,fns in os.walk(p):
        for f in fns:
            try: t+=os.path.getsize(os.path.join(dp,f))
            except: pass
    return t

total=0
print(f"{'APPLY -> ' + ('HARD DELETE' if HARD else '_trash') if APPLY else 'PREVIEW (no changes)'}\n")
print(f"{'kind':5} {'size':>10}  path")
for kind,p in sorted(uniq):
    sz=dsize(p); total+=sz
    print(f"  {kind:4} {sz//1024:>8}KB  {os.path.relpath(p,ROOT)}")
print(f"\ntotal: {total//1024//1024} MB across {len(uniq)} item(s)")

if not APPLY:
    print("\n(preview only) re-run with --apply to move to _trash_<timestamp>")
    print("or --apply --hard to permanently delete.")
    sys.exit()

if HARD:
    for kind,p in uniq:
        try:
            if kind=="dir": shutil.rmtree(p)
            else: os.remove(p)
        except Exception as e: print(f"  skip {p}: {e}")
    print(f"\npermanently deleted {len(uniq)} item(s), {total//1024//1024} MB freed.")
else:
    trash=os.path.join(ROOT, "_trash_tier2_"+time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(trash, exist_ok=True)
    for kind,p in uniq:
        try:
            dest=os.path.join(trash, os.path.relpath(p,ROOT).replace(os.sep,"__"))
            shutil.move(p, dest)
        except Exception as e: print(f"  skip {p}: {e}")
    print(f"\nmoved {len(uniq)} item(s) to {trash}")
    print("Review, run the app, then delete that folder when confident.")

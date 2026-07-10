r"""
cleanup_temp_files.py — safely clean up the temp diagnostic/patch scripts and backup files
accumulated during debugging. PREVIEWS by default (deletes nothing). Only removes with
--apply, and even then moves to a _trash folder (not permanent delete) so you can recover.

  py cleanup_temp_files.py                 # preview: list what WOULD be moved
  py cleanup_temp_files.py --apply         # move matching files to .\_trash\
  py cleanup_temp_files.py --apply --hard  # permanently delete instead of moving to _trash

SAFETY:
  - Never touches your app modules (app_v3.py, page_workbench.py, worker_core.py,
    survey_loader.py, pdf_survey_catalog.py, promote_catalog.py, bcp_capture.py,
    pipeline_run.py, entity_seeder.py, *_loader.py in modules\, etc.)
  - Never touches anything in modules\, .git\, venv\, or subfolders unless --include-subdirs
  - Only matches KNOWN temp-name patterns in the repo ROOT.
  - Shows a numbered list; you can review before --apply.
"""
import os, sys, shutil, fnmatch, time

APPLY   = "--apply" in sys.argv
HARD    = "--hard" in sys.argv
SUBDIRS = "--include-subdirs" in sys.argv
ROOT    = os.getcwd()

# temp-file name patterns (the debugging scripts + their outputs + backups)
TEMP_GLOBS = [
    "check_*.py", "diag_*.py", "patch_*.py", "fix_*.py", "verify_*.py",
    "test_*.py", "probe_*.py", "reset_*.py", "backfill_*.py", "remap_*.py",
    "insert_*.py", "substitute_*.py", "flatten_*.py", "e2e_*.py", "cat_*.py",
    "preflight_*.py", "crawl_scorecard.py", "gen_scout_ticket.py",
    "inventory_scoped.py", "cleanup_temp_files.py",   # (self — only via --hard)
    "*.bak", "*.bak_*", "*.tmp", "*.pyc",
    "scout_synth*.pdf", "scout_synth*.PDF",
]

# NEVER delete these, even if a glob would match
PROTECT = {
    "app_v3.py", "page_workbench.py", "worker_core.py", "survey_loader.py",
    "pdf_survey_catalog.py", "promote_catalog.py", "bcp_capture.py",
    "pipeline_run.py", "entity_seeder.py", "catalog_capture.py",
    "catalog_rules.py", "pdf_db_loader.py", "geography_layers.py",
    "pdf_survey_catalog.py", "requirements.txt", "README.md",
}
PROTECT_PREFIXES = ("page_", "dv_", "app_")   # app pages/modules in root, if any

def is_protected(name):
    if name in PROTECT: return True
    # protect real modules that happen to start with a temp-ish prefix
    if name.endswith(".py") and any(name.startswith(p) for p in PROTECT_PREFIXES):
        # but DO allow our known temp scripts through
        temp_ok = any(fnmatch.fnmatch(name, g) for g in
                      ("check_*.py","diag_*.py","patch_*.py","fix_*.py","verify_*.py",
                       "test_*.py","probe_*.py","reset_*.py","preflight_*.py"))
        return not temp_ok
    return False

def matches_temp(name):
    return any(fnmatch.fnmatch(name, g) for g in TEMP_GLOBS)

# gather candidates (root only, unless --include-subdirs)
candidates = []
walker = os.walk(ROOT) if SUBDIRS else [(ROOT, [], os.listdir(ROOT))]
for dirpath, dirnames, filenames in walker:
    # skip protected dirs
    if any(seg in dirpath for seg in (os.sep+".git", os.sep+"venv", os.sep+"modules",
                                       os.sep+"__pycache__", os.sep+".venv")):
        continue
    for fn in filenames:
        full = os.path.join(dirpath, fn)
        if not os.path.isfile(full): continue
        if is_protected(fn): continue
        if matches_temp(fn):
            candidates.append(full)

candidates.sort()
print(f"repo root: {ROOT}")
print(f"{'PREVIEW (no changes)' if not APPLY else ('HARD DELETE' if HARD else 'MOVE TO _trash')}")
print(f"matched {len(candidates)} temp file(s):\n")
total = 0
for i, p in enumerate(candidates, 1):
    sz = os.path.getsize(p)
    total += sz
    print(f"  {i:3}. {os.path.relpath(p, ROOT)}  ({sz//1024 or 1} KB)")
print(f"\ntotal: {total//1024 or 1} KB across {len(candidates)} files")

if not APPLY:
    print("\n(preview only — nothing deleted)")
    print("Review the list. To move them to a recoverable _trash folder:")
    print("  py cleanup_temp_files.py --apply")
    print("To permanently delete instead:")
    print("  py cleanup_temp_files.py --apply --hard")
    sys.exit()

# APPLY
if HARD:
    for p in candidates:
        try: os.remove(p)
        except Exception as e: print(f"  skip {p}: {e}")
    print(f"\npermanently deleted {len(candidates)} files.")
else:
    trash = os.path.join(ROOT, "_trash_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(trash, exist_ok=True)
    for p in candidates:
        try: shutil.move(p, os.path.join(trash, os.path.basename(p)))
        except Exception as e: print(f"  skip {p}: {e}")
    print(f"\nmoved {len(candidates)} files to: {trash}")
    print("Review it, then delete the _trash folder when you're sure.")

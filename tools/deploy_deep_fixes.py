r"""
deploy_deep_fixes.py — one-shot deploy for the deep-extract promote fixes.

Run this from the data_wrangler_v3 app directory (where app_v3.py / page_workbench.py
live). It:
  1. copies the updated modules into place (with .bak of any it overwrites)
  2. runs each patcher in order (each writes its own .bak, each idempotent)
  3. prints a summary + the exact next steps

Put this file, the updated modules, and the patch_*.py scripts all in the app dir
(or pass --from <dir> to point at where you unzipped them). Then:
    py deploy_deep_fixes.py            # dry run — shows what it will do
    py deploy_deep_fixes.py --apply    # actually copy + patch
"""
import os, sys, shutil, subprocess, time

APPLY = "--apply" in sys.argv
SRC = "."
if "--from" in sys.argv:
    SRC = sys.argv[sys.argv.index("--from") + 1]

HERE = os.getcwd()
MODULES = os.path.join(HERE, "modules")

# (source_filename, dest_dir) — modules to copy into place
COPIES = [
    ("entity_seeder.py",     HERE),        # app dir (or modules — adjust if yours is there)
    ("dv_office_loader.py",  MODULES),
    ("promote_fk_review.py", MODULES),
]

# patchers to run, in order (each edits a file already on disk)
PATCHERS = [
    "patch_survey_blob_resilient.py",   # promote_catalog.py — resilient survey blobs
    "patch_promote_held_summary.py",    # promote_catalog.py — held-rows summary line
    "patch_worker_csv.py",              # worker_core.py     — .csv route
    "patch_wire_fk_review.py",          # page_workbench.py  — render FK grid after run
]

def _log(*a): print(" ", *a)

def main():
    print("=== deploy_deep_fixes ===", "(APPLY)" if APPLY else "(dry run)")
    # sanity: are we in the app dir?
    if not os.path.exists(os.path.join(HERE, "page_workbench.py")) \
       and not os.path.exists(os.path.join(HERE, "pages", "page_workbench.py")):
        print("WARNING: page_workbench.py not found here — are you in the app dir?")
    os.makedirs(MODULES, exist_ok=True)

    print("\n1) copy modules into place:")
    for fn, dest in COPIES:
        src = os.path.join(SRC, fn)
        dst = os.path.join(dest, fn)
        if not os.path.exists(src):
            _log(f"MISSING source {src} — skip"); continue
        rel = os.path.relpath(dst, HERE)
        if APPLY:
            if os.path.exists(dst):
                shutil.copy2(dst, dst + ".bak")
            shutil.copy2(src, dst)
            _log(f"copied -> {rel}" + ("  (.bak saved)" if os.path.exists(dst + ".bak") else ""))
        else:
            _log(f"would copy {fn} -> {rel}")

    print("\n2) run patchers:")
    for p in PATCHERS:
        src = os.path.join(SRC, p)
        if not os.path.exists(src):
            _log(f"MISSING patcher {p} — skip"); continue
        if APPLY:
            _log(f"running {p} ...")
            r = subprocess.run([sys.executable, src], capture_output=True, text=True)
            for line in (r.stdout or "").splitlines():
                _log("   " + line)
            if r.returncode != 0:
                _log(f"   !! {p} exited {r.returncode}")
                for line in (r.stderr or "").splitlines()[-3:]:
                    _log("   " + line)
        else:
            _log(f"would run {p}")

    print("\n3) next steps:")
    print("   • restart Streamlit (patches edit .py on disk; must reload)")
    print("   • re-run the pipeline with Promote + Apply both checked")
    print("   • watch the run log for '⚠ N held' or '✅ no rows held'")
    print("   • the FK review grid appears below 'Pipeline finished (APPLY)'")
    if not APPLY:
        print("\n(dry run — re-run with --apply to actually deploy)")

if __name__ == "__main__":
    main()

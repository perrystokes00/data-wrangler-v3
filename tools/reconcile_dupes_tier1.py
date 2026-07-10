r"""
reconcile_dupes_tier1.py — reconcile the SAFE root-vs-modules\ duplicates by making the
root copy a shim that re-exports from modules\ (the pattern catalog_capture.py already
uses). Only touches files that are IDENTICAL or where modules\ is confirmed live.

Does NOT touch bcp_capture.py or file_viewer.py (genuinely diverged — manual merge).
PREVIEW by default; --apply to act. Every touched root file is backed up to .bak_shim.

  py reconcile_dupes_tier1.py           # preview
  py reconcile_dupes_tier1.py --apply
"""
import os, sys, hashlib

APPLY = "--apply" in sys.argv
ROOT = os.getcwd()

# (filename, live_location, note). live = which copy is real.
# Only SAFE ones here — identical or modules-live with trivial diff.
PLAN = [
    ("pdf_survey_catalog.py", "modules", "identical after today's regex port; app uses modules (15)"),
    ("shapefile_catalog.py",  "modules", "1-line diff; app uses modules (10)"),
]
# files where the modules\ copy is DEAD (0 imports) -> delete modules copy, keep root
DELETE_MODULES_COPY = [
    ("page_workbench.py",   "modules\\ copy has 0 imports; root is live (scorecard is here)"),
    ("pipeline_batch_ui.py","modules\\ copy has 0 imports; root is live"),
]

def sha(p):
    return hashlib.sha1(open(p,"rb").read()).hexdigest()[:12] if os.path.exists(p) else None

def make_shim(stem):
    return (f'"""{stem}.py (root) — shim; canonical implementation lives in modules/{stem}.py.\n'
            f'Kept so `import {stem}` and `from {stem} import ...` keep working.\n"""\n'
            f'from modules.{stem} import *  # noqa: F401,F403\n')

print(f"{'APPLYING' if APPLY else 'PREVIEW'} — root-vs-modules reconciliation\n")

print("=== A) make root a shim -> modules\\ (safe: identical/near-identical) ===")
for fn, live, note in PLAN:
    stem = fn[:-3]
    rp = os.path.join(ROOT, fn); mp = os.path.join(ROOT, "modules", fn)
    if not os.path.exists(mp):
        print(f"  {fn}: modules copy MISSING — skip"); continue
    if not os.path.exists(rp):
        print(f"  {fn}: no root copy — nothing to do"); continue
    identical = sha(rp) == sha(mp)
    print(f"  {fn}: root={sha(rp)} modules={sha(mp)} identical={identical}")
    print(f"       {note}")
    if not identical:
        print(f"       ⚠️  NOT identical — verify the modules\\ copy has all needed changes")
        print(f"          before shimming (root may have a fix modules lacks).")
    if APPLY:
        # back up root, then replace with shim
        open(rp + ".bak_shim", "w", encoding="utf-8").write(open(rp, encoding="utf-8").read())
        open(rp, "w", encoding="utf-8").write(make_shim(stem))
        print(f"       -> root {fn} is now a shim (backup: {fn}.bak_shim)")

print("\n=== B) delete DEAD modules\\ copies (0 imports; root is live) ===")
for fn, note in DELETE_MODULES_COPY:
    mp = os.path.join(ROOT, "modules", fn)
    print(f"  modules\\{fn}: {note}")
    if not os.path.exists(mp):
        print(f"       (already gone)"); continue
    if APPLY:
        # move to a backup rather than hard delete
        bak = mp + ".bak_deadcopy"
        os.replace(mp, bak)
        print(f"       -> moved to modules\\{fn}.bak_deadcopy (delete after app verified)")

print("\n=== C) NOT touched — need manual merge (diverged) ===")
print("  bcp_capture.py   (94% — root has nested-pool fix; app split 9/5)")
print("  file_viewer.py   (95.6% — diverged rendering; app uses modules 7)")
print("  -> reconcile these by hand with a real diff; do them one at a time + test.")

if not APPLY:
    print("\n(preview) re-run with --apply. After applying: restart Streamlit, click through")
    print("every page, run a crawl. If all good, delete the .bak_shim / .bak_deadcopy files.")
else:
    print("\nDONE. RESTART STREAMLIT and test every page + a crawl before deleting backups.")
    print("If anything breaks: restore from .bak_shim / .bak_deadcopy, or git checkout backup-clean.")

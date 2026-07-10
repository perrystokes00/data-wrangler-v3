r"""
tidy_scratch.py — move this session's throwaway diagnostic/one-shot scripts out of
the repo root into _scratch\ (keeps real code + patch_* history in place).

  py tidy_scratch.py           # preview what would move
  py tidy_scratch.py --apply   # move them into _scratch\
  py tidy_scratch.py --apply --include-patches   # also move patch_*.py
  py tidy_scratch.py --apply --delete            # delete instead of move
"""
import sys, os, shutil, glob
from pathlib import Path

# throwaway one-shots created this session (diagnostics / benches / checks)
THROWAWAY = [
    "coord_h3_status.py", "read_bench.py", "bench2.py", "bench3.py",
    "h3_coltypes.py", "provenance_check.py", "gfc_cols.py", "find_promote.py",
    "coord_enrich_diag.py", "fwh_coord_diag.py", "pipeline_funnel.py",
    "wells_with_logs.py", "catalog_coord_fix.py", "catalog_coord_from_csv.py",
    "coord_backfill.py", "gold_key_check.py", "kgs_probe.py",
    "check_tray_persist.py", "las_time.py", "stamp_provenance.py",
]
patterns_extra = ["*_diag.py", "*_bench.py", "bench*.py", "*_probe.py", "*_check.py"]

here = Path(".")
cands = set()
for name in THROWAWAY:
    if (here / name).exists():
        cands.add(name)
if "--include-patches" in sys.argv:
    for p in glob.glob("patch_*.py"):
        cands.add(p)
# also catch obvious diag/bench/probe names
for pat in patterns_extra:
    for p in glob.glob(pat):
        cands.add(p)

cands = sorted(c for c in cands if os.path.isfile(c) and c != "tidy_scratch.py")
if not cands:
    print("nothing to tidy."); sys.exit(0)

print(f"{len(cands)} throwaway script(s):")
for c in cands:
    print("  ", c)

if "--apply" not in sys.argv:
    print("\n[dry run] --apply to move into _scratch\\  (or --apply --delete to remove)")
    sys.exit(0)

if "--delete" in sys.argv:
    for c in cands:
        os.remove(c)
    print(f"deleted {len(cands)} file(s)")
else:
    Path("_scratch").mkdir(exist_ok=True)
    for c in cands:
        shutil.move(c, os.path.join("_scratch", c))
    print(f"moved {len(cands)} file(s) -> _scratch\\")
    # optional gitignore
    gi = Path(".gitignore")
    line = "_scratch/"
    if not gi.exists() or line not in gi.read_text(encoding="utf-8", errors="replace"):
        with open(gi, "a", encoding="utf-8") as f:
            f.write(("" if not gi.exists() else "\n") + line + "\n")
        print("added '_scratch/' to .gitignore")

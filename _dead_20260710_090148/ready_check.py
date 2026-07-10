"""ready_check.py — are all four loader fixes deployed? Prints the exact remaining
steps to a clean end-to-end run. py ready_check.py"""
import os
def has(p, m):
    return os.path.exists(p) and m in open(p, encoding="utf-8", errors="replace").read()

checks = [
    ("worker_core.py  — LAS capture header-only",      "worker_core.py",   "ignore_data=True"),
    ("worker_core.py  — UWI gate keeps crosswalk UWI",  "worker_core.py",   "header UWI wins ONLY if"),
    ("promote_catalog.py — gold coords before the gate","promote_catalog.py","_fill_cat_coords_from_gold"),
    ("page_workbench.py — extract header-only",          "page_workbench.py","ignore_data=True"),
]
print("CODE FIXES DEPLOYED?")
allok = True
for label, p, m in checks:
    ok = has(p, m); allok = allok and ok
    print(f"  [{'OK' if ok else '--'}] {label}")

print()
if not allok:
    print("Deploy the missing file(s) above (the patch_*.py outputs create them),")
    print("then re-run this check. The one you likely still need:")
    print("  py patch_uwi_gate_fallback.py")
else:
    print("All four fixes are in. Do exactly this, in order:")
    print("  1) py seed_uom.py --apply        # seed the 14 log units (one-time)")
    print("  2) RESET + re-run the pipeline    # so the 581 gate-skipped files re-capture")
    print("  3) py pipeline_status.py          # confirm: cat_well ~626, dv_well ~600")
    print()
    print("If a plain re-run doesn't re-capture the skipped files (dv_well stays low),")
    print("you need the RESET first so capture re-attempts them with the fixed gate.")

"""read_after_capture.py — read what happens AFTER [capture] in the two most recent
FCP logs: promote result, commit, errors, rollback. The capture succeeds (402) but
the DB shows 2 — so something after capture wipes/rolls back. py read_after_capture.py"""
import os, glob
RPT = r"C:\Bulk\reports"
logs = sorted(glob.glob(os.path.join(RPT, "pipeline_*.log")),
              key=os.path.getmtime, reverse=True)[:2]
for p in logs:
    print("="*70); print(os.path.basename(p)); print("="*70)
    txt = open(p, encoding="utf-8", errors="replace").read()
    lines = txt.splitlines()
    grab = False
    for ln in lines:
        if "[capture] captured" in ln or "[capture] ✓" in ln:
            grab = True
        if grab:
            print(ln[:130])
    print()

"""find_status_panel.py — locate the file with the 'Pipeline — status' panel
(Captured/Promoted/Remaining tiles + the 'extracted but not captured' warning).
py find_status_panel.py"""
import glob
needles = ["Reprocess", "Remaining", "extracted but not captured",
           "aborted/deadlocked", "captured (aborted"]
for f in glob.glob("*.py") + glob.glob("modules/*.py"):
    try:
        txt = open(f, encoding="utf-8", errors="ignore").read()
    except Exception:
        continue
    hits = [n for n in needles if n in txt]
    if hits:
        print(f"{f}: {hits}")

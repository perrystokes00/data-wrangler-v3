"""check_shapefile_diff.py — the one line that differs between root and modules\
shapefile_catalog.py. Show it in context so we know if the modules\ (live) copy is
missing a fix. py check_shapefile_diff.py"""
import os, difflib
ROOT = os.getcwd()
rp = os.path.join(ROOT,"shapefile_catalog.py")
mp = os.path.join(ROOT,"modules","shapefile_catalog.py")
if not (os.path.exists(rp) and os.path.exists(mp)):
    print("one copy missing:", os.path.exists(rp), os.path.exists(mp)); raise SystemExit
a = open(rp,encoding="utf-8",errors="replace").read().splitlines()
b = open(mp,encoding="utf-8",errors="replace").read().splitlines()
print(f"root: {len(a)} lines   modules: {len(b)} lines\n")
print("=== unified diff (root vs modules) ===")
diff = list(difflib.unified_diff(a, b, "root", "modules", lineterm="", n=3))
for line in diff:
    print(line)
if not diff:
    print("(identical)")
print("\n=== which has the 'break', and is it a real logic change? ===")
print("If root has an extra 'break' modules lacks -> modules (live) may loop where root")
print("stops early. Decide: is the break correct? If yes, it must go into modules\\ before")
print("shimming. If it's cosmetic/unreachable, modules\\ is fine as-is.")

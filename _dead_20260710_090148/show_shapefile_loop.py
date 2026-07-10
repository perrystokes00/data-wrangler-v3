"""show_shapefile_loop.py — show the loop around line 824 in BOTH copies so we can tell
whether the 'break' (in root, not modules) is a real fix. py show_shapefile_loop.py"""
import os
ROOT = os.getcwd()
for label, path in (("ROOT", os.path.join(ROOT,"shapefile_catalog.py")),
                    ("MODULES", os.path.join(ROOT,"modules","shapefile_catalog.py"))):
    print(f"\n========== {label}: {path} ==========")
    lines = open(path,encoding="utf-8",errors="replace").read().splitlines()
    # find the loop: search backward from ~824 for 'for '
    # show lines ~805-835
    start = 800; end = min(len(lines), 838)
    for i in range(start, end):
        marker = ""
        if "break" in lines[i]: marker = "   <<< BREAK"
        if lines[i].strip().startswith("for "): marker = "   <<< LOOP START"
        print(f"  {i+1:4}: {lines[i]}{marker}")

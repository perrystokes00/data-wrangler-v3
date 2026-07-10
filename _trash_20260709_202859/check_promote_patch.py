"""check_promote_patch.py — is the pre-gate gold coord-fill deployed?"""
import os
p = "promote_catalog.py"
if not os.path.exists(p):
    print("run this in the app folder (promote_catalog.py not here)"); raise SystemExit
s = open(p, encoding="utf-8", errors="replace").read()
print("pre-gate gold coord-fill deployed:", "_fill_cat_coords_from_gold" in s)
print("PRE-GATE call present            :", "PRE-GATE" in s)

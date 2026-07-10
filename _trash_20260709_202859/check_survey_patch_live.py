"""check_survey_patch_live.py — 52 survey stations promoted but md/incl/azim all NULL.
Is patch_survey_key_map.py actually deployed in worker_core.py, and is _load_directional
the path these surveys took? py check_survey_patch_live.py"""
import os
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

for rel in ("modules\\worker_core.py","worker_core.py"):
    p = os.path.join(APP, rel)
    if os.path.exists(p):
        s = open(p, encoding="utf-8", errors="replace").read()
        log(f"=== {rel} ===")
        log(f"  _SURVEY_KEY_MAP present: {'_SURVEY_KEY_MAP' in s}")
        log(f"  _remap_station_keys present: {'_remap_station_keys' in s}")
        log(f"  called in _load_directional: {'rows = _remap_station_keys(rows)' in s}")
        break

# also check survey_loader — maybe IT does the column mapping and expects different keys
for rel in ("modules\\survey_loader.py","survey_loader.py"):
    p = os.path.join(APP, rel)
    if os.path.exists(p):
        s = open(p, encoding="utf-8", errors="replace").read()
        log(f"\n=== {rel} (the actual station loader) ===")
        # what keys does it read from each station dict?
        import re
        gets = re.findall(r"\.get\(['\"]([a-zA-Z_]+)['\"]", s)
        keys = sorted(set(gets))
        log(f"  station dict keys it reads (.get): {keys}")
        # does it look for md/incl/azim or MD/INC/AZI?
        log(f"  reads 'md': {'md' in keys}  'incl': {'incl' in keys}  'MD': {'MD' in keys}  'INC': {'INC' in keys}")
        break
else:
    log("\n  survey_loader.py not found in app root/modules — may be elsewhere")

log("\n=== VERDICT ===")
log("  If _SURVEY_KEY_MAP is NOT in worker_core: the patch didn't deploy -> redeploy +")
log("  restart. If it IS deployed but survey_loader reads keys NOT in the map, the map")
log("  targets the wrong names. Either way we align the keys and re-capture the surveys.")
open(r"C:\Bulk\reports\survey_patch_live.txt","w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to C:\\Bulk\\reports\\survey_patch_live.txt")

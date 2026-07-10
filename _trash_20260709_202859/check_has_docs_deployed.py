"""check_has_docs_deployed.py — is the 'Has documents' map query patch deployed?
py check_has_docs_deployed.py"""
import os
for p in ("page_well_map.py", os.path.join("modules","page_well_map.py")):
    if os.path.exists(p):
        s = open(p, encoding="utf-8").read()
        print(f"{p}:")
        print("   'Has documents' in _QUERY_MAP :", '"Has documents"' in s)
        print("   has_docs WHERE handler         :", 'has_docs' in s and 'GLOBAL_FILE_CATALOG g' in s)
if not any(os.path.exists(p) for p in ("page_well_map.py", os.path.join("modules","page_well_map.py"))):
    print("page_well_map.py not found in this directory")

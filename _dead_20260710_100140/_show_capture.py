import os, re
p = next((x for x in ("modules/catalog_capture.py","catalog_capture.py") if os.path.exists(x)), None)
print("FILE:", p)
if p:
    pat = re.compile(r"bcp|executemany|fast_executemany|to_sql|INSERT|BULK|def capture|def _?write|def _?flush|\.commit\(|TABLOCK", re.I)
    for i,l in enumerate(open(p,encoding="utf-8",errors="replace"),1):
        if pat.search(l): print(f"{i:5}: {l.rstrip()[:110]}")

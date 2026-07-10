"""check_cap_invs_state.py — show the actual _cap_invs lines in the DEPLOYED pipeline_run.py
so we can patch the real current text. Read-only. py check_cap_invs_state.py"""
import os
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
p = os.path.join(APP, "pipeline_run.py")
if not os.path.exists(p):
    p = os.path.join(APP, "modules", "pipeline_run.py")
print("file:", p)
s = open(p, encoding="utf-8", errors="replace").read()
print("size:", len(s))
print("already has success-only patch:", "stamp CAPTURED_HASH only on success" in s)
print()
lines = s.splitlines()
for i, ln in enumerate(lines):
    if "_cap_invs" in ln or "total = len(files)" in ln or "def _capture_one" in ln:
        print(f"{i+1}: {ln.rstrip()[:120]}")
print("\n=== exact bytes around 'total = len(files)' (to see whitespace/CRLF) ===")
import re
m = re.search(r"total = len\(files\)", s)
if m:
    seg = s[m.start(): m.start()+260]
    print(repr(seg))

"""verify_deployed_stamp.py — confirm the DEPLOYED pipeline_run.py already stamps
CAPTURED_HASH only for files that produced real cat_well rows. Read-only.
py verify_deployed_stamp.py"""
import os
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
p = os.path.join(APP, "pipeline_run.py")
if not os.path.exists(p):
    p = os.path.join(APP, "modules", "pipeline_run.py")
s = open(p, encoding="utf-8", errors="replace").read()
lines = s.splitlines()

print("=== the _cap_invs 'real captures' logic in your deployed file ===")
start = None
for i, ln in enumerate(lines):
    if "populate _cap_invs from real cat_well" in ln:
        start = i; break
if start is not None:
    for j in range(start, min(start+28, len(lines))):
        print(f"{j+1}: {lines[j].rstrip()[:130]}")
else:
    print("  (marker not found — showing all _cap_invs / _rows_real / _sel_invs lines)")
    for i, ln in enumerate(lines):
        if any(k in ln for k in ("_cap_invs", "_rows_real", "_sel_invs", "CAPTURED_HASH")):
            print(f"{i+1}: {ln.rstrip()[:130]}")

print("\n=== does it also fix the int(INVENTORY_ID) fast-path bug? ===")
print("  int(r[4]) present:", "int(r[4])" in s, "(True = still buggy, False = fixed)")
print("  BCP fast-path present:", "run_bcp_capture" in s)
print("  nested-pool-safe bcp?  (separate file bcp_capture.py)")

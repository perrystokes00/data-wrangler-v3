"""show_int_exact.py — dump every line containing int(r[4]) (or int( on an INVENTORY_ID)
in the deployed pipeline_run.py, with context + exact repr, so the fix matches byte-for-
byte. Read-only. py show_int_exact.py"""
import os
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
p = os.path.join(APP, "pipeline_run.py")
if not os.path.exists(p): p = os.path.join(APP, "modules", "pipeline_run.py")
s = open(p, encoding="utf-8", errors="replace").read()
lines = s.splitlines()

hits = [i for i, ln in enumerate(lines) if "int(r[4])" in ln or "int(r[4]" in ln
        or ("int(" in ln and "r[4]" in ln)]
if not hits:
    # broader: any int() near _las_rows / INVENTORY_ID
    hits = [i for i, ln in enumerate(lines)
            if "int(" in ln and ("_las" in ln or "INVENTORY_ID" in ln or "iid" in ln.lower())]
print(f"lines with int( on an id: {[h+1 for h in hits]}")
for h in hits:
    lo, hi = max(0, h-4), min(len(lines), h+10)
    print(f"\n=== context lines {lo+1}-{hi} ===")
    for j in range(lo, hi):
        print(f"{j+1}: {lines[j].rstrip()}")
    print("\n--- repr of the int line + next 8 (exact bytes) ---")
    print(repr("\n".join(lines[h:h+9])))

# also show the fast-path region generally, in case int() is written differently
print("\n\n=== all 'mark' / HEADER_EXTRACTED='Y' fast-path lines ===")
for i, ln in enumerate(lines):
    if "HEADER_EXTRACTED='Y'" in ln or "mark-extracted" in ln or "_iids" in ln:
        print(f"{i+1}: {ln.rstrip()[:120]}")

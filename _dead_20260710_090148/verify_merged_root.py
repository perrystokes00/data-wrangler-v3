"""verify_merged_root.py — check the MERGED root bcp_capture.py directly: does it still
have run_bcp_capture etc, does it import cleanly, and why did dir() show empty. py verify_merged_root.py"""
import os, sys, ast
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
rp = os.path.join(APP, "bcp_capture.py")
src = open(rp, encoding="utf-8", errors="replace").read()

print(f"root bcp_capture.py: {len(src.splitlines())} lines")
print("\n=== top-level defs (from AST, ground truth) ===")
tree = ast.parse(src)
defs = [n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
print("  functions:", defs)
print("  has __all__:", any(isinstance(n,ast.Assign) and any(getattr(t,'id',None)=='__all__' for t in n.targets) for n in tree.body))
print("  has run_bcp_capture:", "run_bcp_capture" in defs)
print("  has parse_las_rows:", "parse_las_rows" in defs)
print("  has SURVEY_OUTLINE (feature):", "SURVEY_OUTLINE" in src)
print("  has _in_child (nested fix):", "_in_child" in src)

print("\n=== does it import cleanly in a FRESH interpreter? ===")
# fresh subprocess import avoids any stale module cache from the earlier check
import subprocess
code = (
    "import sys; sys.path.insert(0, r'%s'); "
    "import bcp_capture as b; "
    "print('run_bcp_capture' in dir(b), 'run_bcp_capture_segy' in dir(b), "
    "len([x for x in dir(b) if not x.startswith('_')]))" % APP
)
r = subprocess.run([sys.executable,"-c",code], capture_output=True, text=True)
print("  fresh import result (has_run, has_segy, public_count):", r.stdout.strip() or r.stderr.strip()[:200])

print("\n=== VERDICT ===")
print("  If AST shows run_bcp_capture AND fresh import shows True/True/>0: the merge is")
print("  FINE — the earlier empty dir() was a stale-cache artifact of that script's sys.path.")
print("  If fresh import errors: the merge broke something — restore .bak_merge and retry.")

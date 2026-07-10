"""check_bcp_exports.py — the verify check said run_bcp_capture missing, but data loaded.
Find what the module ACTUALLY exports and whether the shim re-exports it. py check_bcp_exports.py"""
import sys, os
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP,"modules"))

import bcp_capture as root
print("=== root bcp_capture public functions ===")
fns = [n for n in dir(root) if not n.startswith("_") and callable(getattr(root,n))]
print("  ", fns)

import importlib
mod = importlib.import_module("modules.bcp_capture")
print("\n=== modules.bcp_capture (shim) public functions ===")
mfns = [n for n in dir(mod) if not n.startswith("_") and callable(getattr(mod,n))]
print("  ", mfns)

print("\n=== do the key functions match between root and shim? ===")
# find the actual capture entry point (likely 'capture' or 'run_bcp_capture' or similar)
for name in ("capture","run_bcp_capture","run_capture","bcp_capture","do_capture"):
    r = hasattr(root, name); m = hasattr(mod, name)
    if r or m:
        same = (getattr(root,name,None) is getattr(mod,name,None)) if (r and m) else False
        print(f"  {name}: root={r} shim={m} same_object={same}")

print("\n=== shim file contents ===")
shim_path = os.path.join(APP,"modules","bcp_capture.py")
print(open(shim_path,encoding="utf-8").read()[:400])

print("\n=== VERDICT ===")
print("  The functions the shim exposes should match root's (star-import re-exports all")
print("  public names). If 'capture' (or whatever the real entry is) shows same_object=True,")
print("  the shim works. run_bcp_capture was just my wrong guess at the name.")

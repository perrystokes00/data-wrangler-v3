"""bcp_ground_truth.py — settle exactly what each CURRENT copy has, so the merge is based
on facts not snapshots. Checks for BOTH features in both copies. py bcp_ground_truth.py"""
import os
ROOT = os.getcwd()
def check(path, label):
    if not os.path.exists(path):
        print(f"{label}: MISSING"); return
    s = open(path,encoding="utf-8",errors="replace").read()
    has_nested = "_in_child" in s and "nested-pool safe" in s
    has_threadfallback = "ThreadPoolExecutor" in s
    has_outline = "SURVEY_OUTLINE" in s and "convex_hull" in s
    has_serial_fallback = "parsing serially" in s
    print(f"{label}: ({len(s.splitlines())} lines)")
    print(f"   nested-pool fix (_in_child + ThreadPool): {has_nested and has_threadfallback}")
    print(f"   serial fallback:                          {has_serial_fallback}")
    print(f"   survey outline (convex hull):             {has_outline}")
    return dict(nested=has_nested and has_threadfallback, outline=has_outline,
                serial=has_serial_fallback, lines=len(s.splitlines()))

print("=== CURRENT files on disk ===\n")
r = check(os.path.join(ROOT,"bcp_capture.py"), "ROOT")
print()
m = check(os.path.join(ROOT,"modules","bcp_capture.py"), "MODULES")

print("\n=== MERGE VERDICT ===")
if r and m:
    need_nested = "root" if r["nested"] else ("modules" if m["nested"] else "NEITHER!")
    need_outline = "modules" if m["outline"] else ("root" if r["outline"] else "NEITHER!")
    print(f"  nested-pool fix is in: {need_nested}")
    print(f"  survey outline is in:  {need_outline}")
    if r["nested"] and r["outline"]:
        print("  -> ROOT already has BOTH. Make modules a copy of root (or root the canonical).")
    elif m["nested"] and m["outline"]:
        print("  -> MODULES already has BOTH. Make root a shim to modules.")
    else:
        print("  -> Each copy has ONE piece. Merge = combine both into one canonical copy.")
        print("     Safest: take whichever has the nested-pool fix, add the outline block to it.")

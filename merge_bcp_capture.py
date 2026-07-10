r"""
merge_bcp_capture.py — reconcile bcp_capture.py. Ground truth:
  ROOT    has the nested-pool fix (Windows-safe LAS parsing) but LACKS survey outline.
  MODULES has the SEG-Y survey outline (convex hull) but LACKS the nested-pool fix.
Merge = keep ROOT (has the critical parsing fix) + ADD the survey-outline block into it.
Result: root becomes the single canonical copy with BOTH features.

Then makes MODULES a shim -> root, so there's ONE implementation and both import styles work.
.bak backups for both. Verifies parse. py merge_bcp_capture.py [--apply]
"""
import os, ast, sys
APPLY = "--apply" in sys.argv
ROOT = os.getcwd()
rp = os.path.join(ROOT, "bcp_capture.py")
mp = os.path.join(ROOT, "modules", "bcp_capture.py")

if not (os.path.exists(rp) and os.path.exists(mp)):
    sys.exit(f"missing a copy: root={os.path.exists(rp)} modules={os.path.exists(mp)}")

r = open(rp, encoding="utf-8").read()

# safety checks: confirm the ground-truth state before editing
if "SURVEY_OUTLINE" in r and "convex_hull" in r:
    sys.exit("root ALREADY has survey outline — re-check; not merging blindly")
if "_in_child" not in r:
    sys.exit("root LACKS nested-pool fix — unexpected; abort")

# the survey-outline block to insert (verbatim from the modules copy / diff)
anchor = '    cxr = h.get("cdp_x_range");     cyr = h.get("cdp_y_range")\n'
outline_block = '''    cxr = h.get("cdp_x_range");     cyr = h.get("cdp_y_range")
    # Survey outline: convex hull of the sampled CDP points (same as the pool
    # extract path). For 2D it's the line corridor; for 3D the survey polygon.
    # cdp_points already read for the bbox, so this adds negligible time.
    _outline = None
    try:
        _pts = [(x, y) for (x, y) in (h.get("cdp_points") or [])
                if x is not None and y is not None and (x != 0 or y != 0)]
        if len(_pts) >= 3:
            from shapely.geometry import MultiPoint
            _hull = MultiPoint(_pts).convex_hull
            if not _hull.is_empty:
                _outline = _hull.wkt
    except Exception:
        _outline = None
'''

if anchor not in r:
    sys.exit("FAILED: SEG-Y anchor line not found in root (file differs from expected)")
r2 = r.replace(anchor, outline_block, 1)

# also add the SURVEY_OUTLINE field into the seismic header row dict
row_anchor = '        "BBOX_MIN_LAT": _rng(cyr, 0), "BBOX_MAX_LAT": _rng(cyr, 1),\n'
row_new = ('        "BBOX_MIN_LAT": _rng(cyr, 0), "BBOX_MAX_LAT": _rng(cyr, 1),\n'
           '        "SURVEY_OUTLINE": _outline,\n')
if row_anchor not in r2:
    sys.exit("FAILED: seismic row anchor (BBOX_MAX_LAT) not found")
r2 = r2.replace(row_anchor, row_new, 1)

# verify the merged root parses AND has both features
ast.parse(r2)
assert "_in_child" in r2 and "SURVEY_OUTLINE" in r2 and "convex_hull" in r2, "merge lost a feature"

shim = ('"""bcp_capture.py (modules) — shim; canonical implementation lives in the repo-root\n'
        'bcp_capture.py (has both the nested-pool fix and the SEG-Y survey outline).\n"""\n'
        'from bcp_capture import *  # noqa: F401,F403\n')

print("MERGE PLAN:")
print("  1. root bcp_capture.py  += survey-outline block (now has BOTH features)")
print("  2. modules\\bcp_capture.py -> shim to root")
print(f"  merged root would be {len(r2.splitlines())} lines, parses OK, both features present")

if APPLY:
    open(rp+".bak_merge","w",encoding="utf-8").write(r)
    open(rp,"w",encoding="utf-8").write(r2)
    open(mp+".bak_merge","w",encoding="utf-8").write(open(mp,encoding="utf-8").read())
    open(mp,"w",encoding="utf-8").write(shim)
    print("\nAPPLIED.")
    print("  root now has nested-pool fix + survey outline")
    print("  modules is a shim -> root")
    print("  backups: bcp_capture.py.bak_merge, modules\\bcp_capture.py.bak_merge")
    print("\n⚠️  IMPORTANT: root uses bare 'from bcp_capture import *' style now canonical,")
    print("   but 5 files import 'modules.bcp_capture' — the shim makes those work too.")
    print("   RESTART Streamlit. Test: a LAS crawl (nested-pool path) AND a SEG-Y crawl")
    print("   (survey outline). Both must work before deleting backups.")
else:
    print("\n(preview) re-run with --apply")

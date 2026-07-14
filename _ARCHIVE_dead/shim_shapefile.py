r"""
shim_shapefile.py — CONFIRMED: modules\shapefile_catalog.py is correct; the root copy has
a stray 'break' (line 827) inside the per-row loop that stops loading after the first
feature with length data (a data-loss bug). Replace root with a shim -> modules\, removing
the buggy copy. Backs up root to .bak_shim first. py shim_shapefile.py [--apply]
"""
import os, sys
APPLY = "--apply" in sys.argv
ROOT = os.getcwd()
rp = os.path.join(ROOT, "shapefile_catalog.py")
mp = os.path.join(ROOT, "modules", "shapefile_catalog.py")

if not os.path.exists(mp):
    sys.exit("modules\\shapefile_catalog.py missing — abort")
if not os.path.exists(rp):
    print("root shapefile_catalog.py already gone — nothing to do"); sys.exit(0)

# safety: confirm the buggy break really is in root and NOT in modules
r = open(rp,encoding="utf-8",errors="replace").read()
m = open(mp,encoding="utf-8",errors="replace").read()
# the length block: root has a break after the 1.60934 line, modules does not
root_has = "* 1.60934" in r and r.split("* 1.60934")[1].split("\n\n")[0].count("break") >= 1
mod_has  = "* 1.60934" in m and m.split("* 1.60934")[1].split("\n\n")[0].count("break") >= 1
print(f"root has stray break after length: {root_has}")
print(f"modules has it (should be False):  {mod_has}")
if mod_has:
    sys.exit("modules ALSO has the break — re-examine before shimming!")

shim = ('"""shapefile_catalog.py (root) — shim; canonical implementation lives in '
        'modules/shapefile_catalog.py.\nKept so `import shapefile_catalog` and '
        '`from shapefile_catalog import ...` keep working.\n"""\n'
        'from modules.shapefile_catalog import *  # noqa: F401,F403\n')

if APPLY:
    open(rp + ".bak_shim","w",encoding="utf-8").write(r)
    open(rp,"w",encoding="utf-8").write(shim)
    print(f"\nroot shapefile_catalog.py -> shim (backup: shapefile_catalog.py.bak_shim)")
    print("the buggy break is gone; app now uses the correct modules\\ copy everywhere.")
    print("RESTART Streamlit, test a shapefile crawl, then delete the .bak_shim.")
else:
    print("\n(preview) re-run with --apply to shim root away")

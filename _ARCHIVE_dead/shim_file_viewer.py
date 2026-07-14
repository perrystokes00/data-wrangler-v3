r"""
shim_file_viewer.py — CONFIRMED: root file_viewer.py is the correct copy. It has:
  - _vsection (nest-safe sections; work when embedded in the Documents page's expanders)
  - PyMuPDF PDF rendering (root comment: base64-iframe "crashed the browser")
modules\ has the OLDER approaches (st.expander that can't nest + base64 iframe PDF). Every
modules-only line is a fragment of those two older approaches — no unique functionality.

The app imports modules\ MORE (7 vs 5), so it's been using the buggy viewer. Fix: make root
canonical, shim modules\ -> root, so the whole app uses the fixed viewer.
.bak backup. Verifies parse. py shim_file_viewer.py [--apply]
"""
import os, sys
APPLY = "--apply" in sys.argv
ROOT = os.getcwd()
rp = os.path.join(ROOT,"file_viewer.py")
mp = os.path.join(ROOT,"modules","file_viewer.py")
if not (os.path.exists(rp) and os.path.exists(mp)):
    sys.exit(f"missing: root={os.path.exists(rp)} modules={os.path.exists(mp)}")

r = open(rp,encoding="utf-8",errors="replace").read()
# safety: root must have the fixes, modules must have the older approach
if "_vsection" not in r or "get_pixmap" not in r:
    sys.exit("root LACKS the fixes (_vsection/PyMuPDF) — abort, re-examine")

shim = ('"""file_viewer.py (modules) — shim; canonical implementation lives in the repo-root\n'
        'file_viewer.py, which has the nest-safe _vsection sections and PyMuPDF PDF render\n'
        '(the base64-iframe approach crashed the browser; bare st.expander cannot nest in the\n'
        'Documents page). Kept so `from modules.file_viewer import ...` keeps working.\n"""\n'
        'from file_viewer import *  # noqa: F401,F403\n')

print("PLAN: make root canonical (has the fixes), shim modules\\file_viewer.py -> root")
print(f"  root: {len(r.splitlines())} lines (has _vsection + PyMuPDF)")
print(f"  modules -> {len(shim.splitlines())}-line shim")

if APPLY:
    open(mp+".bak_shim","w",encoding="utf-8").write(open(mp,encoding="utf-8").read())
    open(mp,"w",encoding="utf-8").write(shim)
    print("\nAPPLIED. modules\\file_viewer.py is now a shim -> root.")
    print("  backup: modules\\file_viewer.py.bak_shim")
    print("  RESTART Streamlit. Test: open the Documents page, view a PDF (should render as")
    print("  page images, not a crashy iframe) and confirm embedded viewers don't error.")
    print("  The 7 files importing modules.file_viewer now get the FIXED viewer.")
else:
    print("\n(preview) re-run with --apply")

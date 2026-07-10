"""
patch_docs_viewport.py — make the map Results panel (and its Documents / Export /
Summary buttons) reflect the wells chosen on the map: use clicked/drilled wells,
else fall back to the current viewport/draw selection (viewport_uwis). Fixes
"documents not reflecting the wells chosen on the map." Idempotent, .bak.
Run: py patch_docs_viewport.py
"""
import sys, ast
P = "page_well_map.py"
s = open(P, encoding="utf-8").read()
if "Results = the drilled" in s:
    print("already patched"); sys.exit(0)

old = "        result_uwis = st.session_state.clicked_uwis\n"
new = ('        # Results = the drilled/clicked set, else the current viewport /\n'
       '        # draw selection, so Documents / Export reflect the wells chosen\n'
       '        # on the map (viewport toggle or a drawn box).\n'
       '        result_uwis = (list(st.session_state.get("clicked_uwis") or [])\n'
       '                       or list(st.session_state.get("viewport_uwis") or []))\n')
if old not in s:
    print("FAILED: result_uwis line not found."); sys.exit(1)
s = s.replace(old, new, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: Results/Documents fall back to viewport/draw selection")

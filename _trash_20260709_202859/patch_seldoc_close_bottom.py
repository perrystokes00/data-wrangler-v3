"""
patch_seldoc_close_bottom.py — add a "Close view" button at the BOTTOM of the map
document viewer, after file_viewer.view() renders the plot. Idempotent, .bak.
Run: py patch_seldoc_close_bottom.py
"""
import sys, ast
P = "page_selected_documents.py"
s = open(P, encoding="utf-8").read()
if "seldoc_close_bottom" in s:
    print("already patched"); sys.exit(0)

old = ('    try:\n'
       '        file_viewer.view(str(path), ext or None)\n'
       '    except Exception as e:\n'
       '        st.error(f"Viewer failed: {e}")\n')
new = old + (
    '\n'
    '    st.markdown("---")\n'
    '    if st.button("\u2716 Close view", key="seldoc_close_bottom",\n'
    '                 use_container_width=True):\n'
    '        st.session_state["seldoc_sel"] = None\n'
    '        st.rerun()\n')

if old not in s:
    print("FAILED: file_viewer.view block not found (run patch_seldoc_grid_fv.py first)."); sys.exit(1)
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: '\u2716 Close view' added at the bottom of the plot")

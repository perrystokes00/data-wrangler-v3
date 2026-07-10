r"""
patch_remove_status_panel.py — remove the confusing 'Pipeline — status' panel
(Catalogued/Captured/Promoted/Remaining tiles + the misleading 'extracted but not
captured' warning). It counted live cat_* staging (which drains on promote), so a
SUCCESSFUL run looked like a failure. Removing it entirely per user request.
In place, .bak, idempotent. py patch_remove_status_panel.py
"""
import sys, os, ast
P = "page_workbench.py"
if not os.path.exists(P):
    sys.exit("page_workbench.py not found")
s = open(P, encoding="utf-8").read()
if "pipeline_batch_ui" not in s:
    print("already removed"); sys.exit(0)

old = '''    st.divider()
    try:
        import os as _bp_os, sys as _bp_sys
        _bp_md = _bp_os.path.join(_bp_os.path.dirname(_bp_os.path.abspath(__file__)), "modules")
        if _bp_md not in _bp_sys.path:
            _bp_sys.path.insert(0, _bp_md)
        import pipeline_batch_ui
        pipeline_batch_ui.render(engine)
    except Exception as _bpe:
        st.caption(f"(batch panel unavailable: {_bpe})")

    with st.expander("ℹ️ About this pipeline", expanded=False):'''
new = '''    with st.expander("ℹ️ About this pipeline", expanded=False):'''

if old not in s:
    sys.exit("FAILED: status-panel block not found in expected form")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: removed the confusing Pipeline — status panel")

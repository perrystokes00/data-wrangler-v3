r"""
patch_wire_run_scorecard.py — add a per-RUN scorecard next to the cumulative one.
(1) stamp fp_run_started (UTC) when Run pipeline kicks off; (2) render the current-run
scorecard right after _render_scorecard. Function-scoped, .bak, idempotent, verifies parse.
py patch_wire_run_scorecard.py
"""
import os, ast, sys
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("pages", "page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "fp_run_started" in s:
    print("already patched"); sys.exit(0)

# 1) stamp run-start UTC right where fp_running is set True
a1 = '''            st.session_state["fp_running"]   = True
            st.session_state["fp_apply_run"] = fp_apply'''
n1 = '''            st.session_state["fp_running"]   = True
            # per-run scorecard anchor: mark when THIS run began (UTC), so the
            # current-run scorecard can scope to files scanned since now.
            from datetime import datetime as _dtu, timezone as _tzu
            st.session_state["fp_run_started"] = _dtu.now(_tzu.utc).strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["fp_apply_run"] = fp_apply'''
if a1 not in s:
    sys.exit("FAILED: fp_running anchor not found")
s = s.replace(a1, n1, 1)

# 2) render the per-run scorecard right after the cumulative one
a2 = '''        _render_scorecard(engine)        # rendered every cycle, including mid-run'''
n2 = '''        _render_scorecard(engine)        # rendered every cycle, including mid-run
        # per-run scorecard: what THIS run just did (cumulative table is all crawls)
        try:
            from modules.current_run_scorecard import render as _render_run_scorecard
            _render_run_scorecard(engine, st, since=st.session_state.get("fp_run_started"))
        except Exception as _rsx:
            st.caption(f"(per-run scorecard unavailable: {str(_rsx)[:100]})")'''
if a2 not in s:
    sys.exit("FAILED: _render_scorecard anchor not found")
s = s.replace(a2, n2, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: per-run scorecard wired (run-start stamped + rendered)")

r"""
patch_fcp_orphan_guard.py — make the File Catalog Pipeline resilient: on entry,
if fp_running is set but the worker thread is dead (desynced state after a tab
switch / session reset), clear the stale flag so the page isn't wedged and the
Run button re-enables. Prevents the 'stuck running / orphan' state. In place,
.bak, idempotent. py patch_fcp_orphan_guard.py
"""
import sys, os, ast
P = "page_workbench.py"
if not os.path.exists(P):
    sys.exit("page_workbench.py not found")
s = open(P, encoding="utf-8").read()
if "_fcp_orphan_guard" in s:
    print("already patched"); sys.exit(0)

# anchor: the 'running = ...' line near the top of _pipeline_run_hero
anchor = '        running = st.session_state.get("fp_running", False)'
if anchor not in s:
    sys.exit("FAILED: 'running = ...' anchor not found in _pipeline_run_hero")

inject = '''        # _fcp_orphan_guard: if fp_running is set but the worker thread is dead
        # (desynced after a tab switch / rerun / session reset), the page would
        # stay wedged with the Run button disabled forever. Detect and clear it.
        _fp_th = st.session_state.get("fp_thread")
        if st.session_state.get("fp_running") and _fp_th is not None and not _fp_th.is_alive():
            _fp_res = st.session_state.get("fp_result", {})
            if _fp_res.get("done") or True:      # thread gone -> run is over
                st.session_state["fp_running"] = False
        running = st.session_state.get("fp_running", False)'''

s = s.replace(anchor, inject, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: added orphan/stale-run guard to File Catalog Pipeline")

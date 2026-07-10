r"""
patch_fcp_poll_readfile.py — companion to the detached-runner patch. The poll loop
now reads the child's LOG FILE (fp_logfile) into fp_log and detects completion via
proc.poll(), loading the state file on exit. Replaces the '_th.is_alive()' liveness
check (there's no reader thread anymore) with a real process check. In place, .bak.
py patch_fcp_poll_readfile.py
"""
import sys, os, ast
P = "page_workbench.py"
if not os.path.exists(P):
    sys.exit("page_workbench.py not found")
s = open(P, encoding="utf-8").read()
if "fp_logfile poll" in s:
    print("already patched"); sys.exit(0)

# At the top of the poll block, pull fresh lines from the log file (if detached run)
old = '''        if st.session_state.get("fp_running"):
            _log = st.session_state.get("fp_log", [])
            _exp = _expected_stages(fp_inventory, fp_capture, fp_vaulton,
                                    fp_promote)'''
new = '''        if st.session_state.get("fp_running"):
            # fp_logfile poll: detached multi-core run writes to a log file — read it
            # fresh each cycle so the log/scorecard update without a reader thread.
            _lf = st.session_state.get("fp_logfile")
            if _lf:
                try:
                    with open(_lf, "r", encoding="utf-8", errors="replace") as _lfh:
                        st.session_state["fp_log"] = _lfh.read().splitlines()
                except Exception:
                    pass
                _pr = st.session_state.get("fp_proc")
                if _pr is not None and _pr.poll() is not None:
                    # process exited — load state file, mark done
                    _res2 = st.session_state.get("fp_result", {})
                    import json as _json2
                    try:
                        with open(st.session_state.get("fp_statep",""), "r",
                                  encoding="utf-8") as _sf2:
                            _res2["state"] = _json2.load(_sf2)
                    except Exception:
                        pass
                    _res2["ok"] = (_pr.returncode == 0)
                    if _pr.returncode != 0 and "err" not in _res2:
                        _res2["err"] = f"runner exit {_pr.returncode}"
                    _res2["done"] = True
                    st.session_state["fp_result"] = _res2
            _log = st.session_state.get("fp_log", [])
            _exp = _expected_stages(fp_inventory, fp_capture, fp_vaulton,
                                    fp_promote)'''

if old not in s:
    sys.exit("FAILED: poll-loop head anchor not found")
s = s.replace(old, new, 1)

# Fix the liveness check: no reader thread for detached runs, so rely on fp_result done
old2 = '''            _th = st.session_state.get("fp_thread")
            _done = bool(_res.get("done") or (_th is not None and not _th.is_alive()))'''
new2 = '''            _th = st.session_state.get("fp_thread")
            _proc_live = st.session_state.get("fp_proc")
            _done = bool(_res.get("done")
                         or (_th is not None and not _th.is_alive())
                         or (_proc_live is not None and _proc_live.poll() is not None))'''
if old2 not in s:
    sys.exit("FAILED: liveness-check anchor not found")
s = s.replace(old2, new2, 1)

# On completion, clear the detached-run session keys so a stale proc can't linger
old3 = '''            if _done:
                st.session_state["fp_running"] = False'''
new3 = '''            if _done:
                st.session_state["fp_running"] = False
                for _k in ("fp_logfile", "fp_proc", "fp_statep"):
                    st.session_state.pop(_k, None)'''
if old3 not in s:
    sys.exit("FAILED: done-block anchor not found")
s = s.replace(old3, new3, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: poll loop reads the detached log file + proper completion")

r"""
patch_fcp_detached_runner.py — make the File Catalog Pipeline reliable by adopting
page_run.py's launch model: the multi-core child writes stdout to a LOG FILE and
runs fully DETACHED (CREATE_NO_WINDOW, no pipe, no daemon reader thread). The poll
loop reads the file. This removes the reader-thread + piped-stdout + rerun-loop
combination that spawned/held nested child processes and left orphans.

Keeps the scorecard/progress UI intact — only the launch + log-source change.
In place, .bak, idempotent.  py patch_fcp_detached_runner.py
"""
import sys, os, ast
P = "page_workbench.py"
if not os.path.exists(P):
    sys.exit("page_workbench.py not found")
s = open(P, encoding="utf-8").read()
if "_fp_logfile" in s:
    print("already patched"); sys.exit(0)

# Replace the piped-stdout + daemon-reader _proc_worker with a DETACHED launch that
# writes to a log file. The poll loop reads st.session_state['fp_logfile'].
old = '''                with open(_cfgp, "w", encoding="utf-8") as _f:
                    _json.dump(_cfg, _f)

                def _proc_worker(_runner=_runner, _cfgp=_cfgp, _statep=_statep,
                                 _buf=_log_buf, _res=_result):
                    try:
                        if not os.path.exists(_runner):
                            _res["ok"] = False
                            _res["err"] = ("pipeline_proc_runner.py not deployed "
                                           "next to pipeline_run.py")
                            _res["done"] = True
                            return
                        _env = dict(os.environ)
                        _env["PYTHONIOENCODING"] = "utf-8"
                        proc = subprocess.Popen(
                            [_sys.executable, "-u", _runner, _cfgp],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            bufsize=1, env=_env,
                            cwd=os.path.dirname(_runner) or None)
                        _res["proc"] = proc
                        for _line in iter(proc.stdout.readline, ""):
                            _buf.append(_line.rstrip("\\n"))
                        proc.stdout.close()
                        _rc = proc.wait()
                        _st = {}
                        try:
                            with open(_statep, "r", encoding="utf-8") as _sf:
                                _st = _json.load(_sf)
                        except Exception:
                            pass
                        _res["state"] = _st
                        _res["ok"] = (_rc == 0)
                        if _rc != 0 and "err" not in _res:
                            _res["err"] = f"runner exit {_rc}"
                    except Exception as e:
                        _res["ok"] = False
                        _res["err"] = f"{type(e).__name__}: {e}"
                    _res["done"] = True

                _th = threading.Thread(target=_proc_worker, daemon=True)'''

new = '''                _logfile = os.path.join(_tmpd, "console.log")
                _cfg["console_log"] = _logfile
                with open(_cfgp, "w", encoding="utf-8") as _f:
                    _json.dump(_cfg, _f)

                # DETACHED launch (page_run.py model): child writes stdout to a LOG
                # FILE; no pipe, no daemon reader thread, no rerun-held handles. The
                # poll loop reads the file. This is what stops orphan/respawn trees.
                if not os.path.exists(_runner):
                    _result["ok"] = False
                    _result["err"] = ("pipeline_proc_runner.py not deployed "
                                      "next to pipeline_run.py")
                    _result["done"] = True
                    _th = None
                else:
                    _env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
                    _CREATE_NO_WINDOW = 0x08000000
                    _fh = open(_logfile, "w", encoding="utf-8")
                    _proc = subprocess.Popen(
                        [_sys.executable, "-u", _runner, _cfgp],
                        stdout=_fh, stderr=subprocess.STDOUT,
                        cwd=os.path.dirname(_runner) or None, env=_env,
                        creationflags=_CREATE_NO_WINDOW)
                    _result["proc"] = _proc
                    st.session_state["fp_logfile"] = _logfile
                    st.session_state["fp_proc"] = _proc
                    st.session_state["fp_statep"] = _statep
                    _th = None      # no reader thread — the poll loop reads the file'''

if old not in s:
    sys.exit("FAILED: multicore _proc_worker block not found in expected form")
s = s.replace(old, new, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: multi-core runner is now a detached log-file process (no reader thread)")

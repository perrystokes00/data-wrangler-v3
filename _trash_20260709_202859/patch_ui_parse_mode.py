r"""
patch_ui_parse_mode.py — wire the 'Use all CPU cores' checkbox (fp_multicore) into
parse_mode so the UI actually runs the BCP LAS fast-path (parse_mode='process').
Currently parse_mode is never passed, so run_pipeline defaults to 'thread' and the
UI captures almost nothing. Sets parse_mode on BOTH the subprocess config dict and
the in-app thread _common. In place, .bak, idempotent.
py patch_ui_parse_mode.py
"""
import sys, os, ast
P = "page_workbench.py"
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (run in app root)")
s = open(P, encoding="utf-8").read()
if '"parse_mode"' in s or "parse_mode=" in s:
    print("already patched (parse_mode present)"); sys.exit(0)

# 1) subprocess config dict — add parse_mode from fp_multicore
a1 = '''                    "do_deep": False,
                    "batch_size": int(fp_batch_size) if fp_batch else None,'''
b1 = '''                    "do_deep": False,
                    "parse_mode": "process" if fp_multicore else "thread",
                    "batch_size": int(fp_batch_size) if fp_batch else None,'''

# 2) in-app thread _common — add parse_mode too
a2 = '''                            per_type_cap=None, stall_timeout=_STALL_TIMEOUT,
                            should_abort=_ev.is_set, ref=REF,
                            report_root=_report, log=_log_buf.append)'''
b2 = '''                            per_type_cap=None, stall_timeout=_STALL_TIMEOUT,
                            should_abort=_ev.is_set, ref=REF,
                            parse_mode=("process" if fp_multicore else "thread"),
                            report_root=_report, log=_log_buf.append)'''

for tag, a, b in (("1-config", a1, b1), ("2-common", a2, b2)):
    if a not in s:
        sys.exit(f"FAILED at {tag}: anchor not found (file differs from expected)")
    s = s.replace(a, b, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: 'Use all CPU cores' now sets parse_mode='process' (BCP fast-path)")

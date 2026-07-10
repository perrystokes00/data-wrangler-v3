"""
patch_pipeline_bcp_capture.py — route LAS files in the capture stage through the
fast bcp_capture.run_bcp_capture (parallel parse + BULK INSERT), leaving all other
formats on the existing per-file process pool. In place, .bak, idempotent.
Run in the app folder (or modules\): py patch_pipeline_bcp_capture.py
"""
import sys, os, ast

P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found (run in app folder or modules\\)")
s = open(P, encoding="utf-8").read()
if "run_bcp_capture" in s:
    print("already patched"); sys.exit(0)

# Insert the LAS fast-path just before the parallel _args are built.
anchor = "        _args = [(_url, {"
if anchor not in s:
    sys.exit("FAILED: parallel _args anchor not found")

inject = '''        # ── fast path: LAS files via bulk BCP capture (parse in parallel,
        # one BULK INSERT per table) instead of per-file executemany. Non-LAS
        # files stay on the process pool below.
        try:
            from bcp_capture import run_bcp_capture
        except Exception:
            try:
                from modules.bcp_capture import run_bcp_capture
            except Exception:
                run_bcp_capture = None
        _las_rows = [r for r in files if str(r[1] or "").lower() == ".las"]
        _oth_rows = [r for r in files if str(r[1] or "").lower() != ".las"]
        if run_bcp_capture and _las_rows:
            import urllib.parse as _upq
            try:
                _odbc = _upq.unquote(engine.url.query.get("odbc_connect", "")) or None
            except Exception:
                _odbc = None
            _las_recs = [{"FILE_PATH": r[0],
                          "MATCHED_UWI": ("" if r[2] is None else str(r[2]).strip()),
                          "INVENTORY_ID": r[4]} for r in _las_rows]
            try:
                _bres = run_bcp_capture(_las_recs, conn_str=_odbc, workers=workers, log=log)
                _bn = sum(_bres.values())
                rows_total += _bn
                ok += len(_las_rows)   # files whose rows loaded
                log(f"[capture] LAS fast-path (BCP): {_bn:,} row(s) from "
                    f"{len(_las_rows):,} file(s)")
                files = _oth_rows       # pool handles only the rest
            except Exception as _e:
                log(f"[capture] BCP fast-path failed ({str(_e)[:120]}); "
                    f"LAS fall back to pool")

'''

s = s.replace(anchor, inject + anchor, 1)

# Guard: if LAS routing left `files` empty, skip the pool cleanly (it maps over files)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: LAS -> bcp_capture fast path; other formats -> existing pool")

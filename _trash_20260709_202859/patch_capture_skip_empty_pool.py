r"""
patch_capture_skip_empty_pool.py — after the LAS BCP fast-path, skip the whole
ProcessPoolExecutor block when no non-LAS files remain. In place, .bak, idempotent.
py patch_capture_skip_empty_pool.py
"""
import sys, os, ast
P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found")
s = open(P, encoding="utf-8").read()
if "no non-LAS files for the pool" in s:
    print("already patched"); sys.exit(0)

old = '''        _proc_sum = 0.0
        _times = []
        try:
            with ProcessPoolExecutor(max_workers=workers,
                                     initializer=_capture_pool_init,
                                     initargs=(_url,)) as pool:
                for fname, status, nrows, err, ptime in pool.map(_capture_proc_one, _args):
                    _proc_sum += ptime or 0.0
                    _times.append((fname, ptime or 0.0))
                    if status == "error" and err:
                        log(f"  [x] {fname}: {str(err)[:400]}")
                    else:
                        rows_total += nrows
                        if status == "done" and nrows:
                            ok += 1
            _did_parallel = True
            log(f"[capture] multi-core parse+capture across {workers} core(s)")
            log(f"[capture-phase] worker process_file sum {_proc_sum:.1f}s / {workers}w "
                f"→ ideal wall ~{_proc_sum / max(workers, 1):.1f}s")
            _times.sort(key=lambda x: -x[1])
            log("[capture-slow] " + " · ".join(
                f"{os.path.basename(str(fn))} {pt:.1f}s" for fn, pt in _times[:6]))
        except Exception as e:
            log(f"[capture] process pool failed ({str(e)[:120]}); "
                f"falling back to single-core")'''

new = '''        _proc_sum = 0.0
        _times = []
        if not _args:
            _did_parallel = True
            log("[capture] no non-LAS files for the pool — skipped")
        else:
            try:
                with ProcessPoolExecutor(max_workers=workers,
                                         initializer=_capture_pool_init,
                                         initargs=(_url,)) as pool:
                    for fname, status, nrows, err, ptime in pool.map(_capture_proc_one, _args):
                        _proc_sum += ptime or 0.0
                        _times.append((fname, ptime or 0.0))
                        if status == "error" and err:
                            log(f"  [x] {fname}: {str(err)[:400]}")
                        else:
                            rows_total += nrows
                            if status == "done" and nrows:
                                ok += 1
                _did_parallel = True
                log(f"[capture] multi-core parse+capture across {workers} core(s)")
                log(f"[capture-phase] worker process_file sum {_proc_sum:.1f}s / {workers}w "
                    f"→ ideal wall ~{_proc_sum / max(workers, 1):.1f}s")
                _times.sort(key=lambda x: -x[1])
                log("[capture-slow] " + " · ".join(
                    f"{os.path.basename(str(fn))} {pt:.1f}s" for fn, pt in _times[:6]))
            except Exception as e:
                log(f"[capture] process pool failed ({str(e)[:120]}); "
                    f"falling back to single-core")'''

if old not in s:
    sys.exit("FAILED: pool block not found in expected form")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak5", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: capture skips the pool entirely when no non-LAS files remain")

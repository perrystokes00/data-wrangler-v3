r"""
patch_bcp_nested_pool.py — fix the LAS BCP fast-path's nested-multiprocessing crash.

Root cause (proven by bcp_probe): run_bcp_capture works perfectly (writes 20 cat_well,
146 curves) when run cleanly — but the pipeline calls it from INSIDE its detached
multi-core worker process, and run_bcp_capture then tries to spawn its OWN
ProcessPoolExecutor. On Windows, a process spawning processes during bootstrap raises
"An attempt has been made to start a new process before the current process has finished
its bootstrapping" — so the parse pool fails, run_bcp_capture writes nothing, and the
pipeline (which stamped CAPTURED_HASH up front) leaves the LAS permanently stuck.

Fix: when we're already inside a spawned child process (or spawning would nest),
parse with a ThreadPoolExecutor instead of a ProcessPoolExecutor. LAS parsing is
lasio file I/O (releases the GIL), so threads give the parallelism without nesting
processes. Detected via multiprocessing.parent_process() (not None => we're a child).
Falls back to serial if even threads look risky. Keeps the fast path; no behavior
change when called from the top-level process.

Function-scoped edit to the parse-pool block. .bak, idempotent, verifies parse.
py patch_bcp_nested_pool.py
"""
import os, ast, sys
P = "bcp_capture.py"
if not os.path.exists(P):
    P = os.path.join("modules", "bcp_capture.py")
if not os.path.exists(P):
    sys.exit("bcp_capture.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "nested-pool safe" in s:
    print("already patched"); sys.exit(0)

anchor = '''    with ProcessPoolExecutor(max_workers=workers) as ex:
        for out in ex.map(parse_las_rows, args):
            for t in _all_tabs:
                buckets[t].extend(out.get(t, []))
            _done += 1
            if _done % _step == 0 or _done == _n:
                log(f"[bcp-capture] parsing {_done:,}/{_n:,} files… "
                    f"({time.time()-t0:.0f}s, OneDrive files hydrate on first read)")'''

replacement = '''    # nested-pool safe: if we're already inside a spawned child process (the
    # pipeline's detached multi-core runner calls this), spawning a nested
    # ProcessPoolExecutor raises the Windows "start a new process before the
    # current process has finished its bootstrapping" error and the parse yields
    # nothing. Detect that and parse with THREADS instead (lasio I/O releases the
    # GIL, so we still get parallelism) — or serially if workers<=1.
    import multiprocessing as _mp
    _in_child = _mp.parent_process() is not None
    _use_threads = _in_child or workers <= 1

    def _drain(_iterable):
        _d = 0
        for out in _iterable:
            for t in _all_tabs:
                buckets[t].extend(out.get(t, []))
            _d += 1
            if _d % _step == 0 or _d == _n:
                log(f"[bcp-capture] parsing {_d:,}/{_n:,} files… "
                    f"({time.time()-t0:.0f}s, OneDrive files hydrate on first read)")

    if _use_threads:
        from concurrent.futures import ThreadPoolExecutor
        _mode = "threads (nested-process-safe)" if _in_child else "threads"
        log(f"[bcp-capture] parse pool: {_mode}, {max(1, workers)} worker(s)")
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            _drain(ex.map(parse_las_rows, args))
    else:
        try:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                _drain(ex.map(parse_las_rows, args))
        except Exception as _pe:
            # last-resort fallback: the process pool failed (e.g. bootstrapping);
            # parse serially so we still capture rather than writing nothing.
            log(f"[bcp-capture] process pool failed ({str(_pe)[:80]}); "
                f"parsing serially")
            buckets.clear()
            for t in _all_tabs:
                buckets[t] = []
            _drain(map(parse_las_rows, args))'''

if anchor not in s:
    sys.exit("FAILED: ProcessPoolExecutor parse-block anchor not found")
s = s.replace(anchor, replacement, 1)

# tag so idempotent
s = s.replace("import multiprocessing as _mp\n    _in_child",
              "import multiprocessing as _mp  # nested-pool safe\n    _in_child", 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: parse pool is now nested-process-safe (threads inside a child)")

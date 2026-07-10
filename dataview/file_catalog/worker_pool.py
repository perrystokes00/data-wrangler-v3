"""
worker_pool.py — the parallel process pool that drains the work queue
=====================================================================
Launches N worker PROCESSES. Each worker builds its OWN SQLAlchemy engine
(engines can't cross the process boundary), then loops:

    claim a batch (atomic)  →  process each file via worker_core.process_file
                            →  mark done / error / skip  →  repeat
                            until the queue is drained.

This is the "parallel process" stage of: parallel crawl → batch → parallel
process. The queue (work_queue.py) is the batch backbone; worker_core is the
per-file keystone; this module is the concurrency engine.

Run standalone:
    python worker_pool.py --server localhost\\SQLEXPRESS --database DataView_Demo \
        --workers 10 --batch 500

Or drive from the UI: call run_pool(...) in a background thread/process and poll
work_queue.progress() for the dashboard.
"""
from __future__ import annotations

import argparse
import os
import time


# ── the worker loop (runs inside each spawned process) ───────────────────────
def worker_loop(server, database, worker_id, batch_size=500, max_attempts=3,
                exts=None, idle_passes=2):
    """One worker process: own engine, drain the queue. Returns a stats dict.

    idle_passes: how many consecutive empty claims before concluding the queue
    is drained (a small >1 guards against a transient empty window while other
    workers are mid-batch and a retry might re-queue a row).
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from dataview.file_catalog import worker_core as wc
    from dataview.file_catalog import work_queue as wq

    engine = wc.make_engine(server, database)

    # Defensive: confirm this worker is actually in the intended database AND
    # the PROC_* columns are visible to ITS connection. A parent/worker DB
    # mismatch (or a stale connection) is the classic cause of "Invalid column
    # name PROC_STATUS" appearing only in workers. Fail loud and clear.
    from sqlalchemy import text as _t
    with engine.connect() as _c:
        _db = _c.execute(_t("SELECT DB_NAME()")).scalar()
        _has = _c.execute(_t("""
            SELECT COUNT(*) FROM sys.columns
             WHERE object_id = OBJECT_ID('file_catalog.GLOBAL_FILE_CATALOG')
               AND name = 'PROC_STATUS'
        """)).scalar()
    if not _has:
        return {"worker": worker_id, "done": 0, "error": 0, "skip": 0, "rows": 0,
                "fatal": f"PROC_STATUS not visible in DB '{_db}' "
                         f"(worker connected to '{_db}', expected '{database}')"}
    stats = {"worker": worker_id, "done": 0, "error": 0, "skip": 0, "rows": 0}
    empties = 0

    while True:
        # claim with deadlock-retry: under heavy concurrency SQL Server may pick
        # this statement as a deadlock victim (error 40001). That's transient —
        # wait a beat and retry rather than letting the worker die.
        batch = None
        for _attempt in range(5):
            try:
                batch = wq.claim_batch(engine, worker_id, batch_size=batch_size,
                                       max_attempts=max_attempts, exts=exts)
                break
            except Exception as _ce:
                if "40001" in str(_ce) or "deadlock" in str(_ce).lower():
                    time.sleep(0.2 * (_attempt + 1))
                    continue
                raise
        if batch is None:
            # claim kept deadlocking — back off and try the outer loop again
            empties += 1
            if empties >= idle_passes:
                break
            time.sleep(0.5)
            continue
        if not batch:
            empties += 1
            if empties >= idle_passes:
                break
            time.sleep(0.5)
            continue
        empties = 0

        marks = []
        FLUSH_EVERY = 50          # flush marks periodically, not only at batch end
        for rec in batch:
            iid = rec["INVENTORY_ID"]
            try:
                r = wc.process_file(engine, rec)
                if r.status == "done":
                    marks.append({"id": iid, "status": "done",
                                  "rows": r.rows_written})
                    stats["done"] += 1
                    stats["rows"] += r.rows_written
                elif r.status == "skip":
                    marks.append({"id": iid, "status": "skip", "rows": 0})
                    stats["skip"] += 1
                else:  # error
                    marks.append({"id": iid, "status": "error",
                                  "error": r.error or "unknown"})
                    stats["error"] += 1
            except Exception as e:                       # noqa: BLE001
                marks.append({"id": iid, "status": "error",
                              "error": f"{type(e).__name__}: {e}"})
                stats["error"] += 1
            # Flush in chunks: one transaction per 50 results (not 500 per-row
            # commits, and not all 500 deferred to batch-end — the latter let one
            # slow file hide a whole batch's progress). Keeps the commit-batching
            # win while surfacing progress steadily.
            if len(marks) >= FLUSH_EVERY:
                wq.mark_results_batch(engine, marks, max_attempts=max_attempts)
                marks = []
        # flush whatever remains for this batch
        if marks:
            wq.mark_results_batch(engine, marks, max_attempts=max_attempts)

    engine.dispose()
    return stats


# ── the parent orchestrator ──────────────────────────────────────────────────
def run_pool(server, database, *, workers=10, batch_size=500, max_attempts=3,
             exts=None, reset_claimed=True, log=print, progress_every=5.0):
    """Launch `workers` processes to drain the queue. Blocks until drained.

    reset_claimed: re-queue rows stuck in 'claimed' from a previous crashed run
    before starting (crash recovery). Does NOT touch done/error rows.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from dataview.file_catalog import worker_core as wc
    from dataview.file_catalog import work_queue as wq
    from concurrent.futures import ProcessPoolExecutor, as_completed
    import threading

    engine = wc.make_engine(server, database)
    wq.ensure_columns(engine, log=log)
    if reset_claimed:
        wq.reset_queue(engine, only_claimed=True, log=log)

    start = wq.progress(engine)
    log(f"[pool] start — {start['pending']:,} pending, {start['done']:,} done, "
        f"{start['error']:,} error · {workers} workers · batch {batch_size}")
    if start["pending"] == 0:
        log("[pool] nothing pending — queue already drained.")
        engine.dispose()
        return start

    # background progress reporter (reads the queue while workers drain it)
    stop_flag = {"stop": False}
    def _report():
        t0 = time.monotonic()
        while not stop_flag["stop"]:
            time.sleep(progress_every)
            p = wq.progress(engine)
            done = p["done"]
            rate = done / max(1e-6, time.monotonic() - t0)
            eta = (p["pending"] + p["claimed"]) / rate if rate > 0 else 0
            log(f"[pool] {done:,}/{p['total']:,} done · {p['pending']:,} pending "
                f"· {p['error']:,} error · ~{rate:.0f}/s · eta {eta/60:.1f}m")
    rep = threading.Thread(target=_report, daemon=True)
    rep.start()

    t0 = time.monotonic()
    agg = {"done": 0, "error": 0, "skip": 0, "rows": 0}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(worker_loop, server, database, f"w{i}",
                            batch_size, max_attempts, exts)
                for i in range(workers)]
        for fut in as_completed(futs):
            try:
                s = fut.result()
                if s.get("fatal"):
                    log(f"[pool] worker {s['worker']} FATAL: {s['fatal']}")
                for k in ("done", "error", "skip", "rows"):
                    agg[k] += s.get(k, 0)
            except Exception as e:
                log(f"[pool] a worker died: {e}")

    stop_flag["stop"] = True
    elapsed = time.monotonic() - t0
    final = wq.progress(engine)
    log(f"[pool] DONE in {elapsed:.0f}s — processed {agg['done']:,} "
        f"({agg['rows']:,} rows), {agg['skip']:,} skipped, {agg['error']:,} error")
    log(f"[pool] queue: {final['done']:,} done · {final['error']:,} error · "
        f"{final['pending']:,} pending")
    engine.dispose()
    return {"elapsed_s": elapsed, **agg, "queue": final}


def main():
    ap = argparse.ArgumentParser(description="Parallel worker pool — drain the "
                                             "file work queue via worker_core")
    ap.add_argument("--server", required=True)
    ap.add_argument("--database", required=True)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--max-attempts", type=int, default=3)
    ap.add_argument("--exts", nargs="*", default=None,
                    help="restrict to these extensions (e.g. .las .pdf)")
    ap.add_argument("--full-reset", action="store_true",
                    help="reset ALL rows to pending first (full reprocess)")
    a = ap.parse_args()

    from dataview.file_catalog import worker_core as wc
    from dataview.file_catalog import work_queue as wq
    if a.full_reset:
        eng = wc.make_engine(a.server, a.database)
        wq.ensure_columns(eng)
        wq.reset_queue(eng, only_claimed=False)
        eng.dispose()

    run_pool(a.server, a.database, workers=a.workers, batch_size=a.batch,
             max_attempts=a.max_attempts, exts=a.exts)


if __name__ == "__main__":
    main()

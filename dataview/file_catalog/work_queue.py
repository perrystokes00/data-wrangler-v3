"""
work_queue.py — database-backed work queue on GLOBAL_FILE_CATALOG
================================================================
The queue IS the catalog. Per-file processing status lives in PROC_* columns on
file_catalog.GLOBAL_FILE_CATALOG, so a crash leaves done-rows done and
pending-rows pending — resumability for free. A pool of worker processes claims
batches atomically (no two workers ever get the same file), processes them via
worker_core.process_file, and marks them done/error.

STATUS lifecycle:  pending → claimed → done | error
  pending : not yet processed (default for a freshly-crawled file)
  claimed : a worker holds it (PROC_WORKER, PROC_CLAIMED_AT set)
  done    : processed OK (PROC_ROWS = rows written)
  error   : failed PROC_ATTEMPTS times (PROC_ERROR holds the last message)

Atomic claim uses SQL Server's UPDATE…OUTPUT with (READPAST, UPDLOCK, ROWLOCK):
READPAST skips rows another worker already locked, so concurrent claims never
collide and never block each other — the standard SQL-Server work-queue pattern.

Columns added (all nullable, safe to add to a populated table):
  PROC_STATUS    VARCHAR(12)   -- pending/claimed/done/error  (NULL = pending)
  PROC_ATTEMPTS  INT           -- retry counter (parked at error when >= max)
  PROC_CLAIMED_AT DATETIME2    -- when claimed (for stale-claim recovery)
  PROC_WORKER    VARCHAR(64)   -- which worker holds/processed it
  PROC_ERROR     VARCHAR(1000) -- last error message
  PROC_ROWS      INT           -- rows written on success
"""
from __future__ import annotations

from sqlalchemy import text as _t

SCHEMA = "file_catalog"
TABLE = "GLOBAL_FILE_CATALOG"
FQ = f"{SCHEMA}.{TABLE}"


# ── one-time schema setup ────────────────────────────────────────────────────
def ensure_columns(engine, log=print):
    """Add the PROC_* work-queue columns if missing. Idempotent and VERIFIED —
    each ADD runs in its own committed transaction, then we re-read sys.columns
    and raise if any column is still missing (so a silent DDL failure surfaces
    here, not as 10 confusing worker crashes)."""
    cols = [
        ("PROC_STATUS",     "VARCHAR(12)"),
        ("PROC_ATTEMPTS",   "INT"),
        ("PROC_CLAIMED_AT", "DATETIME2"),
        ("PROC_WORKER",     "VARCHAR(64)"),
        ("PROC_ERROR",      "VARCHAR(1000)"),
        ("PROC_ROWS",       "INT"),
    ]
    for name, decl in cols:
        with engine.begin() as con:
            exists = con.execute(_t(f"""
                SELECT 1 FROM sys.columns
                 WHERE object_id = OBJECT_ID('{FQ}') AND name = :n
            """), {"n": name}).fetchone()
            if not exists:
                # ALTER TABLE ADD must be its own batch — run it alone, commit.
                con.execute(_t(f"ALTER TABLE {FQ} ADD {name} {decl}"))
                log(f"[queue] added column {name}")

    # verify every column is now present before anyone tries to use it
    with engine.connect() as con:
        present = {r[0] for r in con.execute(_t(f"""
            SELECT name FROM sys.columns
             WHERE object_id = OBJECT_ID('{FQ}') AND name LIKE 'PROC[_]%'
        """)).fetchall()}
    missing = [c for c, _ in cols if c not in present]
    if missing:
        raise RuntimeError(
            f"PROC_* columns failed to add: {missing}. Check permissions on "
            f"{FQ} (need ALTER), then re-run.")

    # index (best effort — non-fatal if it can't be created)
    try:
        with engine.begin() as con:
            con.execute(_t(f"""
                IF NOT EXISTS (SELECT 1 FROM sys.indexes
                               WHERE name = 'IX_GFC_proc_status'
                                 AND object_id = OBJECT_ID('{FQ}'))
                CREATE INDEX IX_GFC_proc_status
                    ON {FQ} (PROC_STATUS, PROC_ATTEMPTS)
                    INCLUDE (FILE_PATH, FILE_EXT, MATCHED_UWI, INVENTORY_ID);
            """))
    except Exception as e:
        log(f"[queue] index skipped ({type(e).__name__}: {e})")
    log("[queue] PROC_* columns verified present")


def reset_queue(engine, only_claimed=True, log=print):
    """Re-queue rows for a fresh run.

    only_claimed=True (default, for crash recovery): reset rows stuck in
    'claimed' (a worker died mid-batch) back to 'pending'. Safe to run at the
    start of every run.

    only_claimed=False: reset EVERYTHING eligible back to 'pending' (full
    reprocess). Done rows go back to pending too — use deliberately.
    """
    with engine.begin() as con:
        if only_claimed:
            n = con.execute(_t(f"""
                UPDATE {FQ} SET PROC_STATUS='pending', PROC_WORKER=NULL,
                                PROC_CLAIMED_AT=NULL
                 WHERE PROC_STATUS='claimed'
            """)).rowcount
            log(f"[queue] re-queued {n} stuck 'claimed' row(s)")
        else:
            n = con.execute(_t(f"""
                UPDATE {FQ} SET PROC_STATUS='pending', PROC_WORKER=NULL,
                                PROC_CLAIMED_AT=NULL, PROC_ATTEMPTS=0,
                                PROC_ERROR=NULL, PROC_ROWS=NULL
                 WHERE ISNULL(FLAG_DELETE,'N')<>'Y'
                   AND DUPLICATE_GROUP IS NULL
            """)).rowcount
            log(f"[queue] reset {n} row(s) to pending (full reprocess)")
    return n


# ── the atomic claim (the concurrency-critical bit) ──────────────────────────
def claim_batch(engine, worker_id, batch_size=500, max_attempts=3,
                exts=None):
    """Atomically claim up to batch_size pending files for this worker.

    Single UPDATE…OUTPUT with (READPAST, UPDLOCK, ROWLOCK): two workers running
    this concurrently can NEVER grab the same row (READPAST skips rows the other
    worker has locked), and neither blocks the other. Returns a list of dicts:
    {INVENTORY_ID, FILE_PATH, FILE_EXT, MATCHED_UWI}. Empty list = queue drained.
    """
    ext_filter = ""
    if exts:
        in_list = ",".join(f"'{e.lower()}'" for e in exts)
        ext_filter = f"AND LOWER(FILE_EXT) IN ({in_list})"

    sql = _t(f"""
        UPDATE TOP (:batch) {FQ} WITH (READPAST, UPDLOCK, ROWLOCK)
           SET PROC_STATUS    = 'claimed',
               PROC_WORKER    = :w,
               PROC_CLAIMED_AT = SYSUTCDATETIME(),
               PROC_ATTEMPTS  = ISNULL(PROC_ATTEMPTS, 0) + 1
        OUTPUT inserted.INVENTORY_ID, inserted.FILE_PATH,
               inserted.FILE_EXT, inserted.MATCHED_UWI
         WHERE (PROC_STATUS IS NULL OR PROC_STATUS = 'pending')
           AND ISNULL(PROC_ATTEMPTS, 0) < :maxatt
           AND ISNULL(FLAG_DELETE, 'N') <> 'Y'
           AND DUPLICATE_GROUP IS NULL
           {ext_filter};
    """)
    # ONE statement sets status + worker + time + attempts and OUTPUTs the rows.
    # Single-statement claim (vs. claim-then-stamp in two updates) is what
    # avoids deadlocks under many concurrent workers: there's no window where a
    # worker holds claim locks while waiting to run a second update.
    with engine.begin() as con:
        rows = con.execute(sql, {"batch": int(batch_size),
                                 "maxatt": int(max_attempts),
                                 "w": str(worker_id)[:64]}).fetchall()
    return [{"INVENTORY_ID": r[0], "FILE_PATH": r[1],
             "FILE_EXT": r[2], "MATCHED_UWI": r[3]} for r in rows]


def mark_done(engine, inventory_id, rows_written=0):
    # Also set HEADER_EXTRACTED='Y' — the column the File Catalog scorecard and
    # the regular (in-page) pipeline read to judge "is this file processed?".
    # The pool tracks completion in PROC_STATUS; without also setting
    # HEADER_EXTRACTED, pool-processed files look "pending/unextracted" to the
    # rest of the UI even though they're done (the phantom-backlog bug).
    with engine.begin() as con:
        con.execute(_t(f"""
            UPDATE {FQ} SET PROC_STATUS='done', PROC_ROWS=:n, PROC_ERROR=NULL,
                            HEADER_EXTRACTED='Y'
             WHERE INVENTORY_ID=:id
        """), {"n": int(rows_written or 0), "id": inventory_id})


def mark_error(engine, inventory_id, message, max_attempts=3):
    """Record an error. The row stays 'pending' (so it retries) until attempts
    reach max_attempts, at which point it parks as 'error'."""
    with engine.begin() as con:
        con.execute(_t(f"""
            UPDATE {FQ}
               SET PROC_ERROR = :msg,
                   PROC_STATUS = CASE WHEN ISNULL(PROC_ATTEMPTS,0) >= :maxatt
                                      THEN 'error' ELSE 'pending' END,
                   PROC_WORKER = NULL, PROC_CLAIMED_AT = NULL
             WHERE INVENTORY_ID = :id
        """), {"msg": str(message)[:1000], "maxatt": int(max_attempts),
               "id": inventory_id})


def mark_skip(engine, inventory_id):
    """A file with no handler / nothing to do — done, zero rows, not an error."""
    with engine.begin() as con:
        con.execute(_t(f"""
            UPDATE {FQ} SET PROC_STATUS='done', PROC_ROWS=0, HEADER_EXTRACTED='Y'
             WHERE INVENTORY_ID=:id
        """), {"id": inventory_id})


def mark_results_batch(engine, results, max_attempts=3):
    """Mark an ENTIRE batch of results in ONE transaction via a staging join —
    NOT one committed UPDATE per row. The per-row form (mark_done/skip/error each
    opening its own engine.begin()) meant 500 transactions per batch per worker;
    with 10 workers that is a commit storm that contends on the queue table and
    slows progressively as the table fills (the tail-stall we hit). This does the
    whole batch as a single set-based UPDATE…JOIN, the same staging pattern used
    elsewhere (~one round-trip instead of 500).

    results: list of dicts {id, status('done'|'skip'|'error'), rows, error}.
    """
    if not results:
        return
    rows = [{
        "id":   r["id"],
        "st":   r["status"],
        "rows": int(r.get("rows") or 0),
        "err":  (str(r.get("error"))[:1000] if r.get("error") else None),
    } for r in results]

    # Split by outcome so each group is one parameterized executemany inside a
    # SINGLE transaction — one commit for the whole batch, not 500. (Avoids the
    # temp-table approach which was fragile across pyodbc fast_executemany.)
    done_ids = [(r["rows"], r["id"]) for r in rows if r["st"] in ("done", "skip")]
    err_rows = [(r["err"], r["id"]) for r in rows if r["st"] == "error"]

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.fast_executemany = True
        if done_ids:
            cur.executemany(
                f"UPDATE {FQ} SET PROC_STATUS='done', PROC_ROWS=?, "
                f"PROC_ERROR=NULL, HEADER_EXTRACTED='Y' WHERE INVENTORY_ID=?",
                done_ids)
        if err_rows:
            # error → 'error' if attempts exhausted, else back to 'pending'
            cur.executemany(
                f"UPDATE {FQ} SET PROC_ERROR=?, "
                f"PROC_STATUS=CASE WHEN ISNULL(PROC_ATTEMPTS,0) >= {int(max_attempts)} "
                f"THEN 'error' ELSE 'pending' END, "
                f"PROC_WORKER=CASE WHEN ISNULL(PROC_ATTEMPTS,0) >= {int(max_attempts)} "
                f"THEN PROC_WORKER ELSE NULL END, "
                f"PROC_CLAIMED_AT=CASE WHEN ISNULL(PROC_ATTEMPTS,0) >= {int(max_attempts)} "
                f"THEN PROC_CLAIMED_AT ELSE NULL END "
                f"WHERE INVENTORY_ID=?",
                err_rows)
        raw.commit()
    finally:
        raw.close()


# ── progress (what the UI polls) ─────────────────────────────────────────────
def progress(engine):
    """Return {pending, claimed, done, error, total} for live monitoring."""
    with engine.connect() as con:
        rows = con.execute(_t(f"""
            SELECT ISNULL(PROC_STATUS,'pending') AS s, COUNT(*) AS n
              FROM {FQ}
             WHERE ISNULL(FLAG_DELETE,'N')<>'Y' AND DUPLICATE_GROUP IS NULL
             GROUP BY ISNULL(PROC_STATUS,'pending')
        """)).fetchall()
    d = {"pending": 0, "claimed": 0, "done": 0, "error": 0}
    for s, n in rows:
        d[s] = n
    d["total"] = sum(d.values())
    return d

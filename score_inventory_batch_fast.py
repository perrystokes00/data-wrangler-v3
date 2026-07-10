"""
score_inventory_batch_fast.py
=============================
Drop-in replacement for score_inventory_batch() in modules/catalog_rules.py.

Same inputs, same return shape, same EXTRACTION_STATUS semantics. Only the
DB access pattern changes — from O(N) round-trips to O(1):

  BEFORE (per file, inside N worker threads + N serial writes):
    * match_uwi():  opens engine.connect(), fires up to 2 SELECTs against
                    dv_well — once PER FILE. The normalized fallback is the
                    non-sargable REPLACE(REPLACE(REPLACE(uwi))) scan.
    * write_score(): opens engine.begin(), fires 1 UPDATE — once PER FILE.
    => ~4N round-trips against SQL Express; the thread pool just makes the
       per-file DB calls contend on the connection pool.

  AFTER:
    * workers do PURE parsing (score_file called with engine=None — no DB).
    * ONE query bulk-loads all extracted UWIs into a temp table and matches
      them against dv_well in a single JOIN (exact + normalized) — the match
      that was N selects becomes 1.
    * ONE bulk UPDATE writes every file's EXTRACTION_STATUS back via a
      temp-table JOIN — the write that was N transactions becomes 1.

Drop this file next to catalog_rules.py (or paste the function in, replacing
the existing score_inventory_batch). It imports the unchanged helpers from
catalog_rules, so behaviour of extraction/scoring is identical.

    from score_inventory_batch_fast import score_inventory_batch_fast
    summary = score_inventory_batch_fast(engine, dialect, ext_filter=[...])
"""
from __future__ import annotations

import re
from sqlalchemy import text

try:
    from modules.catalog_rules import extract_files_parallel
except ModuleNotFoundError:
    from catalog_rules import extract_files_parallel


def score_inventory_batch_fast(engine, dialect: str,
                               ext_filter: list = None,
                               limit: int = 200,
                               progress_callback=None,
                               max_workers: int = 8) -> dict:
    if ext_filter is None:
        ext_filter = [".las", ".dlis", ".dlf", ".lis", ".segy", ".sgy"]

    summary = {"total": 0, "scored": 0, "errors": 0,
               "success": 0, "partial": 0, "empty": 0, "failed": 0}

    # 1. pull the work list (one query)
    try:
        exts = ",".join(f"'{e}'" for e in ext_filter)
        with engine.connect() as con:
            rows = con.execute(text(f"""
                SELECT TOP {limit} INVENTORY_ID, FILE_PATH, FILE_EXT
                FROM file_catalog.GLOBAL_FILE_CATALOG
                WHERE FILE_EXT IN ({exts})
                  AND (HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED = 'N')
                ORDER BY SCAN_DATE DESC
            """)).fetchall()
    except Exception as e:
        return {"error": str(e)}

    summary["total"] = len(rows)
    if not rows:
        return summary

    # 2. PARALLEL EXTRACTION ONLY — no per-file DB. Pass engine=None so
    #    score_file() runs its no-DB branch (keeps the extracted UWI as the
    #    match key, no dv_well lookup). We resolve dv_well matches in ONE
    #    query afterwards. Collect results in memory (status + extracted UWI).
    #
    #    Per-extension timing is accumulated from each result's elapsed_s so
    #    callers can see WHICH file types dominate capture (returned under the
    #    'by_ext' key: {ext: {n, total_s, max_s, slowest_file}}).
    import os
    results = []   # (inventory_id, status, uwi)
    by_ext = {}
    for r in extract_files_parallel(
        rows, engine=None, max_workers=max_workers,
        progress_callback=progress_callback,
    ):
        uwi = (r.get("fields") or {}).get("uwi")
        if uwi and str(uwi).startswith("__SHP_"):
            uwi = None
        results.append((r["inventory_id"], r["status"], uwi))

        ext = (r.get("file_ext") or "").lower() or "(none)"
        es = float(r.get("elapsed_s") or 0.0)
        b = by_ext.setdefault(
            ext, {"n": 0, "total_s": 0.0, "max_s": 0.0, "slowest_file": None})
        b["n"] += 1
        b["total_s"] += es
        if es > b["max_s"]:
            b["max_s"] = es
            b["slowest_file"] = os.path.basename(r.get("file_path") or "")

    # round for readability and attach to the summary
    summary["by_ext"] = {
        ext: {"n": v["n"],
              "total_s": round(v["total_s"], 2),
              "avg_s": round(v["total_s"] / v["n"], 3) if v["n"] else 0,
              "max_s": round(v["max_s"], 2),
              "slowest_file": v["slowest_file"]}
        for ext, v in sorted(by_ext.items(),
                             key=lambda kv: -kv[1]["total_s"])
    }

    # 3. ONE bulk write-back of EXTRACTION_STATUS via temp-table JOIN.
    #    Stage (inventory_id, status) with fast_executemany, then a single
    #    UPDATE..JOIN — replaces N per-file UPDATE transactions.
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        try:
            cur.fast_executemany = True
        except Exception:
            pass

        cur.execute("IF OBJECT_ID('tempdb..#scores') IS NOT NULL DROP TABLE #scores")
        cur.execute("CREATE TABLE #scores "
                    "(inv_id nvarchar(40) PRIMARY KEY, status nvarchar(20))")
        cur.executemany(
            "INSERT INTO #scores (inv_id, status) VALUES (?, ?)",
            [(inv, st) for inv, st, _ in results])

        cur.execute("""
            UPDATE g SET
                g.EXTRACTION_STATUS = s.status,
                g.HEADER_EXTRACTED  = 'Y',
                g.ROW_CHANGED_DATE  = SYSUTCDATETIME()
            FROM file_catalog.GLOBAL_FILE_CATALOG g
            JOIN #scores s ON s.inv_id = g.INVENTORY_ID
        """)
        wrote = cur.rowcount or 0
        cur.execute("IF OBJECT_ID('tempdb..#scores') IS NOT NULL DROP TABLE #scores")
        raw.commit()
        summary["scored"] = wrote
    except Exception as e:
        raw.rollback()
        return {"error": f"bulk write-back failed: {e}"}
    finally:
        raw.close()

    # 4. tallies (same status buckets as the original)
    for _, status, _ in results:
        if status == "SUCCESS":
            summary["success"] += 1
        elif status == "PARTIAL":
            summary["partial"] += 1
        elif status == "EMPTY":
            summary["empty"] += 1
        elif status == "FAILED":
            summary["failed"] += 1
            summary["errors"] += 1

    return summary

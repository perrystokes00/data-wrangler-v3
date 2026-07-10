"""
binary_curve_stage.py
=====================
Parallel CURVE/TRACE data extraction for binary well-log & seismic files.

WHY THIS EXISTS
---------------
extract_core._extract_fields() reads these files HEADER-ONLY
(lasio.read(..., ignore_data=True), dlisio header, segy header) — fast, which
is why every binary shows EXTRACTED='Y'. The actual CURVE DATA (the log
measurements, the trace samples) is deliberately skipped there. This stage does
the heavy part: it parses the full curve arrays and writes them into the
file_catalog.cat_well_log_curve mirror, which promote_catalog lifts into
dataview.dv_log_curve.

The parse is genuinely CPU-bound AND releases the GIL — lasio's numpy arrays,
dlisio/segyio's C extensions all drop the lock during the heavy read. So unlike
the pure-Python pdfplumber path (where threads gave nothing), this parallelizes
for real. We use a PROCESS pool, mirroring pipeline_run._extract_one_proc:

    parse  → in worker PROCESSES (no DB, picklable, libs imported per-worker)
    write  → in the PARENT, batched executemany into cat_well_log_curve

The DB engine never enters a worker (can't be pickled); workers return plain
row dicts, the parent does every write.

SCOPE: LAS first (ASCII, simplest, and you expect many). The dispatch is
keyed by extension so DLIS / LIS / SEGY slot in behind the same harness once
the LAS path is proven — each just needs its own _parse_<fmt>() returning the
same row shape.

ROW SHAPE returned per file:
    {"fpath", "uwi", "inventory_id", "curves": [ {curve rows...} ], "error"}
where each curve row is a dict ready for capture() into cat_well_log_curve.
"""
from __future__ import annotations

import os


# ── module-level process worker (must be top-level so it pickles) ────────────
def _parse_one_proc(arg):
    """ProcessPoolExecutor worker: full curve-data parse of ONE binary file.

    arg = (fpath, fext, uwi, inventory_id). Pure parse, NO DB — the parent
    writes. Libraries imported lazily inside so each spawned worker loads them
    once and the parent process stays light. Returns a result dict.
    """
    fpath, fext, uwi, inventory_id = arg
    import time as _time
    t0 = _time.monotonic()
    res = {"fpath": fpath, "fext": fext, "uwi": uwi,
           "inventory_id": inventory_id, "curves": [], "n": 0,
           "elapsed_s": 0.0, "error": None}
    try:
        ext = (fext or "").lower()
        if ext == ".las":
            res["curves"] = _parse_las_curves(fpath)
        elif ext in (".dlis", ".dlf", ".dis"):
            res["curves"] = _parse_dlis_curves(fpath)
        elif ext == ".lis":
            res["curves"] = _parse_lis_curves(fpath)
        # SEGY is header-only by design (no trace data) — handled by the
        # existing extract stage, not here.
        else:
            res["error"] = f"no curve parser for {ext}"
        res["n"] = len(res["curves"])
    except Exception as e:                       # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
    res["elapsed_s"] = _time.monotonic() - t0
    return res


def _parse_las_curves(fpath: str) -> list:
    """Full LAS curve-data parse → one row per (curve, depth-sample).

    Mirrors extract_core's LAS read but WITHOUT ignore_data, so the per-curve
    sample arrays are loaded. Returns a list of cat_well_log_curve-shaped dicts.
    The depth curve (first curve / index) keys every sample; each non-depth
    curve contributes its value at that depth.

    Row shape (capture() keeps only columns that exist in the mirror):
        curve_id, curve_mnem, curve_unit, sample_depth, depth_ouom,
        curve_value, active_ind, row_created_by, row_created_date
    """
    import lasio
    import uuid as _uuid
    from datetime import datetime as _dt

    las = lasio.read(fpath)          # FULL read — curve arrays included
    ts  = _dt.now().strftime("%Y-%m-%d %H:%M:%S")

    curves = list(las.curves)
    if not curves:
        return []

    # first curve is the index (depth/time); the rest are log measurements
    depth = None
    try:
        depth = las.index
    except Exception:
        depth = curves[0].data if curves else None
    if depth is None:
        return []

    rows = []
    depth_unit = (curves[0].unit or "ft") if curves else "ft"
    for c in curves[1:]:
        mnem = c.mnemonic
        unit = c.unit or ""
        cid  = _uuid.uuid4().hex[:40].upper()
        data = c.data
        n = min(len(depth), len(data))
        for i in range(n):
            d = depth[i]
            v = data[i]
            # skip null/NaN samples — lasio fills with the LAS NULL (e.g. -999.25)
            try:
                if v is None:
                    continue
                fv = float(v)
                if fv != fv:                     # NaN
                    continue
            except (TypeError, ValueError):
                continue
            try:
                fd = float(d)
                if fd != fd:
                    continue
            except (TypeError, ValueError):
                continue
            rows.append({
                "curve_id":         cid,
                "curve_mnem":       mnem,
                "curve_unit":       unit,
                "sample_depth":     fd,
                "depth_ouom":       depth_unit,
                "curve_value":      fv,
                "active_ind":       "Y",
                "row_created_by":   "DataWrangler",
                "row_created_date": ts,
            })
    return rows


def _parse_dlis_curves(fpath: str) -> list:
    """Full DLIS curve-data parse → one row per (channel, depth-sample).

    Mirrors extract_core's DLIS read (dlisio.dlis.load). Uses frame.curves(),
    which returns a numpy STRUCTURED array with one named field per channel,
    all aligned on the frame index — the correct dlisio API (channels have no
    .name/.mnemonic; the dtype field names ARE the mnemonics). dlisio is a C
    extension and releases the GIL during the read, so this parallelizes.

    The frame's index field (frame.index) keys the samples; every other field
    contributes its value at that depth. Same row shape as LAS so the parent
    writer/seeding is identical. Array (multi-dim) channels are skipped.
    """
    import dlisio
    from dlisio import dlis as _dlis
    import uuid as _uuid
    import numpy as _np
    from datetime import datetime as _dt

    ts   = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    f, *tail = _dlis.load(fpath)
    lfs = [f] + list(tail)
    try:
        for lf in lfs:
            for fr in lf.frames:
                try:
                    arr = fr.curves()          # structured ndarray
                except Exception:
                    continue
                names = list(arr.dtype.names or [])
                if not names:
                    continue
                # index field: frame.index names it; else first field
                idx_name = getattr(fr, "index", None)
                if idx_name not in names:
                    idx_name = names[0]
                depth = arr[idx_name]
                # unit for the index channel, looked up by matching channel
                depth_unit = "ft"
                try:
                    for c in fr.channels:
                        if c.fingerprint and idx_name in str(c.fingerprint):
                            depth_unit = c.units or "ft"
                            break
                except Exception:
                    pass
                # unit lookup per field name (best effort)
                unit_by = {}
                try:
                    for c in fr.channels:
                        fp = str(getattr(c, "fingerprint", "") or "")
                        for nm in names:
                            if nm in fp:
                                unit_by[nm] = c.units or ""
                except Exception:
                    pass

                for nm in names:
                    if nm == idx_name:
                        continue
                    col = arr[nm]
                    if col.ndim != 1:          # array log → skip scalar store
                        continue
                    cid  = _uuid.uuid4().hex[:40].upper()
                    unit = unit_by.get(nm, "")
                    n = min(len(depth), len(col))
                    for i in range(n):
                        try:
                            fd = float(depth[i]); fv = float(col[i])
                            if fd != fd or fv != fv:
                                continue
                        except (TypeError, ValueError):
                            continue
                        rows.append({
                            "curve_id":         cid,
                            "curve_mnem":       nm,
                            "curve_unit":       unit,
                            "sample_depth":     fd,
                            "depth_ouom":       depth_unit,
                            "curve_value":      fv,
                            "active_ind":       "Y",
                            "row_created_by":   "DataWrangler",
                            "row_created_date": ts,
                        })
    finally:
        for lf in lfs:
            try:
                lf.close()
            except Exception:
                pass
    return rows


def _parse_lis_curves(fpath: str) -> list:
    """Full LIS curve-data parse → one row per (curve, depth-sample).

    LIS goes through the project's lis_catalog module (same as extract_core's
    header read). We ask classify_lis for sample data if it exposes it; if the
    deployed lis_catalog only returns curve *metadata* (names/counts, no
    arrays), we return [] gracefully rather than guessing the binary layout —
    LIS curve-sample extraction then stays a known gap to wire when lis_catalog
    grows a sample API. (Header identity/curve names are already captured by the
    extract stage, so nothing is lost; only the per-sample values wait.)
    """
    import uuid as _uuid
    from datetime import datetime as _dt
    try:
        from modules.lis_catalog import classify_lis
    except ImportError:
        from lis_catalog import classify_lis

    ts   = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    cl = classify_lis(fpath)
    # Preferred: a sample-bearing API if lis_catalog provides one. Tolerate
    # several likely shapes without hard-coding one that may not exist.
    samples = (cl.get("samples") or cl.get("curve_data")
               or cl.get("data") or None)
    if not samples:
        # metadata-only deployment → no per-sample values available here
        return []

    depth_unit = cl.get("depth_ouom") or "ft"
    # Expected shape: {"DEPTH":[...], "GR":[...], ...} or
    #                 [{"depth":d, "mnem":m, "unit":u, "value":v}, ...]
    if isinstance(samples, dict):
        depth = samples.get("DEPTH") or samples.get("DEPT") or None
        if depth is None:
            return []
        for mnem, vals in samples.items():
            if mnem in ("DEPTH", "DEPT"):
                continue
            cid = _uuid.uuid4().hex[:40].upper()
            n = min(len(depth), len(vals))
            for i in range(n):
                try:
                    fd = float(depth[i]); fv = float(vals[i])
                    if fd != fd or fv != fv:
                        continue
                except (TypeError, ValueError):
                    continue
                rows.append({
                    "curve_id": cid, "curve_mnem": mnem, "curve_unit": "",
                    "sample_depth": fd, "depth_ouom": depth_unit,
                    "curve_value": fv, "active_ind": "Y",
                    "row_created_by": "DataWrangler", "row_created_date": ts,
                })
    elif isinstance(samples, list):
        # list of per-sample dicts
        _cid_by_mnem: dict = {}
        for s in samples:
            try:
                fd = float(s.get("depth")); fv = float(s.get("value"))
                if fd != fd or fv != fv:
                    continue
            except (TypeError, ValueError):
                continue
            mnem = s.get("mnem") or s.get("curve") or "CURVE"
            cid = _cid_by_mnem.setdefault(mnem, _uuid.uuid4().hex[:40].upper())
            rows.append({
                "curve_id": cid, "curve_mnem": mnem,
                "curve_unit": s.get("unit") or "",
                "sample_depth": fd, "depth_ouom": depth_unit,
                "curve_value": fv, "active_ind": "Y",
                "row_created_by": "DataWrangler", "row_created_date": ts,
            })
    return rows
def run_binary_curve_stage(engine, dialect="mssql", *, workers=8,
                           exts=None, per_file_timeout=120, log=print):
    """Parse full curve data for binary log files in parallel, write curves to
    file_catalog.cat_well_log_curve.

    Selects catalogued LAS (and later DLIS/LIS/SEGY) files with a resolved UWI,
    parses each in a worker PROCESS (full curve data), and batch-writes the
    resulting curve rows in the parent via capture(). Idempotent per file —
    capture() replaces this file's rows scoped to INVENTORY_ID.

    Returns {"curve_files", "curve_rows", "curve_ok", "curve_by_ext"}.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
    from sqlalchemy import text as _t

    try:
        from catalog_capture import capture, reset_replace_state
    except Exception:
        from modules.catalog_capture import capture, reset_replace_state

    if exts is None:
        # LAS only by default — it's the proven path. DLIS/LIS are opt-in via
        # --curve-exts (e.g. ".las .dlis .lis") until validated on real files,
        # because a malformed DLIS can make dlisio block at the C level. The
        # per-file timeout guards the stage, but defaulting to the safe path
        # means an unproven format can't surprise a production run.
        exts = [".las"]
    ext_list = ",".join(f"'{e}'" for e in exts)

    with engine.connect() as con:
        files = con.execute(_t(f"""
            SELECT g.FILE_PATH, g.FILE_EXT, g.MATCHED_UWI, g.INVENTORY_ID,
                   g.FILE_NAME
              FROM file_catalog.GLOBAL_FILE_CATALOG g
             WHERE g.FILE_EXT IN ({ext_list})
               AND ISNULL(g.FLAG_DELETE, 'N') <> 'Y'
               AND g.DUPLICATE_GROUP IS NULL
             ORDER BY g.FILE_NAME
        """)).fetchall()

    total = len(files)
    log(f"[curve] {total:,} binary log file(s) → full curve parse "
        f"({workers} workers)…")
    if total == 0:
        return {"curve_files": 0, "curve_rows": 0, "curve_ok": 0,
                "curve_by_ext": {}}

    # Resolve the curve key per file. LAS normally carries a MATCHED_UWI. DLIS/
    # LIS frequently DON'T (their identity is the filename → well_name), so when
    # MATCHED_UWI is blank we assign a DETERMINISTIC synthetic UWI from the
    # filename stem: 'FN_' + sha1(stem)[:14]. Deterministic so a re-run keys to
    # the same well and capture()'s INVENTORY_ID-scoped replace stays idempotent.
    # NOTE: this is a TESTING key to prove the parse path end-to-end; real
    # identity (resolve filename→existing dv_well, or create a dv_well) is a
    # follow-up. These synthetic-UWI curves will HOLD at promote until a matching
    # dv_well exists — expected for now.
    import hashlib as _hashlib
    def _curve_uwi(matched, fname):
        m = (matched or "").strip()
        if m:
            return m
        stem = os.path.splitext(fname or "")[0] or "UNKNOWN"
        return "FN_" + _hashlib.sha1(stem.upper().encode("utf-8")).hexdigest()[:14].upper()

    args = [(r[0], str(r[1] or "").lower(),
             _curve_uwi(r[2], r[4]), r[3])
            for r in files]

    # parse in PROCESSES; fall back to threads if a process pool can't start
    # (e.g. odd Windows env) — the C-extension GIL release still helps threads.
    def _mk_pool():
        try:
            return ProcessPoolExecutor(max_workers=max(1, workers)), "process"
        except Exception as e:
            log(f"[curve] process pool unavailable ({type(e).__name__}); "
                f"using threads")
            return ThreadPoolExecutor(max_workers=max(1, workers)), "thread"

    pool, mode = _mk_pool()
    log(f"[curve] {mode} workers — first chunk warms up the parsers…")

    ok = rows_total = 0
    by_ext: dict = {}
    try:
        futs = {pool.submit(_parse_one_proc, a): a for a in args}
        for fut in as_completed(futs):
            a = futs[fut]
            fpath, fext, uwi, inv = a
            fname = os.path.basename(fpath)
            try:
                # Per-file timeout: a malformed binary (esp. DLIS) can make the
                # parser block at the C level. Without this, one hung file would
                # stall the whole stage (the as_completed loop would wait on it
                # forever). On timeout we abandon that file and move on. Note:
                # in a PROCESS pool the worker process is still alive but
                # orphaned; it's reclaimed at pool shutdown. Thread mode can't
                # kill the thread, but at least the stage continues.
                r = fut.result(timeout=per_file_timeout)
            except Exception as e:
                etype = type(e).__name__
                log(f"  [x] {fname}: abandoned ({etype}: "
                    f"{str(e)[:120]}) — likely a slow/malformed {fext}")
                b = by_ext.setdefault(fext, {"n": 0, "rows": 0, "secs": 0.0})
                b["n"] += 1
                continue

            # per-ext timing tally
            b = by_ext.setdefault(fext, {"n": 0, "rows": 0, "secs": 0.0})
            b["n"] += 1
            b["secs"] += r.get("elapsed_s", 0.0)

            if r.get("error"):
                log(f"  [x] {fname}: {str(r['error'])[:300]}")
                continue
            curves = r.get("curves") or []
            if not curves:
                continue

            # WRITE in the parent (serial), batched by capture()'s executemany.
            reset_replace_state()
            try:
                n = capture(engine, "cat_well_log_curve", curves,
                            uwi=uwi, inventory_id=inv,
                            source_path=fpath, source="CURVE_LOADER")
                rows_total += n
                b["rows"] += n
                if n:
                    ok += 1
            except Exception as e:
                log(f"  [x] {fname}: write failed: {str(e)[:300]}")
    finally:
        pool.shutdown(wait=True)

    # readable per-ext summary
    summary = {ext: {"files": v["n"], "rows": v["rows"],
                     "secs": round(v["secs"], 1)}
               for ext, v in by_ext.items()}
    log(f"[curve] wrote {rows_total:,} curve sample(s) from {ok:,}/{total:,} "
        f"file(s)")
    return {"curve_files": total, "curve_rows": rows_total, "curve_ok": ok,
            "curve_by_ext": summary}

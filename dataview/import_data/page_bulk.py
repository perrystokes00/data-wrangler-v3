"""
page_bulk.py  —  Data Wrangler · Batch Loader
===================================================
Queue-based batch loader. Each job is a CSV file mapped to a target
table. Mappings are resolved automatically from the fingerprint cache.

Supports:
  - Manual trigger (Run Queue Now button)
  - File watcher (monitors a folder for new CSVs)
  - Windows Task Scheduler integration (via bulk_runner.py)
"""

import json
import os
import pathlib
import threading
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from dataview.core.ui_helpers import shdr, mrow

# ── Paths ──────────────────────────────────────────────────────────────────
_BASE_DIR    = pathlib.Path(__file__).parent
_QUEUE_FILE  = _BASE_DIR / "bulk_queue.json"
_HISTORY_FILE= _BASE_DIR / "bulk_history.json"
_FK_SEED_LOG = _BASE_DIR / "bulk_fk_seed.log"


def _fk_log(msg: str):
    """Append a timestamped line to the FK seed log file."""
    from datetime import datetime as _dt
    ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(_FK_SEED_LOG, "a", encoding="utf-8") as _f:
            _f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass
_WATCHER_FILE= _BASE_DIR / "bulk_watcher.json"

# Module-level FK introspection cache — avoids re-querying sys catalog per job
_fk_intro_cache: dict = {}


# ═══════════════════════════════════════════════════════════════════════════
# QUEUE / HISTORY HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _load_queue() -> list[dict]:
    if _QUEUE_FILE.exists():
        try:
            return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def _save_queue(q: list[dict]) -> None:
    # Strip any non-serializable keys before saving
    _safe = []
    for job in q:
        _j = {k: v for k, v in job.items() if k != "last_result"}
        if "last_result" in job:
            _lr = job["last_result"]
            if isinstance(_lr, dict):
                _j["last_result"] = {k: v for k, v in _lr.items() if k != "job"}
        _safe.append(_j)
    _QUEUE_FILE.write_text(json.dumps(_safe, indent=2), encoding="utf-8")

def _load_history() -> list[dict]:
    if _HISTORY_FILE.exists():
        try:
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def _load_watcher_cfg() -> dict:
    if _WATCHER_FILE.exists():
        try:
            return json.loads(_WATCHER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"folder": "", "enabled": False, "pattern": "*.csv"}

def _save_watcher_cfg(cfg: dict) -> None:
    _WATCHER_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# FINGERPRINT HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _detect_fingerprint(file_path: str, target_table: str) -> tuple[str | None, int]:
    """
    Read the CSV header and compute fingerprint.
    Tries pipeline fingerprint first, then RTM fingerprint as fallback.
    Returns (fingerprint, n_restored) or (None, 0) if not in cache.
    """
    try:
        import hashlib as _hl
        import csv as _csv
        from dataview.import_data.mapping import mapping_fingerprint, _load_cache
        from dataview.import_data.staging import _sanitize_col, _dedupe_cols

        # Read header with delimiter auto-detection (same as staging.py)
        with open(file_path, encoding="utf-8-sig", newline="") as _f:
            _sample = _f.read(4096)
        # Detect delimiter — prefer | over comma
        _first_line = _sample.split('\n')[0] if '\n' in _sample else _sample
        _counts = {d: _first_line.count(d) for d in ('|', '\t', ',', ';')}
        _delim = next((d for d in ('|', '\t', ';', ',') if _counts[d] > 0), ',')

        with open(file_path, encoding="utf-8-sig", newline="") as _f:
            _reader = _csv.reader(_f, delimiter=_delim)
            _raw_headers = next(_reader)
        _raw_headers = [h.strip() for h in _raw_headers]
        # Sanitize same way as staging.py
        src_cols = _dedupe_cols([_sanitize_col(h) for h in _raw_headers])
        while src_cols and src_cols[-1] in ('', 'col'):
            src_cols.pop()

        cache = _load_cache()

        # Strategy 1 — pipeline fingerprint (raw CSV cols, no _batch_loaded_at)
        fp = mapping_fingerprint(target_table, src_cols)
        saved = cache.get(fp, {})
        n_cols = sum(1 for v in saved.values()
                     if isinstance(v, dict) and v.get("source_col", "").strip())
        if n_cols > 0:
            return fp, n_cols

        # Strategy 2 — RTM fingerprint
        _rtm_key = f"RTM:{target_table.upper()}|{','.join(sorted(c.upper() for c in src_cols))}"
        _rtm_fp  = "RTM_" + _hl.sha256(_rtm_key.encode()).hexdigest()[:16]
        saved_rtm = cache.get(_rtm_fp, [])
        n_rtm = sum(1 for r in saved_rtm
                    if isinstance(r, dict) and r.get("Source Column","") and
                    r.get("Source Column","") != "— skip —")
        if n_rtm > 0:
            return _rtm_fp, n_rtm

        return fp, 0
    except Exception:
        return None, 0


# ═══════════════════════════════════════════════════════════════════════════
# JOB RUNNER  (called from UI and from bulk_runner.py)
# ═══════════════════════════════════════════════════════════════════════════


def _run_seed_job(job: dict, engine) -> dict:
    """
    Bulk seed CSV into a PPDM reference table.
    Uses a temp table + single INSERT WHERE NOT EXISTS — no row-by-row loop.
    """
    import csv as _csv
    import time as _time
    import uuid as _uuid
    from sqlalchemy import text as _t
    from dataview.core.db import _detect_dialect as _dd

    t0        = _time.time()
    file_path = job.get("file_path", "")
    table     = job.get("target_table", "").upper()
    pk_cols   = [c.upper() for c in job.get("pk_columns", [])]
    mode      = job.get("mode", "insert")

    try:
        dialect   = _dd(engine)
        is_oracle = dialect == "oracle"
        is_sf     = dialect == "snowflake"

        if is_oracle or is_sf:
            q = lambda n: f'"{n.upper()}"'
            try:
                with engine.connect() as _c:
                    sch = _c.execute(_t(
                        "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                    )).scalar() or "PPDM"
            except Exception:
                sch = "PPDM"
            tgt       = f'"{sch}"."{table}"'
            guid_expr = "RAWTOHEX(SYS_GUID())" if is_oracle else "UUID_STRING()"
            date_expr = ("SYS_EXTRACT_UTC(SYSTIMESTAMP)" if is_oracle
                         else "CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())")
            date_low  = "TO_DATE('1900-01-01','YYYY-MM-DD')"
            date_high = "TO_DATE('2099-12-31','YYYY-MM-DD')"
        else:
            q         = lambda n: f"[{n}]"
            tgt       = f"[dbo].[{table}]"
            guid_expr = "NEWID()"
            date_expr = "GETUTCDATE()"
            date_low  = "CAST('1900-01-01' AS DATETIME2)"
            date_high = "CAST('2099-12-31' AS DATETIME2)"

        # ── Read CSV ──────────────────────────────────────────────────
        with open(file_path, newline="", encoding="utf-8-sig") as fh:
            rows = list(_csv.DictReader(fh))
        if not rows:
            return {"ok": True, "rows_inserted": 0, "rows_skipped": 0,
                    "message": "Empty file", "duration_s": 0}

        # ── Get DB column metadata ────────────────────────────────────
        _col_maxlens = {}
        with engine.connect() as _c:
            if is_oracle or is_sf:
                _meta = _c.execute(_t(
                    "SELECT column_name, character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE UPPER(table_name) = :tbl"
                ), {"tbl": table}).fetchall()
            else:
                _meta = _c.execute(_t(
                    "SELECT c.name, c.max_length "
                    "FROM sys.columns c "
                    "JOIN sys.tables t ON t.object_id = c.object_id "
                    "WHERE UPPER(t.name) = :tbl"
                ), {"tbl": table.upper()}).fetchall()
            db_cols = set()
            for _cn, _ml in _meta:
                db_cols.add(_cn.upper())
                if _ml and int(_ml) > 0:
                    _col_maxlens[_cn.upper()] = int(_ml)

        # ── Determine data and audit cols ─────────────────────────────
        _AUDIT_BASE  = {"ROW_CREATED_BY", "ROW_CHANGED_BY", "ROW_CREATED_DATE",
                        "ROW_CHANGED_DATE", "ROW_EFFECTIVE_DATE", "ROW_EXPIRY_DATE",
                        "ROW_SOURCE", "PPDM_GUID", "ACTIVE_IND"}
        _SKIP_ALWAYS = {"SOURCE_FILE", "TIMESTAMP", "BATCH_ID"}
        _source_is_pk = "SOURCE" in [p.upper() for p in pk_cols]
        _AUDIT = _AUDIT_BASE if _source_is_pk else _AUDIT_BASE | {"SOURCE"}

        csv_cols  = [c.upper() for c in rows[0].keys()]
        data_cols = [c for c in csv_cols
                     if c in db_cols and c not in _AUDIT and c not in _SKIP_ALWAYS]

        if not data_cols:
            return {"ok": False, "rows_inserted": 0, "rows_skipped": 0,
                    "message": f"No matching columns found in {table}",
                    "duration_s": round(_time.time() - t0, 1)}
        if not pk_cols:
            pk_cols = [data_cols[0]]

        audit_vals = {
            "ACTIVE_IND":         "'Y'",
            "PPDM_GUID":          guid_expr,
            "ROW_CREATED_BY":     "'PPDM_LOADER'",
            "ROW_CHANGED_BY":     "'PPDM_LOADER'",
            "ROW_CREATED_DATE":   date_expr,
            "ROW_CHANGED_DATE":   date_expr,
            "ROW_EFFECTIVE_DATE": date_low,
            "ROW_EXPIRY_DATE":    date_high,
        }
        if "SOURCE" in db_cols and not _source_is_pk:
            audit_vals["SOURCE"] = "'PPDM_LOADER'"
        audit_in_db = {k: v for k, v in audit_vals.items() if k in db_cols}

        # ── Filter and clean rows ─────────────────────────────────────
        clean_rows = []
        skipped = 0
        for row in rows:
            # Skip if any PK col is blank
            if any(not str(row.get(pk, row.get(pk.lower(), ""))).strip()
                   for pk in pk_cols):
                skipped += 1
                continue
            clean = {}
            for col in data_cols:
                raw = row.get(col, row.get(col.lower(), ""))
                val = str(raw).strip() if raw not in (None, "NULL", "null", "") else None
                if val and col in _col_maxlens:
                    val = val[:_col_maxlens[col]]
                clean[col] = val
            clean_rows.append(clean)

        if not clean_rows:
            return {"ok": True, "rows_inserted": 0, "rows_skipped": skipped,
                    "message": f"Seed: 0 inserted, {skipped} skipped (all blank PKs)",
                    "duration_s": round(_time.time() - t0, 1)}

        # ── Bulk load into temp table then INSERT WHERE NOT EXISTS ─────
        tmp = f"#seed_{_uuid.uuid4().hex[:8]}"  # unique temp table name
        col_defs  = ", ".join(f"{q(c)} NVARCHAR({_col_maxlens.get(c, 4000)})"
                              for c in data_cols)
        tgt_cols  = ", ".join(q(c) for c in data_cols)
        audit_tgt = ", ".join(q(k) for k in audit_in_db)
        audit_src = ", ".join(v for v in audit_in_db.values())
        src_cols  = ", ".join(f"src.{q(c)}" for c in data_cols)
        ne_clause = " AND ".join(
            f"tgt.{q(pk)} = src.{q(pk)}" for pk in pk_cols
        )

        with engine.begin() as _c:
            # Create temp table
            _c.execute(_t(f"CREATE TABLE [{tmp}] ({col_defs})"))

            # Bulk insert all rows into temp table
            insert_tmp = (
                f"INSERT INTO [{tmp}] ({tgt_cols}) "
                f"VALUES ({', '.join(f':{c.lower()}' for c in data_cols)})"
            )
            _c.execute(_t(insert_tmp), [
                {c.lower(): r[c] for c in data_cols} for r in clean_rows
            ])

            # Single INSERT WHERE NOT EXISTS from temp → target
            if mode == "upsert":
                upd_cols = [c for c in data_cols if c not in pk_cols]
                upd_set  = ", ".join(f"tgt.{q(c)} = src.{q(c)}" for c in upd_cols)
                sql_ins = (
                    f"MERGE {tgt} AS tgt "
                    f"USING [{tmp}] AS src ON ({ne_clause}) "
                    f"WHEN MATCHED THEN UPDATE SET {upd_set} "
                    f"WHEN NOT MATCHED THEN INSERT ({tgt_cols}, {audit_tgt}) "
                    f"VALUES ({src_cols}, {audit_src});"
                )
            else:
                sql_ins = (
                    f"INSERT INTO {tgt} ({tgt_cols}, {audit_tgt}) "
                    f"SELECT {src_cols}, {audit_src} "
                    f"FROM [{tmp}] src "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {tgt} tgt WHERE {ne_clause})"
                )
            result   = _c.execute(_t(sql_ins))
            inserted = result.rowcount if result.rowcount >= 0 else len(clean_rows)
            skipped += len(clean_rows) - inserted

            # Drop temp table
            _c.execute(_t(f"DROP TABLE [{tmp}]"))

        dur = round(_time.time() - t0, 1)
        return {"ok": True, "rows_inserted": inserted, "rows_skipped": skipped,
                "message": f"Seed: {inserted} inserted, {skipped} skipped",
                "duration_s": dur}

    except Exception as e:
        return {"ok": False, "rows_inserted": 0, "rows_skipped": 0,
                "message": f"Seed job error: {e}",
                "duration_s": round(_time.time() - t0, 1)}

def run_job(job: dict, engine, ppdm_schema, progress_cb=None, cancel_flag=None) -> dict:
    """
    Execute a single batch load job end-to-end.

    job keys: file_path, target_table, mode ('insert'|'merge')
    Returns result dict with: ok, rows_inserted, rows_skipped,
                               rows_error, message, duration_s
    """
    from dataview.import_data.staging   import ingest_file, load_to_staging
    from dataview.import_data.mapping   import (build_mapping, mapping_fingerprint,
                                   restore_mapping_from_disk)
    from dataview.import_data.normalize import normalize_server
    from dataview.core.fk        import introspect_fk_constraints, check_fk_violations
    from dataview.core.fk_entity import is_reference_table, build_fk_graph
    from dataview.core.validate  import validate
    from dataview.import_data.promote   import promote_server, promote_merge

    # ── Seed mode: direct CSV → table insert, no pipeline ──────────────
    if job.get("seed_mode"):
        return _run_seed_job(job, engine)

    t0 = time.time()
    _stage_times = {}

    def _cb(msg: str, pct: int = 0):
        _now = time.time()
        if _stage_times:
            _last = list(_stage_times.keys())[-1]
            _stage_times[_last] = round(_now - _stage_times[_last], 1)
        _stage_times[msg] = _now  # converted to duration on next _cb
        if progress_cb:
            progress_cb(msg, pct)

    # Stage definitions for card display: (name, start_pct, end_pct)
    _STAGES = [
        ("Ingest",   5),
        ("Stage",   15),
        ("Normalize",30),
        ("Map",     40),
        ("FK Check",55),
        ("Validate",70),
        ("Promote", 85),
    ]

    try:
        file_path    = job["file_path"]
        target_table = job["target_table"]
        mode         = job.get("mode", "insert")

        if not pathlib.Path(file_path).exists():
            return {"ok": False, "message": f"File not found: {file_path}",
                    "rows_inserted": 0, "rows_skipped": 0, "rows_error": 0,
                    "duration_s": 0}

        # ── Dialect detection ────────────────────────────────────────────
        from dataview.core.db import get_dialect as _bulk_gd
        _d         = _bulk_gd(engine)
        _is_oracle = (_d.name == "oracle")
        if _is_oracle:
            try:
                from sqlalchemy import text as _t2
                with engine.connect() as _sc:
                    _ora_schema = _sc.execute(_t2(
                        _d.current_schema_sql()
                    )).scalar() or "PERRY"
            except Exception:
                _ora_schema = "PERRY"
        else:
            _ora_schema = "dbo"
        _dbo = _ora_schema
        _q   = _d.quote
        _tq  = _d.qualified

        # ── 1. Ingest ───────────────────────────────────────────────────
        _cb("Ingest", 5)
        import pandas as _pd
        # Read just the header to get column names
        _hdr = _pd.read_csv(file_path, nrows=0)
        _src_cols = list(_hdr.columns)

        # ── 2. Load to staging ──────────────────────────────────────────
        _cb("Stage", 15)
        from sqlalchemy import text as _t
        import hashlib as _sh
        stg_schema = _ora_schema if _is_oracle else "stg"
        _fp_name   = pathlib.Path(file_path).stem
        stg_table  = ("RAW_" if _is_oracle else "raw_") + _sh.sha256(_fp_name.encode()).hexdigest()[:8]

        if _is_oracle:
            # Oracle: use staging.py Oracle path (executemany)
            raw    = pathlib.Path(file_path).read_bytes()
            ingest = ingest_file(raw, pathlib.Path(file_path).name)
            if not ingest.ok:
                return {"ok": False, "message": f"Staging failed: {ingest.message}",
                        "rows_inserted": 0, "rows_skipped": 0, "rows_error": 0,
                        "duration_s": round(time.time()-t0, 1)}
            sr = load_to_staging(engine, ingest, schema=stg_schema, table_name=stg_table)
            if not sr.ok:
                return {"ok": False, "message": f"Staging failed: {sr.message}",
                        "rows_inserted": 0, "rows_skipped": 0, "rows_error": 0,
                        "duration_s": round(time.time()-t0, 1)}
            stg_table = sr.table_name.split(".")[-1] if "." in (sr.table_name or "") else sr.table_name
            _use_bulk = False
        else:
            try:
                _col_defs = ", ".join(
                    f"[{c}] NVARCHAR(500)" for c in _src_cols
                ) + ", [_batch_loaded_at] DATETIME2 DEFAULT GETUTCDATE()"
                with engine.begin() as _con:
                    _con.execute(_t(
                        f"IF OBJECT_ID('[{stg_schema}].[{stg_table}]','U') IS NOT NULL "
                        f"DROP TABLE [{stg_schema}].[{stg_table}]"
                    ))
                    _con.execute(_t(
                        f"CREATE TABLE [{stg_schema}].[{stg_table}] ({_col_defs})"
                    ))
                    _bulk_sql = (
                        f"BULK INSERT [{stg_schema}].[{stg_table}] "
                        f"FROM '{file_path}' "
                        f"WITH (FORMAT='CSV', FIRSTROW=2, "
                        f"FIELDTERMINATOR=',', ROWTERMINATOR='0x0a', "
                        f"TABLOCK, CODEPAGE='65001')"
                    )
                    _con.execute(_t(_bulk_sql))
                    _con.execute(_t(
                        f"UPDATE [{stg_schema}].[{stg_table}] "
                        f"SET [_batch_loaded_at] = GETUTCDATE() "
                        f"WHERE [_batch_loaded_at] IS NULL"
                    ))
                _use_bulk = True
            except Exception as _bulk_err:
                _use_bulk = False
                raw    = pathlib.Path(file_path).read_bytes()
                ingest = ingest_file(raw, pathlib.Path(file_path).name)
                if not ingest.ok:
                    return {"ok": False, "message": f"Staging failed: {ingest.message}",
                            "rows_inserted": 0, "rows_skipped": 0, "rows_error": 0,
                            "duration_s": round(time.time()-t0, 1)}
                sr = load_to_staging(engine, ingest)
                if not sr.ok:
                    return {"ok": False, "message": f"Staging failed: {sr.message}",
                            "rows_inserted": 0, "rows_skipped": 0, "rows_error": 0,
                            "duration_s": round(time.time()-t0, 1)}
                stg_table = sr.table_name.split(".")[-1] if "." in (sr.table_name or "") else sr.table_name

        # ── 3. Get staged column names only — no full data pull ────────
        with engine.connect() as con:
            if _is_oracle:
                cols = list(con.execute(_t(
                    f'SELECT * FROM "{stg_schema}"."{stg_table.upper()}" WHERE 1=0')).keys())
            else:
                cols = list(con.execute(_t(
                    f"SELECT TOP 0 * FROM [{stg_schema}].[{stg_table}]")).keys())
        # Strip _batch_loaded_at — audit column, not part of any fingerprint key
        cols = [c for c in cols if c.lower() != "_batch_loaded_at"]
        df = _pd.DataFrame(columns=cols)

        # ── 4. Normalize — trim whitespace, uppercase codes, standardize dates ──
        _cb("Normalize", 25)
        try:
            col_types = {}
            if ppdm_schema and target_table:
                _tbl_def_norm = ppdm_schema.get_table(target_table)
                if _tbl_def_norm:
                    col_types = {c.column_name.lower(): c.data_type
                                 for c in _tbl_def_norm.columns}
            _norm_result = normalize_server(
                engine, stg_table, df, col_types,
                schema=stg_schema
            )
            if _norm_result.ok:
                _cb(f"Normalize: {_norm_result.message}", 25)
            else:
                _cb(f"Normalize warning: {_norm_result.message}", 25)
        except Exception as _norm_err:
            _cb(f"Normalize skipped: {_norm_err}", 25)

        # ── 5. Build mapping from fingerprint ───────────────────────────
        _cb("Map", 40)
        import hashlib as _hl2
        from dataview.import_data.mapping import _load_cache as _lc2
        target_cols = ppdm_schema.get_table(target_table).columns if ppdm_schema else []

        col_mapping = build_mapping(target_table, target_cols, list(df.columns))

        # Strategy 1 — pipeline fingerprint
        fp = mapping_fingerprint(target_table, list(df.columns))
        n_restored = restore_mapping_from_disk(col_mapping, fp)

        if n_restored == 0:
            # Strategy 2 — RTM fingerprint
            _rtm_key = (f"RTM:{target_table.upper()}|"
                        f"{','.join(sorted(c.upper() for c in df.columns))}")
            _rtm_fp  = "RTM_" + _hl2.sha256(_rtm_key.encode()).hexdigest()[:16]
            _cache   = _lc2()
            _rtm_saved = _cache.get(_rtm_fp, [])
            if _rtm_saved:
                # RTM cache stores rows: [{Target Column, Source Column, Transform, Constant}]
                for m in col_mapping.mapped:
                    for _row in _rtm_saved:
                        _tc = _row.get("Target Column", _row.get("PPDM Column","")).lstrip("🔑 ").strip()
                        if _tc.upper() == m.ppdm_col.upper():
                            _sc = _row.get("Source Column","")
                            if _sc and _sc != "— skip —" and _sc in df.columns:
                                m.source_col = _sc
                                m.transform  = _row.get("Transform","")
                                n_restored  += 1
                            break

        if n_restored == 0:
            _all_cols = sorted(c.upper() for c in df.columns)
            return {"ok": False,
                    "message": (
                        f"No saved mapping found for {target_table}. "
                        f"Fingerprint: {fp[:8]}… "
                        f"Key cols ({len(_all_cols)}): {', '.join(_all_cols)}. "
                        f"Use Quick Fingerprint with this exact file to create a matching fingerprint."
                    ),
                    "rows_inserted": 0, "rows_skipped": 0, "rows_error": 0,
                    "duration_s": round(time.time()-t0, 1)}

        # ── 5b. Auto-seed FK parent tables from staging data ───────────
        _cb("FK Seed", 50)
        _fks_seed_log = []
        _fks_seed_err = None
        try:
            from sqlalchemy import text as _s5t
            from dataview.import_data.mapping import build_transform_sql as _s5bts
            _fk_log(f"=== FK Seed: {target_table} / {job.get('file_name','?')} ===")
            _s5_tbl_def = ppdm_schema.get_table(target_table) if ppdm_schema else None
            if _s5_tbl_def:
                _s5_seeded = set()
                # mapping lookup: ppdm_col -> (source_col, transform)
                _s5_mp = {
                    m.ppdm_col.upper(): (m.source_col, m.transform)
                    for m in col_mapping.mapped
                    if m.source_col and not m.auto_generated
                }
                _fk_log(f"  Mapped PPDM cols: {sorted(_s5_mp.keys())}")
                # Group FK cols by parent table (handles composite PKs)
                _s5_by_parent = {}
                for _fc in _s5_tbl_def.fk_columns:
                    if _fc.fk_table_name:
                        _s5_by_parent.setdefault(_fc.fk_table_name, []).append(
                            (_fc.fk_column_name, _fc.column_name))
                _fk_log(f"  Parent tables ({len(_s5_by_parent)}): {sorted(_s5_by_parent.keys())}")

                _s5_cache = _lc2()

                for _s5_pt, _s5_pairs in _s5_by_parent.items():
                    # Skip reference tables — user loads via RTM only
                    if any(_s5_pt.lower().startswith(p) for p in ('r_','ra_','rb_')):
                        _fk_log(f"  SKIP {_s5_pt}: reference table — load via RTM")
                        continue
                    if _s5_pt in _s5_seeded:
                        continue
                    # Only seed tables with an RTM fingerprint
                    _s5_has_rtm = any(
                        k.startswith("RTM_") and isinstance(v, list)
                        and any(
                            r.get("Target Column","").lstrip("\U0001f511 ").strip()
                             .lstrip("🔑 ").strip().upper()
                            == _s5_pairs[0][0].upper()
                            for r in v
                        )
                        for k, v in _s5_cache.items()
                    )
                    if not _s5_has_rtm:
                        _fk_log(f"  SKIP {_s5_pt}: no RTM fingerprint for pk={_s5_pairs[0][0]}")
                        _fks_seed_log.append(f"skip {_s5_pt}(pk={_s5_pairs[0][0]})")
                        # Route entity tables to RTM prompt
                        _entity_rtm_needed.append(_s5_pt)
                        continue
                    # Build pk_mappings: pk_col -> (src_col, xform)
                    _s5_pkm = {}
                    for _pk_col, _cc in _s5_pairs:
                        _m = _s5_mp.get(_cc.upper())
                        if _m:
                            _s5_pkm[_pk_col.upper()] = (_m[0], _m[1])
                    if not _s5_pkm:
                        _fk_log(f"  SKIP {_s5_pt}: pk cols {[p[1] for p in _s5_pairs]} not in mapping")
                        _fks_seed_log.append(f"skip {_s5_pt}:no_pk_map(cols={[p[1] for p in _s5_pairs]})")
                        continue
                    _fk_log(f"  FOUND {_s5_pt}: pkm={list(_s5_pkm.keys())} srcs={[v[0] for v in _s5_pkm.values()]}")
                    _fks_seed_log.append(f"found {_s5_pt}:pkm={list(_s5_pkm.keys())}")
                    # Get extra non-PK cols from RTM fingerprint
                    _s5_extra = {}
                    _s5_first_src = list(_s5_pkm.values())[0][0]
                    for _rk, _rv in _s5_cache.items():
                        if not _rk.startswith("RTM_") or not isinstance(_rv, list):
                            continue
                        _rtm_has_pk = any(
                            r.get("Target Column","").lstrip("🔑 ").strip().upper()
                            == list(_s5_pkm.keys())[0]
                            for r in _rv
                        )
                        if not _rtm_has_pk:
                            continue
                        # Collect non-PK cols from this RTM fingerprint
                        _s5_par_def = ppdm_schema.get_table(_s5_pt) if ppdm_schema else None
                        _s5_par_cols = {c.column_name.upper()
                                        for c in _s5_par_def.columns} if _s5_par_def else set()
                        for _r in _rv:
                            _tc = _r.get("Target Column","").lstrip("🔑 ").strip().upper()
                            _sc = _r.get("Source Column","")
                            _xf = _r.get("Transform","— none —")
                            if _tc in _s5_pkm:
                                continue
                            if _sc and _sc != "— skip —" and _sc in df.columns and _tc in _s5_par_cols:
                                _s5_extra[_tc] = (_sc, "" if _xf == "— none —" else _xf)
                        break

                    # Build SQL parts
                    _s5_par_def = ppdm_schema.get_table(_s5_pt) if ppdm_schema else None
                    _s5_par_cols = {c.column_name.upper()
                                    for c in _s5_par_def.columns} if _s5_par_def else set()
                    if _is_oracle:
                        _s5_AUDIT = {
                            "SOURCE":             "'PPDM_LOADER'",
                            "ROW_CREATED_BY":     "'PPDM_LOADER'",
                            "ROW_CHANGED_BY":     "'PPDM_LOADER'",
                            "ROW_CREATED_DATE":   "SYS_EXTRACT_UTC(SYSTIMESTAMP)",
                            "ROW_CHANGED_DATE":   "SYS_EXTRACT_UTC(SYSTIMESTAMP)",
                            "ROW_EFFECTIVE_DATE": "TO_DATE('1900-01-01','YYYY-MM-DD')",
                            "ROW_EXPIRY_DATE":    "TO_DATE('2099-12-31','YYYY-MM-DD')",
                            "ACTIVE_IND":         "'Y'",
                            "PPDM_GUID":          "RAWTOHEX(SYS_GUID())",
                        }
                    else:
                        _s5_AUDIT = {
                            "SOURCE":             "'PPDM_LOADER'",
                            "ROW_CREATED_BY":     "'PPDM_LOADER'",
                            "ROW_CHANGED_BY":     "'PPDM_LOADER'",
                            "ROW_CREATED_DATE":   "GETUTCDATE()",
                            "ROW_CHANGED_DATE":   "GETUTCDATE()",
                            "ROW_EFFECTIVE_DATE": "CAST('1900-01-01' AS DATETIME2)",
                            "ROW_EXPIRY_DATE":    "CAST('2099-12-31' AS DATETIME2)",
                            "ACTIVE_IND":         "'Y'",
                            "PPDM_GUID":          "NEWID()",
                        }
                    _s5_sub  = []
                    _s5_tgt  = []
                    _s5_src  = []
                    _s5_ne   = []
                    def _s5_expr(col, xform):
                        """Build dialect-aware expression for Step 5b seeding."""
                        if _is_oracle:
                            _cq = _q(col.upper())
                            if xform in ("SHA1_40", "SHA1"):
                                return (f"UPPER(RAWTOHEX(DBMS_CRYPTO.HASH("
                                        f"UTL_RAW.CAST_TO_RAW(UPPER(TRIM({_cq}))),3)))")
                            elif xform == "SHA1_20":
                                return (f"SUBSTR(UPPER(RAWTOHEX(DBMS_CRYPTO.HASH("
                                        f"UTL_RAW.CAST_TO_RAW(UPPER(TRIM({_cq}))),3))),1,20)")
                            elif xform == "UPPER":
                                return f"UPPER(TRIM({_cq}))"
                            else:
                                return f"TRIM({_cq})"
                        else:
                            return _s5bts(col, xform)

                    # Get max lengths for PK cols to avoid truncation
                    _s5_maxlens = {}
                    if _s5_par_def:
                        for _col in _s5_par_def.columns:
                            _ml = (getattr(_col, 'max_length', None) or
                                   getattr(_col, 'maxlen', None) or
                                   getattr(_col, 'char_length', None) or
                                   getattr(_col, 'length', None))
                            if _ml and int(_ml) > 0:
                                _s5_maxlens[_col.column_name.upper()] = int(_ml)

                    for _pkc, (_psc, _pxf) in _s5_pkm.items():
                        _expr = _s5_expr(_psc, _pxf)
                        # Wrap with LEFT/SUBSTR to prevent truncation
                        _ml = _s5_maxlens.get(_pkc.upper())
                        if _ml and _pxf not in ("SHA1_40", "SHA1", "SHA1_20"):
                            if _is_oracle:
                                _expr = f"SUBSTR({_expr}, 1, {_ml})"
                            else:
                                _expr = f"LEFT({_expr}, {_ml})"
                        _s5_sub.append(f"{_expr} AS {_q(_pkc)}")
                        _s5_tgt.append(_q(_pkc))
                        _s5_src.append(f"src.{_q(_pkc)}")
                        _s5_ne.append(f"tgt.{_q(_pkc)} = src.{_q(_pkc)}")
                    for _ec, (_esc, _exf) in _s5_extra.items():
                        _expr = _s5_expr(_esc, _exf)
                        _s5_sub.append(f"{_expr} AS {_q(_ec)}")
                        _s5_tgt.append(_q(_ec))
                        _s5_src.append(f"src.{_q(_ec)}")
                    _s5_aud_tgt = [_q(k) for k in _s5_AUDIT if k in _s5_par_cols]
                    _s5_aud_val = [v for k, v in _s5_AUDIT.items() if k in _s5_par_cols]
                    if not _s5_tgt or not _s5_ne:
                        continue
                    _s5_filter = list(_s5_pkm.values())[0][0]
                    _s5_trim = f"{_q(_s5_filter)} IS NOT NULL" if _is_oracle else f"LTRIM(RTRIM({_q(_s5_filter)})) <> ''"
                    _s5_sql = " ".join([
                        f"INSERT INTO {_tq(_dbo, _s5_pt)}",
                        f"({", ".join(_s5_tgt + _s5_aud_tgt)})",
                        f"SELECT {", ".join(_s5_src + _s5_aud_val)}",
                        "FROM (",
                        f"SELECT DISTINCT {", ".join(_s5_sub)}",
                        f"FROM {_tq(stg_schema, stg_table)}",
                        f"WHERE {_q(_s5_filter)} IS NOT NULL",
                        f"AND {_s5_trim}",
                        ") src WHERE NOT EXISTS (",
                        f"SELECT 1 FROM {_tq(_dbo, _s5_pt)} tgt",
                        f"WHERE {" AND ".join(_s5_ne)}",
                        ")",
                    ])
                    try:
                        with engine.begin() as _s5c:
                            _fk_log(f"  SQL: {_s5_sql[:300]}")
                            _s5r = _s5c.execute(_s5t(_s5_sql))
                            _s5_msg = f"{_s5_pt}: +{_s5r.rowcount}" if _s5r.rowcount > 0 else f"{_s5_pt}: exists"
                            _fk_log(f"  RESULT {_s5_msg}")
                            _fks_seed_log.append(_s5_msg)
                            if progress_cb:
                                progress_cb(f"FK Seed {_s5_msg}", 52)
                        _s5_seeded.add(_s5_pt)
                    except Exception as _s5e:
                        _fk_log(f"  ERROR {_s5_pt}: {_s5e}")
                        _fks_seed_err = f"{_s5_pt} failed: {_s5e} SQL: {_s5_sql[:300]}"
        except Exception as _s5oe:
            _fks_seed_err = f"Step5b: {_s5oe}"

        # ── Step 5c: Oracle FK parent table seeding ─────────────────────────
        # Seeds ALL FK parent tables from staging using Oracle-native SQL.
        # Uses direct INSERT...SELECT to avoid connection pool stale read issues.
        if _is_oracle:
            try:
                from sqlalchemy import text as _s5ct
                from collections import defaultdict as _s5dd

                # Get all FK constraints — catalog fast path, live DB fallback
                _fk_by_parent = _s5dd(list)
                _s5c_cat_ok = False
                try:
                    import importlib as _s5c_il
                    _s5c_fkc = _s5c_il.import_module("modules.fk_catalog").get_catalog(engine)
                    if _s5c_fkc.available:
                        for _con in _s5c_fkc.get_fk_constraints(target_table.upper()):
                            _fkpt = _con["parent_table"].upper()
                            _fkps = _dbo.upper()
                            for _fkcc, _fkpk in zip(_con["child_cols"], _con["parent_cols"]):
                                _fk_by_parent[(_fkpt, _fkps)].append(
                                    (_fkcc.upper(), _fkpk.upper())
                                )
                        _s5c_cat_ok = True
                except Exception:
                    pass
                if not _s5c_cat_ok:
                    # Live DB fallback
                    with engine.connect() as _fkcon:
                        _fk_meta = _fkcon.execute(_s5ct(
                            "SELECT cc.column_name, rcon.table_name, rcon.owner, pc.column_name "
                            "FROM all_constraints con "
                            "JOIN all_cons_columns cc "
                            "  ON cc.constraint_name=con.constraint_name AND cc.owner=con.owner "
                            "JOIN all_constraints rcon "
                            "  ON rcon.constraint_name=con.r_constraint_name AND rcon.owner=con.r_owner "
                            "JOIN all_cons_columns pc "
                            "  ON pc.constraint_name=rcon.constraint_name AND pc.owner=rcon.owner "
                            "  AND pc.position=cc.position "
                            "WHERE con.constraint_type='R' "
                            "  AND con.table_name=:tbl AND con.owner=:sch "
                            "ORDER BY rcon.table_name, cc.position"
                        ), {"tbl": target_table.upper(), "sch": _dbo.upper()}).fetchall()
                    for _fkcc, _fkpt, _fkps, _fkpk in _fk_meta:
                        _fk_by_parent[(_fkpt.upper(), _fkps.upper())].append(
                            (_fkcc.upper(), _fkpk.upper())
                        )

                # Build mapping lookup
                _s5c_map = {}
                for _m in getattr(col_mapping, "mapped", []):
                    if _m.source_col and not getattr(_m, "auto_generated", False):
                        _xf = (getattr(_m, "transform", "") or "").upper()
                        _s5c_map[_m.ppdm_col.upper()] = (_m.source_col.upper(), _xf)

                _AUDIT_COLS = {"PPDM_GUID","ROW_CREATED_BY","ROW_CREATED_DATE",
                               "ROW_CHANGED_BY","ROW_CHANGED_DATE",
                               "ROW_EFFECTIVE_DATE","ROW_EXPIRY_DATE","ACTIVE_IND","SOURCE"}

                def _audit_v(c):
                    c = c.upper()
                    if c == "PPDM_GUID":    return "RAWTOHEX(SYS_GUID())"
                    if c == "ACTIVE_IND":   return "'Y'"
                    if c == "SOURCE":       return "'PPDM_LOADER'"
                    if "EFFECTIVE" in c:    return "TO_DATE('1900-01-01','YYYY-MM-DD')"
                    if "EXPIRY" in c:       return "TO_DATE('2099-12-31','YYYY-MM-DD')"
                    if "DATE" in c:         return "SYS_EXTRACT_UTC(SYSTIMESTAMP)"
                    return "'PPDM_LOADER'"

                _fk_log(f"  S5C map keys: {list(_s5c_map.keys())[:10]}")
                for (_fkpt, _fkps), _cpairs in _fk_by_parent.items():
                    # Skip reference tables — user loads via RTM only
                    if any(_fkpt.lower().startswith(p) for p in ('r_','ra_','rb_')):
                        _fk_log(f"  SKIP {_fkpt}: reference table — load via RTM")
                        continue
                    _pfull = f'"{_fkps}"."{_fkpt}"'
                    try:
                        # Find mapped child col
                        _src_col = None
                        _src_xf  = ""
                        _par_pk  = None
                        for _cc, _pk in _cpairs:
                            _fk_log(f"  S5C {_fkpt}: checking child_col={_cc} in map={_cc in _s5c_map}")
                            if _cc in _s5c_map:
                                _src_col, _src_xf = _s5c_map[_cc]
                                _par_pk = _pk
                                break
                        if not _src_col:
                            _fk_log(f"  S5C {_fkpt}: no mapping — skipped (cpairs={_cpairs})")
                            continue

                        # Compound PK guard — use catalog for FULL pk list
                        _s5c_full_pk = []
                        try:
                            if _s5c_cat_ok and _s5c_fkc.available:
                                _s5c_full_pk = _s5c_fkc.get_pk_cols(_fkpt)
                        except Exception:
                            pass
                        if not _s5c_full_pk:
                            _s5c_full_pk = [pk for _, pk in _cpairs]
                        _s5c_mapped_pks = {pk for cc, pk in _cpairs if cc in _s5c_map}
                        _s5c_missing_pks = [p for p in _s5c_full_pk
                                            if p not in _s5c_mapped_pks]
                        if _s5c_missing_pks:
                            _fk_log(f"  S5C {_fkpt}: compound PK incomplete — missing {_s5c_missing_pks}")
                            continue

                        # For compound PKs build multi-col INSERT
                        # Collect ALL mapped pk cols (not just the first one)
                        _s5c_pk_map = {pk: _s5c_map[cc]
                                       for cc, pk in _cpairs if cc in _s5c_map}

                        # Build value expression
                        _sq = f'"{_src_col.upper()}"'
                        if _src_xf in ("SHA1_40", "SHA1"):
                            _val_expr = (f"UPPER(RAWTOHEX(DBMS_CRYPTO.HASH("
                                         f"UTL_RAW.CAST_TO_RAW(UPPER(TRIM({_sq}))),3)))")
                        elif _src_xf == "UPPER":
                            _val_expr = f"UPPER(TRIM({_sq}))"
                        else:
                            _val_expr = f"TRIM({_sq})"

                        # Get parent table columns — catalog first, live DB fallback
                        _pmeta = {}
                        _pk_list = []
                        try:
                            if _s5c_cat_ok and _s5c_fkc.available:
                                _cat_meta = _s5c_fkc.get_col_meta(_fkpt)
                                _pmeta = {
                                    col: (info["type"].upper(), info["max_length"])
                                    for col, info in _cat_meta.items()
                                }
                                _pk_list = _s5c_fkc.get_pk_cols(_fkpt)
                        except Exception:
                            pass
                        if not _pmeta:
                            with engine.connect() as _pc:
                                _pmeta = {r[0].upper(): (r[1].upper(), int(r[2]) if r[2] else 4000)
                                          for r in _pc.execute(_s5ct(
                                              "SELECT column_name, data_type, char_length "
                                              "FROM all_tab_columns "
                                              "WHERE owner=:sch AND table_name=:tbl"
                                          ), {"sch": _fkps, "tbl": _fkpt}).fetchall()}
                        if not _pk_list:
                            with engine.connect() as _pc2:
                                _pk_list = [r[0].upper() for r in _pc2.execute(_s5ct(
                                    "SELECT cc.column_name FROM all_constraints con "
                                    "JOIN all_cons_columns cc "
                                    "  ON cc.constraint_name=con.constraint_name AND cc.owner=con.owner "
                                    "WHERE con.constraint_type='P' "
                                    "  AND con.table_name=:tbl AND con.owner=:sch "
                                    "ORDER BY cc.position"
                                ), {"tbl": _fkpt, "sch": _fkps}).fetchall()]
                        if not _pk_list:
                            _pk_list = [_par_pk]

                        # Build INSERT cols and values — compound PK aware
                        _ins_tgt = []
                        _ins_src = []
                        for _pkc in _pk_list:
                            _pmeta_c = _pmeta.get(_pkc, {})
                            _maxlen  = _pmeta_c[1] if isinstance(_pmeta_c, tuple) else 4000
                            # Use per-pk-col mapping if available (compound PK)
                            if _pkc in _s5c_pk_map:
                                _pkc_src, _pkc_xf = _s5c_pk_map[_pkc]
                                _sq_pkc = f'"{_pkc_src.upper()}"'
                                _sq_clean_pkc = (
                                    f"REPLACE(REPLACE(REPLACE(REPLACE({_sq_pkc},"
                                    f"CHR(9),''),CHR(13),''),CHR(10),''),' ','')"
                                )
                                if _pkc_xf in ("SHA1_40", "SHA1"):
                                    _pkc_expr = (f"UPPER(RAWTOHEX(DBMS_CRYPTO.HASH("
                                                 f"UTL_RAW.CAST_TO_RAW(UPPER(TRIM({_sq_clean_pkc}))),3)))")
                                elif _pkc_xf == "UPPER":
                                    _pkc_expr = f"UPPER(TRIM({_sq_pkc}))"
                                else:
                                    _pkc_expr = f"TRIM({_sq_pkc})"
                                _this_expr = (f"SUBSTR({_pkc_expr},1,{_maxlen})"
                                              if _maxlen < 4000 else _pkc_expr)
                            else:
                                _this_expr = (f"SUBSTR({_val_expr},1,{_maxlen})"
                                              if _maxlen < 4000 else _val_expr)
                            _ins_tgt.append(f'"{_pkc}"')
                            _ins_src.append(_this_expr)

                        # Add NOT NULL non-audit string cols — catalog first
                        _nn_cols = set()
                        try:
                            if _s5c_cat_ok and _s5c_fkc.available:
                                _nn_cols = set(_s5c_fkc.get_not_null_cols(_fkpt))
                        except Exception:
                            pass
                        if not _nn_cols:
                            with engine.connect() as _pc3:
                                _nn_cols = {r[0].upper() for r in _pc3.execute(_s5ct(
                                    "SELECT column_name FROM all_tab_columns "
                                    "WHERE owner=:sch AND table_name=:tbl AND nullable='N'"
                                ), {"sch": _fkps, "tbl": _fkpt}).fetchall()}

                        _ins_tgt_set = set(_ins_tgt)  # track to avoid duplicates
                        for _pcol, (_pdtype, _pmaxlen) in _pmeta.items():
                            if _pcol in set(_pk_list): continue
                            if _pcol in _AUDIT_COLS: continue
                            if f'"{_pcol}"' in _ins_tgt_set: continue  # skip duplicates
                            if _pcol in _nn_cols and _pdtype in ("VARCHAR2","NVARCHAR2","CHAR"):
                                _capped2 = (f"SUBSTR({_val_expr},1,{_pmaxlen})"
                                            if _pmaxlen < 4000 else _val_expr)
                                _ins_tgt.append(f'"{_pcol}"')
                                _ins_tgt_set.add(f'"{_pcol}"')
                                _ins_src.append(_capped2)

                        # Add audit cols
                        for _ac in _AUDIT_COLS:
                            if _ac in _pmeta:
                                _ins_tgt.append(f'"{_ac}"')
                                _ins_src.append(_audit_v(_ac))

                        # Build NOT EXISTS — cover ALL PK cols for compound key safety
                        _ne_sql = ("NOT EXISTS (SELECT 1 FROM {} EX WHERE {})".format(
                            _pfull,
                            " AND ".join(
                                'EX."{}" = {}'.format(_pk_list[i], _ins_src[i])
                                for i in range(len(_pk_list))
                            )
                        ))

                        _seed_sql = (
                            f"INSERT INTO {_pfull} ({','.join(_ins_tgt)}) "
                            f"SELECT DISTINCT {','.join(_ins_src)} "
                            f'FROM "{stg_schema}"."{stg_table.upper()}" STG '
                            f'WHERE TRIM({_sq}) IS NOT NULL '
                            f"AND {_ne_sql}"
                        )

                        with engine.begin() as _sc:
                            _sr = _sc.execute(_s5ct(_seed_sql))
                            _msg = f"{_fkpt.lower()}: +{_sr.rowcount}"
                            _fks_seed_log.append(_msg)
                            _fk_log(f"  REF SEED {_msg}")
                            if progress_cb:
                                progress_cb(f"FK Seed {_msg}", 53)
                            # Capture for audit CSV
                            if _sr.rowcount > 0:
                                try:
                                    with engine.connect() as _avc:
                                        _av_rows = [r[0] for r in _avc.execute(_s5ct(
                                            f'SELECT DISTINCT "{_src_col.upper()}" '
                                            f'FROM "{stg_schema}"."{stg_table.upper()}" '
                                            f'WHERE "{_src_col.upper()}" IS NOT NULL'
                                        )).fetchall()]
                                    # long_names = raw source values (before any hash transform)
                                    _is_sha1 = _src_xf in ("SHA1_40", "SHA1", "SHA1_20")
                                    _fk_seed_meta[_fkpt.lower()] = {
                                        "values":     _av_rows,
                                        "pk_col":     _par_pk,
                                        "src_col":    _src_col,
                                        "long_names": _av_rows if _is_sha1 else None,
                                    }
                                except Exception:
                                    pass

                    except Exception as _rse:
                        _fk_log(f"  REF SEED {_fkpt}: {str(_rse)[:80]}")

            except Exception as _s5ce:
                _fk_log(f"  STEP 5C ERROR: {_s5ce}")

                # ── 6. FK check — blocking on unresolved parent rows ───────────
        _cb("FK Check", 55)
        _fk_violations = []
        _fk_t = {}
        try:
            _fk_t0 = time.time()
            # Build FK constraints from schema JSON — only mapped columns, instant
            # Exclude known circular/structural tables that should never block
            _EXCL_FK = {
                'well_area','field_area','well_node','well_bore',
                'r_source','r_ppdm_row_quality','source_document',
                'ppdm_measurement_system','ppdm_quantity',
                'r_ppdm_uom_usage','ppdm_unit_of_measure',
                'strat_unit','strat_name_set',
            }
            if target_table.lower() in {'field','strat_unit','strat_name_set',
                                        'business_associate','area'}:
                _EXCL_FK.add(target_table.lower())

            _mapped_src = {m.ppdm_col.upper(): m.source_col
                           for m in col_mapping.mapped
                           if m.source_col and not m.auto_generated}
            _mapped_lower = {k.lower() for k in _mapped_src}
            _mapped_const = {
                m.ppdm_col.upper(): getattr(m, 'const_value', '')
                for m in col_mapping.mapped
                if getattr(m, 'const_value', '') and not getattr(m, 'auto_generated', False)
            }

            _check_constraints = []
            _ppdm_schema = ppdm_schema
            if _ppdm_schema:
                from dataview.core.fk import FKConstraint, FKColumn
                _tbl_def = _ppdm_schema.get_table(target_table)
                if _tbl_def:
                    _seen = set()
                    for _fc in _tbl_def.fk_columns:
                        # Include if source-mapped or constant-mapped
                        _fc_up = _fc.column_name.upper()
                        if _fc_up not in _mapped_src and _fc_up not in _mapped_const:
                            continue
                        _pt = _fc.fk_table_name
                        # Check all FK columns — nullable or not
                        # (nullable FKs will be nulled out at promote time if not satisfied,
                        #  but we still want to report and write missing values)
                        if not _pt or _pt.lower() in _EXCL_FK:
                            continue
                        if _pt.lower() == target_table.lower():
                            continue
                        _cname = f"FK_{target_table}_{_fc.column_name}"
                        if _cname not in _seen:
                            _seen.add(_cname)
                            _check_constraints.append(FKConstraint(
                                constraint_name=_cname,
                                child_table=target_table,
                                child_schema=_dbo,
                                parent_table=_pt,
                                parent_schema=_dbo,
                                columns=[FKColumn(
                                    fk_col=_fc.column_name,
                                    ref_col=_fc.fk_column_name,
                                    ordinal=1,
                                    nullable=not _fc.not_null,
                                )],
                            ))
            else:
                # Fallback to DB introspection
                _intro_key = target_table.lower()
                if _intro_key not in _fk_intro_cache:
                    _fk_intro_cache[_intro_key] = introspect_fk_constraints(
                        engine, target_table, schema=_dbo)
                intro = _fk_intro_cache[_intro_key]
                if intro.ok and intro.constraints:
                    # Also build constant value lookup from mapping
                    _mapped_const = {
                        m.ppdm_col.upper(): m.const_value
                        for m in col_mapping.mapped
                        if getattr(m, 'const_value', '') and not getattr(m, 'auto_generated', False)
                    }
                    _check_constraints = [
                        c for c in intro.constraints
                        if c.parent_table.lower() not in _EXCL_FK
                        and c.parent_table.lower() != target_table.lower()
                        and any(
                            _mapped_src.get(col.fk_col.upper()) or
                            _mapped_const.get(col.fk_col.upper())
                            for col in c.columns
                        )
                    ]
            _fk_t["intro"] = round(time.time() - _fk_t0, 2)
            if _check_constraints:
                from sqlalchemy import text as _fkt
                _parent_tables = list({c.parent_table for c in _check_constraints})
                _tbl_in = ",".join(f"'{t}'" for t in _parent_tables)

                # Step 1: row counts for all parent tables in one query
                _fk_t1 = time.time()
                try:
                    if _is_oracle:
                        _has_rows = set()
                        with engine.connect() as _fkc:
                            for _pt_chk in _parent_tables:
                                try:
                                    _cnt = _fkc.execute(_fkt(
                                        f'SELECT COUNT(*) FROM "{_dbo}"."{_pt_chk.upper()}"'
                                    )).scalar() or 0
                                    if _cnt > 0:
                                        _has_rows.add(_pt_chk.lower())
                                except Exception:
                                    pass
                    else:
                        with engine.connect() as _fkc:
                            _cnt_rows = _fkc.execute(_fkt(
                                f"SELECT t.name, SUM(p.rows) "
                                f"FROM sys.partitions p "
                                f"JOIN sys.tables t ON t.object_id=p.object_id "
                                f"JOIN sys.schemas s ON s.schema_id=t.schema_id "
                                f"WHERE p.index_id IN (0,1) AND s.name='dbo' "
                                f"AND t.name IN ({_tbl_in}) GROUP BY t.name"
                            )).fetchall()
                            _has_rows = {row[0].lower() for row in _cnt_rows if (row[1] or 0) > 0}
                except Exception as _ce:
                    _fk_t["count_err"] = str(_ce)[:80]
                    _has_rows = set()
                _fk_t["count"] = round(time.time() - _fk_t1, 2)
                _fk_t["n_parents"] = len(_parent_tables)
                _fk_t["n_satisfied"] = len(_has_rows)
                _unsatisfied = [t for t in _parent_tables if t.lower() not in _has_rows]
                if _unsatisfied:
                    _fk_t["unsatisfied"] = _unsatisfied[:5]

                # Step 2: server-side EXISTS check for each mapped FK column
                _fk_t2 = time.time()
                _seen_violations = set()
                for _c in _check_constraints:
                    _ptbl = _c.parent_table
                    _ptbl_l = _ptbl.lower()
                    for _fkcol in _c.columns:
                        _src_col   = _mapped_src.get(_fkcol.fk_col.upper())
                        _const_val = _mapped_const.get(_fkcol.fk_col.upper())
                        if not _src_col and not _const_val:
                            continue
                        _vk = f"{_ptbl_l}.{_src_col or _const_val}"
                        if _vk in _seen_violations:
                            continue
                        _seen_violations.add(_vk)
                        try:
                            with engine.connect() as _fkc2:
                                if not _is_oracle:
                                    try:
                                        _fkc2.execute(_fkt("SET LOCK_TIMEOUT 5000"))
                                    except Exception:
                                        pass
                                # Get transform for this column from mapping
                                _xform = next(
                                    (m.transform for m in col_mapping.mapped
                                     if m.source_col == _src_col and not m.auto_generated),
                                    ""
                                )
                                # Handle constant value mappings
                                if _const_val and not _src_col:
                                    _const_esc = str(_const_val).replace("'","''")
                                    if _is_oracle:
                                        _ora_ptbl = f'"{_dbo}"."{_ptbl.upper()}"'
                                        _ora_rcol = f'"{_fkcol.ref_col.upper()}"'
                                        _mv = [r[0] for r in _fkc2.execute(_fkt(
                                            f"SELECT 1 FROM DUAL WHERE NOT EXISTS ("
                                            f"SELECT 1 FROM {_ora_ptbl} ref "
                                            f"WHERE ref.{_ora_rcol} = '{_const_esc}')"
                                        )).fetchall()]
                                        if _mv:
                                            _mv = [_const_val]
                                    else:
                                        _mv = [r[0] for r in _fkc2.execute(_fkt(
                                            f"SELECT '{_const_esc}' WHERE NOT EXISTS ("
                                            f"SELECT 1 FROM [dbo].[{_ptbl}] ref "
                                            f"WHERE ref.[{_fkcol.ref_col}] = '{_const_esc}')"
                                        )).fetchall()]
                                    if _mv:
                                        _fk_violations.append(type('V', (), {
                                            'constraint': _c,
                                            'missing_values': _mv,
                                        })())
                                    continue

                                # Build transformed expression
                                if _is_oracle:
                                    _sc_q = f'src."{_src_col.upper()}"'
                                    _src_expr = _sc_q
                                    if _xform in ("SHA1_40", "SHA1"):
                                        _src_expr = (f"UPPER(RAWTOHEX(DBMS_CRYPTO.HASH("
                                                     f"UTL_RAW.CAST_TO_RAW(UPPER(TRIM({_sc_q}))),3)))")
                                    elif _xform == "SHA1_20":
                                        _src_expr = (f"SUBSTR(UPPER(RAWTOHEX(DBMS_CRYPTO.HASH("
                                                     f"UTL_RAW.CAST_TO_RAW(UPPER(TRIM({_sc_q}))),3))),1,20)")
                                    elif _xform == "UPPER":
                                        _src_expr = f"UPPER({_sc_q})"
                                else:
                                    _src_expr = f"src.[{_src_col}]"
                                    if _xform in ("SHA1_40", "SHA1"):
                                        _src_expr = (f"CONVERT(CHAR(40), HASHBYTES('SHA1', "
                                                     f"CAST(UPPER(LTRIM(RTRIM(src.[{_src_col}]))) AS NVARCHAR(4000))), 2)")
                                    elif _xform == "SHA1_20":
                                        _src_expr = (f"LEFT(CONVERT(CHAR(40), HASHBYTES('SHA1', "
                                                     f"CAST(UPPER(LTRIM(RTRIM(src.[{_src_col}]))) AS NVARCHAR(4000))), 2), 20)")
                                    elif _xform == "UPPER":
                                        _src_expr = f"UPPER(src.[{_src_col}])"

                                # Check all FK parent tables including empty ones
                                if _is_oracle:
                                    _mv = [r[0] for r in _fkc2.execute(_fkt(
                                            f'SELECT DISTINCT src."{_src_col.upper()}" '
                                            f'FROM "{stg_schema}"."{stg_table.upper()}" src '
                                            f'WHERE src."{_src_col.upper()}" IS NOT NULL '
                                            f'AND TRIM(src."{_src_col.upper()}") IS NOT NULL '
                                            f'AND NOT EXISTS ('
                                            f'SELECT 1 FROM "{_dbo}"."{_ptbl.upper()}" ref '
                                            f'WHERE ref."{_fkcol.ref_col.upper()}" = {_src_expr})'
                                            f''
                                    )).fetchall()]
                                else:
                                    _mv = [r[0] for r in _fkc2.execute(_fkt(
                                        f"SELECT DISTINCT src.[{_src_col}] "
                                            f"FROM [{stg_schema}].[{stg_table}] src WITH (NOLOCK) "
                                            f"WHERE src.[{_src_col}] IS NOT NULL "
                                            f"AND LTRIM(RTRIM(src.[{_src_col}])) <> '' "
                                            f"AND NOT EXISTS ("
                                            f"SELECT 1 FROM [dbo].[{_ptbl}] ref WITH (NOLOCK) "
                                            f"WHERE ref.[{_fkcol.ref_col}] = {_src_expr})"
                                    )).fetchall()]
                            if _mv:
                                _fk_violations.append(type('V', (), {
                                    'constraint': _c,
                                    'missing_values': _mv,
                                })())
                        except Exception:
                            pass
                _fk_t["exists_check"] = round(time.time() - _fk_t2, 2)
        except Exception:
            pass

        # ── Depth-2 check: find parent tables of violated ref tables ──────
        # e.g. r_well_status violated → also check r_well_status_type
        try:
            _d2_viols_added = set()
            for _v in list(_fk_violations):
                _vptbl = _v.constraint.parent_table
                if not any(_vptbl.lower().startswith(p) for p in ('r_','ra_','rb_')):
                    continue
                # Get FK constraints of the violated ref table itself
                with engine.connect() as _d2c:
                    if _is_oracle:
                        _d2_rows = _d2c.execute(_t(
                            "SELECT cc.column_name, rcon.table_name, pc.column_name "
                            "FROM all_constraints con "
                            "JOIN all_cons_columns cc ON cc.constraint_name=con.constraint_name AND cc.owner=con.owner "
                            "JOIN all_constraints rcon ON rcon.constraint_name=con.r_constraint_name AND rcon.owner=con.r_owner "
                            "JOIN all_cons_columns pc ON pc.constraint_name=rcon.constraint_name AND pc.owner=rcon.owner AND pc.position=cc.position "
                            "WHERE con.constraint_type='R' AND con.table_name=:tbl AND con.owner=:sch"
                        ), {"tbl": _vptbl.upper(), "sch": _dbo.upper()}).fetchall()
                    else:
                        _d2_rows = _d2c.execute(_t(
                            "SELECT cc.name, pt.name, pc.name "
                            "FROM sys.foreign_keys fk "
                            "JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id "
                            "JOIN sys.columns cc ON cc.object_id=fk.parent_object_id AND cc.column_id=fkc.parent_column_id "
                            "JOIN sys.tables pt ON pt.object_id=fk.referenced_object_id "
                            "JOIN sys.columns pc ON pc.object_id=fk.referenced_object_id AND pc.column_id=fkc.referenced_column_id "
                            "JOIN sys.tables ct ON ct.object_id=fk.parent_object_id "
                            "WHERE ct.name=:tbl"
                        ), {"tbl": _vptbl}).fetchall()
                for _d2cc, _d2pt, _d2pc in _d2_rows:
                    if not any(_d2pt.lower().startswith(p) for p in ('r_','ra_','rb_')):
                        continue
                    if _d2pt.lower() in _d2_viols_added:
                        continue
                    # Find staging source col for this fk col
                    _d2_src = _mapped_src.get(_d2cc.upper(), "")
                    if not _d2_src:
                        # Try via the violating table's mapping — use same source col
                        for _vc2 in _v.constraint.columns:
                            if _vc2.ref_col.upper() == _d2cc.upper():
                                _d2_src = _mapped_src.get(_vc2.fk_col.upper(), "")
                                break
                    if not _d2_src:
                        continue
                    # Check if d2 parent table has the staging values
                    try:
                        with engine.connect() as _d2vc:
                            if _is_oracle:
                                _d2mv = [r[0] for r in _d2vc.execute(_t(
                                    f'SELECT DISTINCT src."{_d2_src.upper()}" '
                                    f'FROM "{stg_schema}"."{stg_table.upper()}" src '
                                    f'WHERE src."{_d2_src.upper()}" IS NOT NULL '
                                    f'AND NOT EXISTS (SELECT 1 FROM "{_dbo}"."{_d2pt.upper()}" ref '
                                    f'WHERE ref."{_d2pc.upper()}" = TRIM(src."{_d2_src.upper()}"))'
                                    f' FETCH FIRST 20 ROWS ONLY'
                                )).fetchall()]
                            else:
                                _d2mv = [r[0] for r in _d2vc.execute(_t(
                                    f"SELECT DISTINCT TOP 20 src.[{_d2_src}] "
                                    f"FROM [{stg_schema}].[{stg_table}] src WITH (NOLOCK) "
                                    f"WHERE src.[{_d2_src}] IS NOT NULL "
                                    f"AND LTRIM(RTRIM(src.[{_d2_src}])) <> '' "
                                    f"AND NOT EXISTS (SELECT 1 FROM [dbo].[{_d2pt}] ref WITH (NOLOCK) "
                                    f"WHERE ref.[{_d2pc}] = src.[{_d2_src}])"
                                )).fetchall()]
                        if _d2mv:
                            from dataview.core.fk import FKConstraint, FKColumn
                            _fk_violations.append(type('V', (), {
                                'constraint': FKConstraint(
                                    constraint_name=f"D2_{_d2pt}",
                                    child_table=_vptbl,
                                    child_schema=_dbo,
                                    parent_table=_d2pt,
                                    parent_schema=_dbo,
                                    columns=[FKColumn(
                                        fk_col=_d2cc, ref_col=_d2pc,
                                        ordinal=1, nullable=True)],
                                ),
                                'missing_values': _d2mv,
                            })())
                            _d2_viols_added.add(_d2pt.lower())
                    except Exception:
                        pass
        except Exception:
            pass

        if _fk_violations:
            # Separate reference table violations from entity violations
            _ref_viols = [v for v in _fk_violations
                          if any(v.constraint.parent_table.lower().startswith(p)
                                 for p in ('r_','ra_','rb_'))]
            _ent_viols = [v for v in _fk_violations if v not in _ref_viols]

            # Dedup summary by parent table — ref tables only
            _viol_seen = {}
            for _vs in _fk_violations:
                _vpt = _vs.constraint.parent_table
                if _vpt not in _viol_seen:
                    _viol_seen[_vpt] = _vs.missing_values[:3]
            _ref_viol_seen = {t: v for t, v in _viol_seen.items()
                              if any(t.lower().startswith(p) for p in ('r_','ra_','rb_'))}
            _viol_summary = "; ".join(
                f"{tbl}: {vals}" for tbl, vals in list(_ref_viol_seen.items())[:6]
            ) or "; ".join(
                f"{tbl}: {vals}" for tbl, vals in list(_viol_seen.items())[:6]
            )
            _seed_note = f" | Step5b: {_fks_seed_err}" if _fks_seed_err else ""

            if _ref_viols:
                _ref_tbls = ", ".join(sorted({v.constraint.parent_table for v in _ref_viols}))
                _ref_msg = (
                    f"Reference table(s) not seeded: {_ref_tbls}. "
                    f"Open the interactive app → Stage 6 → RTM to seed these tables "
                    f"before re-running the batch job."
                )

                # Write missing distinct values to CSV in reference_files directory
                try:
                    import csv as _vcsv, pathlib as _vpath
                    from datetime import datetime as _vdt
                    # Write to reference_files subfolder of source data directory
                    _src_dir = _vpath.Path(job.get("file_path", "")).parent
                    _ref_dir = (_src_dir / "reference_files") if (_src_dir and _src_dir.exists()) else None
                    if not _ref_dir:
                        _export_root = job.get("export_root", "").strip()
                        _ref_dir = _vpath.Path(_export_root) / "reference_files" if _export_root else None
                    if _ref_dir:
                        _ref_dir.mkdir(parents=True, exist_ok=True)
                        if progress_cb:
                            progress_cb(f"Writing missing values to {_ref_dir}", 0)
                        _v_ts     = _vdt.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                        _v_batch  = str(job.get("id", ""))
                        _v_file   = job.get("file_name", "")
                        # Group violations by parent table — accumulate ALL FK cols
                        # including non-violating cols for composite PKs
                        _viol_by_tbl = {}
                        for _vv in _ref_viols:
                            _vtbl = _vv.constraint.parent_table.lower()
                            if _vtbl not in _viol_by_tbl:
                                _viol_by_tbl[_vtbl] = {"cols": [], "rows": set()}
                            for _vc in _vv.constraint.columns:
                                _vsrc = _mapped_src.get(_vc.fk_col.upper(), "")
                                _vref = _vc.ref_col if hasattr(_vc, 'ref_col') else _vc.fk_col
                                _col_entry = (_vc.fk_col, _vref, _vsrc)
                                if _col_entry not in _viol_by_tbl[_vtbl]["cols"]:
                                    _viol_by_tbl[_vtbl]["cols"].append(_col_entry)

                        # For composite PKs: add ALL FK cols from _check_constraints
                        # that reference the same parent table (even non-violating ones)
                        for _cc in _check_constraints:
                            _ctbl = _cc.parent_table.lower()
                            if _ctbl not in _viol_by_tbl:
                                continue  # only tables that already have violations
                            for _vc in _cc.columns:
                                _vsrc = _mapped_src.get(_vc.fk_col.upper(), "")
                                _vref = _vc.ref_col if hasattr(_vc, 'ref_col') else _vc.fk_col
                                _col_entry = (_vc.fk_col, _vref, _vsrc)
                                if _col_entry not in _viol_by_tbl[_ctbl]["cols"] and _vsrc:
                                    _viol_by_tbl[_ctbl]["cols"].append(_col_entry)

                                # Debug: log to fk_t so it appears in stage timings
                        _r_ws_cc = [(c.columns[0].fk_col, c.columns[0].ref_col if hasattr(c.columns[0],'ref_col') else '?')
                                    for c in _check_constraints if c.parent_table.lower() == 'r_well_status']
                        _fk_t["r_ws_cc"] = str(_r_ws_cc)
                        _fk_t["viol_tbl_cols"] = {_dt: [c[1] for c in _di['cols']] for _dt, _di in _viol_by_tbl.items()}

                        # Now query staging for distinct combinations per table
                        from sqlalchemy import text as _vcst
                        _stg_full_vc = (f"[{stg_schema}].[{stg_table}]"
                                        if not _is_oracle else
                                        f'"{stg_schema}"."{stg_table.upper()}"')
                        for _vtbl, _vinfo in _viol_by_tbl.items():
                            _vcols = [c for c in _vinfo["cols"] if c[2]]  # only mapped cols
                            if not _vcols:
                                continue
                            try:
                                if _is_oracle:
                                    _sel = ", ".join(f'"{c[2].upper()}"' for c in _vcols)
                                    _whr = " AND ".join(f'"{c[2].upper()}" IS NOT NULL' for c in _vcols)
                                else:
                                    _sel = ", ".join(f"[{c[2]}]" for c in _vcols)
                                    _whr = " AND ".join(f"[{c[2]}] IS NOT NULL AND LTRIM(RTRIM([{c[2]}])) <> ''" for c in _vcols)
                                with engine.connect() as _vcc:
                                    _combo_rows = _vcc.execute(_vcst(
                                        f"SELECT DISTINCT {_sel} FROM {_stg_full_vc} WHERE {_whr}"
                                    )).fetchall()
                                for _cr in _combo_rows:
                                    _viol_by_tbl[_vtbl]["rows"].add(tuple(str(v) for v in _cr))
                            except Exception:
                                pass

                        for _vtbl, _vinfo in _viol_by_tbl.items():
                            _vcols   = _vinfo["cols"]
                            _vf      = _ref_dir / f"{_vtbl}_missing.csv"
                            # Sort cols by actual PK ordinal from DB to get correct column order
                            try:
                                with engine.connect() as _pko_con:
                                    _pko_rows = {r[0].upper(): r[1] for r in _pko_con.execute(_s5t(
                                        "SELECT c.name, ic.key_ordinal "
                                        "FROM sys.indexes i "
                                        "JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id "
                                        "JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id "
                                        "JOIN sys.tables t ON t.object_id=i.object_id "
                                        "WHERE i.is_primary_key=1 AND t.name=:tbl"
                                    ), {"tbl": _vtbl}).fetchall()}
                                if _pko_rows:
                                    _vcols = sorted(_vcols,
                                        key=lambda c: _pko_rows.get(c[1].upper(), 99))
                            except Exception:
                                pass
                            # Column headers = ref_col names (the PK cols of parent table)
                            _vpk_cols = [c[1] for c in _vcols if c[2]] or [c[1] for c in _vcols]
                            _vfields  = _vpk_cols + ["source_file", "timestamp", "batch_id"]

                            # Read existing rows for dedup on PK tuple
                            _existing_keys = set()
                            if _vf.exists():
                                try:
                                    with open(_vf, newline="", encoding="utf-8") as _vrf:
                                        _vrd = _vcsv.DictReader(_vrf)
                                        for _vr in _vrd:
                                            _existing_keys.add(
                                                tuple(_vr.get(p, "") for p in _vpk_cols))
                                except Exception:
                                    pass

                            # Only write new rows not already in file
                            _new_rows = sorted(
                                r for r in _vinfo["rows"]
                                if r not in _existing_keys
                            )
                            if _new_rows:
                                _vexists = _vf.exists()
                                with open(_vf, "a", newline="", encoding="utf-8") as _vfh:
                                    _vw = _vcsv.DictWriter(_vfh, fieldnames=_vfields)
                                    if not _vexists:
                                        _vw.writeheader()
                                    for _vrow in _new_rows:
                                        _rd = {_vpk_cols[i]: _vrow[i]
                                               for i in range(min(len(_vpk_cols), len(_vrow)))}
                                        _rd["source_file"] = _v_file
                                        _rd["timestamp"]   = _v_ts
                                        _rd["batch_id"]    = _v_batch
                                        _vw.writerow(_rd)
                except Exception as _ve:
                    if progress_cb:
                        progress_cb(f"CSV write error: {_ve}", 0)
            else:
                _ref_msg = ""

            # Build ref_dir path for message
            try:
                import pathlib as _rdp
                _rd = _rdp.Path(job.get("file_path","")).parent / "reference_files"
            except Exception:
                _rd = None
            _rd_msg = f" | Missing values written to: {_rd}" if (_rd and _ref_viols) else ""
            return {"ok": False,
                    "message": f"FK violations — {_viol_summary}.{_seed_note}"
                               + (f" | {_ref_msg}" if _ref_msg else "")
                               + _rd_msg,
                    "ref_tables_needed": [v.constraint.parent_table for v in _ref_viols],
                    "rows_inserted": 0, "rows_skipped": 0, "rows_error": len(_fk_violations),
                    "duration_s": round(time.time()-t0, 1)}

        # ── 7. Validate — fast server-side: NOT NULL + duplicate PK only ──
        _cb("Validate", 70)
        from dataview.core.validate import validate_server as _validate_server
        val = _validate_server(
            engine, stg_table, col_mapping, target_cols,
            schema=stg_schema, target_table=target_table,
            checks=("not_null", "duplicate_pk"),
        )
        if val.clean_row_count == 0:
            return {"ok": False,
                    "message": f"Validation: 0 clean rows "
                               f"({len(val.errors)} error(s)). Nothing promoted.",
                    "rows_inserted": 0, "rows_skipped": val.rows_checked,
                    "rows_error": len(val.errors),
                    "duration_s": round(time.time()-t0, 1)}

        # ── 8. Promote ──────────────────────────────────────────────────
        _cb("Promote", 85)
        if mode == "merge":
            # Get PK cols
            pk_cols = []
            try:
                with engine.connect() as con:
                    if _is_oracle:
                        _pk_rows = con.execute(_t("""
                            SELECT cc.column_name
                            FROM all_constraints con
                            JOIN all_cons_columns cc
                              ON cc.constraint_name=con.constraint_name AND cc.owner=con.owner
                            WHERE con.constraint_type='P'
                            AND con.table_name=UPPER(:tbl)
                            AND con.owner=SYS_CONTEXT('USERENV','CURRENT_SCHEMA')
                            ORDER BY cc.position
                        """), {"tbl": target_table}).fetchall()
                    else:
                        _pk_rows = con.execute(_t("""
                            SELECT c.name FROM sys.indexes i
                            JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                            JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                            JOIN sys.tables t ON t.object_id=i.object_id
                            JOIN sys.schemas s ON s.schema_id=t.schema_id
                            WHERE i.is_primary_key=1 AND t.name=:tbl AND s.name='dbo'
                            ORDER BY ic.key_ordinal
                        """), {"tbl": target_table}).fetchall()
                pk_cols = [r[0] for r in _pk_rows]
            except Exception:
                pass
            result = promote_merge(engine, stg_table, target_table,
                                   col_mapping, pk_cols=pk_cols, schema=stg_schema if not _is_oracle else _dbo)
        else:
            result = promote_server(engine, stg_table, target_table,
                                    col_mapping, schema=stg_schema if not _is_oracle else _dbo)

        _cb("Done", 100)
        # Finalize last stage duration
        if _stage_times:
            _last = list(_stage_times.keys())[-1]
            _stage_times[_last] = round(time.time() - _stage_times[_last], 1)
        if _fk_t:
            _stage_times["fk_detail"] = _fk_t
        return {
            "ok":            result.ok,
            "message":       result.message,
            "rows_inserted": result.rows_inserted,
            "rows_skipped":  result.rows_skipped,
            "rows_error":    result.rows_error,
            "duration_s":    round(time.time() - t0, 1),
            "stage_times":   _stage_times,
            "fk_seeded":     _fks_seed_log,
            "fk_seed_err":   _fks_seed_err,
        }

    except Exception as exc:
        import traceback
        return {
            "ok": False,
            "message": f"{exc}\n{traceback.format_exc()}",
            "rows_inserted": 0, "rows_skipped": 0, "rows_error": 0,
            "duration_s": round(time.time() - t0, 1),
        }


# ═══════════════════════════════════════════════════════════════════════════
# STREAMLIT PAGE
# ═══════════════════════════════════════════════════════════════════════════

def render(S):
    shdr("Batch Loader",
         "Queue CSV files for unattended loading. Mappings resolved from fingerprint cache.")

    engine      = getattr(S, "engine", None)
    ppdm_schema = getattr(S, "ppdm_schema", None)

    if not engine:
        st.warning("⚠️ Not connected to a database. Go to Stage 1 to connect first.")
        return

    queue   = _load_queue()
    history = _load_history()

    # Auto-clear done/failed jobs so queue is clean on open
    _cleaned = [j for j in queue if j["status"] not in ("done", "failed")]
    if len(_cleaned) != len(queue):
        queue = _cleaned
        _save_queue(queue)

    # ── Tabs ───────────────────────────────────────────────────────────────
    tab_queue, tab_run, tab_history, tab_schedule, tab_maint = st.tabs([
        "📋 Queue", "▶ Run", "📜 History", "⏰ Schedule", "🧹 Maintenance"
    ])

    # ══════════════════════════════════════════════════════════════════════
    # TAB 1 · QUEUE BUILDER
    # ══════════════════════════════════════════════════════════════════════
    with tab_queue:

        # ── Build FK Queue ─────────────────────────────────────────────
        st.markdown("#### 🔗 Build FK queue from target table")
        st.caption(
            "Auto-adds FK/entity parent tables in dependency order, then the target. "
            "Only tables with a matching CSV file in the folder are queued — "
            "tables with no CSV are skipped even if they are FK parents. "
            "Re-save the mapping from Stage 5 to restrict to only mapped FK columns."
        )

        _bfk_c1, _bfk_c2, _bfk_c3 = st.columns([2, 2, 1])
        with _bfk_c1:
            _table_opts = ppdm_schema.all_table_names if ppdm_schema else []
            _bfk_tbl = st.selectbox("Target table", ["— select —"] + _table_opts,
                                    key="bfk_target_tbl")
        with _bfk_c2:
            _bfk_folder = st.text_input("CSV folder",
                                        value=getattr(S, "import_root", ""),
                                        placeholder=r"C:\data\source_data",
                                        key="bfk_folder_input")
        with _bfk_c3:
            _bfk_mode = st.selectbox("Mode", ["insert", "merge"], key="bfk_mode")

        if st.button("🔗 Build FK queue", type="primary",
                     use_container_width=True, key="bfk_build"):
            if _bfk_tbl == "— select —":
                st.error("Select a target table.")
            elif not _bfk_folder or not pathlib.Path(_bfk_folder.strip()).is_dir():
                st.error(f"Enter a valid CSV folder path. Got: {_bfk_folder!r}")
            else:
                _bfk_folder = _bfk_folder.strip()
                _bfk_errors = []
                _bfk_info   = []
                _new_jobs   = []
                _skipped    = []

                # ── 1. Query FK dependency graph — mapped columns only ──
                _d1_tables = []
                _d2_tables = []
                _dep_ok    = False
                try:
                    from dataview.import_data.mapping import _load_cache, mapping_fingerprint

                    _EXCL_BFK = {
                        'well_area','field_area','well_node','well_bore',
                        'r_source','r_ppdm_row_quality','source_document',
                        'ppdm_measurement_system','ppdm_quantity',
                        'r_ppdm_uom_usage','ppdm_unit_of_measure',
                        'strat_unit','strat_name_set',
                    }

                    _cache = _load_cache()

                    # Get mapped columns — session mapping first, then cache
                    _mapped_ppdm = set()

                    # First try: active pipeline mapping in session
                    _session_mapping = getattr(S, 'col_mapping', None)
                    if (_session_mapping and
                        getattr(_session_mapping, 'target_table', '').lower() == _bfk_tbl.lower()):
                        _mapped_ppdm = {
                            m.ppdm_col.lower() for m in _session_mapping.mapped
                            if m.source_col and not m.auto_generated
                        }

                    # Second try: find by _meta.target_table in cache
                    if not _mapped_ppdm:
                        for _fp_key, _fp_val in _cache.items():
                            if not isinstance(_fp_val, dict):
                                continue
                            _meta = _fp_val.get('_meta', {})
                            if isinstance(_meta, dict) and \
                               _meta.get('target_table', '').lower() == _bfk_tbl.lower():
                                _mapped_ppdm = {c.lower() for c in _meta.get('mapped_cols', [])}
                                if _mapped_ppdm:
                                    break

                    # Build FK graph from schema JSON filtered to mapped columns
                    if ppdm_schema and _mapped_ppdm:
                        _tbl_def = ppdm_schema.get_table(_bfk_tbl)
                        if _tbl_def:
                            _seen_d1 = set()
                            for _fc in _tbl_def.fk_columns:
                                if _fc.column_name.lower() not in _mapped_ppdm:
                                    continue
                                _pt = _fc.fk_table_name
                                if not _pt or _pt.lower() in _EXCL_BFK:
                                    continue
                                if _pt.lower() == _bfk_tbl.lower():
                                    continue
                                if _pt not in _seen_d1:
                                    _seen_d1.add(_pt)
                                    _d1_tables.append(_pt)

                            # D2 grandparents — only if D1 has mapped FK cols
                            _seen_d2 = set()
                            for _d1_pt in _d1_tables:
                                _d1_tbl_def = ppdm_schema.get_table(_d1_pt)
                                if not _d1_tbl_def:
                                    continue
                                for _fc2 in _d1_tbl_def.fk_columns:
                                    _pt2 = _fc2.fk_table_name
                                    if not _pt2 or _pt2.lower() in _EXCL_BFK:
                                        continue
                                    if _pt2 in _d1_tables or _pt2 in _seen_d2:
                                        continue
                                    if _pt2.lower() == _bfk_tbl.lower():
                                        continue
                                    _seen_d2.add(_pt2)
                                    _d2_tables.append(_pt2)
                    elif ppdm_schema:
                        # No mapping found yet — fall back to all FK parents
                        _tbl_def = ppdm_schema.get_table(_bfk_tbl)
                        if _tbl_def:
                            for _fc in _tbl_def.fk_columns:
                                _pt = _fc.fk_table_name
                                if _pt and _pt.lower() not in _EXCL_BFK and _pt.lower() != _bfk_tbl.lower():
                                    if _pt not in _d1_tables:
                                        _d1_tables.append(_pt)

                    _bfk_info.append(
                        f"Found {len(_d2_tables)} depth-2 and {len(_d1_tables)} depth-1 parent tables.")
                    _dep_ok = True
                except Exception as _e:
                    _bfk_errors.append(f"FK graph query failed: {_e}")

                # ── 2. Match CSV files from folder to tables ───────────
                if _dep_ok:
                    try:
                        _cache     = _load_cache()
                        _csv_files = list(pathlib.Path(_bfk_folder).glob("*.csv"))
                        _bfk_info.append(f"Found {len(_csv_files)} CSV file(s) in folder.")

                        def _find_csv_for_table(tbl):
                            import csv as _fcsv
                            from dataview.import_data.staging import _sanitize_col, _dedupe_cols

                            def _get_fp_for_file(path, tbl):
                                """Read header with delimiter detection and return fingerprint."""
                                try:
                                    with open(path, encoding="utf-8-sig", newline="") as _f:
                                        _sample = _f.read(4096)
                                    _first = _sample.split('\n')[0]
                                    _counts = {d: _first.count(d) for d in ('|', '\t', ',', ';')}
                                    _delim = next((d for d in ('|', '\t', ';', ',') if _counts[d] > 0), ',')
                                    with open(path, encoding="utf-8-sig", newline="") as _f:
                                        _hdrs = next(_fcsv.reader(_f, delimiter=_delim))
                                    _hdrs = [h.strip() for h in _hdrs]
                                    _cols = _dedupe_cols([_sanitize_col(h) for h in _hdrs])
                                    while _cols and _cols[-1] in ('', 'col'):
                                        _cols.pop()
                                    _fp1 = mapping_fingerprint(tbl, _cols + ["_batch_loaded_at"])
                                    _fp2 = mapping_fingerprint(tbl, _cols)
                                    # Return whichever fingerprint has a saved mapping
                                    for _fp in (_fp1, _fp2):
                                        _saved = _cache.get(_fp, {})
                                        _n = sum(1 for v in _saved.values()
                                                 if isinstance(v, dict) and v.get("source_col","").strip())
                                        if _n > 0:
                                            return _fp, _n
                                    return _fp1, 0
                                except Exception:
                                    return None, 0

                            # Search only the main CSV folder — reference_files
                            # subfolder is no longer used for batch loading
                            _search_dir = pathlib.Path(_bfk_folder)

                            # Strategy 1 — exact name match
                            _exact = _search_dir / f"{tbl}.csv"
                            if _exact.exists():
                                _fp, _n = _get_fp_for_file(str(_exact), tbl)
                                if _fp:
                                    return str(_exact), _fp, _n

                            # Strategy 2 — fingerprint scan across all CSVs in folder
                            for _csv in _search_dir.glob("*.csv"):
                                _fp, _n = _get_fp_for_file(str(_csv), tbl)
                                if _fp and _fp in _cache:
                                    return str(_csv), _fp, _n
                            return None, None, 0

                        # ── 3. Build ordered job list ──────────────────
                        # r_source always goes first — excluded from FK graph
                        # but required by virtually every target table
                        _special_first = ['r_source']
                        _ordered_tables = _special_first + _d2_tables + _d1_tables + [_bfk_tbl]

                        # Find RTM fingerprints — tables with RTM fingerprints
                        # are auto-seeded by Step 5b during well load, skip from queue
                        _rtm_seeded_tbls = set()
                        for _ck, _cv in _cache.items():
                            if _ck.startswith("RTM_") and isinstance(_cv, list) and _cv:
                                # Extract target table from RTM key pattern
                                # RTM key = "RTM:" + TABLE + "|" + cols (hashed)
                                # We can't reverse the hash, but we can check _meta
                                pass
                        # Check pipeline fingerprints for RTM-seeded tables
                        for _ck, _cv in _cache.items():
                            if not _ck.startswith("RTM_") and isinstance(_cv, dict):
                                _cm = _cv.get("_meta", {})
                                if isinstance(_cm, dict):
                                    _ct = _cm.get("target_table", "").lower()
                                    if _ct and _ct != _bfk_tbl.lower():
                                        # Check if this table has an RTM fingerprint
                                        for _rk in _cache:
                                            if _rk.startswith("RTM_"):
                                                # RTM fingerprints are keyed by table+cols
                                                # If any RTM fp exists for this table, mark it
                                                pass

                        # Find RTM-seeded tables by checking RTM fp entries
                        # RTM fps have list values with Target Column entries
                        # We identify which tables they seed by matching against _d1_tables
                        _has_rtm = set()
                        for _d1t in _d1_tables + _d2_tables:
                            # Check if any RTM fingerprint maps to this table's PK col
                            _d1_tdef = ppdm_schema.get_table(_d1t) if ppdm_schema else None
                            if not _d1_tdef:
                                continue
                            _d1_pks = {c.column_name.upper() for c in _d1_tdef.columns
                                       if c.is_primary_key}
                            for _rk, _rv in _cache.items():
                                if not _rk.startswith("RTM_") or not isinstance(_rv, list):
                                    continue
                                _rtm_tgt_cols = {
                                    r.get("Target Column","").lstrip("🔑 ").strip().upper()
                                    for r in _rv
                                }
                                if _d1_pks & _rtm_tgt_cols:
                                    _has_rtm.add(_d1t.lower())
                                    break

                        # Pre-scan: only include tables that have a CSV available
                        # Skip tables that will be auto-seeded by Step 5b (have RTM fingerprint)
                        _available = {}
                        for _tbl in _ordered_tables:
                            if _tbl.lower() in _has_rtm and _tbl.lower() != _bfk_tbl.lower():
                                continue  # auto-seeded by Step 5b — skip from queue
                            _csv_path, _fp, _n = _find_csv_for_table(_tbl)
                            if _csv_path:
                                _available[_tbl] = (_csv_path, _fp, _n)

                        # Always include the target table even if no CSV found yet
                        if _bfk_tbl not in _available:
                            _csv_path, _fp, _n = _find_csv_for_table(_bfk_tbl)
                            if _csv_path:
                                _available[_bfk_tbl] = (_csv_path, _fp, _n)

                        # Find ALL CSVs in the folder that match the target table fingerprint
                        # so all files are queued in one click, not just the first match
                        _target_csv_jobs = []
                        _already_queued = {j["file_path"] for j in queue}
                        for _csv_f in sorted(pathlib.Path(_bfk_folder).glob("*.csv")):
                            if str(_csv_f) in _already_queued:
                                continue
                            # Inline fingerprint check for this specific file
                            _fp_f, _n_f = None, 0
                            try:
                                import csv as _fcsv2
                                from dataview.import_data.staging import _sanitize_col, _dedupe_cols
                                from dataview.import_data.mapping import mapping_fingerprint as _mfp2
                                with open(str(_csv_f), encoding="utf-8-sig", newline="") as _ff:
                                    _sample2 = _ff.read(4096)
                                _first2 = _sample2.split('\n')[0]
                                _counts2 = {d: _first2.count(d) for d in ('|','\t',',',';')}
                                _delim2 = next((d for d in ('|','\t',';',',') if _counts2[d] > 0), ',')
                                with open(str(_csv_f), encoding="utf-8-sig", newline="") as _ff:
                                    _hdrs2 = next(_fcsv2.reader(_ff, delimiter=_delim2))
                                _cols2 = _dedupe_cols([_sanitize_col(h.strip()) for h in _hdrs2])
                                while _cols2 and _cols2[-1] in ('', 'col'):
                                    _cols2.pop()
                                for _fp2 in (_mfp2(_bfk_tbl, _cols2 + ["_batch_loaded_at"]),
                                             _mfp2(_bfk_tbl, _cols2)):
                                    _saved2 = _cache.get(_fp2, {})
                                    _n2 = sum(1 for v in _saved2.values()
                                              if isinstance(v, dict) and v.get("source_col","").strip())
                                    if _n2 > 0:
                                        _fp_f, _n_f = _fp2, _n2
                                        break
                            except Exception:
                                pass
                            if _fp_f and _n_f > 0:
                                _target_csv_jobs.append((str(_csv_f), _fp_f, _n_f))

                        _new_jobs = []
                        _no_map   = []
                        _skipped  = [t for t in _ordered_tables
                                     if t != _bfk_tbl and t not in _available]

                        _next_id = max((j["id"] for j in queue), default=0) + 1
                        # Add FK parent tables first (excluding target)
                        for _tbl in _ordered_tables:
                            if _tbl == _bfk_tbl or _tbl not in _available:
                                continue
                            _csv_path, _fp, _n = _available[_tbl]
                            _status = "ready" if _n > 0 else "no_mapping"
                            if _status == "no_mapping":
                                _no_map.append(_tbl)
                            _new_jobs.append({
                                "id":           _next_id,
                                "file_path":    _csv_path,
                                "file_name":    pathlib.Path(_csv_path).name,
                                "target_table": _tbl,
                                "mode":         _bfk_mode,
                                "fingerprint":  _fp or "",
                                "mapped_cols":  _n,
                                "status":       _status,
                                "added":        datetime.now().isoformat()[:19],
                                "export_root":  getattr(S, "export_root", ""),
                            })
                            _next_id += 1
                        # Add all matching CSVs for the target table
                        for _csv_path, _fp, _n in _target_csv_jobs:
                            _new_jobs.append({
                                "id":           _next_id,
                                "file_path":    _csv_path,
                                "file_name":    pathlib.Path(_csv_path).name,
                                "target_table": _bfk_tbl,
                                "mode":         _bfk_mode,
                                "fingerprint":  _fp or "",
                                "mapped_cols":  _n,
                                "status":       "ready",
                                "added":        datetime.now().isoformat()[:19],
                                "export_root":  getattr(S, "export_root", ""),
                            })
                            _next_id += 1

                        if _new_jobs:
                            queue.extend(_new_jobs)
                            _save_queue(queue)
                            _tbl_jobs = [j for j in _new_jobs if j["target_table"] == _bfk_tbl]
                            _par_jobs  = [j for j in _new_jobs if j["target_table"] != _bfk_tbl]
                            _msg = f"✅ Added {len(_new_jobs)} job(s)"
                            if _par_jobs:
                                _msg += " · FK parents: " + " → ".join(j["target_table"] for j in _par_jobs)
                            if _tbl_jobs:
                                _msg += f" · {len(_tbl_jobs)} {_bfk_tbl} file(s): " + ", ".join(j["file_name"] for j in _tbl_jobs)
                            if _skipped:
                                _msg += (f" · {len(_skipped)} FK parent table(s) skipped "
                                         f"(no CSV in folder)")
                            st.session_state["_bfk_result"] = {
                                "success": _msg,
                                "no_csv":  [],
                                "no_map":  _no_map,
                            }
                        else:
                            _bfk_errors.append(
                                "No matching CSVs found. Make sure your CSV folder contains "
                                "files that have been run through the interactive pipeline.")

                    except Exception as _e:
                        import traceback as _tb
                        _bfk_errors.append(f"CSV matching failed: {_e}\n{_tb.format_exc()}")

                # Show all info and errors
                for _msg in _bfk_info:
                    st.info(_msg)
                for _msg in _bfk_errors:
                    st.error(_msg)

                if _new_jobs or _skipped:
                    st.rerun()

        st.markdown("---")

        # ── Show FK queue build result (persists across rerun) ────────
        if st.session_state.get("_bfk_result"):
            _bfk_r = st.session_state["_bfk_result"]
            st.success(_bfk_r["success"])
            if _bfk_r.get("no_csv"):
                st.warning(f"⚠️ No CSV found for: {', '.join(_bfk_r['no_csv'])}")
            if _bfk_r.get("no_map"):
                st.warning(f"⚠️ No saved mapping for: {', '.join(_bfk_r['no_map'])} "
                           "— run interactive pipeline first.")
            if st.button("✕ Dismiss", key="bfk_dismiss"):
                del st.session_state["_bfk_result"]
                st.rerun()

        st.markdown("#### Add single job")

        c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
        with c1:
            _file_path = st.text_input("CSV file path",
                                       placeholder=r"C:\data\wells.csv",
                                       key="bulk_file_path")
        with c2:
            # Get available table names from schema
            _table_opts = []
            if ppdm_schema:
                _table_opts = ppdm_schema.all_table_names if ppdm_schema else []
            _target_tbl = st.selectbox("Target table", ["— select —"] + _table_opts,
                                       key="bulk_target_tbl")
        with c3:
            _mode = st.selectbox("Mode", ["insert", "merge"], key="bulk_mode")
        with c4:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ Add", use_container_width=True):
                if not _file_path or _target_tbl == "— select —":
                    st.error("File path and target table required.")
                else:
                    # Check fingerprint
                    fp, n_cols = _detect_fingerprint(_file_path, _target_tbl)
                    _status = "ready" if n_cols > 0 else "no_mapping"
                    queue.append({
                        "id":           len(queue) + 1,
                        "file_path":    _file_path,
                        "file_name":    pathlib.Path(_file_path).name,
                        "target_table": _target_tbl,
                        "mode":         _mode,
                        "fingerprint":  fp or "",
                        "mapped_cols":  n_cols,
                        "status":       _status,
                        "added":        datetime.now().isoformat()[:19],
                    })
                    _save_queue(queue)
                    st.rerun()

        st.markdown("---")
        st.markdown("#### ⚡ Quick fingerprint")
        st.caption(
            "Auto-maps columns by name and saves the fingerprint. "
            "Override transforms (e.g. SHA1_40) for columns like `FIELD_ID` or `BUSINESS_ASSOCIATE_ID` "
            "that need a hash key derived from another column."
        )

        _qf_c1, _qf_c2, _qf_c3 = st.columns([3, 2, 1])
        with _qf_c1:
            _qf_path = st.text_input("Reference CSV path",
                                     placeholder=r"C:\data\source_data\reference_files\r_well_class.csv",
                                     key="qf_path")
        with _qf_c2:
            _qf_tbl = st.selectbox("Target table",
                                   ["— select —"] + (_table_opts or []),
                                   key="qf_target_tbl")
        with _qf_c3:
            st.markdown("<br>", unsafe_allow_html=True)
            _qf_load = st.button("🔍 Load columns",
                                 use_container_width=True, key="qf_load")

        # ── Step 1: Load columns and show editable grid ────────────────
        _qf_grid_key = f"qf_grid_{_qf_tbl}"
        _qf_cols_key = f"qf_cols_{_qf_tbl}"

        if _qf_load and _qf_path and _qf_tbl != "— select —":
            if not pathlib.Path(_qf_path).exists():
                st.error(f"File not found: {_qf_path}")
            else:
                try:
                    import csv as _qfcsv
                    from dataview.import_data.staging import _sanitize_col, _dedupe_cols
                    from dataview.import_data.mapping import build_mapping

                    _qf_raw = pathlib.Path(_qf_path).read_bytes()
                    _qf_sample = _qf_raw[:4096].decode("utf-8-sig", errors="ignore")
                    _qf_first = _qf_sample.split('\n')[0]
                    _qf_counts = {d: _qf_first.count(d) for d in ('|', '\t', ',', ';')}
                    _qf_delim = next((d for d in ('|', '\t', ';', ',') if _qf_counts[d] > 0), ',')

                    with open(_qf_path, encoding="utf-8-sig", newline="") as _qff:
                        _qf_raw_hdrs = next(_qfcsv.reader(_qff, delimiter=_qf_delim))
                    _qf_raw_hdrs = [h.strip() for h in _qf_raw_hdrs]
                    _qf_cols = _dedupe_cols([_sanitize_col(h) for h in _qf_raw_hdrs])
                    while _qf_cols and _qf_cols[-1] in ('', 'col'):
                        _qf_cols.pop()

                    # Auto-map by exact name match
                    _qf_target_cols = (ppdm_schema.get_table(_qf_tbl).columns
                                       if ppdm_schema else [])
                    _qf_mapping = build_mapping(_qf_tbl, _qf_target_cols, _qf_cols)
                    _qf_src_upper = {c.upper(): c for c in _qf_cols}

                    _qf_grid_rows = []
                    for m in _qf_mapping.mapped:
                        _is_pk = getattr(m, "is_pk", False)
                        # Always include PK columns (compound keys need all parts mapped);
                        # skip auto_generated only for non-PK columns
                        if m.auto_generated and not _is_pk:
                            continue
                        _match = _qf_src_upper.get(m.ppdm_col.upper())
                        _qf_grid_rows.append({
                            "Target Column": ("🔑 " if _is_pk else "") + m.ppdm_col,
                            "Source Column": _match or "— skip —",
                            "Transform": "— none —",
                        })

                    # PKs first, then matched cols, then unmatched
                    _qf_grid_rows.sort(key=lambda r: (
                        0 if r["Target Column"].startswith("🔑") else
                        1 if r["Source Column"] != "— skip —" else 2,
                        r["Target Column"]
                    ))
                    # Show all rows — user needs to assign unmapped cols
                    _qf_grid_rows_show = _qf_grid_rows

                    st.session_state[_qf_grid_key] = _qf_grid_rows_show
                    st.session_state[_qf_cols_key] = _qf_cols
                except Exception as _qle:
                    st.error(f"Failed to load columns: {_qle}")

        # ── Step 2: Show editable grid if loaded ──────────────────────
        if _qf_grid_key in st.session_state and _qf_tbl != "— select —":
            _qf_cols = st.session_state.get(_qf_cols_key, [])
            _qf_xforms = ["— none —", "UPPER", "LOWER", "TRIM", "SHA1_40", "SHA1_20"]
            _qf_skip = "— skip —"
            _qf_src_opts = [_qf_skip] + _qf_cols

            _qf_n_matched = sum(1 for r in st.session_state[_qf_grid_key]
                                if r["Source Column"] != "— skip —")
            _qf_n_total   = len(st.session_state[_qf_grid_key])
            st.caption(
                f"{_qf_n_matched} of {_qf_n_total} column(s) auto-matched by name — "
                f"set Source Column for the rest, then click Save."
            )

            _qf_edited = st.data_editor(
                pd.DataFrame(st.session_state[_qf_grid_key]),
                use_container_width=True,
                hide_index=True,
                key=f"qf_editor_{_qf_tbl}",
                column_config={
                    "Target Column": st.column_config.TextColumn(disabled=True, width="medium"),
                    "Source Column": st.column_config.SelectboxColumn(
                        options=_qf_src_opts, width="medium"),
                    "Transform": st.column_config.SelectboxColumn(
                        options=_qf_xforms, width="small"),
                }
            )
            # Don't update session state here — only update on Save click
            # to prevent edits being lost on rerender

            _qf_save = st.button("⚡ Save fingerprint",
                                 type="primary", use_container_width=True, key="qf_run")

            # Sync data_editor edits into session state on every render
            # so Save button always reads the latest user edits
            _qf_editor_key = f"qf_editor_{_qf_tbl}"
            if _qf_editor_key in st.session_state:
                st.session_state[f"qf_edited_{_qf_tbl}"] = (
                    _qf_edited.to_dict("records")
                )

            if _qf_save:
                try:
                    from dataview.import_data.mapping import (build_mapping, mapping_fingerprint,
                                                 save_mapping_to_disk)
                    from dataview.import_data.staging import _sanitize_col, _dedupe_cols

                    _qf_target_cols = (ppdm_schema.get_table(_qf_tbl).columns
                                       if ppdm_schema else [])
                    _qf_mapping = build_mapping(_qf_tbl, _qf_target_cols, _qf_cols)

                    # Read from synced session state — more reliable than widget on Save click
                    _qf_current_rows = (
                        st.session_state.get(f"qf_edited_{_qf_tbl}")
                        or _qf_edited.to_dict("records")
                    )
                    _n_mapped = 0
                    for m in _qf_mapping.mapped:
                        _is_pk = getattr(m, "is_pk", False)
                        if m.auto_generated and not _is_pk:
                            continue
                        for _row in _qf_current_rows:
                            _tc = _row["Target Column"].lstrip("🔑 ").strip()
                            if _tc.upper() == m.ppdm_col.upper():
                                _sc = _row.get("Source Column", _qf_skip)
                                _xf = _row.get("Transform", "— none —")
                                if _sc and _sc != _qf_skip:
                                    m.source_col = _sc
                                    m.transform  = "" if _xf == "— none —" else _xf
                                    _n_mapped += 1
                                break

                    if _n_mapped == 0:
                        st.error(
                            "⚠️ No columns were mapped — all Source Columns are set to "
                            "'— skip —'. Assign at least one Source Column in the grid "
                            "before saving."
                        )
                        st.stop()

                    # Save both fingerprint variants
                    _qf_fp  = mapping_fingerprint(_qf_tbl, _qf_cols + ["_batch_loaded_at"])
                    save_mapping_to_disk(_qf_fp, _qf_mapping)
                    _qf_fp2 = mapping_fingerprint(_qf_tbl, _qf_cols)
                    save_mapping_to_disk(_qf_fp2, _qf_mapping)

                    st.success(
                        f"✅ Fingerprint saved for **{_qf_tbl}** — "
                        f"{_n_mapped} column(s) mapped. Key: `{_qf_fp}`"
                    )
                    st.caption(
                        f"Key built from {len(_qf_cols)} cols (sorted): "
                        f"`{'`, `'.join(sorted(c.upper() for c in _qf_cols)[:8])}`"
                        f"{'…' if len(_qf_cols) > 8 else ''}"
                    )
                    # Refresh queue
                    for _qj in queue:
                        if (_qj["target_table"] == _qf_tbl
                                and _qj["status"] == "no_mapping"):
                            _fp2, _n2 = _detect_fingerprint(
                                _qj["file_path"], _qj["target_table"])
                            _qj["fingerprint"] = _fp2 or ""
                            _qj["mapped_cols"] = _n2
                            _qj["status"] = "ready" if _n2 > 0 else "no_mapping"
                    _save_queue(queue)
                    # Clear grid
                    st.session_state.pop(_qf_grid_key, None)
                    st.session_state.pop(_qf_cols_key, None)
                    st.rerun()
                except Exception as _qfe:
                    import traceback as _qftb
                    st.error(f"Failed: {_qfe}\n{_qftb.format_exc()}")

        # ── Queue table ────────────────────────────────────────────────
        if not queue:
            st.info("Queue is empty. Add jobs above.")
        else:
            _status_icon = {"ready": "✅", "no_mapping": "⚠️",
                            "running": "🔄", "done": "✅", "failed": "❌"}
            _status_color = {"ready": "#166534", "no_mapping": "#92400e",
                             "running": "#1e40af", "done": "#166534", "failed": "#991b1b"}
            _status_bg    = {"ready": "#dcfce7", "no_mapping": "#fef3c7",
                             "running": "#dbeafe", "done": "#dcfce7", "failed": "#fee2e2"}

            # ── Compact HTML table ────────────────────────────────────
            _rows_html = ""
            for j in queue:
                _st   = j["status"]
                _icon = _status_icon.get(_st, "❓")
                _tc   = _status_color.get(_st, "#374151")
                _bg   = _status_bg.get(_st, "#f9fafb")
                _rows_html += (
                    f'<tr style="border-bottom:1px solid #f3f4f6">'
                    f'<td style="padding:5px 8px;color:#9ca3af;width:32px;text-align:center">'
                    f'{j["id"]}</td>'
                    f'<td style="padding:5px 8px;font-size:13px;max-width:220px;overflow:hidden;'
                    f'text-overflow:ellipsis;white-space:nowrap" title="{j["file_name"]}">'
                    f'{j["file_name"]}</td>'
                    f'<td style="padding:5px 8px">'
                    f'<code style="font-size:12px;background:#f1f5f9;padding:1px 5px;'
                    f'border-radius:4px">{j["target_table"]}</code></td>'
                    f'<td style="padding:5px 8px;color:#6b7280;font-size:13px;text-align:center">'
                    f'{j["mode"]}</td>'
                    f'<td style="padding:5px 8px;color:#6b7280;font-size:13px;text-align:center">'
                    f'{j["mapped_cols"]}</td>'
                    f'<td style="padding:5px 8px">'
                    f'<span style="background:{_bg};color:{_tc};padding:2px 8px;'
                    f'border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap">'
                    f'{_icon} {_st}</span></td>'
                    f'<td style="padding:5px 4px;width:32px"></td>'
                    f'</tr>'
                )

            st.markdown(
                f'<table style="width:100%;border-collapse:collapse;font-size:13px;'
                f'background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;'
                f'overflow:hidden">'
                f'<thead><tr style="background:#f9fafb;border-bottom:2px solid #e5e7eb">'
                f'<th style="padding:7px 8px;color:#6b7280;font-size:11px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.05em;width:32px;text-align:center">#</th>'
                f'<th style="padding:7px 8px;color:#6b7280;font-size:11px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.05em;text-align:left">File</th>'
                f'<th style="padding:7px 8px;color:#6b7280;font-size:11px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.05em;text-align:left">Target Table</th>'
                f'<th style="padding:7px 8px;color:#6b7280;font-size:11px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.05em;text-align:center">Mode</th>'
                f'<th style="padding:7px 8px;color:#6b7280;font-size:11px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.05em;text-align:center">Cols</th>'
                f'<th style="padding:7px 8px;color:#6b7280;font-size:11px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:.05em;text-align:left">Status</th>'
                f'<th style="width:32px"></th>'
                f'</tr></thead>'
                f'<tbody>{_rows_html}</tbody>'
                f'</table>',
                unsafe_allow_html=True
            )

            # Selectbox remove — clean single control, no floating button alignment issues
            _del_opts = {f"#{j['id']} — {j['file_name']} → {j['target_table']}": j["id"]
                         for j in queue}
            _del_c1, _del_c2 = st.columns([4, 1])
            with _del_c1:
                _del_sel = st.selectbox("Remove job", list(_del_opts.keys()),
                                        key="bulk_del_sel", label_visibility="collapsed")
            with _del_c2:
                if st.button("🗑 Remove", key="bulk_del_btn", use_container_width=True):
                    _del_jid = _del_opts.get(_del_sel)
                    if _del_jid:
                        queue = [j for j in queue if j["id"] != _del_jid]
                        _save_queue(queue)
                        st.rerun()

            # ── Metrics ───────────────────────────────────────────────
            st.markdown('<div style="margin-top:4px"></div>', unsafe_allow_html=True)
            _n_ready   = sum(1 for j in queue if j["status"] == "ready")
            _n_nomap   = sum(1 for j in queue if j["status"] == "no_mapping")
            mrow([
                ("Total jobs",  len(queue),  "#79c0ff"),
                ("Ready",       _n_ready,    "#56d364"),
                ("No mapping",  _n_nomap,    "#f0883e"),
                ("Done/Failed", len(queue) - _n_ready - _n_nomap, "#8b949e"),
            ])

            if _n_nomap:
                st.warning(
                    f"⚠️ {_n_nomap} job(s) have no saved mapping. "
                    "The source file's columns don't match any saved fingerprint for that table. "
                    "Use **⚡ Quick Fingerprint** above to map this file, or run the "
                    "interactive pipeline with this file first."
                )
                # Per-job diagnostic — show what's cached for each unmapped table
                try:
                    from dataview.import_data.mapping import _load_cache, mapping_fingerprint
                    from dataview.import_data.staging import _sanitize_col, _dedupe_cols
                    import csv as _dcsv
                    _cache = _load_cache()
                    _nomap_jobs = [j for j in queue if j["status"] == "no_mapping"]
                    for _nmj in _nomap_jobs:
                        _tbl = _nmj["target_table"]
                        _fp  = _nmj.get("fingerprint", "")
                        # Find cached fingerprints for this target table via _meta
                        _cached_for_tbl = [
                            k for k, v in _cache.items()
                            if isinstance(v, dict)
                            and v.get("_meta", {}).get("target_table", "").lower() == _tbl.lower()
                        ]
                        # Get source cols from the file
                        _src_cols_str = ""
                        try:
                            with open(_nmj["file_path"], encoding="utf-8-sig", newline="") as _f:
                                _sample = _f.read(2048)
                            _first = _sample.split('\n')[0]
                            _counts = {d: _first.count(d) for d in ('|','	',',',';')}
                            _delim = next((d for d in ('|','	',';',',') if _counts[d]>0), ',')
                            with open(_nmj["file_path"], encoding="utf-8-sig", newline="") as _f:
                                _hdrs = next(_dcsv.reader(_f, delimiter=_delim))
                            _cols = _dedupe_cols([_sanitize_col(h.strip()) for h in _hdrs])
                            _src_cols_str = f"{len(_cols)} cols: `{'`, `'.join(_cols[:5])}{'…' if len(_cols)>5 else ''}`"
                        except Exception:
                            _src_cols_str = "could not read file"
                        if _cached_for_tbl:
                            # Mapping exists for this table but different source columns
                            _cached_cols = []
                            for _ck in _cached_for_tbl[:1]:
                                _cached_cols = list(_cache[_ck].get("_meta", {}).get("mapped_cols", []))
                            st.info(
                                f"**#{_nmj['id']} {_tbl}** — fingerprint mismatch. "
                                f"File has {_src_cols_str}. "
                                f"Cached mapping: {len(_cached_cols)} cols "
                                f"(`{', '.join(_cached_cols[:5])}{"…" if len(_cached_cols)>5 else ""}`). "
                                "Use **⚡ Quick Fingerprint** above with this file to remap."
                            )
                        else:
                            st.info(
                                f"**#{_nmj['id']} {_tbl}** — no cached mapping for this table. "
                                f"File has {_src_cols_str}. "
                                "Run the interactive pipeline with this file, "
                                "or use **⚡ Quick Fingerprint** above."
                            )
                except Exception as _de:
                    st.caption(f"Diagnostic error: {_de}")

            # ── Action buttons ────────────────────────────────────────
            st.markdown("---")
            _ab1, _ab2, _ab3, _ab4, _ab5 = st.columns([2, 1.2, 1.2, 1.2, 1.2])
            with _ab1:
                if st.button("▶ Run Queue Now", type="primary",
                             use_container_width=True, key="bulk_run_from_queue",
                             disabled=_n_ready == 0):
                    st.session_state["bulk_run_triggered"] = True
                    st.rerun()
            with _ab2:
                if st.button("📜 History", use_container_width=True,
                             key="bulk_hist_from_queue"):
                    st.session_state["bulk_switch_to_hist"] = True
                    st.rerun()
            with _ab3:
                if st.button("🗑️ Clear done/failed", use_container_width=True,
                             key="bulk_clear_done"):
                    queue = [j for j in queue if j["status"] not in ("done", "failed")]
                    _save_queue(queue)
                    st.rerun()
            with _ab4:
                if st.button("🗑️ Clear all", use_container_width=True,
                             key="bulk_clear_all"):
                    _save_queue([])
                    st.rerun()
            with _ab5:
                if st.button("🔄 Refresh", use_container_width=True,
                             key="bulk_refresh_fp"):
                    for j in queue:
                        if j["status"] in ("ready", "no_mapping"):
                            fp, n = _detect_fingerprint(j["file_path"], j["target_table"])
                            j["fingerprint"] = fp or ""
                            j["mapped_cols"] = n
                            j["status"] = "ready" if n > 0 else "no_mapping"
                    _save_queue(queue)
                    st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # TAB 2 · RUN
    # ══════════════════════════════════════════════════════════════════════
    with tab_run:
        _ready_jobs = [j for j in queue if j["status"] == "ready"]

        if not _ready_jobs:
            st.info("No ready jobs in the queue. Add jobs in the Queue tab.")
        else:
            st.markdown(f"**{len(_ready_jobs)} job(s) ready to run.**")
            _stop_on_error = st.checkbox("Stop on first error", value=False,
                                         key="bulk_stop_on_error")

            _run_col, _stop_col = st.columns([3, 1])
            with _run_col:
                _run_clicked = st.button(f"▶ Run {len(_ready_jobs)} job(s) now",
                             type="primary", use_container_width=True,
                             key="bulk_run_now")

            with _stop_col:
                if st.button("⏹ Stop", use_container_width=True, key="bulk_stop_btn"):
                    st.session_state["_bulk_cancel"] = True
                    st.rerun()

            if st.session_state.get("_bulk_cancel"):
                st.session_state["_bulk_cancel"] = False

            if _run_clicked:

                _STAGE_NAMES = ["Ingest","Stage","Normalize","Map","FK Seed","FK Check","Validate","Promote","Done"]
                _STAGE_PCTS  = [5, 15, 25, 40, 50, 55, 70, 85, 100]

                # Colors: done=green, running=blue, failed=red, waiting=gray
                _C = {
                    "done":    ("#166534","#16a34a","#dcfce7"),   # dark,border,bg
                    "running": ("#1e40af","#3b82f6","#dbeafe"),
                    "failed":  ("#991b1b","#ef4444","#fee2e2"),
                    "waiting": ("#6b7280","#d1d5db","#f9fafb"),
                }
                _ICONS = {"done":"✅","running":"🔄","failed":"❌","waiting":"○"}

                def _pipeline_html(current_stage, failed_stage=None, rows=0, elapsed_s=0, detail=""):
                    _sidx = _STAGE_NAMES.index(current_stage) if current_stage in _STAGE_NAMES else -1
                    _pct  = _STAGE_PCTS[_sidx] if 0 <= _sidx < len(_STAGE_PCTS) else 0

                    # Build cards + arrows
                    _cards_html = '<div style="display:flex;align-items:center;gap:0;flex-wrap:nowrap;">'
                    for _si, (_sn, _sp) in enumerate(zip(_STAGE_NAMES, _STAGE_PCTS)):
                        if failed_stage and _sn == failed_stage:
                            _st = "failed"
                        elif _si < _sidx:
                            _st = "done"
                        elif _si == _sidx:
                            _st = "running"
                        else:
                            _st = "waiting"
                        _tc, _bd, _bg = _C[_st]
                        _icon = _ICONS[_st]
                        if _sn == "Done" and _st == "done" and rows:
                            _extra = f"{rows:,} rows"
                        elif _st == "running" and _sn == "FK Seed" and detail:
                            _extra = detail[:20]
                        elif _st == "running" and elapsed_s > 0:
                            _extra = f"{elapsed_s}s…"
                        else:
                            _extra = f"{_sp}%"
                        _style = (f"background:{_bg};border:2px solid {_bd};border-radius:8px;"
                                  f"padding:8px 4px;text-align:center;min-width:68px;flex:1;")
                        if _st == "running":
                            _style += "box-shadow:0 0 0 3px rgba(59,130,246,0.3);"
                        _cards_html += (
                            f'<div style="{_style}">'
                            f'<div style="font-size:18px;line-height:1">{_icon}</div>'
                            f'<div style="font-size:11px;font-weight:700;color:{_tc};margin-top:3px">{_sn}</div>'
                            f'<div style="font-size:10px;color:{_tc};font-weight:500">{_extra}</div>'
                            f'</div>'
                        )
                        if _si < len(_STAGE_NAMES) - 1:
                            _arr_col = _bd if _si < _sidx else "#d1d5db"
                            _cards_html += (
                                f'<div style="color:{_arr_col};font-size:18px;font-weight:700;'
                                f'padding:0 2px;flex-shrink:0;line-height:1;margin-top:-4px">›</div>'
                            )
                    _cards_html += '</div>'

                    # Progress bar — animate width for running stage
                    _bar_pct  = _pct
                    _bar_extra = ""
                    if elapsed_s > 0 and current_stage == "Normalize":
                        _bar_extra = (
                            f'<div style="font-size:10px;color:#1e40af;margin-top:2px">'
                            f'⏱ Normalizing on server… {elapsed_s}s elapsed'
                            f'{(" · " + detail) if detail else ""}</div>'
                        )
                    _bar = (
                        f'<div style="margin-top:8px;background:#e5e7eb;border-radius:6px;height:8px;">'
                        f'<div style="background:linear-gradient(90deg,#2563eb,#16a34a);'
                        f'border-radius:6px;height:8px;width:{_bar_pct}%;transition:width 0.4s ease;"></div>'
                        f'</div>'
                        f'<div style="font-size:10px;color:#6b7280;text-align:right;margin-top:2px">'
                        f'{_bar_pct}% complete</div>'
                        f'{_bar_extra}'
                    )

                    return (
                        f'<div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;'
                        f'padding:12px 14px;margin:4px 0 8px;">'
                        f'{_cards_html}{_bar}</div>'
                    )

                _overall_ph = st.empty()
                _results = []

                for _job in _ready_jobs:
                    st.markdown(
                        f'<div style="font-size:13px;font-weight:700;margin:12px 0 4px;">'
                        f'📄 {_job["file_name"]} &nbsp;→&nbsp; <code>{_job["target_table"]}</code></div>',
                        unsafe_allow_html=True)

                    _pipeline_ph  = st.empty()
                    _fk_detail_ph = st.empty()  # sub-line for FK seed activity
                    _pipeline_ph.markdown(_pipeline_html("Ingest"), unsafe_allow_html=True)

                    _norm_start    = [0.0]
                    _norm_detail   = [""]
                    _current_stage = ["Ingest"]
                    _cancelled     = [False]
                    _fk_seed_detail = [""]
                    _fk_seed_log   = []  # cumulative list of seeded tables

                    def _progress_cb(msg, pct, _ph=_pipeline_ph):
                        # Only update shared state — never call st.* from thread
                        if msg == "Normalize" or msg.startswith("Normalize"):
                            if _norm_start[0] == 0:
                                _norm_start[0] = time.time()
                            if ":" in msg:
                                _norm_detail[0] = msg.split(":", 1)[1].strip()
                            elif "·" in msg:
                                _norm_detail[0] = msg.split("·", 1)[1].strip()
                            _current_stage[0] = "Normalize"
                        elif msg.startswith("FK Seed"):
                            # Detail message from Step 5b e.g. "FK Seed field: +793 new"
                            _detail_part = msg.split("FK Seed ", 1)
                            _det = _detail_part[1].strip() if len(_detail_part) > 1 else ""
                            if _det:
                                _fk_seed_detail[0] = _det
                                if _det not in _fk_seed_log:
                                    _fk_seed_log.append(_det)
                            _current_stage[0] = "FK Seed"
                        else:
                            if msg == "FK Check":
                                _fk_seed_detail[0] = ""  # clear seed detail
                            _current_stage[0] = msg

                    import threading as _thr
                    _job_result = [None]
                    _job_done   = [False]

                    def _run_thread():
                        _job_result[0] = run_job(_job, engine, ppdm_schema, _progress_cb,
                                                  cancel_flag=_cancelled)
                        _job_done[0]   = True

                    _t = _thr.Thread(target=_run_thread, daemon=True)
                    _t.start()

                    _stop_ph = st.empty()
                    while not _job_done[0]:
                        if st.session_state.get("_bulk_cancel"):
                            _cancelled[0] = True
                            st.session_state["_bulk_cancel"] = False
                            _stop_ph.warning("⏹ Cancelling after current statement…")
                        _stage = _current_stage[0]
                        if _stage == "Normalize" and _norm_start[0] > 0:
                            _elapsed = int(time.time() - _norm_start[0])
                            _pipeline_ph.markdown(
                                _pipeline_html("Normalize", elapsed_s=_elapsed,
                                               detail=_norm_detail[0]),
                                unsafe_allow_html=True)
                        else:
                            _pipeline_ph.markdown(
                                _pipeline_html(_stage), unsafe_allow_html=True)
                        # Show cumulative FK seed log below pipeline bar
                        if _fk_seed_log:
                            _log_html = " &nbsp;·&nbsp; ".join(
                                f"🌱 {e}" for e in _fk_seed_log)
                            _fk_detail_ph.markdown(
                                f'<div style="font-size:12px;color:#1e40af;padding:2px 0 4px 4px;">'
                                f'{_log_html}</div>',
                                unsafe_allow_html=True)
                        time.sleep(0.25)

                    _t.join()
                    _stop_ph.empty()
                    _fk_detail_ph.empty()
                    _result = _job_result[0] or {"ok": False, "message": "Job thread failed",
                                                  "rows_inserted": 0, "rows_skipped": 0,
                                                  "rows_error": 0, "duration_s": 0}
                    _result["job"]    = _job
                    _result["ran_at"] = datetime.now().isoformat()[:19]
                    _results.append(_result)

                    if _result["ok"]:
                        _pipeline_ph.markdown(
                            _pipeline_html("Done", rows=_result.get("rows_inserted", 0)),
                            unsafe_allow_html=True)
                        # Show FK seed results
                        _fk_seeded = _result.get("fk_seeded", [])
                        if _fk_seeded:
                            st.caption(f"🌱 FK seeded: {' · '.join(_fk_seeded)}")
                        _fk_seed_err = _result.get("fk_seed_err")
                        if _fk_seed_err:
                            st.caption(f"⚠️ FK seed error: {_fk_seed_err[:200]}")
                        _ref_needed = _result.get("ref_tables_needed", [])
                        if _ref_needed:
                            st.warning(
                                f"⛔ Reference table(s) not seeded: **{', '.join(_ref_needed)}**\n\n"
                                f"Open **Stage 6 → RTM** in the interactive app to seed these, then re-run."
                            )
                        # Show stage timings
                        _st = _result.get("stage_times", {})
                        if _st:
                            _timing_str = " · ".join(
                                f"{k}: {v}s" for k, v in _st.items())
                            st.caption(f"⏱ Stage timings: {_timing_str}")
                    else:
                        # Detect which stage failed from message
                        _msg = _result.get("message", "")
                        _fail_stg = next(
                            (s for s in _STAGE_NAMES if s.lower() in _msg.lower()), "Promote")
                        _pipeline_ph.markdown(
                            _pipeline_html(_fail_stg, failed_stage=_fail_stg),
                            unsafe_allow_html=True)

                    for _qj in queue:
                        if _qj["id"] == _job["id"]:
                            _qj["status"] = "done" if _result["ok"] else "failed"
                    _save_queue(queue)

                    if not _result["ok"] and _stop_on_error:
                        _overall_ph.error(f"Stopped after error on {_job['file_name']}.")
                        break

                _ok_count   = sum(1 for r in _results if r["ok"])
                _fail_count = len(_results) - _ok_count
                _total_rows = sum(r.get("rows_inserted", 0) for r in _results)
                # Collect all FK seed activity across all jobs
                _all_seeded = []
                for _r in _results:
                    _all_seeded.extend(_r.get("fk_seeded", []))
                _seed_summary = f" · 🌱 FK seeded: {', '.join(_all_seeded)}" if _all_seeded else ""
                if _fail_count == 0:
                    _overall_ph.success(f"✅ All {_ok_count} job(s) complete — {_total_rows:,} rows inserted.{_seed_summary}")
                else:
                    _overall_ph.warning(f"⚠️ {_ok_count} succeeded, {_fail_count} failed — {_total_rows:,} rows inserted.{_seed_summary}")

                _hist = _load_history()
                # Write one entry per job — same format as bulk_runner.py
                for _r in _results:
                    _hist.insert(0, {
                        "completed":     datetime.now().isoformat()[:19],
                        "file_name":     _r["job"]["file_name"],
                        "target_table":  _r["job"]["target_table"],
                        "status":        "done" if _r["ok"] else "failed",
                        "message":       _r.get("message", ""),
                        "rows_inserted": _r.get("rows_inserted", 0),
                        "rows_skipped":  _r.get("rows_skipped", 0),
                        "duration_s":    _r.get("duration_s", 0),
                        "stage_times":   _r.get("stage_times", {}),
                        "fk_seeded":     _r.get("fk_seeded", []),
                        "fk_seed_err":   _r.get("fk_seed_err", ""),
                    })
                _HISTORY_FILE.write_text(json.dumps(_hist[:200], indent=2), encoding="utf-8")
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # TAB 3 · HISTORY
    # ══════════════════════════════════════════════════════════════════════
    with tab_history:
        # Clear nav flag — user must click History tab manually (Streamlit limitation)
        st.session_state.pop("bulk_switch_to_hist", None)
        if not history:
            st.info("No run history yet.")
        else:
            # Summary table
            _hist_rows = []
            for _h in history[:50]:
                _hist_rows.append({
                    "Completed":      _h.get("completed", _h.get("ran_at", "-")),
                    "File":           _h.get("file_name", "-"),
                    "Table":          _h.get("target_table", "-"),
                    "Status":         "✅" if _h.get("status") == "done" else "❌",
                    "Rows inserted":  _h.get("rows_inserted", 0),
                    "Duration (s)":   _h.get("duration_s", 0),
                })
            if _hist_rows:
                st.dataframe(pd.DataFrame(_hist_rows), use_container_width=True,
                             hide_index=True)

            # Detail for most recent runs
            if history:
                with st.expander("Latest run detail", expanded=True):
                    _detail_jobs = history[:10]
                    for _r in _detail_jobs:
                        _ok   = _r.get("status") == "done"
                        _icon = "✅" if _ok else "❌"
                        _ins  = _r.get("rows_inserted", 0)
                        _skp  = _r.get("rows_skipped", 0)
                        _dur  = _r.get("duration_s", 0)
                        _fn   = _r.get("file_name", "")
                        _tbl  = _r.get("target_table", "")
                        st.markdown(
                            f"{_icon} **{_fn}** → **{_tbl}** — "
                            f"{_ins:,} inserted · {_skp:,} skipped · {_dur}s"
                        )
                        _st = _r.get("stage_times", {})
                        if _st:
                            _timing_str = " · ".join(
                                f"{k}: {v}s" for k, v in _st.items()
                                if isinstance(v, (int, float)))
                            _fk_d = _st.get("fk_detail", {})
                            _fk_str = (f" | FK: intro={_fk_d.get('intro')}s "
                                      f"count={_fk_d.get('count')}s "
                                      f"parents={_fk_d.get('n_parents')} "
                                      f"satisfied={_fk_d.get('n_satisfied')} "
                                      f"unsatisfied={_fk_d.get('unsatisfied',[])} "
                                      f"unchecked={_fk_d.get('unchecked',[])} "
                                      f"err={_fk_d.get('count_err','')}") if _fk_d else ""
                            st.caption(f"⏱ {_timing_str}{_fk_str}")
                        _fk_seeded = _r.get("fk_seeded", [])
                        if _fk_seeded:
                            st.caption(f"🌱 FK seeded: {' · '.join(_fk_seeded)}")
                        _fk_se = _r.get("fk_seed_err")
                        if _fk_se:
                            st.caption(f"⚠️ FK seed error: {_fk_se[:300]}")
                        if not _ok:
                            st.caption(_r.get("message","")[:400])

            if st.button("🗑️ Clear history", key="bulk_clear_hist"):
                _HISTORY_FILE.write_text("[]", encoding="utf-8")
                st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # TAB 4 · SCHEDULE
    # ══════════════════════════════════════════════════════════════════════
    with tab_schedule:
        st.markdown("#### File watcher")
        st.caption("Monitors a folder and auto-adds new CSVs to the queue.")

        _wcfg = _load_watcher_cfg()
        _w_folder  = st.text_input("Watch folder",
                                   value=_wcfg.get("folder", ""),
                                   placeholder=r"C:\data\incoming",
                                   key="bulk_watch_folder")
        _w_pattern = st.text_input("File pattern", value=_wcfg.get("pattern", "*.csv"),
                                   key="bulk_watch_pattern")
        _w_table   = st.selectbox(
            "Default target table (for new files)",
            ["— select —"] + (ppdm_schema.all_table_names if ppdm_schema else []),
            key="bulk_watch_table"
        )
        _w_enabled = st.toggle("Enable file watcher",
                               value=_wcfg.get("enabled", False),
                               key="bulk_watch_enabled")

        if st.button("💾 Save watcher config", key="bulk_save_watcher"):
            _save_watcher_cfg({
                "folder":        _w_folder,
                "pattern":       _w_pattern,
                "default_table": _w_table if _w_table != "— select —" else "",
                "enabled":       _w_enabled,
            })
            st.success("Watcher config saved.")

        st.markdown("---")
        st.markdown("#### Windows Task Scheduler")
        st.caption(
            "Run the queue automatically on a schedule using `bulk_runner.py`. "
            "No Streamlit required — runs headless."
        )

        _runner_path = _BASE_DIR / "bulk_runner.py"
        _python_path = "python"

        st.code(
            f'# Run the queue once (add to Task Scheduler)\n'
            f'{_python_path} "{_runner_path}" '
            f'--db-server PERRY\\SQLEXPRESS '
            f'--db-name PPDM39_DEMO_1 '
            f'--windows-auth\n\n'
            f'# With file watcher (runs continuously)\n'
            f'{_python_path} "{_runner_path}" '
            f'--db-server PERRY\\SQLEXPRESS '
            f'--db-name PPDM39_DEMO_1 '
            f'--windows-auth --watch',
            language="bash"
        )

        st.markdown(
            "**Task Scheduler setup:**\n"
            "1. Open Task Scheduler → Create Basic Task\n"
            "2. Set trigger (Daily, Weekly, or On startup)\n"
            "3. Action: Start a program → `python.exe`\n"
            f"4. Arguments: `\"{_runner_path}\" --db-server ... --windows-auth`\n"
            "5. The queue and history files are shared with this page"
        )

    # ══════════════════════════════════════════════════════════════════════
    # TAB 5 · MAINTENANCE
    # ══════════════════════════════════════════════════════════════════════
    with tab_maint:
        st.markdown("#### 🧹 Temp File Cleanup")
        st.caption(
            "Removes staging temp files from the Bulk folder and bad row reports "
            "from the project folder. Reference catalog CSVs are never deleted."
        )

        _bulk_dir = pathlib.Path(getattr(S, "import_root", "") or r"C:\Bulk")
        _proj_dir = pathlib.Path(__file__).parent

        # Scan temp files
        _stg_csvs  = sorted(_bulk_dir.glob("stage_stg_*.csv"))   if _bulk_dir.exists() else []
        _bad_lines = sorted(_bulk_dir.glob("stage_stg_*_bad_lines.csv")) if _bulk_dir.exists() else []
        _bad_rows  = sorted(_proj_dir.glob("bad_rows_*.csv"))

        _mc1, _mc2, _mc3 = st.columns(3)
        with _mc1:
            st.metric("Staging temp files", len(_stg_csvs))
        with _mc2:
            st.metric("Bad line reports", len(_bad_lines))
        with _mc3:
            st.metric("Bad row reports", len(_bad_rows))

        _days = st.slider("Delete files older than (days)", 0, 30, 7, key="maint_days")

        if st.button("🧹 Clean up temp files", key="maint_clean", type="primary"):
            import time as _tm
            _now  = _tm.time()
            _cutoff = _now - (_days * 86400)
            _deleted = []
            _errors  = []
            for _f in _stg_csvs + _bad_lines + _bad_rows:
                try:
                    if _f.stat().st_mtime < _cutoff:
                        _f.unlink()
                        _deleted.append(_f.name)
                except Exception as _de:
                    _errors.append(f"{_f.name}: {_de}")
            if _deleted:
                st.success(f"✅ Deleted {len(_deleted)} file(s): {', '.join(_deleted[:10])}"
                           + (f" + {len(_deleted)-10} more" if len(_deleted) > 10 else ""))
            else:
                st.info(f"No files older than {_days} day(s) found.")
            if _errors:
                st.warning(f"⚠️ {len(_errors)} error(s): {'; '.join(_errors[:3])}")

        st.markdown("---")
        st.markdown("#### 🗂 Mapping Cache")

        from dataview.import_data.mapping import _load_cache as _lc_maint, _save_cache as _sc_maint
        _maint_cache = _lc_maint()
        _cache_path  = pathlib.Path(__file__).parent / "modules" / "mapping_cache.json"
        _cache_size  = _cache_path.stat().st_size / 1024 if _cache_path.exists() else 0
        _rtm_fps     = [k for k in _maint_cache if k.startswith("RTM_")]
        _pipe_fps    = [k for k in _maint_cache if not k.startswith("RTM_")]

        _cc1, _cc2, _cc3 = st.columns(3)
        with _cc1:
            st.metric("Pipeline fingerprints", len(_pipe_fps))
        with _cc2:
            st.metric("RTM fingerprints", len(_rtm_fps))
        with _cc3:
            st.metric("Cache size", f"{_cache_size:.1f} KB")

        # Identify orphaned fingerprints — no CSV in watch folders
        _watch_dirs = []
        if getattr(S, "import_root", ""):
            _watch_dirs.append(pathlib.Path(S.import_root))
        _all_watch_csvs = []
        for _wd in _watch_dirs:
            if _wd.exists():
                _all_watch_csvs += list(_wd.glob("*.csv"))

        if _all_watch_csvs and _maint_cache:
            from dataview.import_data.staging import _sanitize_col, _dedupe_cols
            import csv as _mcsv
            _known_fps = set()
            for _wcsv in _all_watch_csvs:
                try:
                    with open(_wcsv, encoding="utf-8-sig", newline="") as _wf:
                        _wsample = _wf.read(4096)
                    _wfirst = _wsample.split('\n')[0]
                    _wcounts = {d: _wfirst.count(d) for d in ('|', '\t', ',', ';')}
                    _wdelim = next((d for d in ('|', '\t', ';', ',') if _wcounts[d] > 0), ',')
                    with open(_wcsv, encoding="utf-8-sig", newline="") as _wf:
                        _whdrs = next(_mcsv.reader(_wf, delimiter=_wdelim))
                    _whdrs = [h.strip() for h in _whdrs]
                    _wcols = _dedupe_cols([_sanitize_col(h) for h in _whdrs])
                    while _wcols and _wcols[-1] in ('', 'col'):
                        _wcols.pop()
                    from dataview.import_data.mapping import mapping_fingerprint as _mfp
                    for _tbl_n in ([_wcsv.stem] + list(_maint_cache.keys())):
                        _known_fps.add(_mfp(_tbl_n, _wcols + ["_batch_loaded_at"]))
                        _known_fps.add(_mfp(_tbl_n, _wcols))
                except Exception:
                    continue

            _orphaned = [k for k in _pipe_fps if k not in _known_fps]
            if _orphaned:
                st.warning(f"⚠️ {len(_orphaned)} orphaned pipeline fingerprint(s) — "
                           f"no matching CSV found in watch folders.")
                if st.button("🗑 Remove orphaned fingerprints", key="maint_orphan"):
                    for _ok in _orphaned:
                        _maint_cache.pop(_ok, None)
                    _sc_maint(_maint_cache)
                    st.success(f"✅ Removed {len(_orphaned)} orphaned fingerprint(s).")
                    st.rerun()
            else:
                st.info("✅ No orphaned fingerprints found.")
        else:
            st.caption("Configure import/export folders in Settings to enable orphan detection.")

        if st.button("🗑 Clear entire cache", key="maint_clear_cache"):
            _sc_maint({})
            st.success("✅ Mapping cache cleared.")
            st.rerun()

    # ══════════════════════════════════════════════════════════════════════
    # RUN EXECUTION — fires from Queue tab "Run Queue Now" OR Run tab button
    # Rendered outside tabs so progress display is always visible
    # ══════════════════════════════════════════════════════════════════════
    _run_triggered = st.session_state.pop("bulk_run_triggered", False)
    if _run_triggered:
        _ready_jobs = [j for j in queue if j["status"] == "ready"]
        if not _ready_jobs:
            st.warning("No ready jobs to run.")
        else:
            _stop_on_error = st.session_state.get("bulk_stop_on_error", False)

            _STAGE_NAMES = ["Ingest","Stage","Normalize","Map","FK Check","Validate","Promote","Done"]
            _STAGE_PCTS  = [5, 15, 30, 40, 55, 70, 85, 100]
            _C = {
                "done":    ("#166534","#16a34a","#dcfce7"),
                "running": ("#1e40af","#3b82f6","#dbeafe"),
                "failed":  ("#991b1b","#ef4444","#fee2e2"),
                "waiting": ("#6b7280","#d1d5db","#f9fafb"),
            }
            _ICONS = {"done":"✅","running":"🔄","failed":"❌","waiting":"○"}

            def _pipeline_html_ex(current_stage, failed_stage=None, rows=0, elapsed_s=0, detail=""):
                _sidx = _STAGE_NAMES.index(current_stage) if current_stage in _STAGE_NAMES else -1
                _pct  = _STAGE_PCTS[_sidx] if 0 <= _sidx < len(_STAGE_PCTS) else 0
                _cards_html = '<div style="display:flex;align-items:center;gap:0;flex-wrap:nowrap;">'
                for _si, (_sn, _sp) in enumerate(zip(_STAGE_NAMES, _STAGE_PCTS)):
                    if failed_stage and _sn == failed_stage:
                        _st2 = "failed"
                    elif _si < _sidx:
                        _st2 = "done"
                    elif _si == _sidx:
                        _st2 = "running"
                    else:
                        _st2 = "waiting"
                    _tc, _bd, _bg = _C[_st2]
                    _icon = _ICONS[_st2]
                    if _sn == "Done" and _st2 == "done" and rows:
                        _extra = f"{rows:,} rows"
                    elif _st2 == "running" and elapsed_s > 0:
                        _extra = f"{elapsed_s}s…"
                    else:
                        _extra = f"{_sp}%"
                    _style = (f"background:{_bg};border:2px solid {_bd};border-radius:8px;"
                              f"padding:8px 4px;text-align:center;min-width:68px;flex:1;")
                    if _st2 == "running":
                        _style += "box-shadow:0 0 0 3px rgba(59,130,246,0.3);"
                    _cards_html += (
                        f'<div style="{_style}">'
                        f'<div style="font-size:18px;line-height:1">{_icon}</div>'
                        f'<div style="font-size:11px;font-weight:700;color:{_tc};margin-top:3px">{_sn}</div>'
                        f'<div style="font-size:10px;color:{_tc};font-weight:500">{_extra}</div>'
                        f'</div>'
                    )
                    if _si < len(_STAGE_NAMES) - 1:
                        _arr_col = _bd if _si < _sidx else "#d1d5db"
                        _cards_html += (
                            f'<div style="color:{_arr_col};font-size:18px;font-weight:700;'
                            f'padding:0 2px;flex-shrink:0;line-height:1;margin-top:-4px">›</div>'
                        )
                _cards_html += '</div>'
                _bar_extra = ""
                if elapsed_s > 0 and current_stage == "Normalize":
                    _bar_extra = (
                        f'<div style="font-size:10px;color:#1e40af;margin-top:2px">'
                        f'⏱ Normalizing… {elapsed_s}s{(" · "+detail) if detail else ""}</div>'
                    )
                _bar = (
                    f'<div style="margin-top:8px;background:#e5e7eb;border-radius:6px;height:8px;">'
                    f'<div style="background:linear-gradient(90deg,#2563eb,#16a34a);'
                    f'border-radius:6px;height:8px;width:{_pct}%;transition:width 0.4s ease;"></div>'
                    f'</div>'
                    f'<div style="font-size:10px;color:#6b7280;text-align:right;margin-top:2px">'
                    f'{_pct}% complete</div>{_bar_extra}'
                )
                return (
                    f'<div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;'
                    f'padding:12px 14px;margin:4px 0 8px;">{_cards_html}{_bar}</div>'
                )

            st.markdown("---")
            st.markdown(f"### ▶ Running {len(_ready_jobs)} job(s)…")
            _overall_ph = st.empty()
            _results    = []

            for _job in _ready_jobs:
                st.markdown(
                    f'<div style="font-size:13px;font-weight:700;margin:12px 0 4px;">'
                    f'📄 {_job["file_name"]} &nbsp;→&nbsp; <code>{_job["target_table"]}</code></div>',
                    unsafe_allow_html=True)
                _pipeline_ph    = st.empty()
                _pipeline_ph.markdown(_pipeline_html_ex("Ingest"), unsafe_allow_html=True)
                _norm_start     = [0.0]
                _norm_detail    = [""]
                _current_stage  = ["Ingest"]
                _cancelled      = [False]

                def _progress_cb_ex(msg, pct, _ph=_pipeline_ph):
                    if msg == "Normalize" or msg.startswith("Normalize"):
                        if _norm_start[0] == 0:
                            _norm_start[0] = time.time()
                        if ":" in msg:
                            _norm_detail[0] = msg.split(":", 1)[1].strip()
                        elif "·" in msg:
                            _norm_detail[0] = msg.split("·", 1)[1].strip()
                        _current_stage[0] = "Normalize"
                    else:
                        _current_stage[0] = msg

                import threading as _thr2
                _job_result = [None]
                _job_done   = [False]

                def _run_thread_ex(_j=_job):
                    _job_result[0] = run_job(_j, engine, ppdm_schema, _progress_cb_ex,
                                             cancel_flag=_cancelled)
                    _job_done[0] = True

                _t = _thr2.Thread(target=_run_thread_ex, daemon=True)
                _t.start()
                _stop_ph = st.empty()
                while not _job_done[0]:
                    if st.session_state.get("_bulk_cancel"):
                        _cancelled[0] = True
                        st.session_state["_bulk_cancel"] = False
                        _stop_ph.warning("⏹ Cancelling…")
                    _stage = _current_stage[0]
                    if _stage == "Normalize" and _norm_start[0] > 0:
                        _elapsed = int(time.time() - _norm_start[0])
                        _pipeline_ph.markdown(
                            _pipeline_html_ex("Normalize", elapsed_s=_elapsed,
                                              detail=_norm_detail[0]),
                            unsafe_allow_html=True)
                    else:
                        _pipeline_ph.markdown(_pipeline_html_ex(_stage), unsafe_allow_html=True)
                    time.sleep(1)
                _t.join()
                _stop_ph.empty()
                _result = _job_result[0] or {"ok": False, "message": "Job thread failed",
                                              "rows_inserted": 0, "rows_skipped": 0,
                                              "rows_error": 0, "duration_s": 0}
                _result["job"]    = _job
                _result["ran_at"] = datetime.now().isoformat()[:19]
                _results.append(_result)

                if _result["ok"]:
                    _pipeline_ph.markdown(
                        _pipeline_html_ex("Done", rows=_result.get("rows_inserted", 0)),
                        unsafe_allow_html=True)
                    _st2 = _result.get("stage_times", {})
                    if _st2:
                        _timing_str = " · ".join(f"{k}: {v}s" for k, v in _st2.items()
                                                  if isinstance(v, (int, float)))
                        st.caption(f"⏱ {_timing_str}")
                else:
                    _msg = _result.get("message", "")
                    _fail_stg = next(
                        (s for s in _STAGE_NAMES if s.lower() in _msg.lower()), "Promote")
                    _pipeline_ph.markdown(
                        _pipeline_html_ex(_fail_stg, failed_stage=_fail_stg),
                        unsafe_allow_html=True)
                    st.error(_msg[:600])

                for _qj in queue:
                    if _qj["id"] == _job["id"]:
                        _qj["status"] = "done" if _result["ok"] else "failed"
                _save_queue(queue)

                if not _result["ok"] and _stop_on_error:
                    _overall_ph.error(f"Stopped after error on {_job['file_name']}.")
                    break

            _ok_count   = sum(1 for r in _results if r["ok"])
            _fail_count = len(_results) - _ok_count
            _total_rows = sum(r.get("rows_inserted", 0) for r in _results)
            if _fail_count == 0:
                _overall_ph.success(f"✅ All {_ok_count} job(s) complete — {_total_rows:,} rows inserted.")
            else:
                _overall_ph.warning(f"⚠️ {_ok_count} succeeded, {_fail_count} failed — {_total_rows:,} rows inserted.")

            _hist = _load_history()
            for _r in _results:
                _hist.insert(0, {
                    "completed":     datetime.now().isoformat()[:19],
                    "file_name":     _r["job"]["file_name"],
                    "target_table":  _r["job"]["target_table"],
                    "status":        "done" if _r["ok"] else "failed",
                    "message":       _r.get("message", ""),
                    "rows_inserted": _r.get("rows_inserted", 0),
                    "rows_skipped":  _r.get("rows_skipped", 0),
                    "duration_s":    _r.get("duration_s", 0),
                    "stage_times":   _r.get("stage_times", {}),
                })
            _HISTORY_FILE.write_text(json.dumps(_hist[:200], indent=2), encoding="utf-8")
            st.rerun()


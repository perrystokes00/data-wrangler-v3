"""
promote.py  —  PPDM Loader · Module 8: Promote
===============================================
Executes the final INSERT of clean rows from the staging table
into the PPDM target table.

Architecture:
  - Live mode: single server-side INSERT INTO target SELECT FROM staging
    WHERE _stg_row_id NOT IN (bad rows)
    Wrapped in a transaction — all-or-nothing, rollback on any error.
  - Demo mode: simulates the insert on the in-memory DataFrame and
    returns a detailed PromoteResult.

Also writes a promote log to the staging schema for auditability.

Test:
    python promote.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib  import sha256
from typing   import Optional

import pandas as pd


def compute_data_hash(df: "pd.DataFrame") -> str:
    """
    Compute a stable SHA-256 fingerprint of a DataFrame's data content.
    Rows are sorted so row-order differences don't affect the hash.
    Column names are included so schema changes are detected.
    """
    cols = sorted(df.columns.tolist())
    sorted_df = (
        df[cols]
        .astype(str)
        .apply(lambda c: c.str.strip().str.upper())
        .sort_values(by=cols)
        .reset_index(drop=True)
    )
    col_sig  = "|".join(cols)
    row_sigs = sorted_df.apply(lambda r: "|".join(r.values), axis=1)
    raw      = col_sig + "\n" + "\n".join(row_sigs)
    return sha256(raw.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPE
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PromoteResult:
    ok:            bool
    message:       str
    rows_inserted: int = 0
    rows_skipped:  int = 0
    rows_error:    int = 0
    target_table:  str = ""
    staging_table: str = ""
    timestamp:     str = field(default_factory=lambda: datetime.utcnow().isoformat())
    sql_executed:  str = ""
    bad_rows_file: str = ""  # path to bad rows CSV report if any


# ═══════════════════════════════════════════════════════════════════════
# SERVER-SIDE PROMOTE
# ═══════════════════════════════════════════════════════════════════════

def promote_server(
    engine,
    staging_table: str,
    target_table:  str,
    mapping,               # ColumnMapping from mapping.py
    schema: str = "dbo",
) -> PromoteResult:
    """
    Execute server-side INSERT INTO target SELECT FROM staging.
    Duplicate rows excluded via NOT EXISTS on PK columns.
    Wrapped in a transaction for atomicity.

    Args:
        engine         : SQLAlchemy Engine
        staging_table  : STG_* table name
        target_table   : PPDM target table name
        mapping        : ColumnMapping with active_pairs
        schema         : SQL Server schema (default dbo)
    """
    try:
        from sqlalchemy import text
        from sqlalchemy import text as _txt

        # active_pairs returns (ppdm_col, select_expr) where select_expr
        # already includes any transform (UPPER, LEFT:N, CASE, SQL:, etc.)
        # and/or constant. auto_generated_cols carry server expressions like NEWID().
        pairs     = mapping.active_pairs        # [(ppdm_col, select_expr)]
        auto_cols = mapping.auto_generated_cols  # audit + GUID cols (server expressions)

        # Fallback: if active_pairs is empty, build from mp.mapped directly
        if not pairs:
            pairs = []
            for m in getattr(mapping, "mapped", []):
                if getattr(m, "auto_generated", False):
                    continue
                src = getattr(m, "source_col", "") or ""
                if not src:
                    continue
                expr = getattr(m, "select_expr", None) or f"[{src}]"
                pairs.append((m.ppdm_col, expr))

        # ── Dialect branch ───────────────────────────────────────────
        from modules.db import get_dialect as _ps_gd
        _ps_dialect = _ps_gd(engine)
        if _ps_dialect.name == "oracle":
            return _promote_server_oracle(
                engine, staging_table, target_table, mapping, schema,
                pairs, auto_cols
            )
        # If we reach here on Oracle something went wrong with dialect detection
        if hasattr(engine, 'dialect') and 'oracle' in str(engine.dialect.name).lower():
            return _promote_server_oracle(
                engine, staging_table, target_table, mapping, schema,
                pairs, auto_cols
            )
        if _ps_dialect.name == "snowflake" or (
                hasattr(engine, 'dialect') and 'snowflake' in str(engine.dialect.name).lower()):
            return _promote_server_snowflake(
                engine, staging_table, target_table, mapping, schema,
                pairs, auto_cols
            )

        # Columns that should never be auto-injected
        _FK_AUDIT_SKIP = {"ROW_QUALITY", "REMARK", "CONTAIN_TYPE"}
        if not auto_cols:
            auto_cols = [
                m for m in getattr(mapping, "mapped", [])
                if getattr(m, "auto_generated", False)
                and getattr(m, "ppdm_col", "").upper() not in _FK_AUDIT_SKIP
            ]
        else:
            auto_cols = [m for m in auto_cols
                         if getattr(m, "ppdm_col", "").upper() not in _FK_AUDIT_SKIP]

        # Filter auto_cols to only columns that actually exist in the target table
        if engine and auto_cols:
            try:
                with engine.connect() as _ec:
                    _tgt_cols = {r[0].upper() for r in _ec.execute(_txt(
                        "SELECT c.name FROM sys.columns c "
                        "JOIN sys.tables t ON t.object_id = c.object_id "
                        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                        "WHERE LOWER(t.name) = LOWER(:tbl) AND s.name = 'dataview'"
                    ), {"tbl": target_table}).fetchall()}
                auto_cols = [m for m in auto_cols
                             if getattr(m, "ppdm_col", "").upper() in _tgt_cols]
            except Exception as _filt_e:
                # If column lookup fails, drop any known-problematic cols
                auto_cols = [m for m in auto_cols
                             if getattr(m, "ppdm_col", "").upper() not in
                             {"ROW_QUALITY", "REMARK"}]

        if not pairs and not auto_cols:
            return PromoteResult(
                ok=False, message="No columns mapped — nothing to promote.",
                target_table=target_table, staging_table=staging_table
            )

        # Strip any schema prefix from staging_table (may arrive as "stg.raw_data")
        _stg_bare = staging_table.split(".")[-1] if staging_table and "." in staging_table else staging_table
        stg_full  = f"[{schema}].[{_stg_bare}]"
        tgt_full  = f"[dataview].[{target_table}]"

        # For source-mapped columns: select_expr is already the full expression
        # (e.g. "UPPER([OPERATOR])", "LEFT([TD], 40)", "'CONSTANT_VALUE'")
        # For auto-generated: use auto_gen_expr directly (NEWID(), GETUTCDATE(), etc.)
        # Filter pairs: only include a column if its select_expr is either
        #   a) a pure constant/server expression (starts with ' or is a function)
        #   b) references a staging column that actually exists in stg.raw_data
        # This prevents "Invalid column name" errors when a PPDM column is mapped
        # to a source column that doesn't exist in the current staging table.
        import re as _re
        _stg_cols_early = set()
        try:
            with engine.connect() as _sc:
                _stg_cols_early = {r[0].upper() for r in _sc.execute(_txt(
                    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = :sch AND TABLE_NAME = :tbl"
                ), {"sch": schema, "tbl": _stg_bare}).fetchall()}
        except Exception as _stg_fetch_err:
            # Log but don't silently swallow — if staging cols can't be fetched
            # skip the filter entirely rather than dropping all pairs
            import warnings as _w
            _w.warn(f"Could not fetch staging columns for filter: {_stg_fetch_err}")

        def _expr_refs_missing_col(expr, stg_cols):
            """Return True if expr contains [COL] references not in staging.
            Returns False (don't drop) when stg_cols is empty — fail open."""
            if not stg_cols:
                return False   # can't validate — keep the pair
            refs = _re.findall(r'\[([^\]]+)\]', expr)
            return any(r.upper() not in stg_cols for r in refs)

        pairs = [
            (p, expr) for p, expr in pairs
            if not _expr_refs_missing_col(expr, _stg_cols_early)
        ]

        # Wrap date/datetime columns in TRY_CONVERT to handle empty strings
        # and malformed dates gracefully (converts to NULL instead of error)
        _date_target_cols = set()
        _datetime_cols    = set()  # specifically 'datetime' type (narrower range than datetime2)
        try:
            with engine.connect() as _dtc:
                _dt_rows = _dtc.execute(_txt(
                    "SELECT c.name, t.name FROM sys.columns c "
                    "JOIN sys.types t ON t.user_type_id = c.user_type_id "
                    "JOIN sys.tables tbl ON tbl.object_id = c.object_id "
                    "JOIN sys.schemas s ON s.schema_id = tbl.schema_id "
                    "WHERE LOWER(tbl.name) = LOWER(:tbl) AND s.name = 'dataview' "
                    "AND t.name IN ('date','datetime','datetime2','smalldatetime')"
                ), {"tbl": target_table}).fetchall()
                _date_target_cols = {r[0].upper() for r in _dt_rows}
                _datetime_cols    = {r[0].upper() for r in _dt_rows if r[1] == 'datetime'}
        except Exception:
            pass

        # Get target column max lengths for truncation protection
        _col_max_lengths = {}
        try:
            with engine.connect() as _mlc:
                for _row in _mlc.execute(_txt(
                    "SELECT c.name, c.max_length, t.name "
                    "FROM sys.columns c JOIN sys.types t ON t.user_type_id=c.user_type_id "
                    "JOIN sys.tables tbl ON tbl.object_id=c.object_id "
                    "JOIN sys.schemas s ON s.schema_id=tbl.schema_id "
                    "WHERE LOWER(tbl.name)=LOWER(:tbl) AND s.name='dataview' "
                    "AND t.name IN ('nvarchar','varchar','char','nchar') AND c.max_length > 0"
                ), {"tbl": target_table}).fetchall():
                    _cname, _maxlen, _tname = _row
                    _char_len = _maxlen // 2 if 'n' in _tname else _maxlen
                    _col_max_lengths[_cname.upper()] = _char_len
        except Exception:
            pass

        # Get numeric columns — wrap in TRY_CONVERT to handle non-numeric source values
        _numeric_cols = {}  # col_upper -> sql_type
        try:
            with engine.connect() as _nc:
                for _row in _nc.execute(_txt(
                    "SELECT c.name, t.name, c.precision, c.scale "
                    "FROM sys.columns c JOIN sys.types t ON t.user_type_id=c.user_type_id "
                    "JOIN sys.tables tbl ON tbl.object_id=c.object_id "
                    "JOIN sys.schemas s ON s.schema_id=tbl.schema_id "
                    "WHERE LOWER(tbl.name)=LOWER(:tbl) AND s.name='dataview' "
                    "AND t.name IN ('numeric','decimal','float','real','money','smallmoney')"
                ), {"tbl": target_table}).fetchall():
                    _nc_name, _nc_type, _nc_prec, _nc_scale = _row
                    if _nc_type in ('numeric', 'decimal'):
                        _numeric_cols[_nc_name.upper()] = f"NUMERIC({_nc_prec},{_nc_scale})"
                    elif _nc_type == 'float':
                        _numeric_cols[_nc_name.upper()] = "FLOAT"
                    elif _nc_type == 'real':
                        _numeric_cols[_nc_name.upper()] = "REAL"
                    else:
                        _numeric_cols[_nc_name.upper()] = "NUMERIC(19,4)"
        except Exception:
            pass

        def _wrap_date(p, expr):
            if p.upper() in _date_target_cols:
                if not any(expr.upper().startswith(x) for x in
                           ("GETUTCDATE", "GETDATE", "CAST(", "CONVERT(", "NULL", "'")):
                    # Use DATETIME for datetime cols — narrower range, avoids out-of-range error
                    _dt_type = "DATETIME" if p.upper() in _datetime_cols else "DATETIME2"
                    return f"TRY_CONVERT({_dt_type}, NULLIF(LTRIM(RTRIM({expr})), ''))"
            return expr

        def _wrap_numeric(p, expr):
            _ntype = _numeric_cols.get(p.upper())
            if _ntype:
                if not any(expr.upper().startswith(x) for x in
                           ("GETUTCDATE", "GETDATE", "CAST(", "CONVERT(", "NULL", "'")):
                    return f"TRY_CONVERT({_ntype}, NULLIF(LTRIM(RTRIM({expr})), ''))"
            return expr

        def _wrap_length(p, expr):
            _maxlen = _col_max_lengths.get(p.upper())
            if _maxlen and _maxlen > 0:
                if not any(expr.upper().startswith(x) for x in
                           ("GETUTCDATE", "GETDATE", "CAST(", "NEWID", "NULL", "'")):
                    return f"LEFT({expr}, {_maxlen})"
            return expr

        pairs = [(p, _wrap_date(p, _wrap_numeric(p, _wrap_length(p, expr)))) for p, expr in pairs]

        tgt_col_parts = (
            [f"[{p}]"          for p, _   in pairs] +
            [f"[{m.ppdm_col}]" for m      in auto_cols]
        )
        src_col_parts = (
            [expr              for _, expr in pairs] +
            [m.auto_gen_expr   for m       in auto_cols]
        )

        tgt_cols_sql = ", ".join(tgt_col_parts)
        src_cols_sql = ", ".join(src_col_parts)

        # Duplicates handled by NOT EXISTS on PK; FK violations by EXISTS filters.
        ids_str = None
        where   = ""

        # Build a map from target col name -> select expression
        _col_to_expr = {p.upper(): expr for p, expr in pairs}

        # Reuse staging columns fetched earlier for pair filtering
        _stg_cols = _stg_cols_early

        # Build WHERE NOT EXISTS clause to skip duplicate PKs
        _pk_cols = []
        try:
            with engine.connect() as _pk_con:
                _pk_rows = _pk_con.execute(_txt("""
                    SELECT c.name
                    FROM sys.indexes i
                    JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                    JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                    JOIN sys.tables t ON t.object_id = i.object_id
                    JOIN sys.schemas s ON s.schema_id = t.schema_id
                    WHERE i.is_primary_key = 1 AND LOWER(t.name) = LOWER(:tbl) AND s.name = 'dataview'
                    ORDER BY ic.key_ordinal
                """), {"tbl": target_table}).fetchall()
                _pk_cols = [r[0] for r in _pk_rows]
        except Exception:
            _pk_cols = []

        if _pk_cols:
            _ne_parts = []
            for p in _pk_cols:
                expr = _col_to_expr.get(p.upper())
                if expr and not expr.startswith("["):
                    # Add src. prefix to bare column references in expression
                    import re as _nere
                    _src_expr = _nere.sub(r'\[([^\]]+)\]', lambda m: f"src.[{m.group(1)}]", expr)
                    _ne_parts.append(f"tgt.[{p}] = {_src_expr}")
                elif p.upper() in _stg_cols:
                    _ne_parts.append(f"tgt.[{p}] = src.[{p}]")
            _dup_filter = (
                f"NOT EXISTS (SELECT 1 FROM {tgt_full} tgt WHERE {' AND '.join(_ne_parts)})"
                if _ne_parts else None
            )
        else:
            _dup_filter = None

        # Build FK parent filters to skip rows with missing FK parents.
        # IMPORTANT: skip any parent table that is currently empty — an empty
        # parent table would block ALL rows even when the data is valid.
        # SQL Server's own FK constraint enforces integrity at INSERT time.
        _fk_filters = []
        try:
            from collections import defaultdict

            _fk_rows = engine.connect().execute(_txt("""
                SELECT cc.name AS child_col, pt.name AS parent_tbl, pc.name AS parent_col,
                       cc.is_nullable
                FROM sys.foreign_keys fk
                JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
                JOIN sys.tables ct  ON ct.object_id = fk.parent_object_id
                JOIN sys.columns cc ON cc.object_id = fk.parent_object_id AND cc.column_id = fkc.parent_column_id
                JOIN sys.tables pt  ON pt.object_id = fk.referenced_object_id
                JOIN sys.columns pc ON pc.object_id = fk.referenced_object_id AND pc.column_id = fkc.referenced_column_id
                JOIN sys.schemas s  ON s.schema_id = ct.schema_id
                WHERE LOWER(ct.name) = LOWER(:tbl) AND s.name = 'dataview'
            """), {"tbl": target_table}).fetchall()

            _fk_groups = defaultdict(list)
            for child_col, parent_tbl, parent_col, is_nullable in _fk_rows:
                cc_up = child_col.upper()
                # Skip nullable FK columns — optional references, not enforced
                if is_nullable:
                    continue
                # Include FK if col is in staging OR has a constant mapping
                if cc_up in _stg_cols or cc_up in _col_to_expr:
                    _fk_groups[parent_tbl].append((child_col, parent_col))

            for parent_tbl, col_pairs in _fk_groups.items():
                # Skip FK filter if parent table is empty — avoids blocking all
                # rows when parent tables haven't been loaded yet.
                # SQL Server FK constraint still enforces integrity at INSERT time.
                try:
                    with engine.connect() as _fk_chk_con:
                        _par_count = _fk_chk_con.execute(_txt(
                            f"SELECT COUNT(*) FROM [dataview].[{parent_tbl}] WITH (NOLOCK)"
                        )).scalar() or 0
                    if _par_count == 0:
                        continue   # parent table empty — skip this FK filter
                except Exception:
                    continue       # can't check — skip rather than block

                _join_parts = []
                _skip_fk    = False
                for cc, pc in col_pairs:
                    expr = _col_to_expr.get(cc.upper())
                    if expr and not _expr_refs_missing_col(expr, _stg_cols_early):
                        # Expression references only valid staging columns.
                        # If it's a bare [COL] reference, prefix with src.
                        # Pure constants (quoted strings, functions) are used as-is.
                        import re as _re2
                        _is_bare_col = bool(_re2.fullmatch(r'\[[^\]]+\]', expr.strip()))
                        if _is_bare_col:
                            _join_parts.append(f"fk_{parent_tbl}.[{pc}] = src.{expr}")
                        else:
                            _join_parts.append(f"fk_{parent_tbl}.[{pc}] = {expr}")
                    elif cc.upper() in _stg_cols_early:
                        # Direct staging column — no mapping, use bare col name
                        _join_parts.append(f"fk_{parent_tbl}.[{pc}] = src.[{cc}]")
                    else:
                        # Column not in staging and no valid expression — skip filter
                        _skip_fk = True
                        break
                if _skip_fk or not _join_parts:
                    continue
                _fk_filters.append(
                    f"EXISTS (SELECT 1 FROM [dataview].[{parent_tbl}] fk_{parent_tbl} "
                    f"WHERE {' AND '.join(_join_parts)})"
                )
        except Exception:
            pass

        # ── Pre-validate: date conversion failures only ───────────────────
        _bad_rows_file = None
        _bad_pk_filter = ""
        _bad_row_count = 0
        try:
            _pk_col = _pk_cols[0] if _pk_cols else None
            if _pk_col and _date_target_cols:
                _bad_pks = {}
                with engine.connect() as _bcon:
                    for _tp, _expr in pairs:
                        if _tp.upper() not in _date_target_cols:
                            continue
                        import re as _re3
                        _refs = _re3.findall(r'\[([^\]]+)\]', _expr)
                        _raw_col = _refs[0] if _refs else None
                        if not _raw_col or _raw_col.upper() not in _stg_cols:
                            continue
                        try:
                            _brows = _bcon.execute(_txt(
                                f"SELECT src.[{_pk_col}] "
                                f"FROM {stg_full} src "
                                f"WHERE src.[{_raw_col}] IS NOT NULL "
                                f"AND LTRIM(RTRIM(src.[{_raw_col}])) <> '' "
                                f"AND TRY_CONVERT(DATETIME2, NULLIF(LTRIM(RTRIM(src.[{_raw_col}])), '')) IS NULL"
                            )).fetchall()
                            for _br in _brows:
                                _pk_val = str(_br[0])
                                if _pk_val not in _bad_pks:
                                    _bad_pks[_pk_val] = []
                                _bad_pks[_pk_val].append(f"Invalid date in {_raw_col}")
                        except Exception:
                            continue

                if _bad_pks:
                    _bad_row_count = len(_bad_pks)
                    import csv as _bcsv, os as _bos
                    _bad_dir = _bos.path.dirname(_bos.path.abspath(__file__))
                    _bad_path = _bos.path.join(
                        _bad_dir, f"bad_rows_{target_table}_{staging_table}.csv"
                    )
                    with open(_bad_path, "w", encoding="utf-8", newline="") as _bf:
                        _bw = _bcsv.writer(_bf, quoting=_bcsv.QUOTE_ALL)
                        _bw.writerow([_pk_col, "REASONS"])
                        for _pk_val, _reasons in _bad_pks.items():
                            _bw.writerow([_pk_val, "; ".join(_reasons)])
                    _bad_rows_file = _bad_path
                    _pk_list = ", ".join(f"'{v}'" for v in _bad_pks.keys())
                    _bad_pk_filter = f"src.[{_pk_col}] NOT IN ({_pk_list})"
        except Exception:
            pass

        # Add bad row exclusion to WHERE conditions
        _conditions = []
        if _dup_filter:
            _conditions.append(_dup_filter)
        _conditions.extend(_fk_filters)
        if _bad_pk_filter:
            _conditions.append(_bad_pk_filter)

        # Exclude rows where any PK source column is NULL or empty
        for _pk in _pk_cols:
            _pk_expr = _col_to_expr.get(_pk.upper())
            if _pk_expr and not _pk_expr.startswith("'") and "NEWID" not in _pk_expr.upper():
                # Extract raw source column reference from expression
                import re as _pkre
                _pk_refs = _pkre.findall(r'\[([^\]]+)\]', _pk_expr)
                _pk_src = _pk_refs[0] if _pk_refs else None
                if _pk_src and _pk_src.upper() in _stg_cols:
                    _conditions.append(
                        f"src.[{_pk_src}] IS NOT NULL "
                        f"AND LTRIM(RTRIM(src.[{_pk_src}])) <> ''"
                    )

        _where_final = ("WHERE " + " AND ".join(_conditions)) if _conditions else ""

        # Split pairs into PK/data cols vs auto-generated (NEWID, GETUTCDATE etc.)
        # We need DISTINCT on source data only — NEWID() must be applied AFTER dedup
        _user_pairs = [(p, expr) for p, expr in pairs]
        _auto_exprs = [(m.ppdm_col, m.auto_gen_expr) for m in auto_cols]

        # Check if any auto col uses NEWID — if so use subquery pattern for dedup
        _has_newid = any("NEWID" in e.upper() for _, e in _auto_exprs)

        if _has_newid and _user_pairs:
            # Subquery dedup pattern — DISTINCT on PK expression only,
            # then pick first non-null value for non-PK cols, NEWID() applied after.
            # This prevents duplicate PK errors when source has slight variations
            # in non-PK columns (e.g. trailing spaces in BA_LONG_NAME) that would
            # otherwise survive DISTINCT and collide on insert.
            _pk_set = {p.upper() for p in _pk_cols}
            _pk_pairs  = [(p, expr) for p, expr in _user_pairs if p.upper() in _pk_set]
            _npk_pairs = [(p, expr) for p, expr in _user_pairs if p.upper() not in _pk_set]

            # Inner SELECT: PK exprs + MIN() on non-PK cols to collapse duplicates
            _inner_pk  = ", ".join(f"{expr} AS [{p}]" for p, expr in _pk_pairs)
            _inner_npk = ", ".join(f"MIN({expr}) AS [{p}]" for p, expr in _npk_pairs)
            _inner_sel = ", ".join(filter(None, [_inner_pk, _inner_npk]))
            _inner_grp = ", ".join(expr for _, expr in _pk_pairs)

            _outer_tgt = ", ".join(
                [f"[{p}]" for p, _ in _user_pairs] +
                [f"[{m.ppdm_col}]" for m in auto_cols]
            )
            _outer_src = ", ".join(
                [f"dedup.[{p}]" for p, _ in _user_pairs] +
                [m.auto_gen_expr for m in auto_cols]
            )
            # Inner WHERE — all conditions except dup filter
            _inner_conds = [c for c in _conditions if "NOT EXISTS" not in c]
            _inner_where = ("WHERE " + " AND ".join(_inner_conds)) if _inner_conds else ""

            # Outer NOT EXISTS against target table
            _pk_matches = " AND ".join(
                f"tgt.[{p}] = dedup.[{p}]"
                for p in _pk_cols
                if any(pp.upper() == p.upper() for pp, _ in _user_pairs)
            )
            _outer_where = (f"WHERE NOT EXISTS (SELECT 1 FROM {tgt_full} tgt "
                           f"WHERE {_pk_matches})") if _pk_matches else ""

            _grp_clause = f"GROUP BY {_inner_grp}" if _inner_grp else ""

            insert_sql = (
                f"INSERT INTO {tgt_full} ({_outer_tgt})\n"
                f"SELECT {_outer_src}\n"
                f"FROM (\n"
                f"    SELECT {_inner_sel}\n"
                f"    FROM {stg_full} src\n"
                f"    {_inner_where}\n"
                f"    {_grp_clause}\n"
                f") dedup\n"
                f"{_outer_where}"
            )
        else:
            # Always deduplicate on PK to prevent duplicate key errors
            # when source data has repeated values (e.g. same operator many times)
            if _pk_cols and _dup_filter:
                _pk_set2   = {p.upper() for p in _pk_cols}
                _pk_pairs2 = [(p, expr) for p, expr in pairs if p.upper() in _pk_set2]
                _npk_pairs2= [(p, expr) for p, expr in pairs if p.upper() not in _pk_set2]
                if _pk_pairs2:
                    _i_pk  = ", ".join(f"{expr} AS [{p}]" for p, expr in _pk_pairs2)
                    _i_npk = ", ".join(f"MIN({expr}) AS [{p}]" for p, expr in _npk_pairs2)
                    _i_sel = ", ".join(filter(None, [_i_pk, _i_npk]))
                    _i_grp = ", ".join(expr for _, expr in _pk_pairs2)
                    _a_tgt = ", ".join(
                        [f"[{p}]" for p, _ in pairs] +
                        [f"[{m.ppdm_col}]" for m in auto_cols]
                    )
                    _a_src = ", ".join(
                        [f"dedup.[{p}]" for p, _ in pairs] +
                        [m.auto_gen_expr for m in auto_cols]
                    )
                    _pk_match2 = " AND ".join(
                        f"tgt.[{p}] = dedup.[{p}]"
                        for p in _pk_cols
                        if any(pp.upper() == p.upper() for pp, _ in pairs)
                    )
                    _ow2 = (f"WHERE NOT EXISTS (SELECT 1 FROM {tgt_full} tgt "
                            f"WHERE {_pk_match2})") if _pk_match2 else ""
                    _inner_conds2 = [c for c in _conditions if "NOT EXISTS" not in c]
                    _iw2 = ("WHERE " + " AND ".join(_inner_conds2)) if _inner_conds2 else ""
                    insert_sql = (
                        f"INSERT INTO {tgt_full} ({_a_tgt})\n"
                        f"SELECT {_a_src}\n"
                        f"FROM (\n"
                        f"    SELECT {_i_sel}\n"
                        f"    FROM {stg_full} src\n"
                        f"    {_iw2}\n"
                        f"    GROUP BY {_i_grp}\n"
                        f") dedup\n"
                        f"{_ow2}"
                    )
                else:
                    insert_sql = (
                        f"INSERT INTO {tgt_full} ({tgt_cols_sql})\n"
                        f"SELECT {src_cols_sql}\n"
                        f"FROM {stg_full} src\n"
                        f"{_where_final}"
                    )
            else:
                insert_sql = (
                    f"INSERT INTO {tgt_full} ({tgt_cols_sql})\n"
                    f"SELECT {src_cols_sql}\n"
                    f"FROM {stg_full} src\n"
                    f"{_where_final}"
                )

        # Count total staging rows and skip count
        total_rows = _count_rows(engine, stg_full)
        skip_count = 0  # skip list removed — handled by NOT EXISTS/EXISTS filters

        # Pre-dedup: remove duplicate PKs from staging table before INSERT.
        # Keeps the row with the lowest rowid for each PK combination.
        # This handles cases where source data has repeated values (e.g. same
        # operator appearing in many well rows) that survive the GROUP BY path.
        if _pk_cols:
            _pk_stg_exprs = []
            for _pkc in _pk_cols:
                _expr = _col_to_expr.get(_pkc.upper())
                if _expr:
                    _pk_stg_exprs.append(f"{_expr} AS _pk_{_pkc}")
                elif _pkc.upper() in _stg_cols:
                    _pk_stg_exprs.append(f"[{_pkc}] AS _pk_{_pkc}")
            if _pk_stg_exprs:
                _dedup_pk_cols = ", ".join(
                    _col_to_expr.get(_pkc.upper()) or f"[{_pkc}]"
                    for _pkc in _pk_cols
                    if _col_to_expr.get(_pkc.upper()) or _pkc.upper() in _stg_cols
                )
                if _dedup_pk_cols:
                    _dedup_sql = (
                        f"WITH _cte AS ("
                        f"SELECT *, ROW_NUMBER() OVER (PARTITION BY {_dedup_pk_cols} "
                        f"ORDER BY (SELECT NULL)) AS _rn "
                        f"FROM {stg_full}"
                        f") DELETE FROM _cte WHERE _rn > 1"
                    )
                    try:
                        with engine.begin() as _dd_con:
                            _dd_result = _dd_con.execute(text(_dedup_sql))
                            skip_count = _dd_result.rowcount
                    except Exception as _dd_err:
                        pass  # dedup failed — proceed anyway, INSERT will catch dups

        with engine.begin() as con:           # atomic transaction
            result = con.execute(text(insert_sql))
            inserted = result.rowcount

        # Write audit log
        _write_audit_log(engine, schema, staging_table, target_table,
                         inserted, skip_count, insert_sql)

        # ── Populate intersection tables derived from well source data ──────
        # well_area: populated from AREA_ID + AREA_TYPE mapped columns
        _area_rows = 0
        _area_msg  = ""
        _stg_cols_upper = set()
        try:
            with engine.connect() as _ac:
                _stg_cols_upper = {r[0].upper() for r in _ac.execute(text(
                    f"SELECT c.name FROM sys.columns c "
                    f"JOIN sys.tables t ON t.object_id=c.object_id "
                    f"JOIN sys.schemas s ON s.schema_id=t.schema_id "
                    f"WHERE t.name=:tbl AND s.name=:sch"
                ), {"tbl": staging_table, "sch": schema}).fetchall()}
        except Exception:
            pass

        _has_area = ("AREA_ID" in _stg_cols_upper and "AREA_TYPE" in _stg_cols_upper
                     and "UWI" in _stg_cols_upper and target_table.lower() == "well")
        if _has_area:
            try:
                _row_source = next(
                    (getattr(m, "const_value", "") or ""
                     for m in getattr(mapping, "mapped", [])
                     if getattr(m, "ppdm_col", "").upper() == "SOURCE"
                     and getattr(m, "const_value", "")),
                    "PPDM"
                )
                _area_sql = text(f"""
                    INSERT INTO [{schema}].[well_area]
                        (UWI, AREA_ID, AREA_TYPE, SOURCE,
                         ROW_CREATED_BY, ROW_CHANGED_BY,
                         ROW_CREATED_DATE, ROW_CHANGED_DATE, ACTIVE_IND)
                    SELECT DISTINCT
                        s.UWI,
                        s.AREA_ID,
                        s.AREA_TYPE,
                        :src AS SOURCE,
                        SYSTEM_USER, SYSTEM_USER,
                        GETDATE(), GETDATE(), 'Y'
                    FROM [{schema}].[{staging_table}] s
                    WHERE s.UWI        IS NOT NULL
                      AND s.AREA_ID   IS NOT NULL
                      AND s.AREA_TYPE IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM [{schema}].[well_area] wa
                          WHERE wa.UWI       = s.UWI
                            AND wa.AREA_ID   = s.AREA_ID
                            AND wa.AREA_TYPE = s.AREA_TYPE
                            AND wa.SOURCE    = :src
                      )
                """)
                with engine.begin() as _ac2:
                    _area_rows = _ac2.execute(_area_sql, {"src": _row_source}).rowcount or 0
                if _area_rows:
                    _area_msg = f" · {_area_rows:,} well_area row(s) inserted"
            except Exception as _ae:
                _area_msg = f" · well_area skipped: {_ae}"

        _dupes = max(0, total_rows - inserted)
        _msg = f"Successfully inserted {inserted:,} rows into {tgt_full}"
        if _dupes:
            _msg += f" ({_dupes} duplicate(s) skipped)"
        if _area_msg:
            _msg += _area_msg
        _bad_msg = f" · {_bad_row_count} bad row(s) excluded — see {_bad_rows_file}" if _bad_row_count else ""
        return PromoteResult(
            ok=True,
            message=_msg + _bad_msg,
            rows_inserted=inserted,
            rows_skipped=_dupes,
            rows_error=_bad_row_count,
            target_table=target_table,
            staging_table=staging_table,
            sql_executed=insert_sql,
            bad_rows_file=_bad_rows_file or "",
        )

    except Exception as exc:
        return PromoteResult(
            ok=False,
            message=f"Promote failed (transaction rolled back): {exc}",
            target_table=target_table,
            staging_table=staging_table,
        )



def _promote_server_snowflake(
    engine,
    staging_table: str,
    target_table:  str,
    mapping,
    schema:        str,
    pairs:         list,
    auto_cols:     list,
) -> "PromoteResult":
    """
    Snowflake-specific promote: INSERT INTO target SELECT FROM staging.
    Translates SQL Server syntax to Snowflake equivalents:
      - [bracket] quoting    → "DOUBLE_QUOTE" uppercase
      - HASHBYTES/CONVERT    → SHA1_HEX()
      - NEWID()              → UUID_STRING()
      - GETUTCDATE()         → CURRENT_TIMESTAMP()::TIMESTAMP_NTZ
      - NVARCHAR             → VARCHAR
      - TRY_CONVERT          → TRY_CAST
      - TOP n / WITH NOLOCK  → omitted
    """
    from sqlalchemy import text as _txt
    import re as _re

    # ── Get Snowflake schema ──────────────────────────────────────────
    try:
        with engine.connect() as _sc:
            sf_schema = _sc.execute(_txt("SELECT CURRENT_SCHEMA()")).scalar() or "DEMO"
    except Exception:
        sf_schema = "DEMO"

    def _q(name):
        return f'"{name.upper()}"'

    _stg_bare = staging_table.split(".")[-1] if "." in staging_table else staging_table
    stg_full  = f'"{sf_schema}"."{_stg_bare.upper()}"'
    tgt_full  = f'"{sf_schema}"."{target_table.upper()}"'

    def _xlat_expr(expr: str) -> str:
        """Translate SQL Server expressions to Snowflake equivalents."""
        if not expr:
            return expr
        e = expr.strip()

        # [ColName] → "COLNAME"
        e = _re.sub(r'\[([^\]]+)\]', lambda m: f'"{m.group(1).upper()}"', e)

        # NVARCHAR → VARCHAR
        e = _re.sub(r'\bNVARCHAR\b', "VARCHAR", e, flags=_re.IGNORECASE)

        # LTRIM(RTRIM(x)) → TRIM(x)
        e = _re.sub(r'\bLTRIM\s*\(\s*RTRIM\s*\((.+?)\)\s*\)',
                    lambda m: "TRIM(" + m.group(1) + ")",
                    e, flags=_re.IGNORECASE)

        # CONVERT(CHAR(40), HASHBYTES('SHA1', expr), 2) → UPPER(SHA1_HEX(UPPER(TRIM(expr))))
        def _hash_replace(m):
            inner = m.group(1).strip()
            cast_m = _re.match(
                r'CAST\s*\((.+?)\s+AS\s+(?:N)?VARCHAR\s*\(\d+\)\s*\)$',
                inner, _re.IGNORECASE | _re.DOTALL)
            if cast_m:
                inner = cast_m.group(1).strip()
            return f"UPPER(SHA1_HEX(UPPER(TRIM({inner}))))"
        e = _re.sub(
            r"CONVERT\s*\(\s*CHAR\s*\(\s*40\s*\)\s*,\s*HASHBYTES\s*\(\s*'SHA1'\s*,\s*(.+?)\s*\)\s*,\s*2\s*\)",
            _hash_replace, e, flags=_re.IGNORECASE)

        # LEFT(expr, n) → LEFT(expr, n) -- Snowflake supports LEFT natively

        # NEWID() → UUID_STRING()
        e = _re.sub(r'\bNEWID\s*\(\s*\)', "UUID_STRING()", e, flags=_re.IGNORECASE)

        # GETUTCDATE() → CURRENT_TIMESTAMP()::TIMESTAMP_NTZ
        e = _re.sub(r'\bGETUTCDATE\s*\(\s*\)', "CURRENT_TIMESTAMP()::TIMESTAMP_NTZ", e, flags=_re.IGNORECASE)
        e = _re.sub(r'\bGETDATE\s*\(\s*\)', "CURRENT_TIMESTAMP()::TIMESTAMP_NTZ", e, flags=_re.IGNORECASE)

        # CAST('date' AS DATETIME2) → TO_DATE('date')
        e = _re.sub(r'CAST\s*\(\s*(\'[^\']+\')\s+AS\s+DATETIME2\s*\)',
                    lambda m: f"TO_DATE({m.group(1)})", e, flags=_re.IGNORECASE)

        # TRY_CONVERT(float, x) → TRY_CAST(x AS FLOAT)
        e = _re.sub(r'TRY_CONVERT\s*\(\s*float\s*,\s*(.+?)\s*\)',
                    lambda m: f"TRY_CAST({m.group(1)} AS FLOAT)", e, flags=_re.IGNORECASE)

        return e

    # ── Fetch staging columns ─────────────────────────────────────────
    _stg_cols = set()
    try:
        with engine.connect() as _sc:
            _stg_cols = {r[0].upper() for r in _sc.execute(_txt(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = :sch AND TABLE_NAME = :tbl"
            ), {"sch": sf_schema, "tbl": _stg_bare.upper()}).fetchall()}
    except Exception:
        pass

    # ── Fetch target PK columns ───────────────────────────────────────
    pk_cols = []
    try:
        with engine.connect() as _sc:
            pk_cols = [r[0].upper() for r in _sc.execute(_txt(
                "SELECT ku.COLUMN_NAME "
                "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
                "JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku "
                "  ON ku.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
                " AND ku.TABLE_SCHEMA = tc.TABLE_SCHEMA "
                "WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY' "
                "  AND tc.TABLE_SCHEMA = :sch AND tc.TABLE_NAME = :tbl"
            ), {"sch": sf_schema, "tbl": target_table.upper()}).fetchall()]
    except Exception:
        pass

    # ── Fetch target column types for date/numeric wrapping ──────────
    _date_cols_sf = set()
    _numeric_cols_sf = {}
    _max_lens_sf = {}
    try:
        with engine.connect() as _sc:
            _tcols = _sc.execute(_txt(
                "SELECT COLUMN_NAME, DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE, "
                "CHARACTER_MAXIMUM_LENGTH FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = :sch AND TABLE_NAME = :tbl"
            ), {"sch": sf_schema, "tbl": target_table.upper()}).fetchall()
            for _row in _tcols:
                _cn, _dt = _row[0].upper(), (_row[1] or "").upper()
                if any(x in _dt for x in ("DATE", "TIME", "TIMESTAMP")):
                    _date_cols_sf.add(_cn)
                elif any(x in _dt for x in ("NUMBER", "FLOAT", "DECIMAL", "NUMERIC", "INT", "REAL")):
                    _numeric_cols_sf[_cn] = _dt
                if _row[4]:
                    _max_lens_sf[_cn] = int(_row[4])
    except Exception:
        pass

    def _wrap_sf(ppdm_col, expr):
        pc = ppdm_col.upper()
        if any(expr.upper().startswith(x) for x in
               ("UUID_STRING", "CURRENT_TIMESTAMP", "TO_DATE", "NULL", "'")):
            return expr
        ml = _max_lens_sf.get(pc)
        if ml and ml > 0:
            expr = f"LEFT({expr}, {ml})"
        if pc in _date_cols_sf:
            expr = f"TRY_TO_DATE(NULLIF(TRIM({expr}), ''))"
        elif pc in _numeric_cols_sf:
            expr = f"TRY_CAST(NULLIF(TRIM({expr}), '') AS FLOAT)"
        return expr

    # ── Build column expressions ──────────────────────────────────────
    _AUTO_SKIP = {"ROW_QUALITY", "REMARK"}
    if not auto_cols:
        auto_cols = [m for m in getattr(mapping, "mapped", [])
                     if getattr(m, "auto_generated", False)
                     and getattr(m, "ppdm_col", "").upper() not in _AUTO_SKIP]

    insert_cols = []
    select_exprs = []

    for ppdm_col, src_expr in pairs:
        xlated = _wrap_sf(ppdm_col, _xlat_expr(src_expr))
        # Check if expr references a missing staging col
        refs = _re.findall(r'"([^"]+)"', xlated)
        if _stg_cols and any(r.upper() not in _stg_cols
                              and r.upper() not in {"Y", "N"}
                              for r in refs
                              if not any(c.isspace() for c in r)):
            continue
        insert_cols.append(_q(ppdm_col))
        select_exprs.append(xlated)

    for ac in auto_cols:
        pc = getattr(ac, "ppdm_col", "")
        expr = getattr(ac, "auto_gen_expr", "") or getattr(ac, "expression", "")
        if not pc or not expr:
            continue
        insert_cols.append(_q(pc))
        select_exprs.append(_xlat_expr(expr))

    if not insert_cols:
        return PromoteResult(
            ok=False, message="No columns to promote.",
            target_table=target_table, staging_table=staging_table)

    # ── Build INSERT ... SELECT with NOT EXISTS dedup ─────────────────
    if pk_cols:
        pk_join = " AND ".join(
            f"tgt.{_q(p)} = src.{_q(p)}" for p in pk_cols)
        sql = (
            f"INSERT INTO {tgt_full} ({chr(44).join(insert_cols)})\n"
            f"SELECT {chr(44).join(select_exprs)}\n"
            f"FROM {stg_full} src\n"
            f"WHERE NOT EXISTS (\n"
            f"    SELECT 1 FROM {tgt_full} tgt WHERE {pk_join}\n"
            f")"
        )
    else:
        sql = (
            f"INSERT INTO {tgt_full} ({chr(44).join(insert_cols)})\n"
            f"SELECT {chr(44).join(select_exprs)}\n"
            f"FROM {stg_full}"
        )

    try:
        with engine.begin() as con:
            con.execute(_txt(sql))
        # Count inserted rows
        with engine.connect() as con:
            n = con.execute(_txt(f"SELECT COUNT(*) FROM {tgt_full}")).scalar() or 0
        return PromoteResult(
            ok=True,
            message=f"Promoted to {tgt_full}: {n:,} total rows",
            rows_inserted=n,
            target_table=target_table,
            staging_table=staging_table,
            sql_executed=sql,
        )
    except Exception as exc:
        return PromoteResult(
            ok=False,
            message=f"Snowflake promote failed: {exc}",
            target_table=target_table,
            staging_table=staging_table,
            sql_executed=sql,
        )


def _promote_server_oracle(
    engine,
    staging_table: str,
    target_table:  str,
    mapping,
    schema:        str,
    pairs:         list,
    auto_cols:     list,
) -> "PromoteResult":
    """
    Oracle-specific promote: INSERT INTO target SELECT FROM staging.
    Translates all SQL Server-specific syntax to Oracle equivalents:
      - sys.* catalog views  → ALL_TAB_COLUMNS / ALL_CONSTRAINTS
      - [bracket] quoting    → "double-quote" quoting
      - TRY_CONVERT          → TO_NUMBER / TO_DATE with exception handling
      - NEWID()              → SYS_GUID()
      - GETUTCDATE()         → SYS_EXTRACT_UTC(SYSTIMESTAMP)
      - TOP n                → FETCH FIRST n ROWS ONLY
      - WITH (NOLOCK)        → omitted
      - CTE DELETE dedup     → ROWID-based DELETE
    """
    from sqlalchemy import text as _txt
    import re as _re

    # ── Get Oracle schema ─────────────────────────────────────────────
    try:
        with engine.connect() as _sc:
            ora_schema = _sc.execute(_txt(
                "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
            )).scalar() or schema.upper()
    except Exception:
        ora_schema = schema.upper()

    def _q(name):
        """Oracle double-quote identifier."""
        return f'"{name.upper()}"'

    # Strip schema prefix from staging table name
    _stg_bare = staging_table.split(".")[-1] if "." in staging_table else staging_table
    stg_full  = f'"{ora_schema}"."{_stg_bare.upper()}"'
    tgt_full  = f'"{ora_schema}"."{target_table.upper()}"'

    # ── Translate auto_gen_expr from SQL Server → Oracle ─────────────
    def _xlat_expr(expr: str) -> str:
        """Translate SQL Server expressions to Oracle equivalents.
        Order: brackets first, then function translations.
        Uses paren-counting for LEFT() to avoid regex greedy issues."""
        import re as _xre
        if not expr:
            return expr
        e = expr.strip()

        # Step 1: [ColName] → "COLNAME"
        e = _xre.sub(r'\[([^\]]+)\]', lambda m: f'"{m.group(1).upper()}"', e)

        # Step 2: NVARCHAR → VARCHAR2
        e = _xre.sub(r'\bNVARCHAR\b', "VARCHAR2", e, flags=_xre.IGNORECASE)

        # Step 3: LTRIM(RTRIM(x)) → TRIM(x)
        e = _xre.sub(r'\bLTRIM\s*\(\s*RTRIM\s*\((.+?)\)\s*\)',
                    lambda m: "TRIM(" + m.group(1) + ")",
                    e, flags=_xre.IGNORECASE)

        # Step 4: CONVERT(CHAR(40), HASHBYTES('SHA1', expr), 2) → Oracle SHA1
        def _hash_replace(m):
            inner = m.group(1).strip()
            cast_m = _xre.match(
                r'CAST\s*\((.+?)\s+AS\s+VARCHAR2\s*\(\d+\)\s*\)$',
                inner, _xre.IGNORECASE | _xre.DOTALL)
            if cast_m:
                inner = cast_m.group(1).strip()
            # Strip ALL whitespace before hashing — TRIM() misses tabs
            _clean = "UPPER(TRIM(REGEXP_REPLACE(" + inner + ", '[\\s]', '')))"
            return "UPPER(RAWTOHEX(DBMS_CRYPTO.HASH(UTL_RAW.CAST_TO_RAW(" + _clean + "),3)))"
        e = _xre.sub(
            r"CONVERT\s*\(\s*CHAR\s*\(\s*40\s*\)\s*,\s*HASHBYTES\s*\(\s*'SHA1'\s*,\s*(.+?)\s*\)\s*,\s*2\s*\)",
            _hash_replace, e, flags=_xre.IGNORECASE)

        # Step 5: LEFT(expr, n) → SUBSTR(expr, 1, n) — paren-counting
        def _replace_left(s):
            result = []
            i = 0
            while i < len(s):
                m = _xre.search(r'\bLEFT\s*\(', s[i:], _xre.IGNORECASE)
                if not m:
                    result.append(s[i:])
                    break
                result.append(s[i:i+m.start()])
                start_pos = i + m.end()
                depth = 1
                j = start_pos
                while j < len(s) and depth > 0:
                    if s[j] == '(': depth += 1
                    elif s[j] == ')': depth -= 1
                    j += 1
                inner = s[start_pos:j-1]
                depth2 = 0
                last_comma = -1
                for k, ch in enumerate(inner):
                    if ch == '(': depth2 += 1
                    elif ch == ')': depth2 -= 1
                    elif ch == ',' and depth2 == 0: last_comma = k
                if last_comma == -1:
                    result.append("LEFT(" + inner + ")")
                else:
                    result.append("SUBSTR(" + inner[:last_comma].strip() +
                                  ", 1, " + inner[last_comma+1:].strip() + ")")
                i = j
            return ''.join(result)
        e = _replace_left(e)

        # Step 6: CAST('date' AS DATETIME2) → TO_DATE
        e = _xre.sub(r"CAST\('([^']+)' AS DATETIME2\)",
                    lambda m: "TO_DATE('" + m.group(1) + "','YYYY-MM-DD')",
                    e, flags=_xre.IGNORECASE)

        # Step 7: scalar functions
        e = _xre.sub(r'\bNEWID\(\)', "RAWTOHEX(SYS_GUID())", e, flags=_xre.IGNORECASE)
        e = _xre.sub(r'\bGETUTCDATE\(\)', "SYS_EXTRACT_UTC(SYSTIMESTAMP)", e, flags=_xre.IGNORECASE)
        e = _xre.sub(r'\bGETDATE\(\)', "SYSDATE", e, flags=_xre.IGNORECASE)
        e = _xre.sub(r'\bSYSTEM_USER\b', "USER", e, flags=_xre.IGNORECASE)
        return e

    # Translate all expressions
    pairs     = [(p, _xlat_expr(expr)) for p, expr in pairs]
    auto_cols_exprs = [(m.ppdm_col, _xlat_expr(m.auto_gen_expr)) for m in auto_cols]

    # ── Get staging columns ───────────────────────────────────────────
    _stg_cols = set()
    try:
        with engine.connect() as _sc2:
            _stg_cols = {r[0].upper() for r in _sc2.execute(_txt(
                "SELECT column_name FROM all_tab_columns "
                "WHERE owner = :sch AND table_name = :tbl"
            ), {"sch": ora_schema.upper(), "tbl": _stg_bare.upper()}).fetchall()}
    except Exception:
        pass

    # ── Get target column types ───────────────────────────────────────
    _date_cols    = set()
    _num_cols     = {}   # col → (data_type, precision, scale)
    _varchar_cols = {}   # col → max char length
    try:
        with engine.connect() as _tc:
            for row in _tc.execute(_txt(
                "SELECT column_name, data_type, data_precision, data_scale, char_length "
                "FROM all_tab_columns "
                "WHERE owner = :sch AND table_name = :tbl"
            ), {"sch": ora_schema.upper(), "tbl": target_table.upper()}).fetchall():
                cname, dtype, prec, scale, charlen = row
                cname = cname.upper()
                dtype = (dtype or "").upper()
                if dtype in ("DATE", "TIMESTAMP"):
                    _date_cols.add(cname)
                elif dtype in ("NUMBER", "FLOAT"):
                    _num_cols[cname] = (dtype, prec or 38, scale or 0)
                elif dtype in ("VARCHAR2", "NVARCHAR2", "CHAR"):
                    if charlen:
                        _varchar_cols[cname] = int(charlen)
    except Exception:
        pass

    # ── Get PKs for NOT EXISTS dedup ──────────────────────────────────
    _pk_cols = []
    try:
        with engine.connect() as _pkc:
            _pk_cols = [r[0].upper() for r in _pkc.execute(_txt(
                "SELECT cc.column_name "
                "FROM all_constraints con "
                "JOIN all_cons_columns cc "
                "  ON cc.constraint_name = con.constraint_name "
                " AND cc.owner = con.owner "
                "WHERE con.constraint_type = 'P' "
                "  AND UPPER(con.table_name) = UPPER(:tbl) "
                "  AND con.owner = :sch "
                "ORDER BY cc.position"
            ), {"tbl": target_table.upper(), "sch": ora_schema.upper()}).fetchall()]
    except Exception:
        pass

    # ── Get FK constraints ────────────────────────────────────────────
    _fk_filters = []
    try:
        from collections import defaultdict
        # Oracle stores all identifiers in uppercase in catalog views
        _ora_schema_upper = ora_schema.upper()
        _tgt_upper        = target_table.upper()
        _fk_rows = engine.connect().execute(_txt(
            "SELECT cc.column_name, pc.table_name, pc.column_name, "
            "  CASE WHEN tc.nullable='Y' THEN 1 ELSE 0 END AS is_nullable "
            "FROM all_constraints con "
            "JOIN all_cons_columns cc "
            "  ON cc.constraint_name = con.constraint_name AND cc.owner = con.owner "
            "JOIN all_constraints rcon "
            "  ON rcon.constraint_name = con.r_constraint_name AND rcon.owner = con.r_owner "
            "JOIN all_cons_columns pc "
            "  ON pc.constraint_name = rcon.constraint_name AND pc.owner = rcon.owner "
            "  AND pc.position = cc.position "
            "JOIN all_tab_columns tc "
            "  ON tc.owner = con.owner AND tc.table_name = con.table_name "
            "  AND tc.column_name = cc.column_name "
            "WHERE con.constraint_type = 'R' "
            "  AND con.table_name = :tbl "
            "  AND con.owner = :sch"
        ), {"tbl": _tgt_upper, "sch": _ora_schema_upper}).fetchall()

        _col_to_expr = {p.upper(): expr for p, expr in pairs}
        _fk_groups    = defaultdict(list)   # parent_tbl -> [(child_col, parent_col)]
        _fk_nullable  = {}                  # parent_tbl -> True if ALL child cols nullable
        for child_col, parent_tbl, parent_col, is_nullable in _fk_rows:
            cc_up = child_col.upper()
            pt_up = parent_tbl.upper()
            if cc_up in _stg_cols or cc_up in _col_to_expr:
                _fk_groups[pt_up].append((child_col, parent_col))
                # Track nullability: group is nullable only if ALL its cols are nullable
                if pt_up not in _fk_nullable:
                    _fk_nullable[pt_up] = bool(is_nullable)
                else:
                    _fk_nullable[pt_up] = _fk_nullable[pt_up] and bool(is_nullable)

        for parent_tbl, col_pairs in _fk_groups.items():
            _par_count = 0
            try:
                with engine.connect() as _fkc:
                    _par_count = _fkc.execute(_txt(
                        f'SELECT COUNT(*) FROM {_q(ora_schema)}.{_q(parent_tbl)}'
                    )).scalar() or 0
            except Exception:
                pass
            if _par_count == 0:
                # Parent table empty — null out nullable FK cols to avoid constraint violation
                _is_nullable_empty = _fk_nullable.get(parent_tbl.upper(), True)
                if _is_nullable_empty:
                    for _cc_e, _pc_e in col_pairs:
                        _col_to_expr[_cc_e.upper()] = "NULL"
                continue

            _join_parts = []
            _skip = False
            for cc, pc in col_pairs:
                expr = _col_to_expr.get(cc.upper())
                if expr:
                    # Add src. prefix to quoted column refs in expr for the EXISTS subquery
                    import re as _fkre
                    _src_expr = _fkre.sub(r'"([^"]+)"', lambda m: 'src."' + m.group(1) + '"', expr)
                    # For simple string column refs (no transform), use UPPER() for case-insensitive match
                    _is_simple_col = (not expr.upper().startswith('UPPER') and
                                      not expr.upper().startswith('RAWTOHEX') and
                                      _varchar_cols.get(pc.upper()))
                    if _is_simple_col:
                        _join_parts.append(
                            f'UPPER(fk_{parent_tbl}.{_q(pc)}) = UPPER(TRIM({_src_expr}))'
                        )
                    else:
                        _join_parts.append(
                            f'fk_{parent_tbl}.{_q(pc)} = TRIM({_src_expr})'
                        )
                elif cc.upper() in _stg_cols:
                    # Use UPPER(TRIM()) for case+space insensitive FK matching
                    _join_parts.append(
                        f'UPPER(fk_{parent_tbl}.{_q(pc)}) = UPPER(TRIM(src.{_q(cc)}))'
                    )
                else:
                    _skip = True
                    break
            if _skip or not _join_parts:
                continue
            _exists_clause = (
                f'EXISTS (SELECT 1 FROM {_q(ora_schema)}.{_q(parent_tbl)} fk_{parent_tbl} '
                f'WHERE {" AND ".join(_join_parts)})'
            )
            _is_nullable_grp = _fk_nullable.get(parent_tbl.upper(), True)
            if _is_nullable_grp:
                # Nullable FK group — allow ALL rows through, but NULL out the FK
                # column in the SELECT when no parent match exists.
                # This way wells with unknown operators/fields still insert.
                import re as _nre_n
                for _cc_n, _pc_n in col_pairs:
                    _ck = _cc_n.upper()
                    _orig = _col_to_expr.get(_ck)
                    if _orig:
                        # Add src. prefix to the original expression for the CASE WHEN
                        _src_e = _nre_n.sub(
                            r'"([^"]+)"',
                            lambda m: 'src."' + m.group(1) + '"',
                            _orig)
                        _col_to_expr[_ck] = (
                            f'CASE WHEN {_exists_clause} '
                            f'THEN {_src_e} ELSE NULL END')
                    elif _ck in _stg_cols:
                        _col_to_expr[_ck] = (
                            f'CASE WHEN {_exists_clause} '
                            f'THEN TRIM(src.{_q(_cc_n)}) ELSE NULL END')
            else:
                # Non-nullable FK — keep original WHERE EXISTS + OR NULL behavior
                import re as _nre
                _null_parts = []
                for cc, pc in col_pairs:
                    expr = _col_to_expr.get(cc.upper())
                    if expr:
                        _refs = _nre.findall(r'"([^"]+)"', expr)
                        if _refs:
                            _null_parts.append(f'TRIM(src.{_q(_refs[0])}) IS NULL')
                    elif cc.upper() in _stg_cols:
                        _null_parts.append(f'TRIM(src.{_q(cc)}) IS NULL')
                if _null_parts:
                    _null_clause = " AND ".join(_null_parts)
                    _fk_filters.append(f'({_exists_clause} OR ({_null_clause}))')
                else:
                    _fk_filters.append(_exists_clause)
    except Exception:
        pass

    # ── Wrap expressions for date/numeric/length ──────────────────────
    def _wrap_date_ora(p, expr):
        if p.upper() in _date_cols:
            if not any(expr.upper().startswith(x) for x in
                       ("SYS_EXTRACT", "SYSDATE", "SYSTIMESTAMP", "TO_DATE",
                        "TO_TIMESTAMP", "NULL", "'")):
                # Try multiple date formats — handles YYYY-MM-DD and DD-Mon-YY etc.
                # Oracle doesn't have TRY_CONVERT so we use nested CASE
                return (
                    f"CASE WHEN TRIM({expr}) IS NULL OR TRIM({expr}) = '' THEN NULL "
                    f"WHEN REGEXP_LIKE(TRIM({expr}), '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$') "
                    f"THEN TO_DATE(TRIM({expr}), 'YYYY-MM-DD') "
                    f"WHEN REGEXP_LIKE(TRIM({expr}), '^[0-9]{{2}}-[A-Za-z]{{3}}-[0-9]{{2}}$') "
                    f"THEN TO_DATE(TRIM({expr}), 'DD-Mon-YY') "
                    f"WHEN REGEXP_LIKE(TRIM({expr}), '^[0-9]{{2}}-[A-Za-z]{{3}}-[0-9]{{4}}$') "
                    f"THEN TO_DATE(TRIM({expr}), 'DD-Mon-YYYY') "
                    f"WHEN REGEXP_LIKE(TRIM({expr}), '^[0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}}$') "
                    f"THEN TO_DATE(TRIM({expr}), 'MM/DD/YYYY') "
                    f"ELSE NULL END"
                )
        return expr

    def _wrap_num_ora(p, expr):
        info = _num_cols.get(p.upper())
        if info:
            dtype, prec, scale = info
            if not any(expr.upper().startswith(x) for x in
                       ("SYS_EXTRACT", "SYSDATE", "NULL", "'")):
                return (f"CASE WHEN TRIM({expr}) IS NOT NULL "
                        f"THEN TO_NUMBER(TRIM({expr})) ELSE NULL END")
        return expr

    def _wrap_len_ora(p, expr):
        maxlen = _varchar_cols.get(p.upper())
        if maxlen and maxlen > 0:
            if not any(expr.upper().startswith(x) for x in
                       ("SYS_EXTRACT", "SYSDATE", "NULL", "'")):
                # TRIM before SUBSTR so spaces do not violate FK constraints at insert
                return f"SUBSTR(TRIM({expr}), 1, {maxlen})"
        return expr

    # Apply nullable-FK CASE WHEN substitutions back into pairs
    _col_to_expr_final = {p.upper(): e for p, e in pairs}
    _col_to_expr_final.update(_col_to_expr)  # overlay nullable FK substitutions
    pairs = [(p, _col_to_expr_final.get(p.upper(), e)) for p, e in pairs]
    pairs = [(p, _wrap_date_ora(p, _wrap_num_ora(p, _wrap_len_ora(p, expr))))
             for p, expr in pairs]

    # ── Filter pairs to only valid staging columns ────────────────────
    def _expr_refs_missing(expr, stg_cols):
        """Check if the staging column refs in expr are all valid.
        Only checks refs OUTSIDE of EXISTS subqueries to avoid false positives
        from schema/table names in the CASE WHEN EXISTS wrapper."""
        if not stg_cols:
            return False
        # Strip EXISTS(...) subqueries before checking refs
        _stripped = _re.sub(r'EXISTS\s*\(SELECT.+?\)', '', expr,
                            flags=_re.IGNORECASE | _re.DOTALL)
        # Also strip CASE WHEN ... THEN / ELSE NULL END wrappers
        # Only check src."COL" style refs — these are staging refs
        refs = _re.findall(r'src\."([^"]+)"', _stripped)
        if not refs:
            # Fall back to all quoted refs if no src. prefix found
            refs = _re.findall(r'"([^"]+)"', _stripped)
        return any(r.upper() not in stg_cols for r in refs)

    pairs = [(p, expr) for p, expr in pairs
             if not _expr_refs_missing(expr, _stg_cols)]

    if not pairs and not auto_cols_exprs:
        return PromoteResult(
            ok=False, message="No columns mapped — nothing to promote.",
            target_table=target_table, staging_table=staging_table
        )

    # ── Build INSERT SQL ──────────────────────────────────────────────
    all_pairs = [(p, expr) for p, expr in pairs] + auto_cols_exprs
    tgt_cols_sql = ", ".join(_q(p) for p, _ in all_pairs)
    src_cols_sql = ", ".join(expr for _, expr in all_pairs)

    # NOT EXISTS duplicate check on PKs
    _dup_filter = ""
    if _pk_cols:
        _pk_match = " AND ".join(
            f'tgt.{_q(p)} = src.{_q(p)}'
            for p in _pk_cols
            if any(pp.upper() == p.upper() for pp, _ in pairs)
        )
        if _pk_match:
            _dup_filter = (f"NOT EXISTS (SELECT 1 FROM {tgt_full} tgt "
                           f"WHERE {_pk_match})")

    # NULL/empty check on PK source columns
    _pk_null_filters = []
    _col_to_expr2 = {p.upper(): expr for p, expr in pairs}
    for _pkc in _pk_cols:
        _expr = _col_to_expr2.get(_pkc.upper())
        if _expr and not _expr.startswith("'") and "SYS_GUID" not in _expr.upper():
            refs = _re.findall(r'"([^"]+)"', _expr)
            _pk_src = refs[0] if refs else None
            if _pk_src and _pk_src.upper() in _stg_cols:
                _pk_null_filters.append(
                    "src." + _q(_pk_src) + " IS NOT NULL"
                )

    _conditions = []
    if _dup_filter:
        _conditions.append(_dup_filter)
    _conditions.extend(_fk_filters)
    _conditions.extend(_pk_null_filters)
    _where = ("WHERE " + " AND ".join(_conditions)) if _conditions else ""

    # Oracle dedup: GROUP BY on PK cols if ROWID dedup fails
    _has_rowid_dedup = False
    if _pk_cols:
        _pk_set = {p.upper() for p in _pk_cols}
        _pk_pairs  = [(p, e) for p, e in pairs if p.upper() in _pk_set]
        _npk_pairs = [(p, e) for p, e in pairs if p.upper() not in _pk_set]
        if _pk_pairs:
            _inner_pk  = ", ".join(f"{e} AS {_q(p)}" for p, e in _pk_pairs)
            _inner_npk = ", ".join(f"MIN({e}) AS {_q(p)}" for p, e in _npk_pairs)
            _inner_sel = ", ".join(filter(None, [_inner_pk, _inner_npk]))
            _inner_grp = ", ".join(e for _, e in _pk_pairs)
            _auto_tgt  = ", ".join(_q(p) for p, _ in auto_cols_exprs)
            _auto_src  = ", ".join(e for _, e in auto_cols_exprs)
            _outer_tgt = ", ".join([_q(p) for p, _ in pairs] + ([_auto_tgt] if _auto_tgt else []))
            _outer_src = ", ".join([f"dedup.{_q(p)}" for p, _ in pairs] + ([_auto_src] if _auto_src else []))
            _pk_match2 = " AND ".join(
                f'tgt.{_q(p)} = dedup.{_q(p)}'
                for p in _pk_cols if any(pp.upper() == p.upper() for pp, _ in pairs)
            )
            _inner_conds = [c for c in _conditions if "NOT EXISTS" not in c]
            _inner_where = ("WHERE " + " AND ".join(_inner_conds)) if _inner_conds else ""
            _outer_where = (f"WHERE NOT EXISTS (SELECT 1 FROM {tgt_full} tgt WHERE {_pk_match2})"
                            if _pk_match2 else "")
            insert_sql = (
                f"INSERT INTO {tgt_full} ({_outer_tgt})\n"
                f"SELECT {_outer_src}\n"
                f"FROM (\n"
                f"    SELECT {_inner_sel}\n"
                f"    FROM {stg_full} src\n"
                f"    {_inner_where}\n"
                f"    GROUP BY {_inner_grp}\n"
                f") dedup\n"
                f"{_outer_where}"
            )
            _has_rowid_dedup = True

    if not _has_rowid_dedup:
        insert_sql = (
            f"INSERT INTO {tgt_full} ({tgt_cols_sql})\n"
            f"SELECT {src_cols_sql}\n"
            f"FROM {stg_full} src\n"
            f"{_where}"
        )

    # ── Count staging rows ────────────────────────────────────────────
    total_rows = 0
    try:
        with engine.connect() as _cnt:
            total_rows = _cnt.execute(_txt(
                f"SELECT COUNT(*) FROM {stg_full}"
            )).scalar() or 0
    except Exception:
        pass

    # ── Execute INSERT (bulk first, row-by-row fallback on integrity error) ──
    inserted    = 0
    _bad_rows   = []   # list of (pk_val, error_msg)
    _bad_file   = ""
    _used_fallback = False

    try:
        with engine.begin() as con:
            result = con.execute(_txt(insert_sql))
            inserted = result.rowcount
    except Exception as _bulk_exc:
        # Check if it's an integrity/constraint error worth retrying row-by-row
        _exc_str = str(_bulk_exc)
        _is_integrity = any(code in _exc_str for code in
                            ("ORA-02291", "ORA-00001", "ORA-02290",
                             "IntegrityError", "integrity"))
        if not _is_integrity:
            return PromoteResult(
                ok=False,
                message=f"Oracle promote failed: {_bulk_exc}\nSQL: {insert_sql[:500]}",
                target_table=target_table,
                staging_table=staging_table,
            )

        # ── Row-by-row fallback ───────────────────────────────────────
        # Build a SELECT version of the dedup query to iterate over rows
        _used_fallback = True
        _select_sql = insert_sql.replace(
            f"INSERT INTO {tgt_full} ({_outer_tgt if _has_rowid_dedup else tgt_cols_sql})\n"
            f"SELECT {_outer_src if _has_rowid_dedup else src_cols_sql}\n",
            f"SELECT {_outer_src if _has_rowid_dedup else src_cols_sql}\n",
            1
        )

        # Extract column names for the bad rows report
        _col_names = [p for p, _ in (pairs if not _has_rowid_dedup else pairs)] +                      [p for p, _ in auto_cols_exprs]

        # Identify PK column index for labelling bad rows
        _pk_idx = 0
        for _i, (_cn, _) in enumerate(all_pairs):
            if _cn.upper() in {p.upper() for p in _pk_cols}:
                _pk_idx = _i
                break

        try:
            with engine.connect() as _sel_con:
                _rows = _sel_con.execute(_txt(_select_sql)).fetchall()
        except Exception as _sel_exc:
            return PromoteResult(
                ok=False,
                message=f"Oracle promote failed (bulk + fallback select failed): {_sel_exc}",
                target_table=target_table,
                staging_table=staging_table,
            )

        # Build per-row INSERT with positional params
        _row_tgt = _outer_tgt if _has_rowid_dedup else tgt_cols_sql
        _row_placeholders = ", ".join(f":p{i}" for i in range(len(_rows[0]))) if _rows else ""
        _row_insert = f"INSERT INTO {tgt_full} ({_row_tgt}) VALUES ({_row_placeholders})"

        for _row in _rows:
            _params = {f"p{i}": v for i, v in enumerate(_row)}
            _pk_val = str(_row[_pk_idx]) if _pk_idx < len(_row) else "unknown"
            try:
                with engine.begin() as _ins_con:
                    _ins_con.execute(_txt(_row_insert), _params)
                inserted += 1
            except Exception as _row_exc:
                _bad_rows.append((_pk_val, str(_row_exc)[:200]))

        # Write bad rows to CSV
        if _bad_rows:
            import csv as _csv, os as _bos
            _bad_dir  = _bos.path.dirname(_bos.path.abspath(__file__))
            _bad_file = _bos.path.join(
                _bad_dir, f"bad_rows_{target_table}_{staging_table}.csv"
            )
            with open(_bad_file, "w", encoding="utf-8", newline="") as _bf:
                _bw = _csv.writer(_bf, quoting=_csv.QUOTE_ALL)
                _bw.writerow(["PK_VALUE", "ERROR"])
                _bw.writerows(_bad_rows)

    _write_audit_log(engine, schema, staging_table, target_table,
                     inserted, max(0, total_rows - inserted), insert_sql)

    _dupes   = max(0, total_rows - inserted - len(_bad_rows))
    _bad_msg = (f" · {len(_bad_rows)} row(s) failed FK/constraint — see {_bad_file}"
                if _bad_rows else "")
    _fb_msg  = " (row-by-row fallback used)" if _used_fallback else ""
    _msg     = f"Successfully inserted {inserted:,} rows into {tgt_full}"
    if _dupes > 0:
        _msg += f" ({_dupes} duplicate(s) skipped)"
    _msg += _bad_msg + _fb_msg

    return PromoteResult(
        ok=True,
        message=_msg,
        rows_inserted=inserted,
        rows_skipped=_dupes,
        rows_error=len(_bad_rows),
        bad_rows_file=_bad_file,
        target_table=target_table,
        staging_table=staging_table,
        sql_executed=insert_sql,
    )


def _count_rows(engine, full_table_name: str) -> int:
    """Fast row count using sys.partitions (avoids full table scan)."""
    try:
        from sqlalchemy import text
        clean = full_table_name.replace("[", "").replace("]", "")
        if "." in clean:
            sch, tbl = clean.split(".", 1)
        else:
            sch, tbl = "dbo", clean
        with engine.connect() as con:
            r = con.execute(text(
                "SELECT SUM(p.rows) FROM sys.partitions p "
                "JOIN sys.tables t ON t.object_id = p.object_id "
                "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                "WHERE p.index_id IN (0,1) "
                "AND t.name = :tbl AND s.name = :sch"
            ), {"tbl": tbl, "sch": sch})
            return r.scalar() or 0
    except Exception:
        try:
            from sqlalchemy import text
            with engine.connect() as con:
                r = con.execute(text(f"SELECT COUNT(*) FROM {full_table_name}"))
                return r.scalar() or 0
        except Exception:
            return 0


def _write_file_record(
    engine,
    schema:        str,
    source_file:   str,
    data_hash:     str,
    target_table:  str,
    row_count:     int,
    col_count:     int,
) -> tuple[bool, str]:
    """
    Write a record to PPDM_LOADER_FILES, creating the table if needed.
    Returns (is_duplicate, existing_load_ts) — duplicate if same hash already loaded
    into the same target table.  Dialect-aware: SQL Server and Oracle.
    """
    try:
        from sqlalchemy import text
        from modules.db import _detect_dialect
        dialect = _detect_dialect(engine)

        if dialect == "oracle":
            # Oracle: use connected user schema, sequences for PK, VARCHAR2 types
            with engine.connect() as _sc:
                ora_schema = _sc.execute(text(
                    "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                )).scalar() or schema.upper()
            files_table = f'"{ora_schema}"."PPDM_LOADER_FILES"'
            seq_name    = f'"{ora_schema}"."PPDM_LOADER_FILES_SEQ"'

            with engine.begin() as con:
                # Create sequence if needed
                con.execute(text(
                    f"BEGIN\n"
                    f"  EXECUTE IMMEDIATE 'CREATE SEQUENCE {seq_name} START WITH 1 INCREMENT BY 1';\n"
                    f"EXCEPTION WHEN OTHERS THEN\n"
                    f"  IF SQLCODE != -955 THEN RAISE; END IF;\n"  # -955 = already exists
                    f"END;"
                ))
                # Create table if needed
                con.execute(text(
                    f"BEGIN\n"
                    f"  EXECUTE IMMEDIATE 'CREATE TABLE {files_table} (\n"
                    f"    file_id      NUMBER PRIMARY KEY,\n"
                    f"    load_ts      TIMESTAMP DEFAULT SYS_EXTRACT_UTC(SYSTIMESTAMP),\n"
                    f"    source_file  VARCHAR2(512),\n"
                    f"    data_hash    VARCHAR2(64)  NOT NULL,\n"
                    f"    target_table VARCHAR2(128) NOT NULL,\n"
                    f"    row_count    NUMBER,\n"
                    f"    col_count    NUMBER,\n"
                    f"    load_status  VARCHAR2(20)  DEFAULT ''LOADED''\n"
                    f"  )';\n"
                    f"EXCEPTION WHEN OTHERS THEN\n"
                    f"  IF SQLCODE != -955 THEN RAISE; END IF;\n"
                    f"END;"
                ))
                # Check duplicate
                dup = con.execute(text(
                    f"SELECT load_ts FROM {files_table} "
                    f"WHERE data_hash = :h AND target_table = :t "
                    f"ORDER BY load_ts DESC FETCH FIRST 1 ROWS ONLY"
                ), {"h": data_hash, "t": target_table}).fetchone()
                if dup:
                    return True, str(dup[0])
                # Insert
                con.execute(text(
                    f"INSERT INTO {files_table} "
                    f"(file_id, source_file, data_hash, target_table, row_count, col_count) "
                    f"VALUES ({seq_name}.NEXTVAL, :f, :h, :t, :r, :c)"
                ), {"f": source_file, "h": data_hash,
                    "t": target_table, "r": row_count, "c": col_count})
            return False, ""

        else:
            # SQL Server
            files_table = f"[{schema}].[PPDM_LOADER_FILES]"
            with engine.begin() as con:
                con.execute(text(
                    f"IF OBJECT_ID('{schema}.PPDM_LOADER_FILES', 'U') IS NULL "
                    f"CREATE TABLE {files_table} ("
                    f"  file_id       INT IDENTITY(1,1) PRIMARY KEY, "
                    f"  load_ts       DATETIME2 DEFAULT GETUTCDATE(), "
                    f"  source_file   NVARCHAR(512), "
                    f"  data_hash     NVARCHAR(64)  NOT NULL, "
                    f"  target_table  NVARCHAR(128) NOT NULL, "
                    f"  row_count     INT, "
                    f"  col_count     INT, "
                    f"  load_status   NVARCHAR(20)  DEFAULT 'LOADED' "
                    f")"
                ))
                dup = con.execute(text(
                    f"SELECT TOP 1 load_ts FROM {files_table} "
                    f"WHERE data_hash = :h AND target_table = :t "
                    f"ORDER BY load_ts DESC"
                ), {"h": data_hash, "t": target_table}).fetchone()
                if dup:
                    return True, str(dup[0])
                con.execute(text(
                    f"INSERT INTO {files_table} "
                    f"(source_file, data_hash, target_table, row_count, col_count) "
                    f"VALUES (:f, :h, :t, :r, :c)"
                ), {"f": source_file, "h": data_hash,
                    "t": target_table, "r": row_count, "c": col_count})
            return False, ""

    except Exception as exc:
        print(f"Warning: could not write file record: {exc}")
        return False, ""


def _write_audit_log(engine, schema, staging, target, inserted, skipped, sql):
    """Write a row to PPDM_LOADER_LOG if it exists, silently skip if not."""
    try:
        from sqlalchemy import text
        from modules.db import _detect_dialect
        dialect = _detect_dialect(engine)

        if dialect == "oracle":
            with engine.connect() as _sc:
                ora_schema = _sc.execute(text(
                    "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                )).scalar() or schema.upper()
            log_table = f'"{ora_schema}"."PPDM_LOADER_LOG"'
            seq_name  = f'"{ora_schema}"."PPDM_LOADER_LOG_SEQ"'
            with engine.begin() as con:
                con.execute(text(
                    f"BEGIN\n"
                    f"  EXECUTE IMMEDIATE 'CREATE SEQUENCE {seq_name} START WITH 1 INCREMENT BY 1';\n"
                    f"EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;"
                ))
                con.execute(text(
                    f"BEGIN\n"
                    f"  EXECUTE IMMEDIATE 'CREATE TABLE {log_table} (\n"
                    f"    log_id        NUMBER PRIMARY KEY,\n"
                    f"    log_ts        TIMESTAMP DEFAULT SYS_EXTRACT_UTC(SYSTIMESTAMP),\n"
                    f"    staging_table VARCHAR2(128),\n"
                    f"    target_table  VARCHAR2(128),\n"
                    f"    rows_inserted NUMBER,\n"
                    f"    rows_skipped  NUMBER,\n"
                    f"    insert_sql    CLOB\n"
                    f"  )';\n"
                    f"EXCEPTION WHEN OTHERS THEN IF SQLCODE != -955 THEN RAISE; END IF; END;"
                ))
                con.execute(text(
                    f"INSERT INTO {log_table} "
                    f"(log_id, staging_table, target_table, rows_inserted, rows_skipped, insert_sql) "
                    f"VALUES ({seq_name}.NEXTVAL, :stg, :tgt, :ins, :skp, :sql)"
                ), {"stg": staging, "tgt": target,
                    "ins": inserted, "skp": skipped, "sql": sql})

        else:
            # SQL Server
            log_table = f"[{schema}].[PPDM_LOADER_LOG]"
            with engine.begin() as con:
                con.execute(text(
                    f"IF OBJECT_ID('{schema}.PPDM_LOADER_LOG','U') IS NULL "
                    f"CREATE TABLE {log_table} ("
                    f"  log_id        INT IDENTITY(1,1) PRIMARY KEY,"
                    f"  log_ts        DATETIME2 DEFAULT GETUTCDATE(),"
                    f"  staging_table NVARCHAR(128),"
                    f"  target_table  NVARCHAR(128),"
                    f"  rows_inserted INT,"
                    f"  rows_skipped  INT,"
                    f"  insert_sql    NVARCHAR(MAX)"
                    f")"
                ))
                con.execute(text(
                    f"INSERT INTO {log_table} "
                    f"(staging_table, target_table, rows_inserted, rows_skipped, insert_sql) "
                    f"VALUES (:stg, :tgt, :ins, :skp, :sql)"
                ), {"stg": staging, "tgt": target,
                    "ins": inserted, "skp": skipped, "sql": sql})

    except Exception:
        pass   # audit log failure should never block a promote


# ═══════════════════════════════════════════════════════════════════════
# MERGE (UPSERT)
# ═══════════════════════════════════════════════════════════════════════

def promote_merge(
    engine,
    staging_table: str,
    target_table:  str,
    mapping,
    pk_cols:       list[str],
    schema: str = "dbo",
) -> PromoteResult:
    """
    Execute server-side MERGE (upsert) from staging into target table.

    WHEN MATCHED → UPDATE non-PK mapped columns.
    WHEN NOT MATCHED → INSERT all mapped columns.

    pk_cols: list of PK column names on the target table (used for ON clause).
    """
    try:
        from sqlalchemy import text
        from modules.db import get_dialect as _mg_gd
        _mg_dialect = _mg_gd(engine).name

        pairs     = mapping.active_pairs
        auto_cols = mapping.auto_generated_cols

        if not pairs:
            pairs = []
            for m in getattr(mapping, "mapped", []):
                if getattr(m, "auto_generated", False):
                    continue
                _src = getattr(m, "source_col", "") or ""
                if not _src:
                    continue
                expr = getattr(m, "select_expr", None) or f"[{_src}]"
                pairs.append((m.ppdm_col, expr))

        _FK_AUDIT_SKIP = {"ROW_QUALITY"}
        if not auto_cols:
            auto_cols = [
                m for m in getattr(mapping, "mapped", [])
                if getattr(m, "auto_generated", False)
                and getattr(m, "ppdm_col", "").upper() not in _FK_AUDIT_SKIP
            ]
        else:
            auto_cols = [m for m in auto_cols
                         if getattr(m, "ppdm_col", "").upper() not in _FK_AUDIT_SKIP]

        # Filter auto_cols to only columns that exist in the target table
        _mg_sch = schema
        try:
            if _mg_dialect == "oracle":
                with engine.connect() as _mg_sc:
                    _mg_sch = _mg_sc.execute(text(
                        "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                    )).scalar() or schema.upper()
                _tgt_cols = {r[0].upper() for r in engine.connect().execute(text(
                    "SELECT column_name FROM all_tab_columns "
                    "WHERE owner=:sch AND table_name=:tbl"
                ), {"sch": _mg_sch.upper(), "tbl": target_table.upper()}).fetchall()}
            elif _mg_dialect == "snowflake":
                with engine.connect() as _mg_sc:
                    _mg_sch = _mg_sc.execute(text("SELECT CURRENT_SCHEMA()")).scalar() or schema
                _tgt_cols = {r[0].upper() for r in engine.connect().execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE UPPER(table_schema)=:sch AND UPPER(table_name)=:tbl"
                ), {"sch": _mg_sch.upper(), "tbl": target_table.upper()}).fetchall()}
            else:
                _mg_sch = "dbo"
                _tgt_cols = {r[0].upper() for r in engine.connect().execute(text(
                    "SELECT c.name FROM sys.columns c "
                    "JOIN sys.tables t ON t.object_id = c.object_id "
                    "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                    "WHERE LOWER(t.name) = LOWER(:tbl) AND s.name = 'dataview'"
                ), {"tbl": target_table}).fetchall()}
            auto_cols = [m for m in auto_cols
                         if getattr(m, "ppdm_col", "").upper() in _tgt_cols]
        except Exception:
            pass

        if not pairs and not auto_cols:
            return PromoteResult(
                ok=False, message="No columns mapped — nothing to promote.",
                target_table=target_table, staging_table=staging_table
            )

        _stg_bare = staging_table.split(".")[-1] if "." in staging_table else staging_table
        import re as _mg_re

        # Dialect-aware quoting, table refs, and expression translation
        if _mg_dialect == "oracle":
            def _q(n): return f'"{n.upper()}"'
            stg_full = f'"{_mg_sch}"."{_stg_bare.upper()}"'
            tgt_full = f'"{_mg_sch}"."{target_table.upper()}"'
            def _xlat(expr):
                e = expr.strip()
                e = _mg_re.sub(r'\[([^\]]+)\]', lambda m: f'"{m.group(1).upper()}"'  , e)
                e = _mg_re.sub(r'\bNVARCHAR\b', "VARCHAR2", e, flags=_mg_re.IGNORECASE)
                e = _mg_re.sub(r'\bLTRIM\s*\(\s*RTRIM\s*\((.+?)\)\s*\)',
                               lambda m: "TRIM(" + m.group(1) + ")", e, flags=_mg_re.IGNORECASE)
                def _hr(m):
                    inner = m.group(1).strip()
                    cm = _mg_re.match(r'CAST\s*\((.+?)\s+AS\s+VARCHAR2\s*\(\d+\)\s*\)$',
                                      inner, _mg_re.IGNORECASE | _mg_re.DOTALL)
                    if cm: inner = cm.group(1).strip()
                    _c = "UPPER(TRIM(REGEXP_REPLACE(" + inner + ", '[\\s]', '')))"
                    return "UPPER(RAWTOHEX(DBMS_CRYPTO.HASH(UTL_RAW.CAST_TO_RAW(" + _c + "),3)))"
                e = _mg_re.sub(
                    r"CONVERT\s*\(\s*CHAR\s*\(\s*40\s*\)\s*,\s*HASHBYTES\s*\(\s*'SHA1'\s*,\s*(.+?)\s*\)\s*,\s*2\s*\)",
                    _hr, e, flags=_mg_re.IGNORECASE)
                return e
            _AUDIT_UPD = {"ROW_CHANGED_BY": "'PPDM_LOADER'",
                          "ROW_CHANGED_DATE": "SYS_EXTRACT_UTC(SYSTIMESTAMP)"}
        elif _mg_dialect == "snowflake":
            def _q(n): return f'"{n.upper()}"'
            stg_full = f'"{_mg_sch}"."{_stg_bare.upper()}"'
            tgt_full = f'"{_mg_sch}"."{target_table.upper()}"'
            def _xlat(expr):
                e = expr.strip()
                e = _mg_re.sub(r'\[([^\]]+)\]', lambda m: f'"{m.group(1).upper()}"'  , e)
                return e
            _AUDIT_UPD = {"ROW_CHANGED_BY": "'PPDM_LOADER'",
                          "ROW_CHANGED_DATE": "CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())"}
        else:
            def _q(n): return f"[{n}]"
            stg_full = f"[{schema}].[{_stg_bare}]"
            tgt_full = f"[dataview].[{target_table}]"
            def _xlat(expr): return expr
            _AUDIT_UPD = {"ROW_CHANGED_BY": "'PPDM_LOADER'",
                          "ROW_CHANGED_DATE": "GETUTCDATE()"}

        pairs = [(p, _xlat(expr)) for p, expr in pairs]

        # Wrap date columns for Oracle
        if _mg_dialect == "oracle":
            _date_suffixes = ("_DATE", "_DT", "_TIME")
            def _wrap_date_mg(p, expr):
                if any(p.upper().endswith(s) for s in _date_suffixes):
                    # Skip if already a date expression
                    _eu = expr.upper().strip()
                    if not any(_eu.startswith(x) for x in
                               ("SYS_EXTRACT", "SYSDATE", "SYSTIMESTAMP", "TO_DATE",
                                "TO_TIMESTAMP", "CASE WHEN", "NULL", "'")):
                        return (
                            f"CASE WHEN TRIM(TO_CHAR({expr})) IS NULL THEN NULL "
                            f"WHEN REGEXP_LIKE(TRIM(TO_CHAR({expr})), '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$') "
                            f"THEN TO_DATE(TRIM(TO_CHAR({expr})), 'YYYY-MM-DD') "
                            f"WHEN REGEXP_LIKE(TRIM(TO_CHAR({expr})), '^[0-9]{{2}}-[A-Za-z]{{3}}-[0-9]{{2}}$') "
                            f"THEN TO_DATE(TRIM(TO_CHAR({expr})), 'DD-Mon-YY') "
                            f"WHEN REGEXP_LIKE(TRIM(TO_CHAR({expr})), '^[0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}}$') "
                            f"THEN TO_DATE(TRIM(TO_CHAR({expr})), 'MM/DD/YYYY') "
                            f"ELSE NULL END"
                        )
                return expr
            pairs = [(p, _wrap_date_mg(p, expr)) for p, expr in pairs]

        pk_upper     = {p.upper() for p in pk_cols}
        pk_pairs     = [(col, expr) for col, expr in pairs if col.upper() in pk_upper]
        update_pairs = [(col, expr) for col, expr in pairs if col.upper() not in pk_upper]

        if not pk_pairs:
            return PromoteResult(
                ok=False,
                message=f"None of the mapped columns are PK columns {pk_cols} — cannot build MERGE ON clause.",
                target_table=target_table, staging_table=staging_table
            )

        using_select = ", ".join(f"{expr} AS {_q(col)}" for col, expr in pairs)
        if _mg_dialect == "oracle":
            using_sql = f"(SELECT {using_select} FROM {stg_full}) src"
        else:
            using_sql = f"(SELECT {using_select} FROM {stg_full}) AS src"

        on_parts     = " AND ".join(f"tgt.{_q(col)} = src.{_q(col)}" for col, _ in pk_pairs)
        update_parts = [f"tgt.{_q(col)} = src.{_q(col)}" for col, _ in update_pairs]
        for acol, aexpr in _AUDIT_UPD.items():
            if any(getattr(m, "ppdm_col", "").upper() == acol for m in auto_cols):
                update_parts.append(f"tgt.{_q(acol)} = {aexpr}")

        insert_tgt = [_q(col) for col, _ in pairs] + [_q(m.ppdm_col) for m in auto_cols]

        def _xlat_auto(expr):
            if _mg_dialect == "oracle":
                expr = expr.replace("NEWID()", "RAWTOHEX(SYS_GUID())")
                expr = expr.replace("GETUTCDATE()", "SYS_EXTRACT_UTC(SYSTIMESTAMP)")
                expr = expr.replace("CAST('1900-01-01' AS DATETIME2)", "TO_DATE('1900-01-01','YYYY-MM-DD')")
                expr = expr.replace("CAST('2099-12-31' AS DATETIME2)", "TO_DATE('2099-12-31','YYYY-MM-DD')")
            elif _mg_dialect == "snowflake":
                expr = expr.replace("NEWID()", "UUID_STRING()")
                expr = expr.replace("GETUTCDATE()", "CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())")
                expr = expr.replace("CAST('1900-01-01' AS DATETIME2)", "TO_DATE('1900-01-01','YYYY-MM-DD')")
                expr = expr.replace("CAST('2099-12-31' AS DATETIME2)", "TO_DATE('2099-12-31','YYYY-MM-DD')")
            return expr

        insert_src = [f"src.{_q(col)}" for col, _ in pairs] + [_xlat_auto(m.auto_gen_expr) for m in auto_cols]

        if _mg_dialect == "oracle":
            merge_sql = f"MERGE INTO {tgt_full} tgt\nUSING {using_sql}\nON ({on_parts})\n"
        else:
            merge_sql = f"MERGE {tgt_full} AS tgt\nUSING {using_sql}\nON ({on_parts})\n"

        if update_parts:
            merge_sql += f"WHEN MATCHED THEN\n    UPDATE SET {chr(44).join(update_parts)}\n"
        merge_sql += f"WHEN NOT MATCHED THEN\n    INSERT ({chr(44).join(insert_tgt)})\n    VALUES ({chr(44).join(insert_src)})"
        if _mg_dialect != "oracle":
            merge_sql += ";"

        total_rows = _count_rows(engine, stg_full)

        with engine.begin() as con:
            result   = con.execute(text(merge_sql))
            affected = result.rowcount

        _write_audit_log(engine, schema, staging_table, target_table,
                         affected, 0, merge_sql)

        return PromoteResult(
            ok=True,
            message=f"MERGE complete — {affected:,} row(s) affected (updated + inserted) in {tgt_full}",
            rows_inserted=affected, rows_skipped=0,
            rows_error=max(0, total_rows - affected),
            target_table=target_table, staging_table=staging_table,
            sql_executed=merge_sql,
        )

    except Exception as exc:
        return PromoteResult(
            ok=False,
            message=f"Promote (merge) failed (transaction rolled back): {exc}",
            target_table=target_table,
            staging_table=staging_table,
        )


# ═══════════════════════════════════════════════════════════════════════
# DEMO PROMOTE
# ═══════════════════════════════════════════════════════════════════════

def promote_demo(
    df: pd.DataFrame,
    mapping,
    skip_indices: set[int],
    validation_report,
    target_table: str,
    staging_table: str,
) -> PromoteResult:
    """
    Demo mode promote — filter df and simulate INSERT, return stats.
    """
    error_indices = getattr(validation_report, "error_row_indices", set())
    all_skip = skip_indices | error_indices

    clean_df = df.drop(index=list(all_skip), errors="ignore")

    pairs = mapping.active_pairs
    if not pairs:
        return PromoteResult(
            ok=False, message="No columns mapped.",
            target_table=target_table, staging_table=staging_table
        )

    try:
        src_cols  = [s for _, s in pairs if s in clean_df.columns]
        ppdm_cols = [p for p, s in pairs if s in clean_df.columns]
        result_df = clean_df[src_cols].copy()
        result_df.columns = ppdm_cols

        tgt_cols_sql = ", ".join(f"[{p}]" for p in ppdm_cols)
        src_cols_sql = ", ".join(f"[{s}]" for s in src_cols)
        skip_ids_str = ", ".join(str(i) for i in sorted(all_skip)) or "—none—"
        sql_preview = (
            f"-- DEMO PREVIEW (not executed)\n"
            f"INSERT INTO dbo.[{target_table}] ({tgt_cols_sql})\n"
            f"SELECT {src_cols_sql}\n"
            f"FROM dbo.[{staging_table}]\n"
            f"WHERE [_stg_row_id] NOT IN ({skip_ids_str})"
        )

        return PromoteResult(
            ok=True,
            message=f"Demo promote: {len(result_df):,} rows would be inserted into [{target_table}]",
            rows_inserted=len(result_df),
            rows_skipped=len(skip_indices),
            rows_error=len(error_indices),
            target_table=target_table,
            staging_table=staging_table,
            sql_executed=sql_preview,
        )

    except Exception as exc:
        return PromoteResult(
            ok=False, message=f"Demo promote failed: {exc}",
            target_table=target_table, staging_table=staging_table
        )


# ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("PPDM Loader — Module 8: Promote Test")
    print("=" * 60)

    from modules.schema import load_schema_from_string
    from modules.mapping import build_mapping
    from modules.validate import ValidationReport

    _J = """{"ppdm_39_schema_domain": [
        {"model":"PPDM 3.9","category":"WELL","sub_category":"well",
         "table_schema":"dbo","table_name":"well","column_name":"UWI",
         "data_type":"nvarchar(40)","not_null":"YES","is_primary_key":"YES",
         "is_foreign_key":"NO","fk_table_schema":null,"fk_table_name":null,
         "fk_column_name":null,"check_constraints":""},
        {"model":"PPDM 3.9","category":"WELL","sub_category":"well",
         "table_schema":"dbo","table_name":"well","column_name":"WELL_NAME",
         "data_type":"nvarchar(255)","not_null":"NO","is_primary_key":"NO",
         "is_foreign_key":"NO","fk_table_schema":null,"fk_table_name":null,
         "fk_column_name":null,"check_constraints":""},
        {"model":"PPDM 3.9","category":"WELL","sub_category":"well",
         "table_schema":"dbo","table_name":"well","column_name":"ACTIVE_IND",
         "data_type":"nvarchar(1)","not_null":"NO","is_primary_key":"NO",
         "is_foreign_key":"NO","fk_table_schema":null,"fk_table_name":null,
         "fk_column_name":null,"check_constraints":""}
    ]}"""

    schema = load_schema_from_string(_J)
    tbl    = schema.get_table("well")

    df = pd.DataFrame({
        "UWI":       ["W001", "W002", "W003", "W004"],
        "WELL_NAME": ["Alpha", "Beta",  "Gamma", "Delta"],
        "ACTIVE_IND":["Y",     "N",     "Y",     "N"],
    })

    mp = build_mapping("well", tbl.columns, list(df.columns))

    skip_set   = {1}
    val_report = ValidationReport(rows_checked=3)
    val_report.issues = []

    from modules.validate import ValidationIssue
    val_report.issues.append(ValidationIssue(
        row_idx=3, ppdm_col="UWI", src_col="UWI",
        value="W004", rule="DUPLICATE_PK", severity="ERROR",
        message="Duplicate PK"
    ))

    print("\n[TEST 1] Demo promote")
    result = promote_demo(df, mp, skip_set, val_report, "well", "STG_WELLS")
    assert result.ok, f"Promote failed: {result.message}"
    assert result.rows_inserted == 2,  f"Expected 2 inserted, got {result.rows_inserted}"
    assert result.rows_skipped  == 1,  f"Expected 1 skipped,  got {result.rows_skipped}"
    assert result.rows_error    == 1,  f"Expected 1 error,    got {result.rows_error}"
    print(f"  ✓  {result.message}")
    print(f"  ✓  inserted={result.rows_inserted}  "
          f"skipped={result.rows_skipped}  errors={result.rows_error}")

    print("\n[TEST 2] SQL preview")
    print(result.sql_executed)
    assert "INSERT INTO" in result.sql_executed
    assert "WHERE" in result.sql_executed
    print("  ✓  SQL preview contains INSERT and WHERE clause")

    print("\n[TEST 3] No mapped columns guard")
    from modules.mapping import ColumnMapping
    empty_mp = ColumnMapping(target_table="well", source_columns=[])
    r2 = promote_demo(df, empty_mp, set(), ValidationReport(), "well", "STG_WELLS")
    assert not r2.ok
    print(f"  ✓  Empty mapping rejected: '{r2.message}'")

    print("\n" + "=" * 60)
    print("All tests passed ✓")
    print("=" * 60)

"""
normalize.py  —  PPDM Loader · Module 4: Normalization
=======================================================
Applies data normalization to the staging table BEFORE mapping and validation.

Server-side (SQL Server) transforms — fast, set-based:
  - LTRIM/RTRIM all string columns
  - UPPER() on Y/N indicator columns (_IND suffix)
  - UPPER() on code columns (short nvarchar columns that look like codes)
  - Standardize date strings to ISO format via multi-format COALESCE:
      101 = MM/DD/YYYY  (US slash  — most common source format)
      103 = DD/MM/YYYY  (UK slash)
      105 = DD-MM-YYYY  (EU dash)
      120 = YYYY-MM-DD  (ISO — already correct, normalizes time portion)

In-memory (Demo Mode) transforms — pandas equivalent of the above.

Returns a NormalizeResult with:
  - The normalized DataFrame
  - A change log showing what was changed and how many values affected

Test:
    python normalize.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
# RESULT TYPE
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class NormChange:
    """Records one category of normalization change."""
    transform:     str        # e.g. "TRIM whitespace"
    columns:       list[str]  # columns affected
    values_changed: int       # total cell count changed


@dataclass
class NormalizeResult:
    ok:       bool
    message:  str
    df:       Optional[pd.DataFrame] = None
    changes:  list[NormChange] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return sum(c.values_changed for c in self.changes)


# ═══════════════════════════════════════════════════════════════════════
# DATE PARSING
# ═══════════════════════════════════════════════════════════════════════

_DATE_FORMATS = [
    "%m/%d/%Y",   # MM/DD/YYYY  — US slash (most common source format)
    "%d/%m/%Y",   # DD/MM/YYYY  — UK slash
    "%d-%m-%Y",   # DD-MM-YYYY  — EU dash
    "%Y-%m-%d",   # YYYY-MM-DD  — ISO
    "%Y%m%d",     # YYYYMMDD    — compact
    "%d-%b-%Y",   # DD-Mon-YYYY — e.g. 30-Mar-1977
]

def _parse_date(val: str) -> Optional[str]:
    v = str(val).strip()
    if not v:
        return None
    for fmt in _DATE_FORMATS:
        try:
            from datetime import datetime
            dt = datetime.strptime(v, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════
# COLUMN CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════

def _is_indicator_col(col: str) -> bool:
    return col.upper().endswith("_IND")


def _is_date_col(col: str, sample_vals: list[str]) -> bool:
    if re.search(r"(_DATE|_DT)$", col.upper()):
        return True
    non_empty = [v for v in sample_vals if v and str(v).strip()]
    if not non_empty:
        return False
    parsed = sum(1 for v in non_empty[:20] if _parse_date(str(v)) is not None)
    return parsed / len(non_empty[:20]) > 0.5


def _is_code_col(col: str, data_type: str = "") -> bool:
    code_suffixes = (
        "_TYPE", "_CLASS", "_STATUS", "_IND", "_CODE", "_SUBTYPE",
        "_OUOM", "_DATUM", "_SOURCE", "_QUALITY", "_LEVEL",
    )
    if any(col.upper().endswith(s) for s in code_suffixes):
        return True
    if data_type:
        m = re.search(r"\((\d+)\)", data_type.lower())
        if m and int(m.group(1)) <= 10:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# SERVER-SIDE NORMALIZATION (SQL Server)
# ═══════════════════════════════════════════════════════════════════════

def build_normalize_sql(
    staging_table: str,
    df_columns: list[str],
    schema_col_types: dict[str, str] | None = None,
    schema: str = "dbo",
    df_sample=None,
    pk_cols: list[str] | None = None,
) -> list[str]:
    full = f"[{schema}].[{staging_table}]"
    statements: list[str] = []
    col_types = schema_col_types or {}

    # Exclude internal/audit columns from normalization
    _SKIP_COLS = {"_batch_loaded_at"}

    trim_cols  = []
    upper_cols = []
    date_cols  = []

    for col in df_columns:
        if col in _SKIP_COLS:
            continue
        dtype = col_types.get(col.lower(), col_types.get(col.upper(), ""))
        hint  = _sql_type_hint(dtype)

        if hint == "string":
            trim_cols.append(col)

        if _is_indicator_col(col) or _is_code_col(col, dtype):
            upper_cols.append(col)

        if hint in ("date", "datetime") or _is_date_col(col, []):
            date_cols.append(col)

    # ── SELECT INTO new table (minimally logged) then rename ─────────────
    # Much faster than UPDATE for large staging tables — avoids full transaction logging
    _date_set = set(date_cols)
    _new_tbl  = f"{staging_table}_norm"
    _full_new = f"[{schema}].[{_new_tbl}]"

    # Detect dominant date format from sample
    _date_style = None
    if date_cols and df_sample is not None:
        import re as _dre
        _sample_vals = []
        for _dc in date_cols[:3]:
            if _dc in df_sample.columns:
                _sample_vals += [
                    str(v).strip() for v in df_sample[_dc].dropna()
                    if str(v).strip()
                ][:20]
        if _sample_vals:
            # Check for ISO format first
            if _dre.match(r'\d{4}-\d{2}-\d{2}', _sample_vals[0]):
                _date_style = 120
            elif _dre.match(r'\d{2}/\d{2}/\d{4}', _sample_vals[0]):
                _date_style = 101
            elif _dre.match(r'\d{2}-\d{2}-\d{4}', _sample_vals[0]):
                # DD-MM-YYYY vs MM-DD-YYYY — look for day > 12 to disambiguate
                _has_day_gt12 = any(
                    _dre.match(r'(\d{2})-\d{2}-\d{4}', _sv) and
                    int(_dre.match(r'(\d{2})-\d{2}-\d{4}', _sv).group(1)) > 12
                    for _sv in _sample_vals[:20]
                )
                _date_style = 105 if _has_day_gt12 else 101

    def _date_expr(c):
        # Always use COALESCE — single style misses ambiguous values.
        # Order: detected style first, then all others as fallback.
        # Style 105 (DD-MM-YYYY) before 101 (MM-DD-YYYY) to handle European dates.
        if _date_style == 120:
            _styles = [120, 105, 101, 103]
        elif _date_style == 105:
            _styles = [105, 120, 103, 101]
        elif _date_style == 101:
            _styles = [101, 105, 120, 103]
        else:
            _styles = [105, 120, 103, 101]
        _conv = ("COALESCE(" +
                 ",".join(f"TRY_CONVERT(date,[{c}],{s})" for s in _styles) +
                 ")")
        return (f"CASE WHEN [{c}] IS NOT NULL AND {_conv} IS NOT NULL "
                f"THEN CONVERT(varchar(10),{_conv},23) ELSE [{c}] END")

    # Build SELECT column list
    sel_parts = []
    for c in df_columns:
        if c in _SKIP_COLS:
            sel_parts.append(f"[{c}]")
        elif c in _date_set:
            sel_parts.append(f"{_date_expr(c)} AS [{c}]")
        elif c in set(trim_cols):
            expr = f"NULLIF(LTRIM(RTRIM(REPLACE(REPLACE([{c}],CHAR(13),''),CHAR(10),''))),'')"
            if c in set(upper_cols):
                expr = f"UPPER({expr})"
            sel_parts.append(f"{expr} AS [{c}]")
        elif c in set(upper_cols):
            sel_parts.append(f"UPPER([{c}]) AS [{c}]")
        else:
            sel_parts.append(f"[{c}]")

    sel_sql = ",\n    ".join(sel_parts)

    statements.append(
        f"IF OBJECT_ID('{schema}.{_new_tbl}','U') IS NOT NULL "
        f"DROP TABLE {_full_new}"
    )
    statements.append(
        f"SELECT\n    {sel_sql}\nINTO {_full_new}\nFROM {full}"
    )

    # Add clustered index — use provided PK cols, else guess from column names
    _idx_col = None
    if pk_cols:
        # Use first PK col that exists in staging columns
        _idx_col = next((c for c in pk_cols if c in df_columns), None)
    if not _idx_col:
        _pk_candidates = [c for c in df_columns
                          if c.upper() in ('UWI', 'WELL_ID', 'BA_ID',
                                           'BUSINESS_ASSOCIATE_ID', 'FIELD_ID',
                                           'SOURCE', 'STATUS_TYPE', 'WELL_CLASS',
                                           'DATUM_TYPE', 'LOCATION_TYPE')]
        if not _pk_candidates:
            _pk_candidates = [c for c in df_columns
                              if c.upper() not in ('_BATCH_LOADED_AT',
                                                   'ROW_CREATED_DATE',
                                                   'ROW_CHANGED_DATE')]
        _idx_col = _pk_candidates[0] if _pk_candidates else None

    if _idx_col:
        statements.append(
            f"CREATE CLUSTERED INDEX [cx_{staging_table}] "
            f"ON {_full_new} ([{_idx_col}])"
        )

    statements.append(f"DROP TABLE {full}")
    statements.append(
        f"EXEC sp_rename '{schema}.{_new_tbl}', '{staging_table}'"
    )

    return statements


def _sql_type_hint(dtype_str: str) -> str:
    d = dtype_str.lower()
    if any(x in d for x in ("numeric", "decimal", "float", "real", "money")):
        return "numeric"
    if "int" in d:
        return "int"
    if "datetime" in d:
        return "datetime"
    if "date" in d:
        return "date"
    return "string"



def _normalize_server_oracle(
    engine,
    staging_table: str,
    df: pd.DataFrame,
    schema_col_types: dict[str, str] | None = None,
    schema: str = "dbo",
) -> NormalizeResult:
    """
    Oracle normalization: UPDATE staging table in-place using Oracle SQL.
    Oracle does not support SELECT INTO or sp_rename so we use UPDATE statements.
    TRY_CONVERT → TO_DATE with exception guard.
    CHAR(13)/CHAR(10) → CHR(13)/CHR(10).
    Bracket notation → double-quote notation.
    """
    try:
        from sqlalchemy import text

        # Use schema param directly if it looks like a real schema name
        # (not "dbo" or "stg") — avoids a DB round-trip on every normalize call
        if schema and schema.upper() not in ("DBO","STG",""):
            ora_schema = schema.upper()
        else:
            try:
                with engine.connect() as _sc:
                    ora_schema = _sc.execute(text(
                        "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                    )).scalar() or schema.upper()
            except Exception:
                ora_schema = schema.upper()

        _q     = lambda n: f'"{n.upper()}"'
        full   = f'"{ora_schema}"."{staging_table.upper()}"'
        col_types = schema_col_types or {}

        _SKIP_COLS  = {"_BATCH_LOADED_AT", "_batch_loaded_at"}
        trim_cols   = []
        upper_cols  = []
        date_cols   = []

        for col in df.columns:
            if col in _SKIP_COLS or col.upper() in _SKIP_COLS:
                continue
            dtype = col_types.get(col.lower(), col_types.get(col.upper(), ""))
            hint  = _sql_type_hint(dtype)
            if hint == "string":
                trim_cols.append(col)
            if _is_indicator_col(col) or _is_code_col(col, dtype):
                upper_cols.append(col)
            if hint in ("date", "datetime") or _is_date_col(col, []):
                date_cols.append(col)

        _date_set  = set(col.upper() for col in date_cols)
        _trim_set  = set(col.upper() for col in trim_cols)
        _upper_set = set(col.upper() for col in upper_cols)

        # Detect dominant date format from sample
        _date_fmt = "YYYY-MM-DD"
        if date_cols and df is not None and len(df) > 0:
            import re as _dre
            _sample_vals = []
            for _dc in date_cols[:3]:
                if _dc in df.columns:
                    _sample_vals += [
                        str(v).strip() for v in df[_dc].dropna()
                        if str(v).strip()
                    ][:10]
            if _sample_vals:
                _v = _sample_vals[0]
                if _dre.match(r'\d{2}/\d{2}/\d{4}', _v):
                    _date_fmt = "MM/DD/YYYY"
                elif _dre.match(r'\d{2}-\d{2}-\d{4}', _v):
                    _date_fmt = "MM-DD-YYYY"

        def _ora_date_expr(c):
            qc = _q(c)
            return (
                f"CASE WHEN {qc} IS NOT NULL AND TRIM({qc}) != '' THEN "
                f"TO_CHAR(TO_DATE(TRIM({qc}),'{_date_fmt}'),'YYYY-MM-DD') "
                f"ELSE {qc} END"
            )

        def _ora_trim_expr(c):
            qc = _q(c)
            expr = (f"NULLIF(TRIM(REPLACE(REPLACE({qc},"
                    f"CHR(13),''),CHR(10),'')),'')")
            if c.upper() in _upper_set:
                expr = f"UPPER({expr})"
            return expr

        # Build SET clauses
        set_clauses = []
        for col in df.columns:
            cu = col.upper()
            if cu in _SKIP_COLS:
                continue
            if cu in _date_set:
                set_clauses.append(f"{_q(col)} = {_ora_date_expr(col)}")
            elif cu in _trim_set:
                set_clauses.append(f"{_q(col)} = {_ora_trim_expr(col)}")
            elif cu in _upper_set:
                set_clauses.append(f"{_q(col)} = UPPER({_q(col)})")

        if not set_clauses:
            return NormalizeResult(
                ok=True,
                message="No normalization needed (no string/date columns detected)",
                df=df,
            )

        # Execute SET clauses in one UPDATE if possible, batch of 100 otherwise.
        # ORA-24344 (success with compilation error) triggers above ~950 chars
        # per SET clause on very wide tables — 100 is safe for WELL (200 cols).
        BATCH = 100
        stmts_run = 0
        with engine.begin() as con:
            # Enable parallel DML for this session
            try:
                con.execute(text("ALTER SESSION ENABLE PARALLEL DML"))
            except Exception:
                pass
            for i in range(0, len(set_clauses), BATCH):
                batch = set_clauses[i:i+BATCH]
                sql = f"UPDATE /*+ PARALLEL(4) */ {full} SET {', '.join(batch)}"
                con.execute(text(sql))
                stmts_run += 1

        return NormalizeResult(
            ok=True,
            message=f"Oracle normalization complete ({stmts_run} UPDATE(s), {len(set_clauses)} column(s) normalized)",
            df=df,
        )

    except Exception as exc:
        return NormalizeResult(ok=False, message=f"Normalization failed: {exc}")


def normalize_server(
    engine,
    staging_table: str,
    df: pd.DataFrame,
    schema_col_types: dict[str, str] | None = None,
    schema: str = "dbo",
    date_format: str | None = None,
) -> NormalizeResult:
    """
    Run server-side normalization on the staging table.
    Optional — called only when user clicks Run Normalization in Stage 3.
    Dialect-aware: SQL Server and Oracle.
    """
    try:
        from sqlalchemy import text
        from dataview.core.db import get_dialect
        _d = get_dialect(engine)

        if _d.name == "oracle":
            return _normalize_server_oracle(engine, staging_table, df, schema_col_types, schema)

        # SQL Server path
        _date_style_override = None
        if date_format == "DMY":   _date_style_override = 105
        elif date_format == "MDY": _date_style_override = 101
        elif date_format == "YMD": _date_style_override = 120

        # Look up PK columns for index creation
        _pk_cols = []
        try:
            with engine.connect() as _pkc:
                _pk_cols = [r[0] for r in _pkc.execute(text("""
                    SELECT c.name FROM sys.indexes i
                    JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                    JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                    JOIN sys.tables t ON t.object_id=i.object_id
                    JOIN sys.schemas s ON s.schema_id=t.schema_id
                    WHERE i.is_primary_key=1 AND t.name=:tbl AND s.name='dbo'
                    ORDER BY ic.key_ordinal
                """), {"tbl": staging_table.replace("stg_","",1)}).fetchall()]
        except Exception:
            pass

        # Build sample df — if date_format specified, inject unambiguous sample values
        _df_sample = df.head(50) if df is not None and len(df) > 0 else None
        if _date_style_override is not None and _df_sample is not None:
            import pandas as _npd
            _df_sample = _df_sample.copy()
            _fmt_sentinel = {105: "29-01-2000", 101: "01/29/2000", 120: "2000-01-29"}
            _sentinel = _fmt_sentinel.get(_date_style_override, "29-01-2000")
            for _dc in _df_sample.columns:
                if "date" in _dc.lower() or _dc.lower().endswith("_dt"):
                    _df_sample[_dc] = _sentinel

        statements = build_normalize_sql(
            staging_table, list(df.columns), schema_col_types, schema,
            df_sample=_df_sample,
            pk_cols=_pk_cols or None
        )

        with engine.begin() as con:
            for sql in statements:
                con.execute(text(sql))

        user_stmts = 0
        try:
            from dataview.reference_tables.user_rules import apply_norm_rules_server
            _cols_only_df = pd.DataFrame(columns=list(df.columns))
            user_stmts, _ = apply_norm_rules_server(
                engine, staging_table, _cols_only_df,
                target_table=staging_table, schema=schema
            )
        except Exception:
            pass

        total = len(statements) + user_stmts
        return NormalizeResult(
            ok=True,
            message=f"Server-side normalization complete ({total} transforms applied)",
            df=df,
        )

    except Exception as exc:
        return NormalizeResult(ok=False, message=f"Normalization failed: {exc}")


# ═══════════════════════════════════════════════════════════════════════
# IN-MEMORY NORMALIZATION (Demo Mode)
# ═══════════════════════════════════════════════════════════════════════

def normalize_demo(
    df: pd.DataFrame,
    schema_col_types: dict[str, str] | None = None,
) -> NormalizeResult:
    try:
        df = df.copy()
        col_types = schema_col_types or {}
        changes: list[NormChange] = []

        # 1. TRIM
        trim_changed = 0
        trim_cols = []
        for col in df.columns:
            dtype = col_types.get(col.lower(), col_types.get(col.upper(), ""))
            if _sql_type_hint(dtype) == "string" or not dtype:
                before = df[col].copy()
                df[col] = df[col].str.strip().replace("", pd.NA).fillna("")
                changed = (before != df[col]).sum()
                if changed > 0:
                    trim_changed += changed
                    trim_cols.append(col)
        if trim_changed:
            changes.append(NormChange("TRIM whitespace", trim_cols, trim_changed))

        # 2. UPPER
        upper_changed = 0
        upper_cols = []
        for col in df.columns:
            is_str_col = (df[col].dtype == object or
                          str(df[col].dtype).lower() in ("str", "string", "large_string"))
            if not is_str_col:
                continue
            dtype = col_types.get(col.lower(), col_types.get(col.upper(), ""))
            hint  = _sql_type_hint(dtype) if dtype else "string"
            if hint not in ("numeric", "int", "date", "datetime"):
                before = df[col].copy()
                df[col] = df[col].str.upper()
                changed = int(
                    (before.fillna("").str.strip() != df[col].fillna("").str.strip()).sum()
                )
                if changed > 0:
                    upper_changed += changed
                    upper_cols.append(col)
        if upper_changed:
            changes.append(NormChange("UPPER all strings", upper_cols, upper_changed))

        # 3. Dates — _DATE_FORMATS already prioritises MM/DD/YYYY first
        date_changed = 0
        date_cols_changed = []
        for col in df.columns:
            dtype = col_types.get(col.lower(), col_types.get(col.upper(), ""))
            sample = df[col].dropna().head(20).tolist()
            if _is_date_col(col, [str(v) for v in sample]):
                before = df[col].copy()
                df[col] = df[col].apply(
                    lambda v: _parse_date(str(v)) or v if pd.notna(v) and str(v).strip() else v
                )
                changed = (before != df[col]).sum()
                if changed > 0:
                    date_changed += changed
                    date_cols_changed.append(col)
        if date_changed:
            changes.append(NormChange("Standardize dates to ISO", date_cols_changed, date_changed))

        # Apply user-defined normalization rules (in-memory)
        try:
            from dataview.reference_tables.user_rules import apply_norm_rules
            df, user_changes = apply_norm_rules(df, target_table="")
        except Exception:
            user_changes = []

        return NormalizeResult(
            ok=True,
            message=f"Normalization complete — {sum(c.values_changed for c in changes):,} values updated",
            df=df,
            changes=changes,
        )

    except Exception as exc:
        return NormalizeResult(ok=False, message=f"Normalization failed: {exc}")


# ═══════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("PPDM Loader — Module 4: Normalization Test")
    print("=" * 60)

    df_test = pd.DataFrame({
        "UWI":          ["  15-82-115-KS-0001  ", "15-52-275-KS-0002", "15-34-541-KS-0003"],
        "WELL_NAME":    [" Sunflower 60-49", "Arkansas 11-11 ", "Sunflower 53-63"],
        "ACTIVE_IND":   ["y", "n", "Y"],
        "SPUD_DATE":    ["03/30/1977", "12/08/1980", "12/17/2012"],   # MM/DD/YYYY
        "COMPLETION_DATE": ["06/15/1998", "09/22/2001", "04/03/2010"],
        "FINAL_TD":     ["3706.1", "6178.6", "6236.98"],
        "FINAL_TD_OUOM":["ft", "FT", "ft"],
    })

    print("\n[TEST 1] Demo normalization — MM/DD/YYYY dates")
    result = normalize_demo(df_test)
    assert result.ok, f"Normalization failed: {result.message}"
    df_n = result.df
    assert df_n.loc[0, "UWI"] == "15-82-115-KS-0001"
    assert df_n.loc[0, "WELL_NAME"] == "SUNFLOWER 60-49"
    assert df_n.loc[0, "ACTIVE_IND"] == "Y"
    assert df_n.loc[0, "SPUD_DATE"] == "1977-03-30", f"Got: {df_n.loc[0, 'SPUD_DATE']}"
    assert df_n.loc[0, "COMPLETION_DATE"] == "1998-06-15", f"Got: {df_n.loc[0, 'COMPLETION_DATE']}"
    assert df_n.loc[2, "FINAL_TD_OUOM"] == "FT"
    print(f"  ✓  TRIM+UPPER+DATE (MM/DD/YYYY) all correct")

    print("\n[TEST 2] SQL statement builder")
    stmts = build_normalize_sql(
        "raw_data",
        ["UWI", "WELL_NAME", "ACTIVE_IND", "SPUD_DATE", "COMPLETION_DATE", "FINAL_TD_OUOM", "_batch_loaded_at"],
        {"uwi": "nvarchar(40)", "active_ind": "nvarchar(1)", "spud_date": "date", "completion_date": "date"},
        schema="stg",
    )
    assert len(stmts) >= 2
    assert not any("_batch_loaded_at" in s for s in stmts), "_batch_loaded_at should be skipped"
    # Verify MM/DD/YYYY format 101 is present in date statement
    date_stmt = next((s for s in stmts if "TRY_CONVERT" in s), None)
    assert date_stmt and "101" in date_stmt, "Format 101 (MM/DD/YYYY) missing from date SQL"
    for i, s in enumerate(stmts, 1):
        print(f"  ✓  SQL {i}: {s[:100]}...")

    print("\n[TEST 3] Date parser — all formats")
    cases = [
        ("03/30/1977", "1977-03-30"),   # MM/DD/YYYY
        ("30/03/1977", "1977-03-30"),   # DD/MM/YYYY  — ambiguous but tries MM first
        ("30-03-1977", "1977-03-30"),   # DD-MM-YYYY
        ("1977-03-30", "1977-03-30"),   # ISO
        ("not-a-date", None),
        ("",           None),
    ]
    for inp, expected in cases:
        got = _parse_date(inp)
        assert got == expected, f"_parse_date('{inp}') → '{got}' expected '{expected}'"
        print(f"  ✓  '{inp}' → '{got}'")

    print("\n" + "=" * 60)
    print("All tests passed ✓")
    print("=" * 60)

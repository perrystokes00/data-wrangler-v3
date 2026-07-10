"""
validate.py  —  PPDM Loader · Module 7: Validation
====================================================
Validates the normalized, mapped DataFrame against PPDM rules before promote.

Checks performed (in order):
  1. NOT NULL / PRIMARY KEY   — required columns must have a value
  2. Data type compatibility  — numeric/date columns must parse correctly
  3. Max length               — nvarchar(n) values must not exceed n chars
  4. Check constraints        — Y/N indicators and other coded cols vs allowed values
  5. Business rules           — PPDM-specific cross-field rules (see BUSINESS_RULES)
  6. Duplicate PK detection   — check for duplicate PK values in source data
                                (and optionally against target table)

Each issue is a ValidationIssue with severity ERROR or WARNING.
  ERROR   → row will not be promoted
  WARNING → row promoted but flagged in the log

Test:
    python validate.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


# ═══════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ValidationIssue:
    row_idx:   int
    ppdm_col:  str
    src_col:   str
    value:     str
    rule:      str
    severity:  str    # "ERROR" | "WARNING"
    message:   str


@dataclass
class ValidationReport:
    issues:      list[ValidationIssue] = field(default_factory=list)
    rows_checked: int = 0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "WARNING"]

    @property
    def error_row_indices(self) -> set[int]:
        return {i.row_idx for i in self.errors}

    @property
    def clean_row_count(self) -> int:
        return self.rows_checked - len(self.error_row_indices)

    def to_dataframe(self) -> pd.DataFrame:
        if not self.issues:
            return pd.DataFrame(columns=[
                "row_idx", "ppdm_col", "src_col", "value",
                "rule", "severity", "message"
            ])
        return pd.DataFrame([
            {"row_idx": i.row_idx, "ppdm_col": i.ppdm_col,
             "src_col": i.src_col, "value": i.value,
             "rule": i.rule, "severity": i.severity,
             "message": i.message}
            for i in self.issues
        ])

    def summary(self) -> str:
        return (
            f"{self.rows_checked} rows checked | "
            f"{len(self.errors)} errors | "
            f"{len(self.warnings)} warnings | "
            f"{self.clean_row_count} clean rows ready to promote"
        )


# ═══════════════════════════════════════════════════════════════════════
# BUSINESS RULES
# ═══════════════════════════════════════════════════════════════════════
# Each rule is a dict:
#   name     : display name
#   severity : ERROR | WARNING
#   check    : callable(row: pd.Series, mapping: dict) → str | None
#              Returns error message string, or None if check passes

def _rule_lat_range(row, mapping):
    """Surface latitude must be between -90 and 90."""
    for col in ("SURFACE_LATITUDE", "BOTTOM_HOLE_LATITUDE"):
        src = mapping.get(col, "")
        if src and src in row.index:
            v = str(row[src]).strip()
            if v:
                try:
                    f = float(v)
                    if not (-90 <= f <= 90):
                        return f"{col} value {v} out of range (-90 to 90)"
                except ValueError:
                    pass
    return None


def _rule_lon_range(row, mapping):
    """Surface longitude must be between -180 and 180."""
    for col in ("SURFACE_LONGITUDE", "BOTTOM_HOLE_LONGITUDE"):
        src = mapping.get(col, "")
        if src and src in row.index:
            v = str(row[src]).strip()
            if v:
                try:
                    f = float(v)
                    if not (-180 <= f <= 180):
                        return f"{col} value {v} out of range (-180 to 180)"
                except ValueError:
                    pass
    return None


def _rule_td_positive(row, mapping):
    """Total depth values must be positive."""
    td_cols = ("FINAL_TD", "DRILL_TD", "LOG_TD", "MAX_TVD", "DEEPEST_DEPTH")
    for col in td_cols:
        src = mapping.get(col, "")
        if src and src in row.index:
            v = str(row[src]).strip()
            if v:
                try:
                    if float(v) < 0:
                        return f"{col} ({v}) must be positive"
                except ValueError:
                    pass
    return None


def _rule_spud_before_completion(row, mapping):
    """SPUD_DATE should be <= COMPLETION_DATE if both present."""
    spud_src = mapping.get("SPUD_DATE", "")
    comp_src = mapping.get("COMPLETION_DATE", "")
    if not (spud_src and comp_src):
        return None
    if spud_src not in row.index or comp_src not in row.index:
        return None
    try:
        from datetime import datetime
        def parse(v):
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
                try:
                    return datetime.strptime(str(v).strip(), fmt)
                except ValueError:
                    continue
            return None
        spud = parse(row[spud_src])
        comp = parse(row[comp_src])
        if spud and comp and spud > comp:
            return (f"SPUD_DATE ({row[spud_src]}) is after "
                    f"COMPLETION_DATE ({row[comp_src]})")
    except Exception:
        pass
    return None


def _rule_uwi_format(row, mapping):
    """UWI should follow expected pattern for Canadian/US well identifiers."""
    src = mapping.get("UWI", "")
    if not src or src not in row.index:
        return None
    v = str(row[src]).strip()
    if not v:
        return None
    # Accept formats: 15-82-115-KS-0001 or standard API 14-digit
    if re.match(r"^\d{2}-\d{2,3}-\d{3}-[A-Z]{2}-\d{4}$", v):
        return None   # Kansas-style ✓
    if re.match(r"^\d{14}$", v):
        return None   # 14-digit API ✓
    if re.match(r"^\d{2}/\d{3}-\d{2}-\d{3}$", v):
        return None   # Canadian-style ✓
    return f"UWI '{v}' does not match known format"


# ── Load user-defined validation rules ────────────────────────────────
def _get_user_val_rules(target_table: str) -> list[dict]:
    try:
        from dataview.reference_tables.user_rules import get_val_rules_for_table
        return get_val_rules_for_table(target_table)
    except Exception:
        return []


BUSINESS_RULES = [
    {"name": "Latitude range",             "severity": "ERROR",   "check": _rule_lat_range},
    {"name": "Longitude range",            "severity": "ERROR",   "check": _rule_lon_range},
    {"name": "Total depth positive",       "severity": "ERROR",   "check": _rule_td_positive},
    {"name": "Spud before completion",     "severity": "WARNING", "check": _rule_spud_before_completion},
    {"name": "UWI format",                 "severity": "WARNING", "check": _rule_uwi_format},
]


# ═══════════════════════════════════════════════════════════════════════
# VALIDATORS
# ═══════════════════════════════════════════════════════════════════════

def _try_parse_numeric(v: str) -> bool:
    try:
        float(str(v).replace(",", ""))
        return True
    except (ValueError, TypeError):
        return False


def _try_parse_date(v: str) -> bool:
    from datetime import datetime
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            datetime.strptime(str(v).strip(), fmt)
            return True
        except ValueError:
            continue
    return False


def _sql_type_hint(dtype_str: str) -> str:
    """Classify a SQL type string into: numeric | date | datetime | string."""
    d = (dtype_str or "").lower()
    if any(x in d for x in ("numeric", "decimal", "float", "real", "int",
                             "money", "smallmoney", "bit")):
        return "numeric"
    if any(x in d for x in ("datetime2", "datetime", "smalldatetime", "timestamp")):
        return "datetime"
    if "date" in d and "time" not in d:
        return "date"
    return "string"


def validate(
    df: pd.DataFrame,
    mapping,            # ColumnMapping from mapping.py
    target_col_defs: list,  # list[ColumnDef]
    skip_indices: set[int] | None = None,
    engine=None,        # optional: check PKs against live target table
    target_table: str = "",  # used to load user-defined validation rules
) -> ValidationReport:
    """
    Full validation pass over df.

    Args:
        df              : normalized source DataFrame
        mapping         : ColumnMapping from mapping.py
        target_col_defs : list[ColumnDef] for the target table
        skip_indices    : row indices already marked for skip (from FK resolution)
        engine          : live DB engine for duplicate PK check (optional)

    Returns:
        ValidationReport
    """
    issues: list[ValidationIssue] = []
    skip_set = skip_indices or set()
    col_map  = mapping.to_dict()  # {ppdm_col: src_col}

    # Build lookup: ppdm_col → ColumnDef
    col_def_map = {getattr(c, "column_name", getattr(c, "ppdm_col", "")).upper(): c for c in target_col_defs}

    # Build check-constraint lookup: src_col → allowed_values
    constraint_map: dict[str, list[str]] = {}
    for ppdm_col, src_col in col_map.items():
        if not src_col:
            continue
        col_def = col_def_map.get(ppdm_col.upper())
        if col_def and getattr(col_def, "allowed_values", None):
            constraint_map[src_col] = getattr(col_def, "allowed_values", None) or []

    # Collect PK source columns for duplicate check
    pk_src_cols = [
        col_map.get(getattr(c, "column_name", getattr(c, "ppdm_col", "")), "")
        for c in target_col_defs
        if getattr(c, "is_primary_key", getattr(c, "is_pk", False))
        and col_map.get(getattr(c, "column_name", getattr(c, "ppdm_col", "")))
    ]

    # Build set of auto-generated (audit) column names — skip validation on these
    # since the app fills them server-side, they won't be in the source df
    auto_ppdm_cols = {m.ppdm_col.upper() for m in mapping.mapped if getattr(m, "auto_generated", False)}

    # ── Row-level checks ──────────────────────────────────────────────
    for idx, row in df.iterrows():
        if idx in skip_set:
            continue

        for ppdm_col, src_col in col_map.items():
            # Skip audit/auto-generated columns — not in source df
            if ppdm_col.upper() in auto_ppdm_cols:
                continue

            if not src_col or src_col not in df.columns:
                continue

            col_def = col_def_map.get(ppdm_col.upper())
            if not col_def:
                continue

            raw = row.get(src_col, "")
            val = str(raw).strip() if pd.notna(raw) else ""

            # 1. NOT NULL / PK check
            if getattr(col_def, "not_null", False) and not val:
                issues.append(ValidationIssue(
                    row_idx=idx, ppdm_col=ppdm_col, src_col=src_col,
                    value=val, rule="NOT NULL",
                    severity="ERROR",
                    message=f"Required column '{ppdm_col}' is empty"
                ))
                continue

            if not val:
                continue   # null in optional col — skip remaining checks

            # 2. Type check
            hint = _sql_type_hint(getattr(col_def, "data_type", "") or "")
            if hint == "numeric" and not _try_parse_numeric(val):
                issues.append(ValidationIssue(
                    row_idx=idx, ppdm_col=ppdm_col, src_col=src_col,
                    value=val, rule="TYPE_CHECK",
                    severity="ERROR",
                    message=f"'{val}' is not numeric (expected {col_def.data_type})"
                ))

            elif hint in ("date", "datetime") and not _try_parse_date(val):
                issues.append(ValidationIssue(
                    row_idx=idx, ppdm_col=ppdm_col, src_col=src_col,
                    value=val, rule="TYPE_CHECK",
                    severity="WARNING",
                    message=f"'{val}' cannot be parsed as a date"
                ))

            # 3. Max length — parse from data_type if no max_length attribute
            max_len = getattr(col_def, "max_length", None)
            if max_len is None:
                import re as _re
                _m = _re.search(r"\((\d+)\)", getattr(col_def, "data_type", "") or "")
                max_len = int(_m.group(1)) if _m else None
            if max_len and len(val) > max_len:
                issues.append(ValidationIssue(
                    row_idx=idx, ppdm_col=ppdm_col, src_col=src_col,
                    value=val, rule="MAX_LENGTH",
                    severity="ERROR",
                    message=f"Value length {len(val)} exceeds {col_def.data_type} limit of {max_len}"
                ))

            # 4. Check constraints
            # Only check if column has a value — empty = NULL, no constraint applies.
            # Also skip audit columns — ACTIVE_IND etc. are filled by the app.
            allowed = getattr(col_def, "allowed_values", None)
            if allowed and val:
                # Case-insensitive comparison — PPDM stores codes in uppercase
                val_upper = val.upper()
                allowed_upper = [a.upper() for a in allowed]
                if val_upper not in allowed_upper:
                    issues.append(ValidationIssue(
                        row_idx=idx, ppdm_col=ppdm_col, src_col=src_col,
                        value=val, rule="CHECK_CONSTRAINT",
                        severity="ERROR",
                        message=f"'{val}' not in allowed values: {allowed}"
                    ))

        # 5. Business rules (built-in + user-defined)
        _all_rules = BUSINESS_RULES + _get_user_val_rules(target_table)
        for rule in _all_rules:
            msg = rule["check"](row, col_map)
            if msg:
                issues.append(ValidationIssue(
                    row_idx=idx, ppdm_col="", src_col="",
                    value="", rule=rule["name"],
                    severity=rule["severity"],
                    message=msg
                ))

    # 6. Duplicate PK check (within source data)
    if pk_src_cols:
        pk_exists = all(c in df.columns for c in pk_src_cols)
        if pk_exists:
            dupes = df[df.duplicated(subset=pk_src_cols, keep=False)].index.tolist()
            for idx in dupes:
                if idx not in skip_set:
                    pk_vals = " | ".join(
                        str(df.loc[idx, c]) for c in pk_src_cols
                    )
                    issues.append(ValidationIssue(
                        row_idx=idx, ppdm_col=" + ".join(pk_src_cols),
                        src_col=" + ".join(pk_src_cols),
                        value=pk_vals, rule="DUPLICATE_PK",
                        severity="ERROR",
                        message=f"Duplicate primary key in source: {pk_vals}"
                    ))

    return ValidationReport(issues=issues, rows_checked=len(df) - len(skip_set))


def validate_server(
    engine,
    staging_table: str,
    mapping,
    target_col_defs: list,
    schema: str = "stg",
    target_table: str = "",
    skip_indices: set | None = None,
    checks: tuple = ("not_null", "type_check", "max_length",
                     "check_constraint", "duplicate_pk", "business_rules"),
) -> ValidationReport:
    """
    Server-side validation — single SQL query for all checks.
    Use checks= to limit which checks run (e.g. ('not_null','duplicate_pk') for speed).
    """
    from sqlalchemy import text as _t
    import re as _re

    # ── Detect dialect and set up quoting ───────────────────────────────
    try:
        from dataview.core.db import get_dialect as _gd
        _dialect = _gd(engine).name if engine else "sqlserver"
    except Exception:
        _dialect = "sqlserver"
    _is_ora       = (_dialect == "oracle")
    _is_snowflake = (_dialect == "snowflake")
    def _try_num(col_expr):
        if _is_snowflake:
            return f"TRY_CAST(TRIM({col_expr}) AS FLOAT) IS NOT NULL"
        return f"TRY_CONVERT(float, {col_expr}) IS NOT NULL"
    def _try_num_null(col_expr):
        if _is_snowflake:
            return f"TRY_CAST(TRIM({col_expr}) AS FLOAT) IS NULL"
        return f"TRY_CONVERT(float, {col_expr}) IS NULL"

    if _is_ora or _is_snowflake:
        _q   = lambda n: '"' + str(n).upper() + '"'
        _sch = schema.upper()
        _tbl = staging_table.upper()
        full = '"' + _sch + '"."' + _tbl + '"'
    else:
        _q   = lambda n: "[" + str(n) + "]"
        full = "[" + schema + "].[" + staging_table + "]"

    # Oracle doesn't allow aliases starting with _ — sanitise them
    def _alias(lbl):
        return lbl.lstrip("_") if _is_ora else lbl

    issues: list[ValidationIssue] = []
    col_map = mapping.to_dict()
    col_def_map = {
        getattr(c, "column_name", getattr(c, "ppdm_col", "")).upper(): c
        for c in target_col_defs
    }
    auto_ppdm_cols = {
        m.ppdm_col.upper() for m in mapping.mapped
        if getattr(m, "auto_generated", False)
    }

    # ── Build single aggregate query for all checks ──────────────────
    select_exprs = ["COUNT(*) AS TOTAL_ROWS"]
    check_meta   = []   # (label, rule, severity, ppdm_col, src_col, message_template)

    for ppdm_col, src_col in col_map.items():
        if not src_col or ppdm_col.upper() in auto_ppdm_cols:
            continue
        col_def = col_def_map.get(ppdm_col.upper())
        if not col_def:
            continue

        label_base = f"{ppdm_col}_{src_col}".replace(" ", "_")[:30]

        # NOT NULL
        if "not_null" in checks and getattr(col_def, "not_null", False):
            lbl = f"nn_{label_base}"[:50]
            _nn_trim = ("TRIM(" + _q(src_col) + ") = ''" if (_is_ora or _is_snowflake)
                        else "LTRIM(RTRIM(" + _q(src_col) + ")) = ''")
            select_exprs.append(
                "SUM(CASE WHEN " + _q(src_col) + " IS NULL OR " + _nn_trim +
                " THEN 1 ELSE 0 END) AS " + _q(lbl)
            )
            check_meta.append((lbl, "NOT NULL", "ERROR", ppdm_col, src_col,
                               f"Required column \'{ppdm_col}\' is empty"))

        # Numeric type check
        hint = _sql_type_hint(getattr(col_def, "data_type", "") or "")
        if "type_check" in checks and hint == "numeric":
            lbl = f"num_{label_base}"[:50]
            if _is_ora:
                _num_expr = (
                    "SUM(CASE WHEN " + _q(src_col) + " IS NOT NULL "
                    "AND TRIM(" + _q(src_col) + ") IS NOT NULL "
                    "AND REGEXP_LIKE(TRIM(" + _q(src_col) + "), '^[+-]?[0-9]*(\\.[0-9]+)?([Ee][+-]?[0-9]+)?$') = 0 "
                    "THEN 1 ELSE 0 END) AS " + _q(lbl)
                )
            else:
                _num_expr = (
                    "SUM(CASE WHEN [" + src_col + "] IS NOT NULL "
                    "AND LTRIM(RTRIM([" + src_col + "])) <> '' "
                    "AND " + _try_num_null(_q(src_col)) + " " if _is_snowflake else "AND TRY_CONVERT(float, [" + src_col + "]) IS NULL "
                    "THEN 1 ELSE 0 END) AS [" + lbl + "]"
                )
            select_exprs.append(_num_expr)
            check_meta.append((lbl, "TYPE_CHECK", "ERROR", ppdm_col, src_col,
                               f"Non-numeric value in {col_def.data_type} column \'{src_col}\'"))

        # Max length
        max_len = getattr(col_def, "max_length", None)
        if max_len is None:
            _m = _re.search(r"\((\d+)\)", getattr(col_def, "data_type", "") or "")
            max_len = int(_m.group(1)) if _m else None
        if "max_length" in checks and max_len and max_len < 4000:
            lbl = f"len_{label_base}"[:50]
            _len_fn = "LENGTH" if (_is_ora or _is_snowflake) else "LEN"
            select_exprs.append(
                "SUM(CASE WHEN " + _len_fn + "(" + _q(src_col) + ") > " + str(max_len) +
                " THEN 1 ELSE 0 END) AS " + _q(lbl)
            )
            check_meta.append((lbl, "MAX_LENGTH", "ERROR", ppdm_col, src_col,
                               f"Value exceeds {col_def.data_type} limit of {max_len}"))

        # Check constraints
        allowed = getattr(col_def, "allowed_values", None)
        if "check_constraint" in checks and allowed:
            _vals = ", ".join(f"N\'{v.upper()}\'" for v in allowed)
            lbl = f"ck_{label_base}"[:50]
            _cc_trim = ("TRIM(" + _q(src_col) + ") IS NOT NULL"
                         if _is_ora else
                         "LTRIM(RTRIM(" + _q(src_col) + ")) <> ''")
            select_exprs.append(
                "SUM(CASE WHEN " + _q(src_col) + " IS NOT NULL "
                "AND " + _cc_trim + " "
                "AND UPPER(" + _q(src_col) + ") NOT IN (" + _vals + ") "
                "THEN 1 ELSE 0 END) AS " + _q(lbl)
            )
            check_meta.append((lbl, "CHECK_CONSTRAINT", "ERROR", ppdm_col, src_col,
                               f"Value not in allowed set for \'{ppdm_col}\'"))

    # Lat/lon business rules
    _lat_col = (col_map.get("surface_latitude") or col_map.get("SURFACE_LATITUDE")) if "business_rules" in checks else None
    _lon_col = col_map.get("surface_longitude") or col_map.get("SURFACE_LONGITUDE")
    if _lat_col:
        if _is_ora:
            select_exprs.append(
                "SUM(CASE WHEN " + _q(_lat_col) + " IS NOT NULL "
                "AND TRIM(CAST(" + _q(_lat_col) + " AS VARCHAR2(50))) IS NOT NULL "
                "AND (TO_NUMBER(TRIM(CAST(" + _q(_lat_col) + " AS VARCHAR2(50)))) < -90 "
                "OR TO_NUMBER(TRIM(CAST(" + _q(_lat_col) + " AS VARCHAR2(50)))) > 90) "
                "THEN 1 ELSE 0 END) AS " + _q("br_lat")
            )
        elif _is_snowflake:
            select_exprs.append(
                f"SUM(CASE WHEN TRY_CAST(TRIM({_q(_lat_col)}) AS FLOAT) IS NOT NULL "
                f"AND (TRY_CAST(TRIM({_q(_lat_col)}) AS FLOAT) < -90 "
                f"OR TRY_CAST(TRIM({_q(_lat_col)}) AS FLOAT) > 90) "
                f"THEN 1 ELSE 0 END) AS BR_LAT"
            )
        else:
            select_exprs.append(
                f"SUM(CASE WHEN TRY_CONVERT(float,[{_lat_col}]) IS NOT NULL "
                f"AND (TRY_CONVERT(float,[{_lat_col}]) < -90 "
                f"OR TRY_CONVERT(float,[{_lat_col}]) > 90) "
                f"THEN 1 ELSE 0 END) AS [br_lat]"
            )
        check_meta.append(("br_lat", "Latitude range", "ERROR",
                           "surface_latitude", _lat_col,
                           "Latitude out of range (-90 to 90)"))
    if _lon_col:
        if _is_ora:
            select_exprs.append(
                "SUM(CASE WHEN " + _q(_lon_col) + " IS NOT NULL "
                "AND TRIM(CAST(" + _q(_lon_col) + " AS VARCHAR2(50))) IS NOT NULL "
                "AND (TO_NUMBER(TRIM(CAST(" + _q(_lon_col) + " AS VARCHAR2(50)))) < -180 "
                "OR TO_NUMBER(TRIM(CAST(" + _q(_lon_col) + " AS VARCHAR2(50)))) > 180) "
                "THEN 1 ELSE 0 END) AS " + _q("br_lon")
            )
        elif _is_snowflake:
            select_exprs.append(
                f"SUM(CASE WHEN TRY_CAST(TRIM({_q(_lon_col)}) AS FLOAT) IS NOT NULL "
                f"AND (TRY_CAST(TRIM({_q(_lon_col)}) AS FLOAT) < -180 "
                f"OR TRY_CAST(TRIM({_q(_lon_col)}) AS FLOAT) > 180) "
                f"THEN 1 ELSE 0 END) AS BR_LON"
            )
        else:
            select_exprs.append(
                f"SUM(CASE WHEN TRY_CONVERT(float,[{_lon_col}]) IS NOT NULL "
                f"AND (TRY_CONVERT(float,[{_lon_col}]) < -180 "
                f"OR TRY_CONVERT(float,[{_lon_col}]) > 180) "
                f"THEN 1 ELSE 0 END) AS [br_lon]"
            )
        check_meta.append(("br_lon", "Longitude range", "ERROR",
                           "surface_longitude", _lon_col,
                           "Longitude out of range (-180 to 180)"))

    # ── Execute single query ─────────────────────────────────────────
    total_rows  = 0
    error_count = 0
    try:
        _nolock = "" if (_is_ora or _is_snowflake) else " WITH (NOLOCK)"
        sql = "SELECT " + ", ".join(select_exprs) + " FROM " + full + _nolock
        with engine.connect() as con:
            row  = con.execute(_t(sql)).fetchone()
            if _is_ora:
                keys = list(con.execute(_t("SELECT " + ", ".join(select_exprs) + " FROM " + full + " WHERE 1=0")).keys())
            else:
                keys = list(con.execute(_t("SELECT TOP 0 " + ", ".join(select_exprs) + " FROM " + full)).keys())
        result = dict(zip(keys, row))
        total_rows = result.get("TOTAL_ROWS", result.get("total_rows", 0)) or 0

        # Oracle uppercases aliases — normalise result keys
        result_ci = {k.upper(): v for k, v in result.items()}
        for lbl, rule, severity, ppdm_col, src_col, msg_tmpl in check_meta:
            cnt = result_ci.get(lbl.upper(), 0) or 0
            if cnt:
                error_count += cnt
                issues.append(ValidationIssue(
                    row_idx=-1, ppdm_col=ppdm_col, src_col=src_col,
                    value="", rule=rule, severity=severity,
                    message=f"{msg_tmpl}: {cnt:,} row(s)"
                ))
    except Exception as _e:
        issues.append(ValidationIssue(
            row_idx=-1, ppdm_col="", src_col="",
            value="", rule="VALIDATE_ERROR", severity="WARNING",
            message=f"Server validation error: {_e}"
        ))

    # ── Duplicate PK check ───────────────────────────────────────────
    pk_src_cols = [] if "duplicate_pk" not in checks else [
        col_map.get(getattr(c, "column_name", getattr(c, "ppdm_col", "")), "")
        for c in target_col_defs
        if getattr(c, "is_primary_key", getattr(c, "is_pk", False))
        and col_map.get(getattr(c, "column_name", getattr(c, "ppdm_col", "")))
    ]
    if pk_src_cols:
        _pk_cols = ", ".join(_q(c) for c in pk_src_cols)
        _nolock2 = "" if (_is_ora or _is_snowflake) else " WITH (NOLOCK)"
        try:
            with engine.connect() as con:
                cnt = con.execute(_t(
                    "SELECT COUNT(*) FROM ("
                    "SELECT " + _pk_cols + " FROM " + full + _nolock2 + " "
                    "GROUP BY " + _pk_cols + " HAVING COUNT(*) > 1) x"
                )).fetchone()[0]
            if cnt:
                error_count += cnt
                issues.append(ValidationIssue(
                    row_idx=-1,
                    ppdm_col=" + ".join(pk_src_cols),
                    src_col=" + ".join(pk_src_cols),
                    value="", rule="DUPLICATE_PK", severity="ERROR",
                    message=f"Duplicate primary key: {cnt:,} duplicate combination(s)"
                ))
        except Exception:
            pass

    # ── User-defined rules on small sample ──────────────────────────
    user_rules = _get_user_val_rules(target_table) if "business_rules" in checks else []
    if user_rules:
        try:
            _sample_sql = ("SELECT * FROM " + full + " WHERE ROWNUM <= 1000"
                           if _is_ora else
                           "SELECT TOP 1000 * FROM " + full + " WITH (NOLOCK)")
            sample_df = pd.read_sql(_sample_sql, engine)
            for idx, row in sample_df.iterrows():
                for rule in user_rules:
                    msg = rule["check"](row, col_map)
                    if msg:
                        issues.append(ValidationIssue(
                            row_idx=idx, ppdm_col="", src_col="",
                            value="", rule=rule["name"],
                            severity=rule["severity"], message=msg
                        ))
        except Exception:
            pass

    clean_rows = max(0, total_rows - error_count)
    return ValidationReport(issues=issues, rows_checked=total_rows)


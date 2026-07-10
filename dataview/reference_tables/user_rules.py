"""
user_rules.py  —  PPDM Loader · User-Defined Rules Engine
==========================================================
Loads, saves, and evaluates user-defined normalization and validation
rules stored in modules/user_rules.json.

NORMALIZATION RULES  (run after Stage 3 global normalize)
  case         — UPPER | lower | title  on a specific column
  replace      — find/replace literal string
  regex_replace— find/replace with regex pattern
  pad          — left or right pad to fixed width
  truncate     — trim value to max character length
  null_sub     — replace empty/null with a default value
  strip_chars  — remove specific characters from value

VALIDATION RULES  (merged into Stage 7 validate)
  not_empty    — column must have a value
  range        — numeric value within [min, max]
  compare_cols — col_a <op> col_b  (< <= > >= == !=)
  date_order   — date col_before <= date col_after
  regex        — value must match pattern

Table field:
  "*"      — rule applies to every table load
  "well"   — only runs when target_table == "well"
  (case-insensitive)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# ── File location ──────────────────────────────────────────────────────────
_HERE       = Path(__file__).parent
_RULES_FILE = _HERE / "user_rules.json"

# ── Date formats for date_order rules ─────────────────────────────────────
_DATE_FMTS = (
    "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y",
    "%d/%m/%Y", "%Y/%m/%d", "%Y%m%d",
)


def _parse_date(v) -> Optional[datetime]:
    s = str(v).strip()
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════════
# LOAD / SAVE
# ═══════════════════════════════════════════════════════════════════════════

def _empty_store() -> dict:
    return {"normalization_rules": [], "validation_rules": []}


def load_store() -> dict:
    """Load full rules store from disk.  Returns empty store if missing."""
    if not _RULES_FILE.exists():
        return _empty_store()
    try:
        with open(_RULES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # Ensure both keys exist
        data.setdefault("normalization_rules", [])
        data.setdefault("validation_rules",    [])
        return data
    except Exception:
        return _empty_store()


def save_store(store: dict) -> None:
    """Persist full rules store to disk."""
    with open(_RULES_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def load_norm_rules() -> list[dict]:
    return load_store()["normalization_rules"]


def load_val_rules() -> list[dict]:
    return load_store()["validation_rules"]


def save_norm_rules(rules: list[dict]) -> None:
    store = load_store()
    store["normalization_rules"] = rules
    save_store(store)


def save_val_rules(rules: list[dict]) -> None:
    store = load_store()
    store["validation_rules"] = rules
    save_store(store)


def _next_id(rules: list[dict], prefix: str) -> str:
    """Generate next NR### or BR### id."""
    existing = set()
    for r in rules:
        m = re.match(rf"{re.escape(prefix)}(\d+)", r.get("id", ""))
        if m:
            existing.add(int(m.group(1)))
    n = 1
    while n in existing:
        n += 1
    return f"{prefix}{n:03d}"


def next_norm_id(rules: list[dict]) -> str:
    return _next_id(rules, "NR")


def next_val_id(rules: list[dict]) -> str:
    return _next_id(rules, "BR")


# ═══════════════════════════════════════════════════════════════════════════
# NORMALIZATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def _matches_table(rule: dict, target_table: str) -> bool:
    tbl = rule.get("table", "*")
    return tbl == "*" or tbl.upper() == (target_table or "").upper()


def apply_norm_rules(
    df: pd.DataFrame,
    target_table: str,
    col_mapping=None,         # ColumnMapping — used to find src col for ppdm col
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Apply enabled normalization rules to df in-place (copy returned).
    Returns (modified_df, change_log) where change_log is list of dicts.

    col_mapping: if provided, resolves PPDM column names to source column names.
                 If None, assumes df columns ARE the PPDM column names.
    """
    df = df.copy()
    changes: list[dict] = []

    # Build ppdm→src lookup
    ppdm_to_src: dict[str, str] = {}
    if col_mapping is not None:
        for m in col_mapping.mapped:
            if m.source_col:
                ppdm_to_src[m.ppdm_col.upper()] = m.source_col
    else:
        # Assume df columns are ppdm cols directly
        for c in df.columns:
            ppdm_to_src[c.upper()] = c

    rules = load_norm_rules()
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if not _matches_table(rule, target_table):
            continue

        ppdm_col = rule.get("column", "").upper()
        src_col  = ppdm_to_src.get(ppdm_col, ppdm_col)  # fallback to ppdm name
        if src_col not in df.columns:
            continue

        rtype = rule.get("type", "")
        before = df[src_col].copy()
        n_changed = 0

        try:
            if rtype == "case":
                case = rule.get("case", "upper")
                mask = df[src_col].notna() & (df[src_col].astype(str).str.strip() != "")
                if case == "upper":
                    df.loc[mask, src_col] = df.loc[mask, src_col].astype(str).str.upper()
                elif case == "lower":
                    df.loc[mask, src_col] = df.loc[mask, src_col].astype(str).str.lower()
                elif case == "title":
                    df.loc[mask, src_col] = df.loc[mask, src_col].astype(str).str.title()

            elif rtype == "replace":
                find    = rule.get("find", "")
                replace = rule.get("replace_with", "")
                if find:
                    df[src_col] = df[src_col].astype(str).str.replace(
                        find, replace, regex=False
                    )

            elif rtype == "regex_replace":
                pattern = rule.get("pattern", "")
                replace = rule.get("replace_with", "")
                if pattern:
                    df[src_col] = df[src_col].astype(str).str.replace(
                        pattern, replace, regex=True
                    )

            elif rtype == "pad":
                direction = rule.get("direction", "left")
                width     = int(rule.get("width", 0))
                char      = str(rule.get("char", " "))[:1] or " "
                if width > 0:
                    mask = df[src_col].notna() & (df[src_col].astype(str).str.strip() != "")
                    if direction == "left":
                        df.loc[mask, src_col] = (
                            df.loc[mask, src_col].astype(str).str.zfill(width)
                            if char == "0"
                            else df.loc[mask, src_col].astype(str).str.rjust(width, char)
                        )
                    else:
                        df.loc[mask, src_col] = (
                            df.loc[mask, src_col].astype(str).str.ljust(width, char)
                        )

            elif rtype == "truncate":
                max_len = int(rule.get("max_length", 0))
                if max_len > 0:
                    df[src_col] = df[src_col].astype(str).str[:max_len]

            elif rtype == "null_sub":
                sub = rule.get("substitute", "")
                df[src_col] = df[src_col].apply(
                    lambda v: sub if (not pd.notna(v) or str(v).strip() == "") else v
                )

            elif rtype == "strip_chars":
                chars = rule.get("chars", "")
                if chars:
                    pattern_sc = f"[{re.escape(chars)}]"
                    df[src_col] = df[src_col].astype(str).str.replace(
                        pattern_sc, "", regex=True
                    )

            # Count changed cells
            n_changed = int((before.fillna("").astype(str) !=
                             df[src_col].fillna("").astype(str)).sum())

        except Exception as exc:
            changes.append({
                "id":      rule["id"],
                "name":    rule.get("name", rule["id"]),
                "column":  src_col,
                "changed": 0,
                "error":   str(exc),
            })
            continue

        if n_changed > 0:
            changes.append({
                "id":      rule["id"],
                "name":    rule.get("name", rule["id"]),
                "column":  src_col,
                "type":    rtype,
                "changed": n_changed,
                "error":   None,
            })

    return df, changes


def apply_norm_rules_server(
    engine,
    staging_table: str,
    df: pd.DataFrame,
    target_table: str,
    col_mapping=None,
    schema: str = "stg",
) -> tuple[int, list[dict]]:
    """
    Apply normalization rules server-side via SQL UPDATE statements.
    Falls back to in-memory for rule types that can't be expressed in SQL.

    Returns (total_statements_run, change_log).
    """
    from sqlalchemy import text as _text

    ppdm_to_src: dict[str, str] = {}
    if col_mapping is not None:
        for m in col_mapping.mapped:
            if m.source_col:
                ppdm_to_src[m.ppdm_col.upper()] = m.source_col
    else:
        for c in df.columns:
            ppdm_to_src[c.upper()] = c

    full     = f"[{schema}].[{staging_table}]"
    changes  = []
    stmts    = []

    rules = load_norm_rules()
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if not _matches_table(rule, target_table):
            continue

        ppdm_col = rule.get("column", "").upper()
        src_col  = ppdm_to_src.get(ppdm_col, ppdm_col)
        if src_col not in df.columns:
            continue

        rtype = rule.get("type", "")
        sql   = None

        if rtype == "case":
            case = rule.get("case", "upper")
            if case == "upper":
                sql = f"UPDATE {full} SET [{src_col}] = UPPER([{src_col}]) WHERE [{src_col}] IS NOT NULL"
            elif case == "lower":
                sql = f"UPDATE {full} SET [{src_col}] = LOWER([{src_col}]) WHERE [{src_col}] IS NOT NULL"
            elif case == "title":
                # SQL Server has no built-in TITLE CASE — skip to in-memory fallback
                sql = None

        elif rtype == "replace":
            find    = (rule.get("find",         "") or "").replace("'", "''")
            replace = (rule.get("replace_with", "") or "").replace("'", "''")
            if find:
                sql = (f"UPDATE {full} SET [{src_col}] = "
                       f"REPLACE([{src_col}], '{find}', '{replace}') "
                       f"WHERE [{src_col}] IS NOT NULL")

        elif rtype == "null_sub":
            sub = (rule.get("substitute", "") or "").replace("'", "''")
            sql = (f"UPDATE {full} SET [{src_col}] = '{sub}' "
                   f"WHERE [{src_col}] IS NULL OR LTRIM(RTRIM([{src_col}])) = ''")

        elif rtype == "truncate":
            max_len = int(rule.get("max_length", 0))
            if max_len > 0:
                sql = (f"UPDATE {full} SET [{src_col}] = LEFT([{src_col}], {max_len}) "
                       f"WHERE LEN([{src_col}]) > {max_len}")

        # pad / regex_replace / strip_chars — no clean SQL equivalent, fall through
        # to in-memory after server pass

        if sql:
            stmts.append((rule, src_col, sql))

    # Execute server-side statements
    n_run = 0
    with engine.begin() as con:
        for rule, src_col, sql in stmts:
            con.execute(_text(sql))
            n_run += 1
            changes.append({
                "id":      rule["id"],
                "name":    rule.get("name", rule["id"]),
                "column":  src_col,
                "type":    rule.get("type", ""),
                "changed": "server-side",
                "error":   None,
            })

    return n_run, changes


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

def _build_val_check(rule: dict):
    """Convert a validation rule dict into check(row, mapping) -> str | None."""
    rtype = rule.get("type", "")

    if rtype == "not_empty":
        col = rule["column"].upper()
        def _fn(row, mapping, _c=col):
            src = mapping.get(_c, "")
            if not src or src not in row.index:
                return None
            v = str(row[src]).strip() if pd.notna(row[src]) else ""
            return f"{_c} must not be empty" if not v else None
        return _fn

    if rtype == "range":
        col  = rule["column"].upper()
        rmin = rule.get("min")
        rmax = rule.get("max")
        def _fn(row, mapping, _c=col, _mn=rmin, _mx=rmax):
            src = mapping.get(_c, "")
            if not src or src not in row.index:
                return None
            raw = row[src]
            if not pd.notna(raw) or str(raw).strip() == "":
                return None
            try:
                v = float(str(raw).replace(",", ""))
            except ValueError:
                return None
            if _mn is not None and v < _mn:
                return f"{_c} value {v} is below minimum {_mn}"
            if _mx is not None and v > _mx:
                return f"{_c} value {v} exceeds maximum {_mx}"
            return None
        return _fn

    if rtype == "compare_cols":
        col_a = rule["col_a"].upper()
        col_b = rule["col_b"].upper()
        op    = rule.get("operator", "<=")
        _OPS  = {
            "<":  lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            ">":  lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }
        fn = _OPS.get(op, lambda a, b: True)
        def _fn(row, mapping, _ca=col_a, _cb=col_b, _op=op, _fn2=fn):
            sa = mapping.get(_ca, "")
            sb = mapping.get(_cb, "")
            if not sa or not sb or sa not in row.index or sb not in row.index:
                return None
            ra, rb = row[sa], row[sb]
            if not pd.notna(ra) or not pd.notna(rb):
                return None
            if str(ra).strip() == "" or str(rb).strip() == "":
                return None
            try:
                a, b = float(str(ra).replace(",", "")), float(str(rb).replace(",", ""))
            except ValueError:
                return None
            if not _fn2(a, b):
                return f"{_ca} ({a}) must be {_op} {_cb} ({b})"
            return None
        return _fn

    if rtype == "date_order":
        cb = rule["col_before"].upper()
        ca = rule["col_after"].upper()
        def _fn(row, mapping, _cb=cb, _ca=ca):
            sb = mapping.get(_cb, "")
            sa = mapping.get(_ca, "")
            if not sb or not sa or sb not in row.index or sa not in row.index:
                return None
            db = _parse_date(row[sb])
            da = _parse_date(row[sa])
            if db and da and db > da:
                return (f"{_cb} ({row[sb]}) must be on or before {_ca} ({row[sa]})")
            return None
        return _fn

    if rtype == "regex":
        col  = rule["column"].upper()
        msg  = rule.get("message", f"{col} does not match expected pattern")
        try:
            pat = re.compile(rule.get("pattern", ""))
        except re.error:
            return None
        def _fn(row, mapping, _c=col, _p=pat, _m=msg):
            src = mapping.get(_c, "")
            if not src or src not in row.index:
                return None
            v = str(row[src]).strip() if pd.notna(row[src]) else ""
            if not v:
                return None
            return _m if not _p.match(v) else None
        return _fn

    return None


def get_val_rules_for_table(target_table: str) -> list[dict]:
    """
    Return BUSINESS_RULES-compatible dicts for enabled validation rules
    matching target_table (or table="*").
    """
    tbl_upper = (target_table or "").upper()
    result = []
    for rule in load_val_rules():
        if not rule.get("enabled", True):
            continue
        rule_tbl = rule.get("table", "*")
        if rule_tbl != "*" and rule_tbl.upper() != tbl_upper:
            continue
        check_fn = _build_val_check(rule)
        if check_fn is None:
            continue
        result.append({
            "name":     f"[User] {rule.get('name', rule.get('id', '?'))}",
            "severity": rule.get("severity", "WARNING"),
            "check":    check_fn,
        })
    return result


# ═══════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("user_rules.py — self test")
    store = load_store()
    nr = store["normalization_rules"]
    vr = store["validation_rules"]
    print(f"  Normalization rules : {len(nr)}")
    print(f"  Validation rules    : {len(vr)}")

    for r in nr:
        print(f"  NR  {r['id']}  {r.get('name','')[:45]}")

    for r in vr:
        fn     = _build_val_check(r)
        status = "✓" if fn else "✗ unknown type"
        print(f"  VAL {r['id']}  {r.get('name','')[:40]:<40}  {status}")

    # Quick norm test
    df = pd.DataFrame({
        "WELL_NAME":  ["sunflower 1", "ARKANSAS 2", "  Permian 3  "],
        "UWI":        ["100-1-2", "100-3-4", "100-5-6"],
    })
    df2, changes = apply_norm_rules(df, "well")
    print(f"\n  Norm test — {len(changes)} change group(s):")
    for c in changes:
        print(f"    {c['id']}  {c['name']}  col={c['column']}  changed={c['changed']}")
    print("\nAll done ✓")

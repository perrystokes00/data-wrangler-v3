"""
value_standardize.py — canonical value standardization (Stage 3)
================================================================
Place in:  .../data_wrangler_v3/modules/value_standardize.py

Applies dataview.dv_value_map to the staging table so raw source values
are conformed to canonical reference vocabulary BEFORE FK resolution.
Set-based (one UPDATE per mapping), governed, auditable.

    apply_value_map(engine, stg_schema, stg_table, col_mapping)
        -> list of dicts: {column, source_value, canonical, rows}

    fetch_value_map(engine)              -> pandas.DataFrame
    upsert_value_map(engine, target_table, target_column,
                     source_value, canonical_value, by="PIPELINE")
"""
from __future__ import annotations


def _target_to_source(col_mapping) -> dict:
    """{ target_column(lower) : staging source column } from the active mapping."""
    out = {}
    for m in (getattr(col_mapping, "mapped", []) or []):
        tgt = getattr(m, "ppdm_col", "") or ""
        src = getattr(m, "source_col", "") or ""
        if tgt and src and not getattr(m, "auto_generated", False):
            out[tgt.lower()] = src
    return out


def fetch_value_map(engine, active_only: bool = True):
    import pandas as pd
    from sqlalchemy import text
    where = "WHERE active_ind = 'Y'" if active_only else ""
    sql = (f"SELECT map_id, target_table, target_column, source_value, "
           f"canonical_value, confirmed_ind, active_ind, source, remark "
           f"FROM dataview.dv_value_map {where} "
           f"ORDER BY target_column, source_value")
    with engine.connect() as con:
        return pd.read_sql(text(sql), con)


def upsert_value_map(engine, target_table, target_column, source_value,
                     canonical_value, by="PIPELINE", source=None, remark=None):
    """Insert or update one mapping. Keyed on (target_column, source_value)."""
    from sqlalchemy import text
    sql = text("""
        MERGE dataview.dv_value_map AS t
        USING (SELECT :tcol AS target_column, :sval AS source_value) AS s
          ON (t.target_column = s.target_column AND t.source_value = s.source_value)
        WHEN MATCHED THEN UPDATE SET
            canonical_value = :canon, target_table = :ttab, active_ind = 'Y',
            confirmed_ind = 'Y', source = :src, remark = :rmk,
            row_changed_by = :by, row_changed_date = GETUTCDATE()
        WHEN NOT MATCHED THEN
            INSERT (target_table, target_column, source_value, canonical_value,
                    confirmed_ind, active_ind, source, remark, row_created_by)
            VALUES (:ttab, :tcol, :sval, :canon, 'Y', 'Y', :src, :rmk, :by);
    """)
    with engine.begin() as con:
        con.execute(sql, {
            "ttab": target_table, "tcol": target_column, "sval": source_value,
            "canon": canonical_value, "src": source, "rmk": remark, "by": by,
        })


def strip_state_prefix_county(engine, stg_schema, stg_table, col_mapping):
    """Strip a leading '<province_state>_' prefix from the county column in
    staging so 'LA_BOSSIER' -> 'BOSSIER' (matching dv_county.county_name).
    Rows whose county does NOT start with their own state code + '_' are left
    untouched, so mixed source formats (prefixed and bare) both normalize to
    bare county names. Returns the number of rows changed."""
    from sqlalchemy import text
    t2s        = _target_to_source(col_mapping)
    county_col = t2s.get("county")
    state_col  = t2s.get("province_state")
    if not county_col or not state_col:
        return 0
    sql = text(
        f"UPDATE t "
        f"SET t.[{county_col}] = "
        f"  SUBSTRING(t.[{county_col}], LEN(LTRIM(RTRIM(t.[{state_col}]))) + 2, 8000) "
        f"FROM [{stg_schema}].[{stg_table}] t "
        f"WHERE NULLIF(LTRIM(RTRIM(t.[{state_col}])),'') IS NOT NULL "
        f"  AND t.[{county_col}] LIKE LTRIM(RTRIM(t.[{state_col}])) + '\\_%' ESCAPE '\\'")
    try:
        with engine.begin() as con:
            return con.execute(sql).rowcount or 0
    except Exception:
        return 0


def apply_value_map(engine, stg_schema, stg_table, col_mapping):
    """
    Conform staging values to canonical per dv_value_map.
    Returns a report list of {column, source_value, canonical, rows}.
    """
    from sqlalchemy import text

    # value map may not exist yet — fail soft
    try:
        vm = fetch_value_map(engine, active_only=True)
    except Exception:
        return []

    if vm is None or vm.empty:
        return []

    t2s = _target_to_source(col_mapping)
    report = []

    with engine.begin() as con:
        for _, r in vm.iterrows():
            tcol  = str(r["target_column"]).strip()
            sval  = str(r["source_value"]).strip()
            canon = str(r["canonical_value"]).strip()
            src_col = t2s.get(tcol.lower())
            if not src_col or not sval or canon == sval:
                continue
            res = con.execute(
                text(f"UPDATE [{stg_schema}].[{stg_table}] "
                     f"SET [{src_col}] = :canon "
                     f"WHERE LTRIM(RTRIM([{src_col}])) = :sval"),
                {"canon": canon, "sval": sval})
            n = res.rowcount or 0
            if n > 0:
                report.append({"column": tcol, "source_value": sval,
                               "canonical": canon, "rows": int(n)})
    return report

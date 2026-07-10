"""
ref_seeder.py — DataView v3 Standards Manager: seed ANY reference/lookup table
from the distinct values of a source table.

Port of the Data Wrangler v2 RTM "From mapping" workflow:
  pick source table+column -> pull DISTINCT values (with row counts)
  -> diff against what's already in the reference table (case-insensitive)
  -> review / canonicalize / approve in an editable grid
  -> idempotent, set-based INSERT with audit columns filled.

No per-row loops: the insert is a single batched INSERT ... SELECT FROM (VALUES ...)
guarded by NOT EXISTS, so re-running is safe and CI-collation duplicates
(OIL vs Oil) are skipped rather than throwing PK violations.

Integration (Standards Manager page):
    from ref_seeder import render_reference_seeder
    render_reference_seeder(engine, schema="dataview", current_user="pmstokes")
"""
from __future__ import annotations
import pandas as pd
from sqlalchemy import text

# audit columns every dv_ reference table carries
_AUDIT_REQUIRED = ("active_ind", "row_created_by", "row_created_date")
_OPTIONAL_DESC  = ("short_name", "long_name", "remark")


# ───────────────────────── introspection ─────────────────────────
def list_tables(engine, schema: str | None = None) -> pd.DataFrame:
    sql = """
        SELECT TABLE_SCHEMA AS [schema], TABLE_NAME AS [table]
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND (:schema IS NULL OR TABLE_SCHEMA = :schema)
        ORDER BY TABLE_SCHEMA, TABLE_NAME
    """
    with engine.connect() as cx:
        return pd.read_sql(text(sql), cx, params={"schema": schema})


def get_columns(engine, schema: str, table: str) -> pd.DataFrame:
    sql = """
        SELECT COLUMN_NAME AS [column],
               DATA_TYPE   AS [type],
               CHARACTER_MAXIMUM_LENGTH AS [max_len],
               IS_NULLABLE AS [nullable]
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :s AND TABLE_NAME = :t
        ORDER BY ORDINAL_POSITION
    """
    with engine.connect() as cx:
        return pd.read_sql(text(sql), cx, params={"s": schema, "t": table})


def get_pk_columns(engine, schema: str, table: str) -> list[str]:
    """Primary-key columns, in key order. Falls back to first column."""
    sql = """
        SELECT k.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS c
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
          ON c.CONSTRAINT_NAME = k.CONSTRAINT_NAME
         AND c.TABLE_SCHEMA   = k.TABLE_SCHEMA
        WHERE c.CONSTRAINT_TYPE = 'PRIMARY KEY'
          AND c.TABLE_SCHEMA = :s AND c.TABLE_NAME = :t
        ORDER BY k.ORDINAL_POSITION
    """
    with engine.connect() as cx:
        pk = [r[0] for r in cx.execute(text(sql), {"s": schema, "t": table})]
    if pk:
        return pk
    cols = get_columns(engine, schema, table)
    return [cols.iloc[0]["column"]] if len(cols) else []


def is_reference_table(name: str) -> bool:
    n = name.lower()
    return n.startswith("dv_r_") or n in ("dv_country", "dv_province_state", "dv_county")


# ───────────────────────── value extraction / diff ─────────────────────────
def distinct_source_values(engine, schema: str, table: str, column: str,
                           trim: bool = True, drop_blank: bool = True) -> pd.DataFrame:
    """DISTINCT values of one column with how many source rows carry each."""
    expr = f"LTRIM(RTRIM([{column}]))" if trim else f"[{column}]"
    where = f"WHERE {expr} IS NOT NULL" + (f" AND {expr} <> ''" if drop_blank else "")
    sql = f"""
        SELECT {expr} AS value, COUNT(*) AS rows
        FROM [{schema}].[{table}]
        {where}
        GROUP BY {expr}
        ORDER BY {expr}
    """
    with engine.connect() as cx:
        return pd.read_sql(text(sql), cx)


def existing_ref_values(engine, schema: str, table: str, pk_col: str) -> set[str]:
    sql = f"SELECT DISTINCT [{pk_col}] AS v FROM [{schema}].[{table}]"
    with engine.connect() as cx:
        return {str(r[0]).strip().lower() for r in cx.execute(text(sql)) if r[0] is not None}


def build_candidate_frame(engine, src_schema, src_table, src_col,
                          ref_schema, ref_table, ref_pk, pk_max_len=None) -> pd.DataFrame:
    """Distinct source values annotated with status (NEW/EXISTS) and length flag."""
    df = distinct_source_values(engine, src_schema, src_table, src_col)
    have = existing_ref_values(engine, ref_schema, ref_table, ref_pk)
    df["value"] = df["value"].astype(str).str.strip()
    df["status"] = df["value"].str.lower().map(lambda v: "EXISTS" if v in have else "NEW")
    df["too_long"] = (df["value"].str.len() > pk_max_len) if pk_max_len else False
    # default UI columns
    df.insert(0, "insert", (df["status"] == "NEW") & (~df["too_long"]))
    df["short_name"] = ""
    df["long_name"] = df["value"]
    return df[["insert", "value", "short_name", "long_name", "rows", "status", "too_long"]]


# ───────────────────────── set-based idempotent insert ─────────────────────────
def insert_reference_values(engine, schema, table, pk_col, rows,
                            current_user="standards_mgr", batch=400) -> int:
    """
    rows: list of dicts with keys value, short_name, long_name (extras ignored if
    the column is absent on the target). Inserts only values not already present
    (NOT EXISTS, case-insensitive via collation). Returns count inserted.
    """
    if not rows:
        return 0
    tbl_cols = set(get_columns(engine, schema, table)["column"].str.lower())
    desc_cols = [c for c in _OPTIONAL_DESC if c in tbl_cols]      # which of short/long/remark exist
    insert_cols = [pk_col] + desc_cols + list(_AUDIT_REQUIRED)
    col_sql = ", ".join(f"[{c}]" for c in insert_cols)

    total = 0
    with engine.begin() as cx:                                   # one transaction
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]
            value_rows, params = [], {"usr": current_user}
            for j, r in enumerate(chunk):
                ph = [f":v{j}"] + [f":d{j}_{k}" for k in range(len(desc_cols))]
                value_rows.append("(" + ", ".join(ph) + ")")
                params[f"v{j}"] = r["value"]
                for k, dc in enumerate(desc_cols):
                    params[f"d{j}_{k}"] = r.get(dc) or None
            vcols = ", ".join(["val"] + [f"d{k}" for k in range(len(desc_cols))])
            sel = ["v.val"] + [f"v.d{k}" for k in range(len(desc_cols))] \
                  + ["N'Y'", ":usr", "SYSUTCDATETIME()"]
            sql = f"""
                INSERT INTO [{schema}].[{table}] ({col_sql})
                SELECT {", ".join(sel)}
                FROM (VALUES {", ".join(value_rows)}) AS v({vcols})
                WHERE NOT EXISTS (
                    SELECT 1 FROM [{schema}].[{table}] t WHERE t.[{pk_col}] = v.val
                );
            """
            total += cx.execute(text(sql), params).rowcount
    return total


# ───────────────────────── Streamlit UI ─────────────────────────
def render_reference_seeder(engine, schema: str = "dataview",
                            current_user: str = "standards_mgr"):
    import streamlit as st

    st.subheader("Seed reference table from a source")
    st.caption("Pull the distinct values out of any source column, review what's "
               "new, and promote the approved set into a reference/lookup table.")

    tables = list_tables(engine, schema)
    if tables.empty:
        st.warning(f"No tables found in schema [{schema}].")
        return
    names = tables["table"].tolist()
    ref_names = [n for n in names if is_reference_table(n)]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Source**")
        src_table = st.selectbox("Source table", names, key="rs_src_tbl")
        src_cols = get_columns(engine, schema, src_table)["column"].tolist()
        src_col = st.selectbox("Source column", src_cols, key="rs_src_col")
    with c2:
        st.markdown("**Target reference table**")
        show_all = st.checkbox("show all tables", value=False, key="rs_all")
        opts = names if show_all else (ref_names or names)
        ref_table = st.selectbox("Reference table", opts, key="rs_ref_tbl")
        pk_guess = get_pk_columns(engine, schema, ref_table)
        ref_cols = get_columns(engine, schema, ref_table)
        ref_pk = st.selectbox("Value (PK) column", ref_cols["column"].tolist(),
                              index=(ref_cols["column"].tolist().index(pk_guess[0])
                                     if pk_guess else 0), key="rs_ref_pk")
        pk_len = ref_cols.loc[ref_cols["column"] == ref_pk, "max_len"]
        pk_len = int(pk_len.iloc[0]) if len(pk_len) and pd.notna(pk_len.iloc[0]) else None

    if st.button("Find distinct values", type="primary"):
        try:
            st.session_state["rs_cand"] = build_candidate_frame(
                engine, schema, src_table, src_col, schema, ref_table, ref_pk, pk_len)
            st.session_state["rs_meta"] = (ref_table, ref_pk)
        except Exception as e:
            st.error(f"Could not read values: {e}")
            return

    cand = st.session_state.get("rs_cand")
    if cand is None:
        return

    n_new = int((cand["status"] == "NEW").sum())
    n_have = int((cand["status"] == "EXISTS").sum())
    n_long = int(cand["too_long"].sum())
    msg = f"{len(cand)} distinct · {n_new} new · {n_have} already present"
    if n_long:
        msg += f" · ⚠ {n_long} exceed the {pk_len}-char key"
    st.info(msg)

    edited = st.data_editor(
        cand, use_container_width=True, hide_index=True, key="rs_editor",
        column_config={
            "insert": st.column_config.CheckboxColumn("seed?", width="small"),
            "value": st.column_config.TextColumn("value", help="edit to canonicalize"),
            "short_name": st.column_config.TextColumn("short_name"),
            "long_name": st.column_config.TextColumn("long_name"),
            "rows": st.column_config.NumberColumn("src rows", disabled=True, width="small"),
            "status": st.column_config.TextColumn("status", disabled=True, width="small"),
            "too_long": st.column_config.CheckboxColumn("⚠ long", disabled=True, width="small"),
        },
    )

    st.download_button("Download candidates (CSV)",
                       edited.to_csv(index=False).encode(),
                       file_name=f"candidates_{src_table}_{src_col}.csv")

    ref_table, ref_pk = st.session_state["rs_meta"]
    approved = edited[edited["insert"] & ~edited["too_long"]]
    approved = approved[approved["value"].astype(str).str.strip() != ""]

    if st.button(f"Insert {len(approved)} value(s) into {ref_table}", disabled=approved.empty):
        try:
            rows = approved[["value", "short_name", "long_name"]].to_dict("records")
            n = insert_reference_values(engine, schema, ref_table, ref_pk, rows, current_user)
            st.success(f"Inserted {n} new value(s) into [{schema}].[{ref_table}]. "
                       f"{len(approved) - n} already present (skipped).")
            # refresh diff so the grid reflects the new state
            st.session_state["rs_cand"] = build_candidate_frame(
                engine, schema, src_table, src_col, schema, ref_table, ref_pk, pk_len)
            st.rerun()
        except Exception as e:
            st.error(f"Insert failed: {e}")

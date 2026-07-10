"""
page_db_explorer.py  --  PPDM Database Explorer
================================================
- Query and Results boxes always open
- Freeform SQL query -- no table selection required
- Optional table selectbox -- populates query with SELECT TOP N
- Row count slider (default 25) when a table is selected
- Export CSV under every table
"""
import io
import streamlit as st
import pandas as pd
from sqlalchemy import text


# -----------------------------------------------------------------------
# CACHED DB QUERIES
# -----------------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def _table_list(_url):
    engine = st.session_state["engine"]
    sql = """
        SELECT s.name + '.' + t.name AS tbl
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        ORDER BY t.name
    """
    with engine.connect() as con:
        rows = con.execute(text(sql)).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=300, show_spinner=False)
def _columns(_url, schema, table):
    engine = st.session_state["engine"]
    sql = """
        SELECT
            c.column_id  AS [#],
            c.name       AS [Column],
            tp.name +
            CASE
                WHEN tp.name IN ('varchar','char')
                     THEN '(' + CASE WHEN c.max_length = -1 THEN 'MAX'
                                     ELSE CAST(c.max_length AS VARCHAR) END + ')'
                WHEN tp.name IN ('nvarchar','nchar')
                     THEN '(' + CASE WHEN c.max_length = -1 THEN 'MAX'
                                     ELSE CAST(c.max_length/2 AS VARCHAR) END + ')'
                WHEN tp.name IN ('decimal','numeric')
                     THEN '(' + CAST(c.precision AS VARCHAR)
                          + ',' + CAST(c.scale AS VARCHAR) + ')'
                ELSE ''
            END          AS [Type],
            CASE WHEN c.is_nullable = 1 THEN 'YES' ELSE 'NO' END AS [Nullable],
            CASE WHEN pk.column_id IS NOT NULL THEN 'PK' ELSE '' END AS [Key]
        FROM sys.columns c
        JOIN sys.types tp ON tp.user_type_id = c.user_type_id
        JOIN sys.tables t  ON t.object_id = c.object_id
        JOIN sys.schemas s ON s.schema_id  = t.schema_id
        LEFT JOIN (
            SELECT ic.column_id, ic.object_id
            FROM sys.index_columns ic
            JOIN sys.indexes i ON i.object_id = ic.object_id
                               AND i.index_id  = ic.index_id
            WHERE i.is_primary_key = 1
        ) pk ON pk.object_id = c.object_id AND pk.column_id = c.column_id
        WHERE s.name = :sch AND t.name = :tbl
        ORDER BY c.column_id
    """
    with engine.connect() as con:
        return pd.read_sql(text(sql), con, params={"sch": schema, "tbl": table})


@st.cache_data(ttl=300, show_spinner=False)
def _indexes(_url, schema, table):
    engine = st.session_state["engine"]
    sql = """
        SELECT
            i.name  AS [Index],
            CASE WHEN i.is_primary_key = 1 THEN 'YES' ELSE 'NO' END AS [PK],
            CASE WHEN i.is_unique      = 1 THEN 'YES' ELSE 'NO' END AS [Unique],
            STRING_AGG(c.name, ', ')
                WITHIN GROUP (ORDER BY ic.key_ordinal) AS [Columns]
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id
                                  AND ic.index_id  = i.index_id
        JOIN sys.columns c  ON c.object_id = i.object_id
                           AND c.column_id  = ic.column_id
        JOIN sys.tables t   ON t.object_id  = i.object_id
        JOIN sys.schemas s  ON s.schema_id  = t.schema_id
        WHERE s.name = :sch AND t.name = :tbl AND i.name IS NOT NULL
        GROUP BY i.name, i.is_primary_key, i.is_unique
        ORDER BY i.is_primary_key DESC, i.name
    """
    with engine.connect() as con:
        return pd.read_sql(text(sql), con, params={"sch": schema, "tbl": table})


@st.cache_data(ttl=300, show_spinner=False)
def _fk_out(_url, schema, table):
    engine = st.session_state["engine"]
    sql = """
        SELECT
            fk.name  AS [FK Name],
            STRING_AGG(cc.name, ', ')
                WITHIN GROUP (ORDER BY fkc.constraint_column_id) AS [Column(s)],
            ps.name + '.' + pt.name  AS [References Table],
            STRING_AGG(pc.name, ', ')
                WITHIN GROUP (ORDER BY fkc.constraint_column_id) AS [Ref Column(s)]
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN sys.tables  ct ON ct.object_id = fk.parent_object_id
        JOIN sys.schemas cs ON cs.schema_id = ct.schema_id
        JOIN sys.columns cc ON cc.object_id = fk.parent_object_id
                           AND cc.column_id = fkc.parent_column_id
        JOIN sys.tables  pt ON pt.object_id = fk.referenced_object_id
        JOIN sys.schemas ps ON ps.schema_id = pt.schema_id
        JOIN sys.columns pc ON pc.object_id = fk.referenced_object_id
                           AND pc.column_id = fkc.referenced_column_id
        WHERE cs.name = :sch AND ct.name = :tbl
        GROUP BY fk.name, ps.name, pt.name
        ORDER BY fk.name
    """
    with engine.connect() as con:
        return pd.read_sql(text(sql), con, params={"sch": schema, "tbl": table})


@st.cache_data(ttl=300, show_spinner=False)
def _fk_in(_url, schema, table):
    engine = st.session_state["engine"]
    sql = """
        SELECT
            fk.name  AS [FK Name],
            cs.name + '.' + ct.name  AS [From Table],
            STRING_AGG(cc.name, ', ')
                WITHIN GROUP (ORDER BY fkc.constraint_column_id) AS [From Column(s)],
            STRING_AGG(pc.name, ', ')
                WITHIN GROUP (ORDER BY fkc.constraint_column_id) AS [Ref Column(s)]
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN sys.tables  ct ON ct.object_id = fk.parent_object_id
        JOIN sys.schemas cs ON cs.schema_id = ct.schema_id
        JOIN sys.columns cc ON cc.object_id = fk.parent_object_id
                           AND cc.column_id = fkc.parent_column_id
        JOIN sys.tables  pt ON pt.object_id = fk.referenced_object_id
        JOIN sys.schemas ps ON ps.schema_id = pt.schema_id
        JOIN sys.columns pc ON pc.object_id = fk.referenced_object_id
                           AND pc.column_id = fkc.referenced_column_id
        WHERE ps.name = :sch AND pt.name = :tbl
        GROUP BY fk.name, cs.name, ct.name
        ORDER BY cs.name, ct.name
    """
    with engine.connect() as con:
        return pd.read_sql(text(sql), con, params={"sch": schema, "tbl": table})


def _run_query(engine, sql):
    try:
        with engine.connect() as con:
            df = pd.read_sql(text(sql), con)
        return df, None
    except Exception as e:
        return None, str(e)


def _csv_btn(df, filename, key):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    st.download_button(
        "Export CSV", buf.getvalue(),
        file_name=filename, mime="text/csv", key=key
    )


# -----------------------------------------------------------------------
# ENTRY POINT
# -----------------------------------------------------------------------

def render(S):
    st.markdown("### Database Explorer")

    if not S.get("engine"):
        st.warning("Not connected -- complete Stage 1 (Connect) first.")
        return

    engine  = S["engine"]
    eng_url = str(engine.url)

    # Session defaults
    for k, v in {
        "dbx_selected": None,
        "dbx_query":    "",
        "dbx_results":  None,
        "dbx_error":    None,
        "dbx_top_n":    25,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ---------------------------------------------------------------
    # TABLE SELECTBOX  (optional -- query works without it)
    # ---------------------------------------------------------------
    try:
        table_list = _table_list(eng_url)
    except Exception as e:
        st.error(f"Could not load table list: {e}")
        return

    options = ["-- none (freeform query) --"] + table_list
    cur     = st.session_state.dbx_selected
    idx     = options.index(cur) if cur in options else 0

    sel_col, slider_col = st.columns([4, 2])

    with sel_col:
        chosen = st.selectbox(
            "Table (optional)",
            options=options,
            index=idx,
            key="dbx_selectbox"
        )

    # Row slider -- only shown when a table is selected
    top_n = st.session_state.dbx_top_n
    if chosen != "-- none (freeform query) --":
        with slider_col:
            top_n = st.slider(
                "Rows", min_value=10, max_value=5000,
                value=st.session_state.dbx_top_n, step=25,
                key="dbx_slider"
            )
            st.session_state.dbx_top_n = top_n

    # Handle table selection / deselection
    if chosen == "-- none (freeform query) --":
        if st.session_state.dbx_selected is not None:
            # Just deselected -- clear table state but keep any typed query
            st.session_state.dbx_selected = None
            st.session_state.dbx_results  = None
            st.session_state.dbx_error    = None
            st.rerun()
    else:
        sch, tbl = chosen.split(".", 1)
        # New table selected OR row count changed -- repopulate query
        if chosen != st.session_state.dbx_selected or top_n != st.session_state.dbx_top_n:
            st.session_state.dbx_selected = chosen
            st.session_state.dbx_query    = f"SELECT TOP {top_n} *\nFROM [{sch}].[{tbl}]"
            st.session_state.dbx_results  = None
            st.session_state.dbx_error    = None
            st.rerun()

    # ---------------------------------------------------------------
    # QUERY BOX  (always open)
    # ---------------------------------------------------------------
    with st.container(border=True):
        if st.session_state.dbx_selected:
            sch, tbl = st.session_state.dbx_selected.split(".", 1)
            st.markdown(f"**Query** -- `[{sch}].[{tbl}]`")
        else:
            st.markdown("**Query**")

        query = st.text_area(
            "SQL",
            value=st.session_state.dbx_query,
            height=150,
            placeholder="SELECT TOP 100 * FROM [dbo].[well]",
            label_visibility="collapsed",
            key="dbx_query_area"
        )
        st.session_state.dbx_query = query

        b1, b2, b3, _ = st.columns([2, 2, 2, 6])

        if b1.button("  Execute  ", type="primary", use_container_width=True):
            if query.strip():
                with st.spinner("Running..."):
                    df, err = _run_query(engine, query)
                st.session_state.dbx_results = df
                st.session_state.dbx_error   = err
                st.rerun()

        if b2.button("  Reset SQL  ", use_container_width=True):
            if st.session_state.dbx_selected:
                sch, tbl = st.session_state.dbx_selected.split(".", 1)
                st.session_state.dbx_query = (
                    f"SELECT TOP {st.session_state.dbx_top_n} *\nFROM [{sch}].[{tbl}]"
                )
            else:
                st.session_state.dbx_query = ""
            st.session_state.dbx_results = None
            st.session_state.dbx_error   = None
            st.rerun()

        if b3.button("  Clear  ", use_container_width=True):
            st.session_state.dbx_query   = ""
            st.session_state.dbx_results = None
            st.session_state.dbx_error   = None
            st.rerun()

    # ---------------------------------------------------------------
    # RESULTS BOX  (always open)
    # ---------------------------------------------------------------
    with st.container(border=True):
        st.markdown("**Results**")

        if st.session_state.dbx_error:
            st.error(f"Error: {st.session_state.dbx_error}")

        elif st.session_state.dbx_results is not None:
            df = st.session_state.dbx_results
            st.caption(f"{len(df):,} rows, {df.shape[1]} columns")
            st.dataframe(df, use_container_width=True, height=400)
            fname = (
                f"{tbl}_results.csv"
                if st.session_state.dbx_selected else "query_results.csv"
            )
            _csv_btn(df, fname, "dl_results")

        else:
            st.caption("Results will appear here after Execute.")

    # ---------------------------------------------------------------
    # TABLE DETAIL  (only when a table is selected)
    # ---------------------------------------------------------------
    if not st.session_state.dbx_selected:
        return

    sch, tbl = st.session_state.dbx_selected.split(".", 1)

    with st.container(border=True):
        st.markdown(f"**Table Detail** -- `[{sch}].[{tbl}]`")

        tab_c, tab_i, tab_fo, tab_fi = st.tabs([
            "Columns",
            "Indexes",
            "FK Out",
            "FK In",
        ])

        with tab_c:
            df_c = _columns(eng_url, sch, tbl)
            st.dataframe(df_c, use_container_width=True, hide_index=True, height=380)
            _csv_btn(df_c, f"{tbl}_columns.csv", "dl_columns")

        with tab_i:
            df_i = _indexes(eng_url, sch, tbl)
            if df_i.empty:
                st.caption("No indexes.")
            else:
                st.dataframe(df_i, use_container_width=True, hide_index=True)
                _csv_btn(df_i, f"{tbl}_indexes.csv", "dl_indexes")

        with tab_fo:
            df_fo = _fk_out(eng_url, sch, tbl)
            if df_fo.empty:
                st.caption("No foreign keys out from this table.")
            else:
                st.dataframe(df_fo, use_container_width=True, hide_index=True)
                _csv_btn(df_fo, f"{tbl}_fk_out.csv", "dl_fk_out")

        with tab_fi:
            df_fi = _fk_in(eng_url, sch, tbl)
            if df_fi.empty:
                st.caption("No other tables reference this table.")
            else:
                st.dataframe(df_fi, use_container_width=True, hide_index=True)
                _csv_btn(df_fi, f"{tbl}_fk_in.csv", "dl_fk_in")

"""
page_db_explorer.py  --  PPDM Database Explorer
================================================
- Query and Results boxes always open
- Freeform SQL query -- no table selection required
- Optional table selectbox -- populates query with SELECT TOP N
- Row count slider (default 25) when a table is selected
- Export CSV under every table
- Dialect-aware: SQL Server and Oracle
"""
import io
import streamlit as st
import pandas as pd
from sqlalchemy import text
from modules.db import _detect_dialect


# -----------------------------------------------------------------------
# DIALECT HELPERS
# -----------------------------------------------------------------------

def _get_dialect(engine):
    return _detect_dialect(engine)

def _q(name, dialect):
    """Dialect-aware identifier quoting."""
    return f'"{name.upper()}"' if dialect in ("oracle", "snowflake") else f"[{name}]"

def _get_schema(engine, dialect, default="dbo"):
    """Get the default schema for the current connection."""
    if dialect == "oracle":
        try:
            with engine.connect() as con:
                return con.execute(text(
                    "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
                )).scalar() or default.upper()
        except Exception:
            return default.upper()
    if dialect == "snowflake":
        try:
            with engine.connect() as con:
                return con.execute(text("SELECT CURRENT_SCHEMA()")).scalar() or "DEMO"
        except Exception:
            return "DEMO"
    return default


# -----------------------------------------------------------------------
# CACHED DB QUERIES
# -----------------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False)
def _table_list(_url):
    engine  = st.session_state["engine"]
    dialect = _get_dialect(engine)
    if dialect == "oracle":
        schema = _get_schema(engine, dialect)
        sql = (
            "SELECT :sch AS sch, table_name AS tbl "
            "FROM all_tables "
            "WHERE owner = :sch "
            "ORDER BY table_name"
        )
        with engine.connect() as con:
            rows = con.execute(text(sql), {"sch": schema}).fetchall()
        return [r[1] for r in rows]
    elif dialect == "snowflake":
        schema = _get_schema(engine, dialect)
        sql = (
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = :sch AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
        with engine.connect() as con:
            rows = con.execute(text(sql), {"sch": schema}).fetchall()
        return [r[0] for r in rows]
    else:
        sql = """
            SELECT s.name AS sch, t.name AS tbl
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            ORDER BY t.name
        """
        with engine.connect() as con:
            rows = con.execute(text(sql)).fetchall()
        return [r[1] if r[0] == "dbo" else f"{r[0]}.{r[1]}" for r in rows]


@st.cache_data(ttl=300, show_spinner=False)
def _columns(_url, schema, table):
    engine  = st.session_state["engine"]
    dialect = _get_dialect(engine)
    if dialect == "oracle":
        sql = """
            SELECT
                c.column_id                          AS "#",
                c.column_name                        AS "Column",
                c.data_type ||
                CASE
                    WHEN c.data_type IN ('VARCHAR2','NVARCHAR2','CHAR')
                         THEN '(' || c.char_length || ')'
                    WHEN c.data_type = 'NUMBER' AND c.data_precision IS NOT NULL
                         THEN '(' || c.data_precision || ',' || NVL(c.data_scale,0) || ')'
                    ELSE ''
                END                                  AS "Type",
                CASE WHEN c.nullable = 'Y' THEN 'YES' ELSE 'NO' END AS "Nullable",
                CASE WHEN p.column_name IS NOT NULL THEN 'PK' ELSE '' END AS "Key"
            FROM all_tab_columns c
            LEFT JOIN (
                SELECT cc.column_name
                FROM all_constraints con
                JOIN all_cons_columns cc
                  ON cc.constraint_name = con.constraint_name
                 AND cc.owner = con.owner
                WHERE con.constraint_type = 'P'
                  AND con.table_name  = :tbl
                  AND con.owner       = :sch
            ) p ON p.column_name = c.column_name
            WHERE c.table_name = :tbl
              AND c.owner      = :sch
            ORDER BY c.column_id
        """
        with engine.connect() as con:
            return pd.read_sql(text(sql), con,
                               params={"sch": schema.upper(), "tbl": table.upper()})
    elif dialect == "snowflake":
        sql = """
            SELECT
                ORDINAL_POSITION AS "#",
                COLUMN_NAME AS "Column",
                DATA_TYPE ||
                CASE WHEN CHARACTER_MAXIMUM_LENGTH IS NOT NULL
                     THEN '(' || CHARACTER_MAXIMUM_LENGTH || ')'
                     WHEN NUMERIC_PRECISION IS NOT NULL
                     THEN '(' || NUMERIC_PRECISION || ',' || COALESCE(NUMERIC_SCALE,0) || ')'
                     ELSE '' END AS "Type",
                IS_NULLABLE AS "Nullable",
                '' AS "Key"
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = :sch AND TABLE_NAME = :tbl
            ORDER BY ORDINAL_POSITION
        """
        with engine.connect() as con:
            return pd.read_sql(text(sql), con,
                               params={"sch": schema.upper(), "tbl": table.upper()})
    else:
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
    engine  = st.session_state["engine"]
    dialect = _get_dialect(engine)
    if dialect == "snowflake":
        return pd.DataFrame(columns=["Index", "Unique", "Columns"])
    if dialect == "oracle":
        sql = """
            SELECT
                i.index_name    AS "Index",
                CASE WHEN c.constraint_type = 'P' THEN 'YES' ELSE 'NO' END AS "PK",
                CASE WHEN i.uniqueness = 'UNIQUE' THEN 'YES' ELSE 'NO' END AS "Unique",
                LISTAGG(ic.column_name, ', ')
                    WITHIN GROUP (ORDER BY ic.column_position) AS "Columns"
            FROM all_indexes i
            JOIN all_ind_columns ic
              ON ic.index_name  = i.index_name
             AND ic.table_owner = i.table_owner
            LEFT JOIN all_constraints c
              ON c.index_name   = i.index_name
             AND c.owner        = i.owner
            WHERE i.table_name  = :tbl
              AND i.table_owner = :sch
            GROUP BY i.index_name, c.constraint_type, i.uniqueness
            ORDER BY "PK" DESC, i.index_name
        """
        with engine.connect() as con:
            return pd.read_sql(text(sql), con,
                               params={"sch": schema.upper(), "tbl": table.upper()})
    else:
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
    engine  = st.session_state["engine"]
    dialect = _get_dialect(engine)
    if dialect == "snowflake":
        return pd.DataFrame(columns=["FK Name", "To Table", "From Column(s)", "To Column(s)"])
    if dialect == "oracle":
        sql = """
            SELECT
                con.constraint_name   AS "FK Name",
                LISTAGG(cc.column_name, ', ')
                    WITHIN GROUP (ORDER BY cc.position) AS "Column(s)",
                rcon.owner || '.' || rcon.table_name AS "References Table",
                LISTAGG(pc.column_name, ', ')
                    WITHIN GROUP (ORDER BY pc.position) AS "Ref Column(s)"
            FROM all_constraints con
            JOIN all_cons_columns cc
              ON cc.constraint_name = con.constraint_name AND cc.owner = con.owner
            JOIN all_constraints rcon
              ON rcon.constraint_name = con.r_constraint_name AND rcon.owner = con.r_owner
            JOIN all_cons_columns pc
              ON pc.constraint_name = rcon.constraint_name AND pc.owner = rcon.owner
             AND pc.position = cc.position
            WHERE con.constraint_type = 'R'
              AND con.table_name = :tbl
              AND con.owner      = :sch
            GROUP BY con.constraint_name, rcon.owner, rcon.table_name
            ORDER BY con.constraint_name
        """
        with engine.connect() as con:
            return pd.read_sql(text(sql), con,
                               params={"sch": schema.upper(), "tbl": table.upper()})
    else:
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
    engine  = st.session_state["engine"]
    dialect = _get_dialect(engine)
    if dialect == "snowflake":
        return pd.DataFrame(columns=["FK Name", "From Table", "From Column(s)", "Ref Column(s)"])
    if dialect == "oracle":
        sql = """
            SELECT
                con.constraint_name   AS "FK Name",
                con.owner || '.' || con.table_name AS "From Table",
                LISTAGG(cc.column_name, ', ')
                    WITHIN GROUP (ORDER BY cc.position) AS "From Column(s)",
                LISTAGG(pc.column_name, ', ')
                    WITHIN GROUP (ORDER BY pc.position) AS "Ref Column(s)"
            FROM all_constraints con
            JOIN all_cons_columns cc
              ON cc.constraint_name = con.constraint_name AND cc.owner = con.owner
            JOIN all_constraints rcon
              ON rcon.constraint_name = con.r_constraint_name AND rcon.owner = con.r_owner
            JOIN all_cons_columns pc
              ON pc.constraint_name = rcon.constraint_name AND pc.owner = rcon.owner
             AND pc.position = cc.position
            WHERE con.constraint_type = 'R'
              AND rcon.table_name = :tbl
              AND rcon.owner      = :sch
            GROUP BY con.constraint_name, con.owner, con.table_name
            ORDER BY con.owner, con.table_name
        """
        with engine.connect() as con:
            return pd.read_sql(text(sql), con,
                               params={"sch": schema.upper(), "tbl": table.upper()})
    else:
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

def _top_sql_for_dialect(engine, sch, tbl):
    """Build a SELECT * query with row limit appropriate for the dialect."""
    dialect = _get_dialect(engine)
    if dialect == "oracle":
        return f'SELECT * FROM "{sch.upper()}"."{tbl.upper()}" FETCH FIRST 100 ROWS ONLY'
    if dialect == "snowflake":
        return f'SELECT * FROM "{sch.upper()}"."{tbl.upper()}" LIMIT 100'
    return f"SELECT TOP 100 *\nFROM [{sch}].[{tbl}]"


def _run_query(engine, sql):
    try:
        q = sql.strip().upper().lstrip("(")
        is_select = q.startswith("SELECT") or q.startswith("WITH")
        if is_select:
            with engine.connect() as con:
                df = pd.read_sql(text(sql), con)
            return df, None
        else:
            with engine.begin() as con:
                result = con.execute(text(sql))
            rows_affected = result.rowcount if result.rowcount >= 0 else 0
            df = pd.DataFrame({"Result": [f"OK -- {rows_affected} row(s) affected"]})
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
# CLAUDE SQL ASSISTANT
# -----------------------------------------------------------------------

def _get_api_key():
    """Find Anthropic API key from .env, environment, or Streamlit secrets."""
    import os
    # 1. Load .env file (same as main app)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    # 2. Environment variable (set by .env or system)
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    # 3. Streamlit secrets fallback
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    return None


def _claude_sql_assist(prompt, current_sql, table_context):
    """Call Claude API to assist with SQL."""
    import json
    import urllib.request

    api_key = _get_api_key()
    if not api_key:
        return None, (
            "No API key found. Add ANTHROPIC_API_KEY to .streamlit/secrets.toml "
            "or set it as an environment variable."
        )

    _db_dialect = _get_dialect(st.session_state.get("engine")) if st.session_state.get("engine") else "sqlserver"
    _dialect_name = {"oracle": "Oracle", "snowflake": "Snowflake"}.get(_db_dialect, "SQL Server")
    _dialect_syntax = {
        "oracle": "Oracle SQL — use double-quote identifiers, FETCH FIRST n ROWS ONLY, SYSDATE",
        "snowflake": "Snowflake SQL — use double-quote uppercase identifiers, LIMIT n, CURRENT_TIMESTAMP()",
    }.get(_db_dialect, "T-SQL (SQL Server) — use square bracket identifiers, TOP n, GETUTCDATE()")
    system = (
        f"You are a {_dialect_name} expert helping with PPDM 3.9 petroleum database queries. "
        "You help with four tasks:\n"
        "1. Generate SQL from plain English descriptions\n"
        "2. Fix SQL errors and syntax issues\n"
        "3. Explain what a SQL query does in plain English\n"
        "4. Optimize slow or inefficient queries\n\n"
        "Rules:\n"
        f"- Always use {_dialect_syntax}\n"
        "- Match identifier quoting to the connected database dialect\n"
        "- Always include a row limit for SELECT * queries\n"
        "- For fix/optimize tasks, return only the corrected SQL\n"
        "- For explain tasks, return a plain English explanation\n"
        "- For generate tasks, return only the SQL\n"
        "- Do not include markdown code fences in SQL responses\n"
        "- Be concise"
    )

    user_parts = []
    if table_context:
        user_parts.append(f"Current table: {table_context}")
        # Include actual column names so Claude uses real columns
        try:
            eng = st.session_state.get("engine")
            if eng:
                if "." in table_context:
                    _ctx_sch, _ctx_tbl = table_context.split(".", 1)
                else:
                    _ctx_sch, _ctx_tbl = "dbo", table_context
                with eng.connect() as _cc:
                    from sqlalchemy import text as _ct
                    _ctx_dialect = _get_dialect(eng)
                    if _ctx_dialect == "snowflake":
                        _col_sql = _ct(
                            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                            "WHERE TABLE_SCHEMA = :sch AND TABLE_NAME = :tbl "
                            "ORDER BY ORDINAL_POSITION")
                        _col_params = {"sch": _ctx_sch.upper(), "tbl": _ctx_tbl.upper()}
                    else:
                        _col_sql = _ct(
                            "SELECT c.name, tp.name AS typ "
                            "FROM sys.columns c "
                            "JOIN sys.types tp ON tp.user_type_id = c.user_type_id "
                            "JOIN sys.tables t ON t.object_id = c.object_id "
                            "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                            "WHERE s.name = :sch AND t.name = :tbl ORDER BY c.column_id")
                        _col_params = {"sch": _ctx_sch, "tbl": _ctx_tbl}
                    _col_rows = _cc.execute(_col_sql, _col_params).fetchall()
                if _col_rows:
                    _q_l = '"' if _ctx_dialect == "snowflake" else "["
                    _q_r = '"' if _ctx_dialect == "snowflake" else "]"
                    _col_list = ", ".join(f"{r[0]} ({r[1]})" for r in _col_rows)
                    user_parts.append(f"Columns in {_q_l}{_ctx_sch}{_q_r}.{_q_l}{_ctx_tbl}{_q_r}: {_col_list}")
        except Exception:
            pass
    if current_sql.strip():
        user_parts.append(f"Current SQL:\n{current_sql}")
    user_parts.append(f"Request: {prompt}")

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "system": system,
        "messages": [{"role": "user", "content": "\n\n".join(user_parts)}]
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["content"][0]["text"], None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return None, f"HTTP {e.code}: {body}"
    except Exception as e:
        return None, str(e)


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
        "dbx_selected":    None,
        "dbx_query":       "",
        "dbx_results":     None,
        "dbx_error":       None,
        "dbx_truncated":   False,
        "dbx_ai_prompt":      "",
        "dbx_ai_response":    None,
        "dbx_ai_error":       None,
        "dbx_confirm_delete": False,
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

    chosen = st.selectbox(
        "Table (optional)",
        options=options,
        index=idx,
        key="dbx_selectbox"
    )

    top_n = 100

    # Handle table selection / deselection
    if chosen == "-- none (freeform query) --":
        if st.session_state.dbx_selected is not None:
            # Just deselected -- clear table state but keep any typed query
            st.session_state.dbx_selected = None
            st.session_state.dbx_results  = None
            st.session_state.dbx_error    = None
            st.rerun()
    else:
        if "." in chosen:
            sch, tbl = chosen.split(".", 1)
        else:
            sch, tbl = _get_schema(engine, _get_dialect(engine)), chosen
        # New table selected OR row count changed -- repopulate query
        if chosen != st.session_state.dbx_selected:
            st.session_state.dbx_selected = chosen
            st.session_state.dbx_query    = _top_sql_for_dialect(engine, sch, tbl)
            st.session_state.dbx_results  = None
            st.session_state.dbx_error    = None
            st.rerun()

    # ---------------------------------------------------------------
    # QUERY BOX  (always open)
    # ---------------------------------------------------------------
    with st.container(border=True):
        if st.session_state.dbx_selected:
            _sel = st.session_state.dbx_selected
            sch, tbl = _sel.split(".", 1) if "." in _sel else (_get_schema(engine, _get_dialect(engine)), _sel)
            st.markdown(f"**Query** -- `{sch}.{tbl}`")
        else:
            st.markdown("**Query**")

        query = st.text_area(
            "SQL",
            value=st.session_state.dbx_query,
            height=150,
            placeholder=_top_sql_for_dialect(engine, "dbo", "well"),
            label_visibility="collapsed",
            key="dbx_query_area"
        )
        st.session_state.dbx_query = query

        b1, b2, b3, b4 = st.columns(4)

        # Quick SELECT TOP 100 button
        if b4.button("TOP 100", use_container_width=True, key="dbx_top100"):
            if st.session_state.dbx_selected:
                _sel3 = st.session_state.dbx_selected
                _sch, _tbl = _sel3.split(".", 1) if "." in _sel3 else (_get_schema(engine, _get_dialect(engine)), _sel3)
                _top_sql = _top_sql_for_dialect(engine, _sch, _tbl)
            else:
                _top_sql = _top_sql_for_dialect(engine, "dbo", "well")
            st.session_state.dbx_query = _top_sql
            with st.spinner("Running..."):
                _tdf, _terr = _run_query(engine, _top_sql)
            st.session_state.dbx_results = _tdf
            st.session_state.dbx_error   = _terr
            st.rerun()

        if b1.button("Execute", type="primary", use_container_width=True):
            if query.strip():
                q_upper = query.strip().upper()
                is_destructive = any(q_upper.startswith(k) for k in ("DELETE", "TRUNCATE", "DROP"))
                if is_destructive and not st.session_state.get("dbx_confirm_delete"):
                    st.session_state.dbx_confirm_delete = True
                    st.rerun()
                else:
                    st.session_state.dbx_confirm_delete = False
                    with st.spinner("Running..."):
                        df, err = _run_query(engine, query)
                    st.session_state.dbx_results = df
                    st.session_state.dbx_error   = err
                    st.rerun()

        if b2.button("Reset SQL", use_container_width=True):
            if st.session_state.dbx_selected:
                _sel2 = st.session_state.dbx_selected
                sch, tbl = _sel2.split(".", 1) if "." in _sel2 else (_get_schema(engine, _get_dialect(engine)), _sel2)
                st.session_state.dbx_query = (
                    _top_sql_for_dialect(engine, sch, tbl)
                )
            else:
                st.session_state.dbx_query = ""
            st.session_state.dbx_results       = None
            st.session_state.dbx_error         = None
            st.session_state.dbx_confirm_delete = False
            st.rerun()

        if b3.button("Clear", use_container_width=True):
            st.session_state.dbx_query          = ""
            st.session_state.dbx_results        = None
            st.session_state.dbx_error          = None
            st.session_state.dbx_confirm_delete = False
            st.rerun()

        # Confirmation dialog for destructive queries
        if st.session_state.get("dbx_confirm_delete"):
            c_warn, c_yes, c_no = st.columns([4, 1, 1])
            c_warn.warning("DELETE / TRUNCATE / DROP — are you sure?")
            if c_yes.button("Yes", type="primary", use_container_width=True, key="dbx_confirm_yes"):
                st.session_state.dbx_confirm_delete = False
                with st.spinner("Running..."):
                    df, err = _run_query(engine, query)
                st.session_state.dbx_results = df
                st.session_state.dbx_error   = err
                st.rerun()
            if c_no.button("No", use_container_width=True, key="dbx_confirm_no"):
                st.session_state.dbx_confirm_delete = False
                st.rerun()

        st.divider()
        st.markdown("**Claude SQL Assistant**")
        st.caption("Describe what you want, ask Claude to fix/explain/optimize the query above, or ask in plain English.")

        # AI prompt — chat_input fires on Enter key press
        ai_prompt = st.chat_input(
            "Ask Claude (press Enter to send)...",
            key="dbx_ai_chat"
        )

        if ai_prompt and ai_prompt.strip():
            st.session_state.dbx_ai_prompt = ai_prompt
            table_ctx = st.session_state.dbx_selected or ""
            with st.spinner("Asking Claude..."):
                result, err = _claude_sql_assist(
                    ai_prompt,
                    st.session_state.dbx_query,
                    table_ctx
                )
            st.session_state.dbx_ai_response = result
            st.session_state.dbx_ai_error    = err
            st.rerun()

        if st.session_state.dbx_ai_error:
            st.error(f"Claude error: {st.session_state.dbx_ai_error}")

        elif st.session_state.dbx_ai_response:
            st.markdown("**Claude suggests:**")
            st.code(st.session_state.dbx_ai_response, language="sql")
            ap1, ap2, _ = st.columns([2, 2, 8])
            if ap1.button("  Apply to Query  ", use_container_width=True, key="dbx_ai_apply"):
                # Extract SQL from response — strip prose, keep only SQL block
                import re as _re
                _raw = st.session_state.dbx_ai_response
                # Try to extract from ```sql ... ``` block first
                _m = _re.search(r'```(?:sql)?\s*(.*?)```', _raw, _re.DOTALL | _re.IGNORECASE)
                if _m:
                    _applied_sql = _m.group(1).strip()
                else:
                    # Find first SELECT/INSERT/UPDATE/DELETE/WITH and take from there
                    _m2 = _re.search(
                        r'((?:SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|DROP|ALTER)\b.*)',
                        _raw, _re.DOTALL | _re.IGNORECASE)
                    _applied_sql = _m2.group(1).strip() if _m2 else _raw.strip()
                    # Strip trailing prose after last semicolon if present
                    if ';' in _applied_sql:
                        _applied_sql = _applied_sql[:_applied_sql.rfind(';')+1].strip()
                st.session_state.dbx_query       = _applied_sql
                st.session_state.dbx_ai_response = None
                st.session_state.dbx_ai_prompt   = ""
                # Execute immediately after applying
                with st.spinner("Running..."):
                    _adf, _aerr = _run_query(engine, _applied_sql)
                st.session_state.dbx_results = _adf
                st.session_state.dbx_error   = _aerr
                st.rerun()
            if ap2.button("  Dismiss  ", use_container_width=True, key="dbx_ai_dismiss"):
                st.session_state.dbx_ai_response = None
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

    _sel4 = st.session_state.dbx_selected
    sch, tbl = _sel4.split(".", 1) if "." in _sel4 else (_get_schema(engine, _get_dialect(engine)), _sel4)

    with st.container(border=True):
        st.markdown(f"**Table Detail** -- `{sch}.{tbl}`")

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
            if st.button("Load indexes", key="dbx_load_idx", use_container_width=True):
                st.session_state.dbx_show_idx = True
            if st.session_state.get("dbx_show_idx"):
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

"""
app.py  —  Data Wrangler · Main Streamlit Application
=============================================================
Thin entry point. Renders sidebar then routes to page modules.

Run:
    streamlit run app.py
"""
import json
import streamlit as st
import pandas as pd

# ── Core DB module (needed immediately for connect widget) ─────────────
from modules.db import DBConfig, connect, connect_demo

# ── Page modules ──────────────────────────────────────────────────────
# Only splash loaded eagerly — rest imported lazily at routing time
import page_splash
import page_licence
import page_file_inventory

# ── All other modules loaded lazily after splash ──────────────────────
# Calling _load_pipeline_modules() populates globals() with every symbol
# that inline app.py code references (type hints, direct calls, etc.)
def _load_pipeline_modules():
    global load_schema_from_dict, load_schema_from_string
    global ingest_file, load_to_staging, load_to_staging_demo, preview_csv, preview_staging_table
    global normalize_server, normalize_demo
    global build_mapping, TRANSFORM_OPTIONS, build_transform_sql
    global introspect_fk_constraints, introspect_fk_demo
    global check_fk_violations, apply_fk_resolutions
    global FKViolation, FKNode
    global get_reference_table_context, insert_reference_rows
    global load_fk_samples, load_fk_samples_batch, clear_parent_values_cache
    global is_reference_table, build_entity_mapping, preview_entity_rows
    global insert_entity_rows, topological_sort, KNOWN_ENTITY_TABLES
    global EntityMapping, build_fk_graph
    global validate
    global promote_server, promote_demo, promote_merge, compute_data_hash, _write_file_record
    global PPDMAgent, build_pipeline_context
    global load_catalog, seed_all, seed_all_server, check_adhoc_queries
    global generate_candidate_rows, SeedResult, sort_entries_by_fk, validate_catalog, EntryValidation
    global page_data_model, page_seed, page_pipeline, page_db_explorer, page_rules
    global page_std_catalog
    global page_ppdm_map

    from modules.schema    import load_schema_from_dict, load_schema_from_string
    from modules.staging   import ingest_file, load_to_staging, load_to_staging_demo, preview_csv, preview_staging_table
    from modules.normalize import normalize_server, normalize_demo
    from modules.mapping   import build_mapping, TRANSFORM_OPTIONS, build_transform_sql
    from modules.fk        import (
        introspect_fk_constraints, introspect_fk_demo,
        check_fk_violations, apply_resolutions as apply_fk_resolutions,
        FKViolation, FKNode,
        get_reference_table_context, insert_reference_rows,
        load_fk_samples, load_fk_samples_batch,
        clear_parent_values_cache,
    )
    from modules.fk_entity import (
        is_reference_table, build_entity_mapping, preview_entity_rows,
        insert_entity_rows, topological_sort, KNOWN_ENTITY_TABLES,
        EntityMapping, build_fk_graph,
    )
    from modules.validate     import validate
    from modules.promote      import promote_server, promote_demo, promote_merge, compute_data_hash, _write_file_record
    from modules.ppdm_agent   import PPDMAgent, build_pipeline_context
    from modules.seed_catalog import load_catalog, seed_all, seed_all_server, check_adhoc_queries, generate_candidate_rows, SeedResult, sort_entries_by_fk, validate_catalog, EntryValidation
    import page_data_model, page_seed, page_pipeline, page_db_explorer, page_rules, page_std_catalog, page_ppdm_map

# Null stubs so DEFAULTS dict type annotations don't crash before lazy load
FKViolation = FKNode = EntityMapping = None

# ═══════════════════════════════════════════════════════════════════════
# PAGE CONFIG & STYLES
# ═══════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Data Wrangler",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── Base ── */
.stApp{background:#f5f7fa;color:#1a1f2e}
.block-container{padding-top:3rem!important;padding-bottom:1rem!important;max-width:1100px}
h1,h2,h3,h4{color:#1a1f2e!important}
/* Leave Streamlit header completely alone — running man lives here */

/* ── Stage header ── */
.shdr{background:#ffffff;border:1px solid #dde3ed;border-left:4px solid #1a6fdb;
      border-radius:6px;padding:8px 14px;margin-bottom:8px;
      box-shadow:0 1px 3px rgba(0,0,0,.06)}
.shdr h3{margin:0;font-size:.95rem;color:#1a1f2e}
.shdr p{margin:3px 0 0;font-size:.78rem;color:#6b7280}

/* ── Metric boxes ── */
.mbox{background:#ffffff;border:1px solid #dde3ed;border-radius:8px;
      padding:12px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.mbox .v{font-size:1.6rem;font-weight:700}
.mbox .l{font-size:.72rem;color:#6b7280;margin-top:2px}

/* ── Pills ── */
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:.66rem;font-weight:600}
.p-req{background:#fff3e0;color:#c45c00}
.p-opt{background:#f1f3f5;color:#6b7280}
.p-pk{background:#e8f0fe;color:#1a56db}
.p-fk{background:#e6f4ea;color:#1e7e34}
.p-ok{background:#e6f4ea;color:#1e7e34}
.p-err{background:#fdecea;color:#c0392b}
.p-wrn{background:#fff8e1;color:#b7770d}

/* ── Sidebar steps ── */
.sstep{padding:5px 10px;border-radius:5px;margin-bottom:2px;font-size:.92rem}
.sstep.done{background:#e6f4ea;color:#1e7e34}
.sstep.active{background:#e8f0fe;color:#1a56db;font-weight:600}
.sstep.pending{color:#374151}

/* ── Inputs ── */
.stTextInput input,.stSelectbox select,.stTextArea textarea{
  background:#ffffff!important;color:#1a1f2e!important;
  border:1px solid #d1d9e6!important;border-radius:5px!important}

/* ── Buttons ── */
.stButton>button{background:#1a6fdb;color:#fff;border:none;
  font-weight:600;border-radius:6px;padding:6px 18px}
.stButton>button:hover{background:#1558b0}

/* ── Dataframes ── */
div[data-testid="stDataFrame"]{border:1px solid #dde3ed;
  border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.05)}

/* ── Sidebar background ── */
section[data-testid="stSidebar"]{background:#dbeafe;border-right:1px solid #bfdbfe}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════════════
STAGES = [
    "1 · Connect",
    "2 · Upload & Stage",
    "3 · Normalize",
    "4 · Select Target",
    "5 · Match & Map",
    "6 · FK Resolution",
    "7 · Validate",
    "8 · Promote",
]

DEFAULTS = dict(
    stage=0, engine=None, demo=False,
    source_df=None, staging_df=None, norm_df=None,
    ppdm_schema=None,
    agent_messages=[],   # chat history for AI assistant
    schema_variant="Schema 3.9",
    target_table=None, target_cols=None,
    col_mapping=None,
    mapping_grid_snapshot=None,  # frozen grid df — rebuilt on Apply/Reset only
    fk_constraints=None,       # list[FKConstraint] from DB introspection
    fk_parent_pks=None,        # {schema.table: [pk_cols]}
    fk_violations=None,        # list[FKViolation] — reference table violations
    fk_entity_tables=None,     # [str] — entity table names in dependency order
    fk_entity_mappings=None,   # {table_name: EntityMapping}
    fk_entity_resolved=None,   # {table_name: bool}
    fk_samples_loaded=False,     # True once FK samples have been fetched
    fk_ref_context=None,        # {violation_idx: context_dict} for r_ tables
    fk_ref_edits=None,          # {violation_idx: [{pk: code, name: desc}]}
    fk_graph=None,              # [FKNode] unified dependency graph (all parent tables)
    fk_node_results=None,       # {table_name: {"rows": int, "action": str}}
    fk_success_dismissed=False, # True after user closes the success banner
    fk_checked=False,
    skip_indices=None,
    val_report=None, promoted=False,
    stg_name=None, src_filename=None,
    seed_catalog_path=r'seed_catalog\catalog\ppdm39_seed_catalog.json',
    seed_catalog=None,
    seed_selected=None,
    seed_results=None,
    seed_src_df=None,
    seed_src_name=None,
    seed_fk_order=None,
    seed_validations=None,
    show_splash=True,
    row_source_user='PPDM_LOADER',
    row_source='DATA_LOADER',   # fallback SOURCE value for all inserts
    last_error=None,
    last_error_stage=None,
    _rtm_expanded=False,
)

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# On a fresh browser session (not a rerun), reset RTM to closed.
if "_app_initialized" not in st.session_state:
    st.session_state["_rtm_expanded"]   = False
    st.session_state["_app_initialized"] = True

S = st.session_state

# ═══════════════════════════════════════════════════════════════════════
# ERROR REPORTING HELPER
# ═══════════════════════════════════════════════════════════════════════
import traceback as _traceback

def report_error(exc: Exception, stage: str = "Pipeline") -> None:
    """Store error in session state and pre-load AI chat with explanation request."""
    tb    = _traceback.format_exc()
    short = str(exc)
    S.last_error       = {"stage": stage, "message": short, "detail": tb}
    S.last_error_stage = stage
    prompt = (
        f"I encountered an error during **{stage}**:\n\n"
        f"```\n{short}\n```\n\n"
        f"<details><summary>Full traceback</summary>\n\n"
        f"```\n{tb.strip()}\n```\n</details>\n\n"
        f"Can you explain what went wrong and how I can fix it?"
    )
    S.agent_messages = [m for m in S.agent_messages if not m.get("_auto_error")]
    S.agent_messages.append({"role": "user", "content": prompt, "_auto_error": True})
    S["_chat_auto_expand"] = True


# ── Dev Resume: load pre-built state from pickle file if present ──────────────
import os as _os, pickle as _pickle
_RESUME_FILE = _os.path.join(_os.path.dirname(__file__), ".dev_resume.pkl")
if _os.path.exists(_RESUME_FILE) and S.stage == 0:
    try:
        with open(_RESUME_FILE, "rb") as _rf:
            _resume = _pickle.load(_rf)
        # Reconnect DB — engine can't be pickled so we rebuild it
        if "_resume_db_cfg" in _resume and _resume.get("engine") is None:
            _rcfg = _resume["_resume_db_cfg"]
            from modules.db import DBConfig, connect as _connect
            _rdb = DBConfig(
                server       = _rcfg["server"],
                database     = _rcfg["database"],
                driver       = _rcfg["driver"],
                windows_auth = _rcfg["windows_auth"],
                username     = _rcfg.get("username", ""),
                password     = _rcfg.get("password", ""),
            )
            _rresult = _connect(_rdb)
            if _rresult.ok:
                _resume["engine"] = _rresult.engine
        import pandas as _pd
        for _k, _v in _resume.items():
            # DataFrames were saved as CSV — reload them
            if isinstance(_v, str) and _v.startswith("__CSV__"):
                _csv_path = _v[7:]
                try:
                    _v = _pd.read_csv(_csv_path, encoding="utf-8-sig", dtype=object)
                    _os.remove(_csv_path)
                except Exception:
                    _v = _pd.DataFrame()
            S[_k] = _v
        _os.remove(_RESUME_FILE)   # consume once
        st.rerun()
    except Exception as _e:
        st.warning(f"Dev resume failed: {_e}")

# ── File-change guard: if source file changed since mapping was built, reset it ──
_cur_parse_key = getattr(S, "_stg_parse_key", None)
_map_parse_key = getattr(S, "_mapping_built_for_parse_key", None)
if (_cur_parse_key and _map_parse_key and
        _cur_parse_key != _map_parse_key and S.col_mapping is not None):
    S.col_mapping              = None
    S.fk_samples_loaded        = False
    S["mapping_grid_snapshot"] = None
    S._mapping_built_for_parse_key = None

# ─── sidebar mode: 'pipeline' or 'delete' ───────────────────────────
if 'app_mode' not in st.session_state:
    st.session_state['app_mode'] = 'pipeline'

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def shdr(title, desc=""):
    st.markdown(f'<div class="shdr"><h3>{title}</h3>'
                + (f'<p>{desc}</p>' if desc else '') + '</div>',
                unsafe_allow_html=True)

def pill(text, cls="p-opt"):
    return f'<span class="pill {cls}">{text}</span>'

def mrow(items):
    cols = st.columns(len(items))
    for c, (lbl, val, color) in zip(cols, items):
        c.markdown(f'<div class="mbox"><div class="v" style="color:{color}">{val}</div>'
                   f'<div class="l">{lbl}</div></div>', unsafe_allow_html=True)

def go():
    S.stage += 1
    st.rerun()

def back():
    S.stage = max(0, S.stage - 1)
    st.rerun()

def reset():
    for k, v in DEFAULTS.items():
        S[k] = v
    S["show_splash"] = False   # never show splash on restart
    st.rerun()

# ═══════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════
if S.get("show_splash", True):
    page_splash.render(S)
    st.stop()

# ── Load all pipeline modules now (past splash, paid once per worker) ──
# Python's import cache (sys.modules) makes subsequent calls near-instant.
_load_pipeline_modules()

with st.sidebar:
    st.markdown(f"### 🛢️ {S.schema_variant} Loader")
    if S.demo:
        st.markdown(pill("🧪 Demo Mode", "p-wrn"), unsafe_allow_html=True)
    elif S.engine:
        st.markdown(pill("● Connected", "p-ok"), unsafe_allow_html=True)

    # ── Schema variant ────────────────────────────────────────────
    _SCHEMA_PATHS = {
        "Schema 3.9":  r"schema_registry\ppdm_39_schema_domain.json",
        "Schema Lite": r"schema_registry\ppdm_lite_schema_domain.json",
    }
    # Migrate old session state values from before the rename
    _SCHEMA_MIGRATE = {"PPDM 3.9": "Schema 3.9", "PPDM Lite": "Schema Lite"}
    if S.schema_variant in _SCHEMA_MIGRATE:
        S.schema_variant = _SCHEMA_MIGRATE[S.schema_variant]

    @st.cache_data(show_spinner=False)
    def _load_schema_cached(path: str):
        import json as _json
        with open(path, encoding="utf-8") as _sf:
            return load_schema_from_dict(_json.load(_sf))

    _prev_variant = S.schema_variant
    S.schema_variant = st.selectbox(
        "Schema", list(_SCHEMA_PATHS.keys()), index=0, key="schema_variant_select",
    )
    if S.schema_variant != _prev_variant:
        try:
            S.ppdm_schema = _load_schema_cached(_SCHEMA_PATHS[S.schema_variant])
            st.toast(f"\u2705 {S.schema_variant} schema loaded")
        except FileNotFoundError:
            st.warning(f"Schema file not found:\n{_SCHEMA_PATHS[S.schema_variant]}")
            S.ppdm_schema = None
        except Exception as _e:
            st.warning(f"Could not load schema: {_e}")
            S.ppdm_schema = None
    if S.ppdm_schema is None:
        try:
            S.ppdm_schema = _load_schema_cached(_SCHEMA_PATHS[S.schema_variant])
        except Exception:
            pass

    _row_user = st.text_input(
        "Created/Changed By",
        value=S.row_source_user,
        key="row_source_user_input",
        help="Value written to ROW_CREATED_BY and ROW_CHANGED_BY on all inserts",
    )
    if _row_user != S.row_source_user:
        S.row_source_user = _row_user

    _row_source = st.text_input(
        "Data Source",
        value=S.row_source,
        key="row_source_input",
        help="Value written to SOURCE on all inserts when not present in the data. "
             "Data always takes priority; this overrides the 'DATA_LOADER' fallback.",
    )
    if _row_source != S.row_source:
        S.row_source = _row_source

    st.markdown("<hr style='margin:4px 0'>", unsafe_allow_html=True)
    for i, lbl in enumerate(STAGES):
        cls  = "done" if i < S.stage else ("active" if i == S.stage else "pending")
        icon = "✓" if i < S.stage else ("▶" if i == S.stage else "○")
        st.markdown(f'<div class="sstep {cls}">{icon} {lbl}</div>', unsafe_allow_html=True)
    if S.stage > 0:
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("↩ Restart"):
                reset()
        with col2:
            if S.stage > 1:
                if st.button("← Back"):
                    back()


    # ── Tools ─────────────────────────────────────────────────────
    st.markdown("---")
    st.caption("TOOLS")
    _rtm_open_flag = st.session_state.pop("_rtm_open", False)
    # Persist expander open state: set True on FK dispatch, keep True
    # while user is actively working, cleared only on explicit close.
    if _rtm_open_flag:
        st.session_state["_rtm_expanded"] = True
    _rtm_expanded = st.session_state.get("_rtm_expanded", False)
    # If opened from FK resolution, default to "From mapping" (if pipeline
    # mapping exists) or "Manual entry". Store intent before expander renders.
    if _rtm_open_flag:
        _has_pipeline_map = bool(
            getattr(S, "col_mapping", None)
            and getattr(getattr(S, "col_mapping", None), "source_columns", None)
        )
        st.session_state["rtm_src_mode"] = (
            "From mapping" if _has_pipeline_map else "Manual entry"
        )
    with st.expander("📋 Reference Table Manager", expanded=_rtm_expanded):
        # Track open state — if user manually collapses, clear it next rerun
        st.session_state["_rtm_expanded"] = True
        # All DB queries are inside the expander — only run when open
        if not S.engine:
            st.info("Connect to a database first.")
        else:
            from sqlalchemy import text as _rtm_text
            _rtm_schema = "dbo"
            _rtm_all = st.checkbox("Show all tables", key="rtm_all_tables", value=True)

            # Table list — cached in session state
            if "rtm_table_list" not in st.session_state:
                with S.engine.connect() as _con:
                    _tbl_rows = _con.execute(_rtm_text(
                        "SELECT t.name FROM sys.tables t "
                        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                        "WHERE s.name = 'dbo' ORDER BY t.name"
                    )).fetchall()
                st.session_state["rtm_table_list"] = [r[0] for r in _tbl_rows]
            _all_tables = st.session_state["rtm_table_list"]
            _ref_tables = [t for t in _all_tables if t.lower().startswith(("r_", "ra_"))]
            _table_list = _all_tables if _rtm_all else _ref_tables

            if st.button("🔄 Refresh table list", key="rtm_refresh_tables"):
                st.session_state.pop("rtm_table_list", None)
                st.rerun()

            if not _table_list:
                st.warning("No tables found.")
            else:
                # Apply pending table selection from FK Resolution
                _rtm_pending = st.session_state.pop("rtm_table_pending", None)
                if _rtm_pending:
                    _match = next((t for t in _table_list
                                   if t.lower() == _rtm_pending.lower()), None)
                    if _match:
                        st.session_state["rtm_table_select"] = _match
                        # Reset mode to "From mapping" (or Manual if no pipeline)
                        _has_pm = bool(
                            getattr(S, "col_mapping", None)
                            and getattr(getattr(S, "col_mapping", None), "source_columns", None)
                        )
                        st.session_state["rtm_src_mode"] = (
                            "From mapping" if _has_pm else "Manual entry"
                        )
                        # Clear FM grid state for the new table so it rebuilds fresh
                        _pending_key = f"rtm_{_match}"
                        st.session_state.pop(f"rtm_fmgrid_{_match}", None)
                        st.session_state.pop(f"rtm_fmgrid_sig_{_match}", None)
                        st.session_state.pop(f"rtm_fmpreview_{_match}", None)
                _rtm_tbl = st.selectbox("Table", _table_list, key="rtm_table_select")
                # Normalise to actual sys.tables case to fix silent introspection failures
                _rtm_tbl = next((t for t in _all_tables if t.lower() == _rtm_tbl.lower()), _rtm_tbl)
                _rtm_key = f"rtm_{_rtm_tbl}"

                # When opened from FK dispatch, default to "From mapping" if a
                # pipeline mapping exists, otherwise fall back to "Manual entry"
                # (handled above at expander open time via _rtm_expanded)
                _rtm_src = st.radio(
                    "Add rows from",
                    ["Manual entry", "From mapping", "CSV upload", "JSON upload", "CSV column extract"],
                    horizontal=True, key="rtm_src_mode"
                )

                # Introspect table — cached per table
                _rtm_cache_key = f"rtm_introspect_{_rtm_tbl}"
                if _rtm_cache_key not in st.session_state:
                    _col_sql = """
                        SELECT c.name, tp.name AS typ, c.is_nullable, c.is_identity,
                               CASE WHEN ic.column_id IS NOT NULL THEN 1 ELSE 0 END AS is_pk,
                               c.is_computed
                        FROM sys.columns c
                        JOIN sys.types tp ON tp.user_type_id = c.user_type_id
                        JOIN sys.tables t  ON t.object_id = c.object_id
                        JOIN sys.schemas s ON s.schema_id = t.schema_id
                        LEFT JOIN sys.indexes i
                               ON i.object_id = c.object_id AND i.is_primary_key = 1
                        LEFT JOIN sys.index_columns ic
                               ON ic.object_id = c.object_id
                              AND ic.index_id = i.index_id
                              AND ic.column_id = c.column_id
                        WHERE LOWER(t.name) = LOWER(:tbl) AND s.name = :sch ORDER BY c.column_id
                    """
                    _fk_sql = """
                        SELECT cc.name, pt.name, pc.name
                        FROM sys.foreign_keys fk
                        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
                        JOIN sys.tables ct  ON ct.object_id = fk.parent_object_id
                        JOIN sys.columns cc ON cc.object_id = fk.parent_object_id
                                           AND cc.column_id = fkc.parent_column_id
                        JOIN sys.tables pt  ON pt.object_id = fk.referenced_object_id
                        JOIN sys.columns pc ON pc.object_id = fk.referenced_object_id
                                           AND pc.column_id = fkc.referenced_column_id
                        JOIN sys.schemas s  ON s.schema_id = ct.schema_id
                        WHERE LOWER(ct.name) = LOWER(:tbl) AND s.name = :sch
                    """
                    with S.engine.connect() as _con:
                        _ci = _con.execute(_rtm_text(_col_sql),
                                           {"tbl": _rtm_tbl, "sch": _rtm_schema}).fetchall()
                        _fi = _con.execute(_rtm_text(_fk_sql),
                                           {"tbl": _rtm_tbl, "sch": _rtm_schema}).fetchall()
                    st.session_state[_rtm_cache_key] = (_ci, _fi)

                _rtm_cols, _rtm_fks = st.session_state[_rtm_cache_key]

                # Existing rows — separate cache, loaded on demand via button
                _rtm_ex_cache_key = f"rtm_existing_{_rtm_tbl}"
                _rtm_existing = []
                _rtm_ex_cols  = []
                if st.button("👁 Show existing rows", key=f"{_rtm_tbl}_show_ex"):
                    st.session_state.pop(_rtm_ex_cache_key, None)
                if _rtm_ex_cache_key in st.session_state:
                    _rtm_existing, _rtm_ex_cols = st.session_state[_rtm_ex_cache_key]
                elif f"{_rtm_tbl}_show_ex" in str(st.session_state):
                    with S.engine.connect() as _con:
                        _ex = _con.execute(_rtm_text(
                            f"SELECT TOP 200 * FROM [{_rtm_schema}].[{_rtm_tbl}] WITH (NOLOCK) ORDER BY (SELECT NULL)"
                        )).fetchall()
                        _ex_cols = list(_con.execute(_rtm_text(
                            f"SELECT TOP 0 * FROM [{_rtm_schema}].[{_rtm_tbl}]"
                        )).keys())
                    st.session_state[_rtm_ex_cache_key] = (_ex, _ex_cols)
                    _rtm_existing, _rtm_ex_cols = _ex, _ex_cols
                # DEBUG — remove after fix
                if not _rtm_cols:
                    st.error(f"⛔ DEBUG: Introspection returned 0 columns for `{_rtm_tbl}` (schema={_rtm_schema}). Cache key: {_rtm_cache_key}")
                else:
                    st.caption(f"DEBUG: {len(_rtm_cols)} columns introspected for `{_rtm_tbl}`")

                if st.button("🔄 Refresh table data", key=f"{_rtm_key}_refresh"):
                    # Clear introspect cache
                    st.session_state.pop(_rtm_cache_key, None)
                    # Clear FK parent value caches, FK opts, and child table cache
                    for _k in list(st.session_state.keys()):
                        if _k.startswith("rtm_parvals_") or _k.startswith("rtm_fkopts_") \
                                or _k.startswith("rtm_childtbls_"):
                            st.session_state.pop(_k, None)
                    st.rerun()

                _AUDIT_SET = {"ROW_CHANGED_BY","ROW_CHANGED_DATE","ROW_CREATED_BY",
                              "ROW_CREATED_DATE","ROW_EFFECTIVE_DATE","ROW_EXPIRY_DATE",
                              "PPDM_GUID","ROW_QUALITY","ACTIVE_IND"}
                # SOURCE is excluded from AUDIT_SET — it's a PK on many tables
                _rtm_pk_cols  = [r[0] for r in _rtm_cols if r[4]]
                _rtm_col_meta = {r[0].upper(): {"name": r[0], "type": r[1],
                                                 "nullable": bool(r[2]), "identity": bool(r[3]),
                                                 "is_pk": bool(r[4]),
                                                 "computed": bool(r[5]) if len(r) > 5 else False} for r in _rtm_cols}
                _rtm_fk_map   = {r[0].upper(): (r[1], r[2]) for r in _rtm_fks}
                _edit_cols    = [r[0] for r in _rtm_cols
                                 if not r[3]                           # not identity
                                 and not (r[5] if len(r) > 5 else False)  # not computed
                                 and r[0].upper() not in _AUDIT_SET]

                # FK dropdown options — loaded lazily only for manual entry
                _rtm_fk_opts = {}
                _fk_opts_key = f"rtm_fkopts_{_rtm_tbl}"
                if _rtm_src == "Manual entry":
                    if _fk_opts_key not in st.session_state:
                        _opts_dict = {}
                        for _fc_upper, (_ptbl, _pcol) in _rtm_fk_map.items():
                            try:
                                with S.engine.connect() as _con:
                                    _orows = _con.execute(_rtm_text(
                                        f"SELECT DISTINCT TOP 500 [{_pcol}] "
                                        f"FROM [dbo].[{_ptbl}] WITH (NOLOCK) ORDER BY 1"
                                    )).fetchall()
                                _opts_dict[_fc_upper] = [str(r[0]) for r in _orows if r[0]]
                            except Exception:
                                _opts_dict[_fc_upper] = []
                        st.session_state[_fk_opts_key] = _opts_dict
                    _rtm_fk_opts = st.session_state[_fk_opts_key]

                # Existing rows
                if _rtm_existing:
                    with st.expander(f"{len(_rtm_existing)} existing row(s)", expanded=False):
                        _ex_df = pd.DataFrame(_rtm_existing, columns=_rtm_ex_cols)
                        _show_cols = [c for c in _rtm_ex_cols if c.upper() not in
                                      {"ROW_CHANGED_DATE","ROW_CREATED_DATE",
                                       "ROW_EFFECTIVE_DATE","ROW_EXPIRY_DATE","PPDM_GUID"}]
                        st.dataframe(_ex_df[_show_cols],
                                     hide_index=True,
                                     height=min(35*len(_rtm_existing)+38, 250))

                # Rows to insert
                _rtm_rows_to_insert = []
                if _rtm_src == "Manual entry":
                    st.markdown("**Enter new rows:**")

                    _edit_cols_set   = set(_edit_cols)
                    _edit_cols_upper = {c.upper(): c for c in _edit_cols}
                    _editor_key      = f"{_rtm_key}_editor"
                    _rows_key        = f"{_rtm_key}_rows"

                    # ── Initialise session state grid (once per table) ──────
                    if _rows_key not in st.session_state:
                        _blank = {c: "" for c in _edit_cols}
                        st.session_state[_rows_key] = [_blank]

                    # ── Sanitise stored rows (remove stale/mismatched keys) ─
                    for _r in st.session_state[_rows_key]:
                        _r.pop("🗑 Delete", None)
                        for _k in list(_r.keys()):
                            _canon = _edit_cols_upper.get(_k.upper())
                            if _canon and _canon != _k:
                                _r[_canon] = _r.pop(_k)
                        for _stale in [k for k in list(_r.keys()) if k not in _edit_cols_set]:
                            _r.pop(_stale, None)

                    # ── Column config ───────────────────────────────────────
                    _rtm_col_cfg = {}
                    for _ec in _edit_cols:
                        _ec_upper = _ec.upper()
                        _is_pk = _rtm_col_meta.get(_ec_upper, {}).get("is_pk", False)
                        if _ec_upper in _rtm_fk_opts and _rtm_fk_opts[_ec_upper]:
                            _rtm_col_cfg[_ec] = st.column_config.SelectboxColumn(
                                _ec, options=_rtm_fk_opts[_ec_upper], required=_is_pk)
                        else:
                            _rtm_col_cfg[_ec] = st.column_config.TextColumn(_ec, required=_is_pk)

                    # ── Render editor — Streamlit owns the data via the key ─
                    # Passing a plain list (not a rebuilt DataFrame) means
                    # Streamlit does NOT reset the editor on rerun.
                    _edited_rtm = st.data_editor(
                        st.session_state[_rows_key],
                        column_config=_rtm_col_cfg,
                        column_order=_edit_cols,
                        hide_index=False,
                        num_rows="fixed",
                        key=_editor_key,
                    )

                    # ── Buttons ─────────────────────────────────────────────
                    _btn_c1, _btn_c2 = st.columns([1, 1])
                    with _btn_c1:
                        if st.button("➕ Add row", key=f"{_rtm_key}_addrow"):
                            # Capture current editor state before appending
                            st.session_state[_rows_key] = (
                                _edited_rtm.to_dict("records")
                                if hasattr(_edited_rtm, "to_dict")
                                else list(_edited_rtm)
                            )
                            st.session_state[_rows_key].append(
                                {c: "" for c in _edit_cols})
                            # Clear editor widget so it redraws with new row count
                            st.session_state.pop(_editor_key, None)
                            st.rerun()
                    with _btn_c2:
                        if st.button("✔ Apply rows", key=f"{_rtm_key}_apply",
                                     help="Commit grid edits before inserting"):
                            st.session_state[_rows_key] = (
                                _edited_rtm.to_dict("records")
                                if hasattr(_edited_rtm, "to_dict")
                                else list(_edited_rtm)
                            )
                            st.rerun()

                    # ── Delete rows ─────────────────────────────────────────
                    _n_rows = len(st.session_state[_rows_key])
                    if _n_rows > 1:
                        _del_idx = st.multiselect(
                            "Delete rows (select by index)",
                            options=list(range(_n_rows)),
                            key=f"{_rtm_key}_delidx",
                            placeholder="Select row numbers to delete…"
                        )
                        if _del_idx and st.button("🗑 Delete selected rows",
                                                   key=f"{_rtm_key}_delrow"):
                            st.session_state[_rows_key] = [
                                r for i, r in enumerate(st.session_state[_rows_key])
                                if i not in _del_idx
                            ] or [{c: "" for c in _edit_cols}]
                            st.session_state.pop(_editor_key, None)
                            st.rerun()

                    # ── Rows available for insert ───────────────────────────
                    # Read from the live editor return value so insert always
                    # uses whatever is currently visible in the grid.
                    _live_rows = (
                        _edited_rtm.to_dict("records")
                        if hasattr(_edited_rtm, "to_dict")
                        else list(_edited_rtm)
                    )
                    _rtm_rows_to_insert = [
                        {k: (None if (v is None or str(v).strip() == "" or str(v).strip().lower() == "none") else v)
                         for k, v in _r.items() if k in _edit_cols_set}
                        for _r in _live_rows
                        if any(str(v).strip() and str(v).strip().lower() != "none"
                               for v in _r.values())
                        and all(
                            str(_r.get(pc, "") or "").strip()
                            and str(_r.get(pc, "") or "").strip().lower() != "none"
                            for pc in _rtm_pk_cols
                        )
                    ]

                elif _rtm_src == "From mapping":
                    # ── Match & Map from pipeline mapping columns ─────────────
                    # Source column list = pipeline Stage 5 source columns.
                    # Auto-match: exact name only (case-insensitive) → skip if no match.
                    # Falls back to Manual entry notice when no pipeline mapping exists.
                    _fm_cmap     = getattr(S, "col_mapping", None)
                    _fm_src_cols = (list(_fm_cmap.source_columns)
                                    if _fm_cmap and _fm_cmap.source_columns else [])

                    if not _fm_src_cols:
                        st.info(
                            "No pipeline mapping found. Complete Stages 2–5 first, "
                            "or use **Manual entry** to add rows directly."
                        )
                    else:
                        _FM_SKIP       = "— skip —"
                        _FM_XFORMS     = ["— none —", "UPPER", "LOWER", "TRIM", "SHA1_20", "SHA1_40"]
                        _fm_grid_key   = f"rtm_fmgrid_{_rtm_tbl}"
                        _fm_preview_key= f"rtm_fmpreview_{_rtm_tbl}"
                        _fm_grid_ver_k = f"rtm_fmgrid_ver_{_rtm_tbl}"
                        _fm_sig_key    = f"rtm_fmgrid_sig_{_rtm_tbl}"
                        _fm_src_upper  = {c.upper(): c for c in _fm_src_cols}
                        _col_opts_fm   = [_FM_SKIP] + _fm_src_cols

                        # Stage 5 mapping lookup: ppdm_col.upper() → source_col
                        _fm_stage5 = {
                            m.ppdm_col.upper(): m.source_col
                            for m in (_fm_cmap.mapped if _fm_cmap else [])
                            if m.source_col and not m.auto_generated
                        }

                        # Signature: rebuilds grid when source cols, target table,
                        # OR the Stage 5 mapping changes (e.g. after restore from disk)
                        _fm_map_sig = "|".join(sorted(
                            f"{k}={v}" for k, v in _fm_stage5.items()
                        ))
                        _fm_sig = f"{_rtm_tbl}|{','.join(sorted(_fm_src_cols))}|{_fm_map_sig}"

                        if _fm_grid_ver_k not in st.session_state:
                            st.session_state[_fm_grid_ver_k] = 0

                        # ── RTM fingerprint — keyed by target table + source cols ──
                        import hashlib as _rtm_hl, json as _rtm_json
                        from pathlib import Path as _rtm_Path
                        _rtm_cache_file = _rtm_Path(__file__).parent / "modules" / "mapping_cache.json"

                        def _rtm_fp():
                            _key = f"RTM:{_rtm_tbl.upper()}|{','.join(sorted(c.upper() for c in _fm_src_cols))}"
                            return "RTM_" + _rtm_hl.sha256(_key.encode()).hexdigest()[:16]

                        def _rtm_load_cache():
                            try:
                                if _rtm_cache_file.exists():
                                    return _rtm_json.loads(_rtm_cache_file.read_text(encoding="utf-8"))
                            except Exception:
                                pass
                            return {}

                        def _rtm_save_cache(fp, rows):
                            try:
                                cache = _rtm_load_cache()
                                # Save only rows with a source col or constant set
                                cache[fp] = [
                                    r for r in rows
                                    if r.get("Source Column", _FM_SKIP) != _FM_SKIP
                                    or str(r.get("Constant", "")).strip()
                                ]
                                _rtm_cache_file.write_text(
                                    _rtm_json.dumps(cache, indent=2, ensure_ascii=False),
                                    encoding="utf-8")
                            except Exception as _rce:
                                st.warning(f"RTM mapping save failed: {_rce}")

                        def _rtm_restore_cache(fp, rows):
                            """Overlay saved mapping onto freshly built grid rows."""
                            cache = _rtm_load_cache()
                            saved = cache.get(fp)
                            if not saved:
                                return rows, 0
                            # Support both old "PPDM Column" and new "Target Column" cache keys
                            _saved_map = {
                                r.get("Target Column", r.get("PPDM Column", "")): r for r in saved
                            }
                            _restored = 0
                            for row in rows:
                                _row_key = row.get("Target Column", row.get("PPDM Column", ""))
                                _saved = _saved_map.get(_row_key)
                                if not _saved:
                                    continue
                                _src = _saved.get("Source Column", _FM_SKIP)
                                # Only restore if source col still exists
                                if _src != _FM_SKIP and _src not in _fm_src_cols:
                                    _src = _FM_SKIP
                                row["Source Column"] = _src
                                row["Transform"]     = _saved.get("Transform", "— none —")
                                row["Constant"]      = _saved.get("Constant", "")
                                if _src != _FM_SKIP or row["Constant"]:
                                    _restored += 1
                            return rows, _restored

                        _fm_fp = _rtm_fp()

                        def _build_fm_grid():
                            _rows = []
                            for _ec in _edit_cols:
                                _ec_upper = _ec.upper()
                                _meta     = _rtm_col_meta.get(_ec_upper, {})
                                _is_pk    = _meta.get("is_pk", False)
                                # Exact match only: stage5 mapping first,
                                # then direct name match, else skip
                                _stage5_src = _fm_stage5.get(_ec_upper, "")
                                if _stage5_src and _stage5_src in _fm_src_cols:
                                    _auto_src = _stage5_src
                                elif _ec_upper in _fm_src_upper:
                                    _auto_src = _fm_src_upper[_ec_upper]
                                else:
                                    _auto_src = _FM_SKIP
                                _rows.append({
                                    "Target Column":   ("🔑 " if _is_pk else "   ") + _ec,
                                    "Source Column": _auto_src,
                                    "Transform":     "— none —",
                                    "Constant":      "",
                                })
                            return _rows

                        # Rebuild grid when source cols, target table, or mapping changes
                        if (st.session_state.get(_fm_sig_key) != _fm_sig
                                or _fm_grid_key not in st.session_state):
                            _new_rows = _build_fm_grid()
                            _new_rows, _n_rtm_restored = _rtm_restore_cache(_fm_fp, _new_rows)
                            st.session_state[_fm_grid_key]   = _new_rows
                            st.session_state[_fm_sig_key]    = _fm_sig
                            st.session_state[_fm_grid_ver_k] = (
                                st.session_state[_fm_grid_ver_k] + 1)
                            st.session_state.pop(_fm_preview_key, None)
                            if _n_rtm_restored:
                                st.toast(f"↩ RTM mapping restored ({_n_rtm_restored} column(s))", icon="✅")

                        # ── Warning banner: required cols still on skip ────────
                        _fm_req_unmapped = [
                            row["Target Column"].lstrip("🔑 ").strip()
                            for row in st.session_state[_fm_grid_key]
                            if _rtm_col_meta.get(
                                row["Target Column"].lstrip("🔑 ").strip().upper(), {}
                            ).get("is_pk", False)
                            or not _rtm_col_meta.get(
                                row["Target Column"].lstrip("🔑 ").strip().upper(), {}
                            ).get("nullable", True)
                            if row["Source Column"] == _FM_SKIP
                            and not str(row.get("Constant", "")).strip()
                        ]
                        if _fm_req_unmapped:
                            st.warning(
                                f"⚠️ {len(_fm_req_unmapped)} required column(s) not yet "
                                f"mapped: `{'`, `'.join(_fm_req_unmapped)}`"
                            )

                        # ── Audit info ─────────────────────────────────────────
                        _n_audit_fm = len([
                            c for c in _rtm_cols if c[0].upper() in _AUDIT_SET])
                        if _n_audit_fm:
                            st.info(
                                f"ℹ️ {_n_audit_fm} audit column(s) (PPDM_GUID, "
                                f"ROW_CREATED_BY, ACTIVE_IND, etc.) are auto-filled "
                                f"by the app and excluded from this grid."
                            )

                        # ── Toolbar: ⚡ Match All | ✖ Clear All ───────────────
                        _fm_tb1, _fm_tb2, _ = st.columns([1, 1, 3])
                        with _fm_tb1:
                            if st.button("⚡ Match All", key=f"{_rtm_key}_fm_match",
                                         use_container_width=True,
                                         help="Re-run exact auto-match for all columns"):
                                st.session_state[_fm_grid_key]   = _build_fm_grid()
                                st.session_state[_fm_grid_ver_k] += 1
                                st.session_state.pop(_fm_preview_key, None)
                                st.rerun()
                        with _fm_tb2:
                            if st.button("✖ Clear All", key=f"{_rtm_key}_fm_clear",
                                         use_container_width=True,
                                         help="Reset all source columns to — skip —"):
                                for _row in st.session_state[_fm_grid_key]:
                                    _row["Source Column"] = _FM_SKIP
                                    _row["Transform"]     = "— none —"
                                    _row["Constant"]      = ""
                                st.session_state[_fm_grid_ver_k] += 1
                                st.session_state.pop(_fm_preview_key, None)
                                st.rerun()

                        # ── Mapping grid ───────────────────────────────────────
                        _fm_grid_df = pd.DataFrame(st.session_state[_fm_grid_key])
                        _fm_editor_key = (f"{_rtm_key}_fm_editor_"
                                          f"v{st.session_state[_fm_grid_ver_k]}")
                        _fm_edited = st.data_editor(
                            _fm_grid_df,
                            column_config={
                                "Target Column": st.column_config.TextColumn(
                                    "Target Column", disabled=True, width="medium"),
                                "Source Column": st.column_config.SelectboxColumn(
                                    "Source Column",
                                    options=_col_opts_fm,
                                    width="medium"),
                                "Transform": st.column_config.SelectboxColumn(
                                    "Transform",
                                    options=_FM_XFORMS,
                                    width="small"),
                                "Constant": st.column_config.TextColumn(
                                    "Constant", width="small",
                                    help="Used only when Source Column is '— skip —'"),
                            },
                            disabled=["Target Column"],
                            use_container_width=True,
                            hide_index=True,
                            num_rows="fixed",
                            key=_fm_editor_key,
                            height=min(35 * len(_edit_cols) + 38, 400),
                        )

                        # ── Apply + Refresh Preview buttons ────────────────────
                        _fm_ap1, _fm_ap2 = st.columns([1, 1])
                        with _fm_ap1:
                            _fm_apply = st.button(
                                "✔ Apply mapping", key=f"{_rtm_key}_fm_apply",
                                use_container_width=True)
                        with _fm_ap2:
                            _fm_refresh = st.button(
                                "🔍 Refresh Preview", key=f"{_rtm_key}_fm_preview_btn",
                                use_container_width=True)

                        if _fm_apply:
                            _applied_rows = _fm_edited.to_dict("records")
                            st.session_state[_fm_grid_key]   = _applied_rows
                            st.session_state[_fm_grid_ver_k] += 1
                            _rtm_save_cache(_fm_fp, _applied_rows)
                            st.toast("💾 RTM mapping saved", icon="✅")
                            st.rerun()

                        # ── Build preview on demand ────────────────────────────
                        if _fm_refresh:
                            # Commit live edits first
                            st.session_state[_fm_grid_key] = _fm_edited.to_dict("records")
                            _df_pipeline = (
                                S.norm_df if S.norm_df is not None
                                else S.staging_df if S.staging_df is not None
                                else None
                            )
                            if _df_pipeline is None or _df_pipeline.empty:
                                st.error("No pipeline data in session — complete Stages 2–3 first.")
                            else:
                                import hashlib as _hl
                                def _fm_apply_xform(series, xform):
                                    if xform == "UPPER":   return series.str.upper()
                                    if xform == "LOWER":   return series.str.lower()
                                    if xform == "TRIM":    return series.str.strip()
                                    if xform == "SHA1_20":
                                        return series.apply(
                                            lambda v: _hl.sha1(str(v).encode()).hexdigest()[:20].upper()
                                            if str(v).strip() else v)
                                    if xform == "SHA1_40":
                                        return series.apply(
                                            lambda v: _hl.sha1(str(v).encode()).hexdigest().upper()
                                            if str(v).strip() else v)
                                    return series

                                _fm_mapped_cols = {}
                                for _grow in st.session_state[_fm_grid_key]:
                                    _ec_clean = _grow["Target Column"].lstrip("🔑 ").strip()
                                    _src_col  = _grow["Source Column"]
                                    _xform    = _grow["Transform"]
                                    _const    = str(_grow.get("Constant") or "").strip()
                                    if (_src_col and _src_col != _FM_SKIP
                                            and _src_col in _df_pipeline.columns):
                                        _series = _df_pipeline[_src_col].astype(str).str.strip()
                                        if _xform and _xform != "— none —":
                                            _series = _fm_apply_xform(_series, _xform)
                                        _fm_mapped_cols[_ec_clean] = _series
                                    elif _const:
                                        _series = pd.Series(
                                            [_const] * len(_df_pipeline), dtype=str)
                                        if _xform and _xform != "— none —":
                                            _series = _fm_apply_xform(_series, _xform)
                                        _fm_mapped_cols[_ec_clean] = _series

                                if _fm_mapped_cols:
                                    _fm_prev = pd.DataFrame(_fm_mapped_cols)
                                    # Drop rows where any PK col is blank
                                    _fm_pk_mapped = [
                                        c for c in _fm_mapped_cols
                                        if _rtm_col_meta.get(c.upper(), {}).get("is_pk", False)
                                    ]
                                    if _fm_pk_mapped:
                                        _fm_pk_mask = _fm_prev[_fm_pk_mapped].apply(
                                            lambda col: col.str.strip().ne(""), axis=0
                                        ).all(axis=1)
                                        _fm_prev = _fm_prev[_fm_pk_mask]
                                    # SOURCE fallback
                                    if "SOURCE" in {c.upper() for c in _fm_mapped_cols}:
                                        _sc5 = next(
                                            c for c in _fm_mapped_cols if c.upper() == "SOURCE")
                                        if _fm_prev[_sc5].eq("").all():
                                            _fm_prev[_sc5] = S.row_source or "DATA_LOADER"
                                    _fm_prev = _fm_prev.drop_duplicates().reset_index(drop=True)
                                    st.session_state[_fm_preview_key] = _fm_prev
                                else:
                                    st.session_state[_fm_preview_key] = pd.DataFrame()
                            st.rerun()

                        # ── Show cached preview ────────────────────────────────
                        if _fm_preview_key in st.session_state:
                            _fm_prev_df = st.session_state[_fm_preview_key]
                            if _fm_prev_df.empty:
                                st.info("No rows generated — map at least one column and refresh.")
                            else:
                                st.markdown(
                                    f"**Preview — {len(_fm_prev_df)} distinct row(s) to insert:**")
                                st.dataframe(
                                    _fm_prev_df,
                                    hide_index=True,
                                    height=min(35 * len(_fm_prev_df) + 38, 300),
                                )
                                _rtm_rows_to_insert = _fm_prev_df.to_dict("records")
                                st.session_state.pop(f"{_rtm_key}_last_msg", None)
                                st.session_state.pop(f"{_rtm_key}_skip_reasons", None)
                        else:
                            st.info("Configure mapping above then click **🔍 Refresh Preview**.")

                elif _rtm_src == "CSV upload":
                    _stg_fname = getattr(S, "_stg_filename", "") or ""
                    if _stg_fname:
                        st.caption(
                            "📂 Source file: **" + _stg_fname + "** — "
                            "upload it below or drag it in from your file manager."
                        )
                    _rtm_csv = st.file_uploader("Upload CSV", type=["csv"],
                                                  key=f"{_rtm_key}_csv")
                    if _rtm_csv:
                        import io as _io
                        _csv_df = pd.read_csv(_io.BytesIO(_rtm_csv.read()),
                                               dtype=str, encoding="utf-8-sig").fillna("")
                        st.dataframe(_csv_df, hide_index=True,
                                     height=min(35*len(_csv_df)+38, 200))
                        st.caption(f"{len(_csv_df)} row(s) ready.")
                        _rtm_rows_to_insert = _csv_df.to_dict("records")
                        # Clear previous result message when new file loaded
                        st.session_state.pop(f"{_rtm_key}_last_msg", None)
                        st.session_state.pop(f"{_rtm_key}_skip_reasons", None)

                elif _rtm_src == "JSON upload":
                    _rtm_json = st.file_uploader("Upload JSON (array of objects)",
                                                   type=["json"], key=f"{_rtm_key}_json")
                    if _rtm_json:
                        import json as _json_mod, io as _io
                        _json_data = _json_mod.load(_io.TextIOWrapper(_rtm_json))
                        # Accept plain array [...] or wrapped object {rows: [...]}
                        if isinstance(_json_data, dict) and "rows" in _json_data:
                            _json_data = _json_data["rows"]
                        if isinstance(_json_data, list):
                            _json_df = pd.DataFrame(_json_data).fillna("").astype(str)
                            st.dataframe(_json_df, hide_index=True,
                                         height=min(35*len(_json_df)+38, 200))
                            st.caption(f"{len(_json_df)} row(s) ready.")
                            _rtm_rows_to_insert = _json_df.to_dict("records")
                            # Clear previous result message when new file loaded
                            st.session_state.pop(f"{_rtm_key}_last_msg", None)
                            st.session_state.pop(f"{_rtm_key}_skip_reasons", None)
                        else:
                            st.error("JSON must be an array of objects: [{...}, {...}]")

                elif _rtm_src == "CSV column extract":
                    import io as _io, difflib as _dl, hashlib as _hl

                    # ── Transform helpers ──────────────────────────────────────
                    _XFORM_OPTIONS = ["— none —", "UPPER", "LOWER", "TRIM", "SHA1_20", "SHA1_40"]

                    def _apply_xform(series, xform):
                        """Apply a named transform to a pandas Series of strings."""
                        if xform == "UPPER":
                            return series.str.upper()
                        elif xform == "LOWER":
                            return series.str.lower()
                        elif xform == "TRIM":
                            return series.str.strip()
                        elif xform == "SHA1_20":
                            return series.apply(
                                lambda v: _hl.sha1(str(v).encode()).hexdigest()[:20].upper()
                                if str(v).strip() else v
                            )
                        elif xform == "SHA1_40":
                            return series.apply(
                                lambda v: _hl.sha1(str(v).encode()).hexdigest().upper()
                                if str(v).strip() else v
                            )
                        return series

                    # ── File uploader ──────────────────────────────────────────
                    _rtm_extract_file = st.file_uploader(
                        "Upload source CSV/Excel", type=["csv", "xlsx", "xls"],
                        key=f"{_rtm_key}_extract_file"
                    )

                    if _rtm_extract_file:
                        # ── Load file ─────────────────────────────────────────
                        _ext = _rtm_extract_file.name.rsplit(".", 1)[-1].lower()
                        _file_bytes = _rtm_extract_file.read()
                        if _ext == "csv":
                            _src_df = pd.read_csv(
                                _io.BytesIO(_file_bytes), dtype=str, encoding="utf-8-sig"
                            ).fillna("")
                        else:
                            _src_df = pd.read_excel(
                                _io.BytesIO(_file_bytes), dtype=str
                            ).fillna("")
                        _src_cols = list(_src_df.columns)
                        st.caption(f"{len(_src_df):,} rows · {len(_src_cols)} columns — {_rtm_extract_file.name}")

                        # ── Auto-suggest by fuzzy name match ──────────────────
                        def _best_match(ppdm_col, candidates):
                            hits = _dl.get_close_matches(
                                ppdm_col.lower(),
                                [c.lower() for c in candidates],
                                n=1, cutoff=0.4
                            )
                            if hits:
                                return candidates[[c.lower() for c in candidates].index(hits[0])]
                            return None

                        # ── Build initial grid state (snapshot keyed to file+table) ──
                        _grid_state_key = f"{_rtm_key}_xgrid"
                        _src_file_sig   = f"{_rtm_extract_file.name}_{len(_src_df)}"
                        _grid_sig_key   = f"{_rtm_key}_xgrid_sig"

                        _col_opts_for_grid = ["— skip —"] + _src_cols

                        if (st.session_state.get(_grid_sig_key) != _src_file_sig
                                or _grid_state_key not in st.session_state):
                            # Build default rows — one row per edit col
                            _default_rows = []
                            for _ec in _edit_cols:
                                _ec_upper = _ec.upper()
                                _is_pk    = _rtm_col_meta.get(_ec_upper, {}).get("is_pk", False)
                                _sugg     = _best_match(_ec, _src_cols)
                                _default_rows.append({
                                    "Target Column": ("🔑 " if _is_pk else "   ") + _ec,
                                    "Source Column": _sugg if _sugg else "— skip —",
                                    "Transform":     "— none —",
                                    "Constant":      "",
                                })
                            st.session_state[_grid_state_key] = _default_rows
                            st.session_state[_grid_sig_key]   = _src_file_sig

                        # ── Editor version counter — bump to force widget re-render ──
                        _grid_ver_key = f"{_rtm_key}_xgrid_ver"
                        if _grid_ver_key not in st.session_state:
                            st.session_state[_grid_ver_key] = 0

                        # ── Toolbar: Match All | Clear All ────────────────────
                        _tb1, _tb2, _tb3 = st.columns([1, 1, 3])
                        with _tb1:
                            if st.button("⚡ Match All", key=f"{_rtm_key}_match_all",
                                         help="Auto-suggest best source column for every target column"):
                                for _row in st.session_state[_grid_state_key]:
                                    _ec_clean = _row["Target Column"].lstrip("🔑 ").strip()
                                    _s = _best_match(_ec_clean, _src_cols)
                                    _row["Source Column"] = _s if _s else "— skip —"
                                st.session_state[_grid_ver_key] += 1
                                st.rerun()
                        with _tb2:
                            if st.button("✖ Clear All", key=f"{_rtm_key}_clear_all",
                                         help="Reset all source column mappings to — skip —"):
                                for _row in st.session_state[_grid_state_key]:
                                    _row["Source Column"] = "— skip —"
                                    _row["Transform"]     = "— none —"
                                    _row["Constant"]      = ""
                                st.session_state[_grid_ver_key] += 1
                                st.rerun()

                        # ── Mapping grid ──────────────────────────────────────
                        _grid_df = pd.DataFrame(st.session_state[_grid_state_key])

                        _grid_col_cfg = {
                            "Target Column": st.column_config.TextColumn(
                                "Target Column", disabled=True, width="medium"),
                            "Source Column": st.column_config.SelectboxColumn(
                                "Source Column",
                                options=_col_opts_for_grid,
                                width="medium"),
                            "Transform": st.column_config.SelectboxColumn(
                                "Transform",
                                options=_XFORM_OPTIONS,
                                width="small"),
                            "Constant": st.column_config.TextColumn(
                                "Constant",
                                width="small",
                                help="Used only when Source Column is '— skip —'"),
                        }

                        # Version suffix forces Streamlit to discard stale widget state
                        _editor_key = f"{_rtm_key}_xgrid_editor_v{st.session_state[_grid_ver_key]}"

                        _edited_grid = st.data_editor(
                            _grid_df,
                            column_config=_grid_col_cfg,
                            hide_index=True,
                            num_rows="fixed",
                            key=_editor_key,
                            height=min(35 * len(_grid_df) + 38, 400),
                        )

                        # ── Apply grid + Refresh Preview ─────────────────────
                        _ap1, _ap2 = st.columns([1, 1])
                        with _ap1:
                            _apply_grid = st.button(
                                "✔ Apply mapping", key=f"{_rtm_key}_xgrid_apply",
                                help="Commit grid edits to session state")
                        with _ap2:
                            _refresh_preview = st.button(
                                "🔍 Refresh Preview", key=f"{_rtm_key}_xgrid_preview",
                                help="Build distinct rows from current mapping")

                        if _apply_grid:
                            st.session_state[_grid_state_key] = _edited_grid.to_dict("records")
                            st.session_state[_grid_ver_key] += 1
                            st.rerun()

                        # ── Build preview on demand ───────────────────────────
                        _preview_key = f"{_rtm_key}_xgrid_preview_df"

                        if _refresh_preview:
                            # Commit live edits first
                            st.session_state[_grid_state_key] = _edited_grid.to_dict("records")
                            # Build extract DataFrame from committed grid
                            _mapped_cols = {}
                            for _grow in st.session_state[_grid_state_key]:
                                _ec_raw   = _grow["Target Column"]
                                _ec_clean = _ec_raw.lstrip("🔑 ").strip()
                                _src_col  = _grow["Source Column"]
                                _xform    = _grow["Transform"]
                                _const    = str(_grow.get("Constant") or "").strip()

                                if _src_col and _src_col != "— skip —" and _src_col in _src_df.columns:
                                    # CSV column path — apply transform if set
                                    _series = _src_df[_src_col].astype(str).str.strip()
                                    if _xform and _xform != "— none —":
                                        _series = _apply_xform(_series, _xform)
                                    _mapped_cols[_ec_clean] = _series
                                elif _const:
                                    # Constant path — only when no source column mapped
                                    _series = pd.Series([_const] * len(_src_df), dtype=str)
                                    if _xform and _xform != "— none —":
                                        _series = _apply_xform(_series, _xform)
                                    _mapped_cols[_ec_clean] = _series
                                # else: skip

                            if _mapped_cols:
                                _prev_df = pd.DataFrame(_mapped_cols)

                                # Drop rows where any PK column is blank
                                _pk_mapped = [
                                    c for c in _mapped_cols
                                    if _rtm_col_meta.get(c.upper(), {}).get("is_pk", False)
                                ]
                                if _pk_mapped:
                                    _pk_mask = _prev_df[_pk_mapped].apply(
                                        lambda col: col.str.strip().ne(""), axis=0
                                    ).all(axis=1)
                                    _prev_df = _prev_df[_pk_mask]

                                # Distinct combinations
                                _prev_df = _prev_df.drop_duplicates().reset_index(drop=True)
                                st.session_state[_preview_key] = _prev_df
                            else:
                                st.session_state[_preview_key] = pd.DataFrame()
                            st.rerun()

                        # ── Show cached preview ───────────────────────────────
                        if _preview_key in st.session_state:
                            _prev_df = st.session_state[_preview_key]
                            if _prev_df.empty:
                                st.info("No rows generated — map at least one column and refresh.")
                            else:
                                st.markdown(f"**Preview — {len(_prev_df)} distinct row(s) to insert:**")
                                st.dataframe(
                                    _prev_df,
                                    hide_index=True,
                                    height=min(35 * len(_prev_df) + 38, 300),
                                )
                                _rtm_rows_to_insert = _prev_df.to_dict("records")
                                st.session_state.pop(f"{_rtm_key}_last_msg", None)
                                st.session_state.pop(f"{_rtm_key}_skip_reasons", None)
                        else:
                            st.info("Configure mapping above then click **🔍 Refresh Preview**.")

                _rtm_run_insert = False

                # Column name diagnostic — show mismatches before FK check
                if _rtm_rows_to_insert and _rtm_col_meta:
                    _csv_cols = set(_rtm_rows_to_insert[0].keys())
                    _tbl_cols = set(_rtm_col_meta.keys())
                    _matched  = {c for c in _csv_cols if c.upper() in _tbl_cols}
                    _unmatched = {c for c in _csv_cols if c.upper() not in _tbl_cols}
                    if _unmatched and not _matched:
                        st.error(
                            f"⛔ No CSV columns match `{_rtm_tbl}` — check column names. "
                            f"CSV has: {sorted(_csv_cols)}. "
                            f"Table expects columns like: {sorted(list(_tbl_cols)[:8])}"
                        )
                    elif _unmatched:
                        st.caption(f"ℹ {len(_matched)} column(s) matched, "
                                   f"{len(_unmatched)} unrecognised (will be ignored): "
                                   f"{sorted(_unmatched)}")

                # FK check — only runs when rows are loaded, cached per parent table
                _rtm_fk_violations = False
                if _rtm_fk_map and _rtm_rows_to_insert:
                    # Only check FK cols that actually appear in the data
                    _csv_cols_upper = {k.upper() for k in _rtm_rows_to_insert[0].keys()}
                    # Build set of child tables (tables that have a FK pointing TO _rtm_tbl)
                    # so we can skip reversed FK checks that would incorrectly block inserts
                    _child_tables_key = f"rtm_childtbls_{_rtm_tbl}"
                    if _child_tables_key not in st.session_state:
                        try:
                            with S.engine.connect() as _con:
                                _child_rows = _con.execute(_rtm_text("""
                                    SELECT DISTINCT ct.name
                                    FROM sys.foreign_keys fk
                                    JOIN sys.tables ct ON ct.object_id = fk.parent_object_id
                                    JOIN sys.tables pt ON pt.object_id = fk.referenced_object_id
                                    JOIN sys.schemas s ON s.schema_id = pt.schema_id
                                    WHERE LOWER(pt.name) = LOWER(:tbl) AND s.name = :sch
                                """), {"tbl": _rtm_tbl, "sch": _rtm_schema}).fetchall()
                            st.session_state[_child_tables_key] = {
                                r[0].lower() for r in _child_rows
                            }
                        except Exception:
                            st.session_state[_child_tables_key] = set()
                    _child_tables = st.session_state[_child_tables_key]
                    for _fc_upper, (_ptbl, _pcol) in _rtm_fk_map.items():
                        if _fc_upper not in _csv_cols_upper:
                            continue  # skip FK cols not in data
                        # Skip self-referencing FK — handled at insert time (two-pass)
                        if _ptbl.lower() == _rtm_tbl.lower():
                            continue
                        # Skip if _ptbl is a child of the current table — reversed FK,
                        # should never block inserting into the parent table
                        if _ptbl.lower() in _child_tables:
                            continue
                        _fc_orig = _rtm_col_meta.get(_fc_upper, {}).get("name", _fc_upper)
                        _incoming = {str(r.get(_fc_orig, r.get(_fc_upper, ""))).strip()
                                     for r in _rtm_rows_to_insert
                                     if r.get(_fc_orig) or r.get(_fc_upper)}
                        if _incoming:
                            # Cache parent values per parent table
                            _par_cache_key = f"rtm_parvals_{_ptbl}_{_pcol}"
                            if _par_cache_key not in st.session_state:
                                try:
                                    with S.engine.connect() as _con:
                                        st.session_state[_par_cache_key] = {
                                        str(r[0]).strip() for r in _con.execute(_rtm_text(
                                            f"SELECT [{_pcol}] FROM [dbo].[{_ptbl}] WITH (NOLOCK)"
                                        )).fetchall()
                                        if r[0] is not None
                                    }
                                except Exception:
                                    st.session_state[_par_cache_key] = set()
                            _missing_par = _incoming - st.session_state[_par_cache_key]
                            if _missing_par:
                                _rtm_fk_violations = True
                                st.warning(
                                    f"⚠ FK violation: `{_fc_orig}` → `{_ptbl}.{_pcol}` — "
                                    f"missing parent value(s): {', '.join(sorted(_missing_par))}. "
                                    f"Insert into `{_ptbl}` first."
                                )

                # Insert buttons — shown after FK check, blocked if violations
                if _rtm_rows_to_insert and not _rtm_fk_violations:
                    if _rtm_src == "CSV upload":
                        if st.button(f"📥 Insert {len(_rtm_rows_to_insert)} rows into {_rtm_tbl}",
                                     key=f"{_rtm_key}_csv_insert", type="primary"):
                            _rtm_run_insert = True
                    elif _rtm_src == "JSON upload":
                        if st.button(f"📥 Insert {len(_rtm_rows_to_insert)} rows into {_rtm_tbl}",
                                     key=f"{_rtm_key}_json_insert", type="primary"):
                            _rtm_run_insert = True
                    elif _rtm_src == "Manual entry":
                        if st.button(f"📥 Insert into {_rtm_tbl}",
                                     key=f"{_rtm_key}_manual_insert",
                                     type="primary"):
                            _rtm_run_insert = True
                    elif _rtm_src == "CSV column extract":
                        if st.button(f"📥 Insert {len(_rtm_rows_to_insert)} distinct rows into {_rtm_tbl}",
                                     key=f"{_rtm_key}_extract_insert", type="primary"):
                            _rtm_run_insert = True
                    elif _rtm_src == "From mapping":
                        if st.button(f"📥 Insert {len(_rtm_rows_to_insert)} rows into {_rtm_tbl}",
                                     key=f"{_rtm_key}_fm_insert", type="primary",
                                     use_container_width=True):
                            _rtm_run_insert = True
                elif _rtm_rows_to_insert and _rtm_fk_violations:
                    st.error("⛔ Resolve FK violations above before inserting.")

                # Show result from last insert
                if f"{_rtm_key}_last_msg" in st.session_state:
                    _last = st.session_state[f"{_rtm_key}_last_msg"]
                    if _last.startswith("✅"):
                        st.success(_last)
                    else:
                        st.error(_last)
                    for _r in st.session_state.get(f"{_rtm_key}_skip_reasons", []):
                        st.warning(f"⚠ Skipped — {_r}")

                if _rtm_run_insert:
                    if True:  # scope block
                        _AUDIT_EXPR_RTM = {
                            "ROW_CREATED_DATE":   "GETUTCDATE()",
                            "ROW_CHANGED_DATE":   "GETUTCDATE()",
                            "ROW_EFFECTIVE_DATE": "CAST('1900-01-01' AS DATETIME2)",
                            "ROW_EXPIRY_DATE":    "CAST('2099-12-31' AS DATETIME2)",
                            "PPDM_GUID":          "NEWID()",
                            "ACTIVE_IND":         "'Y'",
                            "ROW_CREATED_BY":     f"'{S.row_source_user or 'PPDM_LOADER'}'",
                            "ROW_CHANGED_BY":     f"'{S.row_source_user or 'PPDM_LOADER'}'",
                            # SOURCE excluded — must come from data (it's a PK)
                        }

                        # SOURCE fallback priority:
                        #   1. Value present in the data row  (highest)
                        #   2. S.row_source from sidebar      (user-defined)
                        #   3. "DATA_LOADER"                  (last resort)
                        _SOURCE_DEFAULT = S.row_source.strip() if S.row_source.strip() else "DATA_LOADER"

                        _rtm_ok = 0; _rtm_skip = 0; _rtm_dupes = 0
                        _rtm_skip_reasons = []

                        def _get_ci(row, col):
                            """Case-insensitive dict get."""
                            col_up = col.upper()
                            for k, v in row.items():
                                if k.upper() == col_up:
                                    return str(v or "").strip()
                            return ""

                        try:
                            # ── Step 1: validate rows in Python, build clean list ──
                            _clean_rows = []   # list of {col: val} dicts ready to insert
                            for _row_i, _row in enumerate(_rtm_rows_to_insert):
                                _valid_row = {
                                    k: v for k, v in _row.items()
                                    if k.upper() in _rtm_col_meta
                                }
                                if not _valid_row:
                                    _rtm_skip += 1
                                    _rtm_skip_reasons.append(
                                        f"Row {_row_i+1}: no valid column names found "
                                        f"(keys were: {list(_row.keys())[:5]})")
                                    continue
                                # Apply SOURCE fallback if SOURCE is a column on this
                                # table but the row has no value for it
                                if "SOURCE" in _rtm_col_meta:
                                    _src_key = next(
                                        (k for k in _valid_row if k.upper() == "SOURCE"), None)
                                    if _src_key is None:
                                        _valid_row["SOURCE"] = _SOURCE_DEFAULT
                                    elif not str(_valid_row[_src_key]).strip() \
                                            or str(_valid_row[_src_key]).strip().lower() == "none":
                                        _valid_row[_src_key] = _SOURCE_DEFAULT
                                # For self-referencing FK columns (e.g. ROW_SOURCE -> SOURCE):
                                # if blank, default to the row's own PK value so the row
                                # becomes its own parent (bootstrap). Runs after SOURCE fill.
                                for _sr_fk_up, (_sr_ptbl, _sr_pcol) in _rtm_fk_map.items():
                                    if _sr_ptbl.lower() != _rtm_tbl.lower():
                                        continue
                                    _sr_fk_key = next(
                                        (k for k in _valid_row if k.upper() == _sr_fk_up), None)
                                    _sr_fk_val = str(_valid_row.get(_sr_fk_key, "") or "").strip()
                                    if not _sr_fk_val or _sr_fk_val.lower() == "none":
                                        _sr_pk_key = next(
                                            (k for k in _valid_row if k.upper() == _sr_pcol.upper()), None)
                                        _sr_pk_val = str(_valid_row.get(_sr_pk_key, "") or "").strip()
                                        if _sr_pk_val:
                                            if _sr_fk_key:
                                                _valid_row[_sr_fk_key] = _sr_pk_val
                                            else:
                                                _sr_fk_name = _rtm_col_meta.get(_sr_fk_up, {}).get("name", _sr_fk_up)
                                                _valid_row[_sr_fk_name] = _sr_pk_val
                                # Check PK columns present (after SOURCE fill)
                                _missing_pks = [pc for pc in _rtm_pk_cols
                                                if not _get_ci(_valid_row, pc)
                                                or _get_ci(_valid_row, pc).lower() == "none"]
                                if _missing_pks:
                                    _rtm_skip += 1
                                    _rtm_skip_reasons.append(
                                        f"Row {_row_i+1}: missing required PK value(s): {_missing_pks}")
                                    continue
                                _clean_rows.append(_valid_row)

                            if not _clean_rows:
                                st.warning("⚠ No valid rows to insert — check column names match the target table.")
                                st.session_state[f"{_rtm_key}_last_msg"] = "⚠ No valid rows to insert."
                            if _clean_rows:
                                # ── Step 2: determine insert columns from first valid row ──
                                _ins_cols = []
                                for _col in _clean_rows[0].keys():
                                    _cu = _col.upper()
                                    if _cu in _AUDIT_SET and _cu not in {"ACTIVE_IND","ROW_CREATED_BY","ROW_CHANGED_BY"}:
                                        continue
                                    if _rtm_col_meta.get(_cu, {}).get("identity"):
                                        continue
                                    if _rtm_col_meta.get(_cu, {}).get("computed"):
                                        continue
                                    _ins_cols.append(_col)
                                    _ins_cols = list(dict.fromkeys(_ins_cols))  # prevent duplicate column names
                                # Add audit cols
                                _audit_cols = [ac for ac, _ in _AUDIT_EXPR_RTM.items()
                                               if ac.upper() in _rtm_col_meta
                                               and ac.upper() not in {c.upper() for c in _ins_cols}]

                                # ── Step 3: bulk load into temp table via pandas ──
                                import pandas as _rtm_pd
                                _tmp = f"#rtm_stage_{_rtm_tbl}"
                                _tmp_col_defs = ", ".join(
                                    f"[{c}] NVARCHAR(4000)" for c in _ins_cols
                                )
                                _pk_cols_upper = [p.upper() for p in _rtm_pk_cols]

                                with S.engine.begin() as _con:
                                    # Create temp staging table
                                    _con.execute(_rtm_text(
                                        f"IF OBJECT_ID('tempdb..{_tmp}') IS NOT NULL "
                                        f"DROP TABLE {_tmp}"
                                    ))
                                    _con.execute(_rtm_text(
                                        f"CREATE TABLE {_tmp} ({_tmp_col_defs})"
                                    ))
                                    # Batch size limited by ODBC 2100 param max
                                    _batch_size = max(1, min(500, 2000 // max(len(_ins_cols), 1)))
                                    for _bi in range(0, len(_clean_rows), _batch_size):
                                        _batch = _clean_rows[_bi:_bi+_batch_size]
                                        _val_rows = []
                                        _bp = {}
                                        _bpi = 0
                                        for _br in _batch:
                                            _rvals = []
                                            for _bc in _ins_cols:
                                                _bv = str(_br.get(_bc, "") or "").strip()
                                                _bk = f"b{_bpi}"
                                                _bp[_bk] = _bv if _bv.lower() != "none" else None
                                                _rvals.append(f":{_bk}")
                                                _bpi += 1
                                            _val_rows.append(f"({', '.join(_rvals)})")
                                        _con.execute(_rtm_text(
                                            f"INSERT INTO {_tmp} ([{'],['.join(_ins_cols)}]) "
                                            f"VALUES {', '.join(_val_rows)}"
                                        ), _bp)

                                    # ── Step 4: INSERT — two-pass for self-referencing tables ──
                                    # Detect self-referencing FK columns
                                    _self_ref_fks = [
                                        (_fc_up, _pcol2)
                                        for _fc_up, (_ptbl2, _pcol2) in _rtm_fk_map.items()
                                        if _ptbl2.lower() == _rtm_tbl.lower()
                                        and _fc_up in {c.upper() for c in _ins_cols}
                                    ]
                                    _audit_exprs = ", ".join(
                                        f"[{ac}] = {ae}" for ac, ae in _AUDIT_EXPR_RTM.items()
                                        if ac.upper() in _rtm_col_meta
                                        and ac.upper() not in {c.upper() for c in _ins_cols}
                                    )
                                    _col_list = ", ".join(f"[{c}]" for c in _ins_cols)
                                    _src_list = ", ".join(f"src.[{c}]" for c in _ins_cols)
                                    _pk_join  = " AND ".join(
                                        f"tgt.[{pc}] = src.[{pc}]" for pc in _rtm_pk_cols
                                    )
                                    _audit_col_sql = (
                                        f", {', '.join(f'[{ac}]' for ac, _ in _AUDIT_EXPR_RTM.items() if ac.upper() in _rtm_col_meta and ac.upper() not in {c.upper() for c in _ins_cols})}"
                                        if _audit_exprs else ""
                                    )
                                    _audit_val_sql = (
                                        f", {', '.join(ae for ac, ae in _AUDIT_EXPR_RTM.items() if ac.upper() in _rtm_col_meta and ac.upper() not in {c.upper() for c in _ins_cols})}"
                                        if _audit_exprs else ""
                                    )
                                    _insert_sql = (
                                        f"INSERT INTO [{_rtm_schema}].[{_rtm_tbl}] "
                                        f"({_col_list}{_audit_col_sql}) "
                                        f"SELECT {_src_list}{_audit_val_sql} "
                                        f"FROM {_tmp} src "
                                        f"WHERE NOT EXISTS ("
                                        f"SELECT 1 FROM [{_rtm_schema}].[{_rtm_tbl}] tgt "
                                        f"WHERE {_pk_join})"
                                    )
                                    if _self_ref_fks:
                                        _sr_fc = next(
                                            c for c in _ins_cols
                                            if c.upper() == _self_ref_fks[0][0]
                                        )
                                        _sr_pk = _rtm_pk_cols[0]

                                        # Pass 1: rows where the self-ref col points to
                                        # themselves (ROW_SOURCE == SOURCE) — insert these
                                        # first in committed transactions so they exist as
                                        # parents before Pass 2 runs.
                                        _bootstrap_rows = [
                                            r for r in _clean_rows
                                            if _get_ci(r, _sr_fc) == _get_ci(r, _sr_pk)
                                        ]
                                        # Pass 2: rows where self-ref col points to a
                                        # *different* existing row — handled via temp table.
                                        # Also include rows where ROW_SOURCE is empty/None
                                        # (they have no self-ref issue).
                                        _non_bootstrap = [
                                            r for r in _clean_rows
                                            if _get_ci(r, _sr_fc) != _get_ci(r, _sr_pk)
                                        ]
                                        _boot_ok = 0
                                        for _br in _bootstrap_rows:
                                            # Use case-insensitive get for all columns
                                            _bvals = {c: _get_ci(_br, c) or None
                                                      for c in _ins_cols}
                                            _bparams = {f"p{i}": v for i, v in enumerate(_bvals.values())}
                                            _bplaceholders = ", ".join(f":p{i}" for i in range(len(_bvals)))
                                            _bpk_check = " AND ".join(
                                                f"[{pc}] = :p{list(_bvals.keys()).index(pc) if pc in _bvals else 0}"
                                                for pc in _rtm_pk_cols if pc in _bvals
                                            )
                                            with S.engine.begin() as _bcon:
                                                _bex = _bcon.execute(_rtm_text(
                                                    f"IF NOT EXISTS (SELECT 1 FROM [{_rtm_schema}].[{_rtm_tbl}] WHERE {_bpk_check}) "
                                                    f"INSERT INTO [{_rtm_schema}].[{_rtm_tbl}] "
                                                    f"({_col_list}{_audit_col_sql}) "
                                                    f"VALUES ({_bplaceholders}{_audit_val_sql})"
                                                ), _bparams)
                                                _boot_ok += _bex.rowcount
                                        # Pass 2: non-bootstrap rows from temp table.
                                        # These point to a different parent row so that
                                        # parent must now exist (either pre-existing or
                                        # just inserted in Pass 1 above).
                                        # Filter the temp table to only non-bootstrap PKs.
                                        _nb_pk_vals = [
                                            _get_ci(r, _sr_pk) for r in _non_bootstrap
                                        ]
                                        if _nb_pk_vals:
                                            _nb_in = ", ".join(f"'{v}'" for v in _nb_pk_vals)
                                            _res = _con.execute(_rtm_text(
                                                _insert_sql +
                                                f" AND src.[{_sr_pk}] IN ({_nb_in})"
                                            ))
                                            _rtm_ok = _boot_ok + _res.rowcount
                                        else:
                                            _rtm_ok = _boot_ok
                                    else:
                                        _res = _con.execute(_rtm_text(_insert_sql))
                                        _rtm_ok = _res.rowcount
                                    _rtm_dupes = len(_clean_rows) - _rtm_ok
                            # Clear caches and pending rows
                            st.session_state.pop(_fk_opts_key, None)
                            st.session_state.pop(f"{_rtm_key}_pending_rows", None)
                            _msg = f"✅ Inserted {_rtm_ok} row(s) into `{_rtm_tbl}`"
                            if _rtm_skip:
                                _msg += f" ({_rtm_skip} skipped — missing values)"
                            if _rtm_dupes:
                                _msg += f" ({_rtm_dupes} already existed — skipped)"
                            # Show inline AND persist for next render
                            st.success(_msg)
                            st.session_state[f"{_rtm_key}_last_msg"] = _msg
                            if _rtm_skip_reasons:
                                for _r in _rtm_skip_reasons:
                                    st.warning(f"⚠ Skipped — {_r}")
                                st.session_state[f"{_rtm_key}_skip_reasons"] = _rtm_skip_reasons
                        except Exception as _e:
                            _emsg = f"❌ Insert failed: {_e}"
                            st.error(_emsg)
                            st.session_state[f"{_rtm_key}_last_msg"] = _emsg

    with st.expander("🗄️ Database Explorer", expanded=False):
        if st.button("Open Explorer",
                     type="primary" if st.session_state.app_mode == "db_explorer" else "secondary",
                     disabled=not S.get("engine"),
                     key="open_db_explorer"):
            st.session_state.app_mode = "db_explorer"
            st.rerun()
        if not S.get("engine"):
            st.caption("Connect to a database first.")

    with st.expander("📋 Rules Manager", expanded=False):
        st.caption("Normalization & validation rules")
        if st.button("Open Rules Manager",
                     type="primary" if st.session_state.app_mode == "rules" else "secondary",
                     key="open_rules"):
            st.session_state.app_mode = "rules"
            st.rerun()
        if st.session_state.app_mode == "rules":
            if st.button("↩ Back to Pipeline",
                         key="close_rules"):
                st.session_state.app_mode = "pipeline"
                st.rerun()

    with st.expander("📖 Data Model ERD Diagrams", expanded=False):
        st.caption("198 pages · zoom · pan · search")
        if st.button("Open Viewer",
                     type="primary" if st.session_state.app_mode=="data_model" else "secondary",
                     key="open_data_model"):
            st.session_state.app_mode = "data_model"
            st.rerun()
        if st.session_state.app_mode == "data_model":
            if st.button("↩ Close Viewer",
                         key="close_data_model"):
                st.session_state.app_mode = "pipeline"
                st.rerun()

    with st.expander("📂 Standard Formats Catalog", expanded=False):
        st.caption("Load and catalog well logs, seismic and more")
        if st.button("Open File Catalog",
                     type="primary" if st.session_state.app_mode in ("file_catalog", "las_catalog") else "secondary",
                     key="open_file_catalog",
                     disabled=not S.get("engine")):
            st.session_state.app_mode = "file_catalog"
            st.session_state.pop("file_catalog_domain", None)
            st.rerun()
        if not S.get("engine"):
            st.caption("Connect to a database first.")
        if st.session_state.app_mode in ("file_catalog", "las_catalog"):
            if st.button("↩ Back to Pipeline",
                         key="close_file_catalog"):
                st.session_state.app_mode = "pipeline"
                st.rerun()


    with st.expander("🗺️ PPDM Map", expanded=False):
        st.caption("Interactive map of wells, fields and seismic surveys")
        if st.button("Open PPDM Map",
                     type="primary" if st.session_state.app_mode == "ppdm_map" else "secondary",
                     key="open_ppdm_map",
                     disabled=not S.get("engine")):
            st.session_state.app_mode = "ppdm_map"
            st.rerun()
        if not S.get("engine"):
            st.caption("Connect to a database first.")
        if st.session_state.app_mode == "ppdm_map":
            if st.button("↩ Back to Pipeline", key="close_ppdm_map"):
                st.session_state.app_mode = "pipeline"
                st.rerun()

    if st.sidebar.button("🗂 File Inventory", use_container_width=True,
                              key="sb_file_inv"):
        S.app_mode = "file_inventory"
        st.rerun()

    if st.sidebar.button("📋 File Browser", use_container_width=True,
                              key="sb_file_browser"):
        S.app_mode = "file_browser"
        st.rerun()

    with st.expander("🤖 AI Assistant", expanded=False):
        _agent_ok, _agent_msg = PPDMAgent().is_configured()
        if not _agent_ok:
            st.warning(_agent_msg)
            st.code("ANTHROPIC_API_KEY=sk-ant-...", language="bash")
            st.caption("Add this to your .env file in the project root.")
        else:
            # Chat history display
            _chat_container = st.container(height=320)
            with _chat_container:
                if not S.agent_messages:
                    st.caption("Ask me anything about loading data to your database.")
                    st.caption("Try: *How do I load directional surveys?*")
                for _mi, _msg in enumerate(S.agent_messages):
                    with st.chat_message(_msg["role"]):
                        st.markdown(_msg["content"])
                        if _msg["role"] == "assistant":
                            import streamlit.components.v1 as _cv1
                            import json as _json
                            # Use a hidden textarea as the copy source — avoids
                            # unicode escape rendering issues with clipboard API
                            _safe = _msg["content"].replace("</", "</")
                            _cv1.html(f"""
                                <textarea id="ct_{_mi}" style="position:absolute;
                                    left:-9999px;top:-9999px;opacity:0;"
                                    readonly>{_safe}</textarea>
                                <button onclick="
                                    var t=document.getElementById('ct_{_mi}');
                                    t.select(); t.setSelectionRange(0,99999);
                                    navigator.clipboard.writeText(t.value).then(()=>{{
                                        this.textContent='✓ Copied';
                                        this.style.color='#4caf50';
                                        setTimeout(()=>{{
                                            this.textContent='📋 Copy';
                                            this.style.color='#aaa';
                                        }},1500);
                                    }}).catch(()=>{{
                                        document.execCommand('copy');
                                        this.textContent='✓ Copied';
                                        setTimeout(()=>this.textContent='📋 Copy',1500);
                                    }});
                                " style="background:none;border:1px solid #555;color:#aaa;
                                         padding:2px 10px;border-radius:4px;cursor:pointer;
                                         font-size:11px;font-family:sans-serif;">
                                    📋 Copy
                                </button>
                            """, height=32)

            # Input
            _user_input = st.chat_input("Ask about database loading…",
                                         key="agent_chat_input")
            if _user_input:
                S.agent_messages.append({"role": "user", "content": _user_input})
                with st.spinner("Thinking…"):
                    try:
                        _ctx = build_pipeline_context(S)
                        _reply = PPDMAgent().chat(S.agent_messages, _ctx)
                    except Exception as _ae:
                        _reply = f"⚠️ Error: {_ae}"
                S.agent_messages.append({"role": "assistant", "content": _reply})
                st.rerun()

            if S.agent_messages:
                if st.button("🗑 Clear chat", key="agent_clear"):
                    S.agent_messages = []
                    st.rerun()

    # ── One-time setup: Seed reference tables ─────────────────────
    st.markdown("---")
    st.caption("ONE-TIME SETUP")
    if st.button("🌱 Seed Reference Tables",
                 type="primary" if st.session_state.app_mode=="seed" else "secondary",
                 key="open_seed"):
        st.session_state.app_mode = "seed"
        st.rerun()
    if st.button("↩ Back to Pipeline",
                 disabled=st.session_state.app_mode in ("pipeline", "data_model"),
                 key="back_to_pipeline_seed"):
        st.session_state.app_mode = "pipeline"
        st.rerun()

    # ── Shutdown ──────────────────────────────────────────────────────
    st.sidebar.divider()
    with st.sidebar.expander("⏹ Shutdown", expanded=False):
        st.caption("Stop the Data Wrangler server.")
        if st.button("⏹ Shutdown Data Wrangler", type="primary",
                     key="shutdown_btn"):
            st.success("Shutting down… you can close this tab.")
            import os
            os._exit(0)

# ═══════════════════════════════════════════════════════════════════════
# STAGE 1 · CONNECT
# ═══════════════════════════════════════════════════════════════════════


# ── Main area routing ──────────────────────────────────────────────

# Show error banner if a previous error is stored
if S.get("last_error"):
    _err = S.last_error
    import streamlit as _st2
    with st.container():
        st.error(
            f"⚠️ **Error in {_err['stage']}**: {_err['message']}  \n"
            f"The AI Assistant has been pre-loaded with this error — "
            f"expand **🤖 AI Assistant** in the sidebar for an explanation.",
            icon="🚨"
        )
        with st.expander("Show full traceback", expanded=False):
            st.code(_err["detail"], language="python")
        if st.button("✕ Dismiss error", key="_dismiss_error"):
            S.last_error = None
            S.last_error_stage = None
            st.rerun()

def _render_file_catalog_landing():
    """Domain selection landing page for the File Catalog."""
    st.title("📂 Standard Formats Catalog")
    st.caption(
        "Select a domain to catalog, search and view your petroleum files. "
        "All formats are indexed into the PPDM schema."
    )
    st.divider()

    def _domain_card(col, icon, title, formats, description, btn_label, btn_key, domain):
        with col:
            with st.container(border=True):
                st.markdown(
                    f"<div style='font-size:42px;text-align:center;"
                    f"padding:8px 0 4px 0'>{icon}</div>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<h3 style='text-align:center;margin:0 0 4px 0'>{title}</h3>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<p style='text-align:center;color:grey;font-size:13px;"
                    f"margin:0 0 8px 0'>{formats}</p>",
                    unsafe_allow_html=True
                )
                st.caption(description)
                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                if st.button(btn_label, key=btn_key,
                             type="primary", use_container_width=True):
                    st.session_state["file_catalog_domain"] = domain
                    st.rerun()

    def _coming_card(col, icon, title, formats, description):
        with col:
            with st.container(border=True):
                st.markdown(
                    f"<div style='font-size:42px;text-align:center;"
                    f"padding:8px 0 4px 0;opacity:0.45'>{icon}</div>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<h3 style='text-align:center;margin:0 0 4px 0;"
                    f"opacity:0.45'>{title}</h3>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<p style='text-align:center;color:grey;font-size:13px;"
                    f"margin:0 0 8px 0;opacity:0.45'>{formats}</p>",
                    unsafe_allow_html=True
                )
                st.caption(description)
                st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
                st.button("Coming Soon", key=f"fc_{title.lower().replace(' ','_')}",
                          use_container_width=True, disabled=True)

    # ── Row 1 ─────────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)

    _domain_card(
        col1, "📁", "Manage Repositories",
        "Add · Edit · Delete",
        "Register and manage the file system locations "
        "where your well logs and seismic files are stored.",
        "Manage Repositories →", "fc_repos", "repos"
    )
    _domain_card(
        col2, "🛢️", "Well Logs",
        "LAS · DLIS · LIS",
        "Crawl, catalog and search well log files. "
        "Auto fuzzy-match to PPDM wells by UWI. Plot curves.",
        "Open Well Log Catalog →", "fc_wells", "wells"
    )

    # ── Row 2 ─────────────────────────────────────────────────────────────────
    col3, col4 = st.columns(2)

    _domain_card(
        col3, "🌊", "Seismic",
        "SEG-Y · UKOAA P1/90",
        "Catalog SEG-Y and P1/90 files. Survey maps, "
        "EBCDIC headers, bounding boxes and section viewer.",
        "Open Seismic Catalog →", "fc_seismic", "seismic"
    )
    _domain_card(
        col4, "📋", "Browse & Copy",
        "LAS · DLIS · LIS · SEG-Y · P190",
        "Search all cataloged files across every format. "
        "Select files and copy them to a local destination folder.",
        "Browse & Copy Files →", "fc_browse", "browse"
    )

    st.divider()
    st.caption("Additional domains can be added as needed.")



try:
    if st.session_state.app_mode == "data_model":
        page_data_model.render(S)
    elif st.session_state.app_mode == "seed":
        page_seed.render(S)
    elif st.session_state.app_mode == "db_explorer":
        page_db_explorer.render(S)
    elif st.session_state.app_mode == "rules":
        page_rules.render(S)
    elif st.session_state.app_mode == "ppdm_map":
        page_ppdm_map.run()
    elif st.session_state.app_mode == "file_inventory":
        page_file_inventory.run()
    elif st.session_state.app_mode == "file_browser":
        page_file_browser.render()
    elif st.session_state.app_mode in ("file_catalog", "las_catalog"):
        _domain = st.session_state.get("file_catalog_domain")
        if _domain == "repos":
            page_std_catalog.run_repos()
        elif _domain == "wells":
            page_std_catalog.run()
        elif _domain == "seismic":
            page_std_catalog.run_seismic()
        else:
            _render_file_catalog_landing()
    else:
        page_pipeline.render(S)
except Exception as _page_exc:
    import traceback as _tb
    # Only auto-rerun for pipeline errors — catalog/map pages show error inline
    if st.session_state.app_mode == "ppdm_map":
        st.error(f"**Error:** {_page_exc}")
        with st.expander("Full traceback"):
            st.code(_tb.format_exc())
    if st.session_state.app_mode in ("file_catalog", "las_catalog"):
        st.error(f"**Error:** {_page_exc}")
        with st.expander("Full traceback"):
            st.code(_tb.format_exc())
    else:
        _stage = f"Stage {S.get('stage', '?')}"
        report_error(_page_exc, _stage)
        st.rerun()

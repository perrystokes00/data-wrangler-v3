"""
app_v3.py  —  DataView v3
=========================
Clean scaffolding built around the DataView schema and ML-powered imports.
Replaces the PPDM 3.9 pipeline-centric v2 with a data-domain-centric v3.

Navigation is card-based on the splash screen.
All heavy modules loaded lazily after connect.

Dialect support: SQL Server · Oracle · Snowflake
"""
from __future__ import annotations
import os
import streamlit as st

st.set_page_config(
    page_title="DataView",
    page_icon="🛢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════════
# THEME SYSTEM
# ═══════════════════════════════════════════════════════════════════════

THEMES = {
    "Default (Teal)": {
        "bg":          "#0a8a96",
        "bg_mid":      "#0d8f9e",
        "sidebar":     "#0a7a8a",
        "primary":     "#1ab8c4",
        "primary_dark":"#0d8a94",
        "accent":      "#c4915a",
        "text":        "#e8f4f5",
        "text_dim":    "#7aacb5",
        "card_shadow": "rgba(26,184,196,0.15)",
        "conn_ok":     "#3dd68c",
        "conn_err":    "#f87171",
        "desc":        "Default teal palette from the Data Wrangler logo",
    },
    "High Contrast": {
        "bg":          "#000000",
        "bg_mid":      "#1a1a1a",
        "sidebar":     "#111111",
        "primary":     "#ffff00",
        "primary_dark":"#cccc00",
        "accent":      "#ff8c00",
        "text":        "#ffffff",
        "text_dim":    "#cccccc",
        "card_shadow": "rgba(255,255,0,0.2)",
        "conn_ok":     "#00ff00",
        "conn_err":    "#ff4444",
        "desc":        "WCAG AAA — maximum contrast for low vision",
    },
    "Deuteranopia (Blue/Orange)": {
        "bg":          "#1a2a4a",
        "bg_mid":      "#1e3255",
        "sidebar":     "#152038",
        "primary":     "#5b9bd5",
        "primary_dark":"#3a7abf",
        "accent":      "#f28c28",
        "text":        "#f0f4ff",
        "text_dim":    "#a0b4d0",
        "card_shadow": "rgba(91,155,213,0.2)",
        "conn_ok":     "#5b9bd5",
        "conn_err":    "#f28c28",
        "desc":        "Safe for green-blind (deuteranopia) — uses blue/orange only",
    },
    "Protanopia (Blue/Yellow)": {
        "bg":          "#1a1a3a",
        "bg_mid":      "#222250",
        "sidebar":     "#141430",
        "primary":     "#6699ff",
        "primary_dark":"#4477dd",
        "accent":      "#ffcc00",
        "text":        "#f0f0ff",
        "text_dim":    "#9999cc",
        "card_shadow": "rgba(102,153,255,0.2)",
        "conn_ok":     "#6699ff",
        "conn_err":    "#ffcc00",
        "desc":        "Safe for red-blind (protanopia) — uses blue/yellow only",
    },
    "Light / Print": {
        "bg":          "#f5f7fa",
        "bg_mid":      "#e8ecf0",
        "sidebar":     "#dde3ea",
        "primary":     "#0066cc",
        "primary_dark":"#004499",
        "accent":      "#cc6600",
        "text":        "#1a1a2e",
        "text_dim":    "#555577",
        "card_shadow": "rgba(0,102,204,0.12)",
        "conn_ok":     "#007700",
        "conn_err":    "#cc0000",
        "desc":        "Light background — good for printing and bright rooms",
    },
}

def _inject_theme(t: dict):
    """Inject theme CSS with !important to beat Streamlit defaults."""
    bg      = t['bg']
    bg_mid  = t['bg_mid']
    sidebar = t['sidebar']
    primary = t['primary']
    pri_dk  = t['primary_dark']
    accent  = t['accent']
    text    = t['text']
    txt_dim = t['text_dim']
    c_ok    = t['conn_ok']
    c_err   = t['conn_err']
    shadow  = t['card_shadow']
    st.markdown(f"""
    <style>
    :root {{
        --teal:       {primary};
        --teal-dark:  {pri_dk};
        --teal-dim:   {primary}22;
        --sandy:      {accent};
        --sandy-dim:  {accent}22;
        --navy:       {bg};
        --navy-mid:   {bg_mid};
        --navy-light: {primary};
        --sidebar:    {sidebar};
        --text:       {text};
        --text-dim:   {txt_dim};
    }}
    html, body, .stApp,
    [class*="css"],
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    .main, .block-container {{
        background: {bg} !important;
        color: {text} !important;
    }}
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div {{
        background: {sidebar} !important;
    }}
    [data-testid="stSidebar"] * {{ color: {text} !important; }}
    [data-testid="stHeader"]  {{ background: {bg} !important; }}
    [data-testid="stToolbar"] {{ background: {bg} !important; }}
    [data-testid="stDecoration"] {{ background: {bg} !important; }}
    button[kind="primary"] {{
        background: {pri_dk} !important;
        border-color: {primary} !important;
        color: {text} !important;
    }}
    button[kind="primary"]:hover {{ background: {primary} !important; }}
    .conn-pill.connected    {{ color:{c_ok};  border-color:{c_ok}44;  background:{bg_mid}; }}
    .conn-pill.disconnected {{ color:{c_err}; border-color:{c_err}44; background:{bg_mid}; }}
    div[data-testid="stHorizontalBlock"]
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        background: {bg_mid} !important;
        border: 1px solid {pri_dk} !important;
    }}
    div[data-testid="stHorizontalBlock"]
    div[data-testid="stVerticalBlockBorderWrapper"]:hover {{
        border-color: {primary} !important;
        box-shadow: 0 8px 24px {shadow};
    }}
    </style>
    """, unsafe_allow_html=True)


# ── Global CSS — layout and fonts only, NO hardcoded colors ─────────
# All colors come from CSS variables set by _inject_theme()
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    background: var(--navy) !important;
    color: var(--text) !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: var(--sidebar) !important;
    border-right: 1px solid var(--teal-dark) !important;
}
[data-testid="stSidebar"] * { color: var(--text) !important; }
[data-testid="stSidebar"] .stButton button {
    background: transparent;
    border: 1px solid var(--navy-light);
    color: var(--text) !important;
    text-align: left;
    border-radius: 6px;
    transition: all 0.15s;
    font-size: 13px;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: var(--navy-mid);
    border-color: var(--teal);
    color: var(--teal) !important;
}
[data-testid="stSidebar"] .stButton button[kind="primary"] {
    background: var(--teal-dark);
    border-color: var(--teal);
    color: #fff !important;
}

/* Main area background */
[data-testid="stAppViewContainer"] > .main {
    background: var(--navy) !important;
}
[data-testid="stHeader"] { background: var(--navy) !important; }

/* Nav cards */
div[data-testid="stHorizontalBlock"] div[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--navy-mid) !important;
    border: 1px solid var(--navy-light) !important;
    border-radius: 12px !important;
    transition: border-color 0.2s, transform 0.15s, box-shadow 0.2s;
}
div[data-testid="stHorizontalBlock"] div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: var(--teal) !important;
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(26,184,196,0.15);
}

/* Primary buttons — teal */
button[kind="primary"] {
    background: var(--teal-dark) !important;
    border-color: var(--teal) !important;
    color: #fff !important;
}
button[kind="primary"]:hover {
    background: var(--teal) !important;
}

/* Connection pill */
.conn-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    font-family: 'IBM Plex Mono', monospace;
    padding: 3px 12px;
    border-radius: 20px;
    margin-bottom: 12px;
}
.conn-pill.connected    { background:#0a2e22; color:#3dd68c; border:1px solid #3dd68c44; }
.conn-pill.disconnected { background:#2e0a0a; color:#f87171; border:1px solid #f8717144; }

/* Section header in sidebar */
.sec-hdr {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 1.5px;
    margin: 20px 0 6px 0;
    padding-bottom: 6px;
    border-bottom: 1px solid var(--navy-light);
}

/* App header */
.dv-header {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px 0 8px 0;
    border-bottom: 2px solid var(--teal-dark);
    margin-bottom: 20px;
}
.dv-title {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 42px;
    color: var(--teal);
    letter-spacing: 2px;
    line-height: 1;
    margin: 0;
}
.dv-subtitle {
    font-size: 12px;
    color: var(--sandy);
    font-family: 'IBM Plex Mono', monospace;
    letter-spacing: 1px;
    margin: 0;
}
.dv-badge {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    background: var(--sandy-dim);
    color: var(--sandy);
    padding: 2px 8px;
    border-radius: 20px;
    border: 1px solid var(--sandy);
}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════════════

DEFAULTS = dict(
    engine          = None,
    dialect         = None,       # "mssql" | "oracle" | "snowflake"
    db_label        = "",         # "server/database" display string
    connected       = False,
    app_mode        = "splash",   # current page
    demo            = False,
    theme           = "Default (Teal)",
)

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

S = st.session_state

# ── Inject theme at top level so CSS applies to entire page ───────────
_inject_theme(THEMES[S.get("theme", "Default (Teal)")])


# ═══════════════════════════════════════════════════════════════════════
# SIDEBAR — connection + nav
# ═══════════════════════════════════════════════════════════════════════

with st.sidebar:
    # Header
    import base64 as _sb64, pathlib as _spl
    _sb_b64 = ""
    for _slp in ["assets/data_wrangler.png", "data_wrangler.png"]:
        if _spl.Path(_slp).exists():
            _sb_b64 = _sb64.b64encode(_spl.Path(_slp).read_bytes()).decode()
            break
    if _sb_b64:
        st.markdown(
            f"<img src=\"data:image/png;base64,{_sb_b64}\" "
            f"style=\"width:100%;max-width:200px;border-radius:8px\"/>",
            unsafe_allow_html=True)
    st.markdown(
        "<div style=\"font-family:\'IBM Plex Mono\',monospace;font-size:11px;"
        "color:#ffffff;font-weight:600;letter-spacing:1px;"
        "margin:6px 0 2px 0\">DATA WRANGLER SOLUTIONS LLC</div>"
        "<div style=\"font-size:10px;color:#b2e8ee;"
        "font-family:\'IBM Plex Mono\',monospace;letter-spacing:1px\">"
        "v3.0 · DataView</div>",
        unsafe_allow_html=True)

    # Theme selector
    st.markdown("<div class='sec-hdr'>Appearance</div>", unsafe_allow_html=True)
    theme_choice = st.selectbox(
        "Color theme",
        options=list(THEMES.keys()),
        index=list(THEMES.keys()).index(S.get("theme", "Default (Teal)")),
        key="sb_theme",
        label_visibility="collapsed")
    if theme_choice != S.get("theme"):
        S.theme = theme_choice
        st.rerun()
    _inject_theme(THEMES[S.get("theme", "Default (Teal)")])
    st.caption(THEMES[S.get("theme", "Default (Teal)")]["desc"])

    # Connection status
    if S.connected:
        st.markdown(
            f"<div class='conn-pill connected'>● {S.db_label}</div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='conn-pill disconnected'>○ Not connected</div>",
            unsafe_allow_html=True)

    # ── Connect panel ─────────────────────────────────────────────────
    with st.expander("🔌 Connect", expanded=not S.connected):
        # Suppress browser autofill / autocomplete popups on the connection
        # form. Chrome will helpfully (annoyingly) suggest previously-entered
        # values when these inputs get focus, and the suggestion box is large
        # enough to obscure the form below it. Setting autocomplete to a
        # nonsense value or "new-password" tells Chrome NOT to suggest stored
        # values. Streamlit doesn't expose autocomplete on st.text_input
        # directly, so we do it via JS targeting only inputs with our sb_*
        # keys.
        st.markdown("""
            <script>
            (function() {
                function suppressAutofill() {
                    var inputs = window.parent.document.querySelectorAll(
                        'input[aria-label="Server"], '       +
                        'input[aria-label="Database"], '     +
                        'input[aria-label="Username"], '     +
                        'input[aria-label="Password"], '     +
                        'input[aria-label="Account"], '      +
                        'input[aria-label="Warehouse"], '    +
                        'input[aria-label="Host:Port/SID"]'
                    );
                    inputs.forEach(function(inp) {
                        // 'new-password' is Chrome's "stop autofilling this" signal
                        inp.setAttribute('autocomplete', 'new-password');
                        inp.setAttribute('autocorrect', 'off');
                        inp.setAttribute('autocapitalize', 'off');
                        inp.setAttribute('spellcheck', 'false');
                    });
                }
                // Run once now, then on a delay (Streamlit may rerender)
                suppressAutofill();
                setTimeout(suppressAutofill, 500);
                setTimeout(suppressAutofill, 1500);
            })();
            </script>
        """, unsafe_allow_html=True)

        dialect = st.selectbox("Dialect",
            ["SQL Server", "Oracle", "Snowflake"], key="sb_dialect")

        if dialect == "SQL Server":
            server   = st.text_input("Server",   value=r"localhost\SQLEXPRESS", key="sb_server")
            database = st.text_input("Database", value="DataView",              key="sb_database")
            win_auth = st.checkbox("Windows Auth", value=True, key="sb_winauth")
            username = password = ""
            if not win_auth:
                username = st.text_input("Username", key="sb_user")
                password = st.text_input("Password", type="password", key="sb_pass")
            driver   = st.selectbox("Driver",
                ["ODBC Driver 17 for SQL Server",
                 "ODBC Driver 18 for SQL Server",
                 "SQL Server"], key="sb_driver")

        elif dialect == "Oracle":
            server   = st.text_input("Host:Port/SID",
                                     placeholder="localhost:1521/ORCL", key="sb_server")
            database = ""
            win_auth = False
            username = st.text_input("Username", key="sb_user")
            password = st.text_input("Password", type="password", key="sb_pass")
            driver   = ""

        else:  # Snowflake
            server   = st.text_input("Account",
                                     placeholder="orgname-accountname", key="sb_server")
            database = st.text_input("Database", key="sb_database")
            win_auth = False
            username = st.text_input("Username", key="sb_user")
            password = st.text_input("Password", type="password", key="sb_pass")
            driver   = st.text_input("Warehouse", value="COMPUTE_WH", key="sb_driver")

        col_a, col_b = st.columns(2)
        if col_a.button("Connect", key="sb_connect",
                        type="primary", use_container_width=True):
            with st.spinner("Connecting…"):
                try:
                    from modules.db import DBConfig, connect as _connect
                    cfg = DBConfig(
                        server       = server,
                        database     = database,
                        driver       = driver,
                        windows_auth = win_auth,
                        username     = username,
                        password     = password,
                    )
                    result = _connect(cfg)
                    if result.ok:
                        S.engine    = result.engine
                        S.connected = True
                        S.dialect   = dialect.lower().replace(" ", "_")
                        S.db_label  = f"{server}/{database}" if database else server
                        S.app_mode  = "splash"
                        st.rerun()
                    else:
                        st.error(result.message)
                except Exception as e:
                    st.error(str(e))

        if col_b.button("Demo", key="sb_demo",
                        use_container_width=True):
            try:
                from modules.db import connect_demo
                result = connect_demo()
                S.engine    = result.engine
                S.connected = True
                S.demo      = True
                S.db_label  = "Demo Mode"
                S.app_mode  = "splash"
                st.rerun()
            except Exception as e:
                st.error(str(e))

    # ── Navigation (only when connected) ─────────────────────────────
    if S.connected:
        st.markdown("<div class='sec-hdr'>Navigation</div>",
                    unsafe_allow_html=True)

        NAV = [
            ("splash",        "🏠", "Home"),
            ("well_map",      "🗺",  "Mapping"),
            ("importer",      "📥", "Import Data"),
            ("db_explorer",   "🔍", "DB Explorer"),
            ("workbench",     "🗂️", "File Catalog"),
            ("ref_tables",    "📋", "Reference Tables"),
        ]
        for mode, icon, label in NAV:
            is_active = S.app_mode == mode
            if st.button(f"{icon}  {label}", key=f"nav_{mode}",
                         type="primary" if is_active else "secondary",
                         use_container_width=True):
                S.app_mode = mode
                st.rerun()

        with st.expander("📤 Exporters", expanded=False):
            EXPORTERS = [
                ("ppdm_export", "📤", "→ DB 3.9"),
            ]
            for mode, icon, label in EXPORTERS:
                is_active = S.app_mode == mode
                if st.button(f"{icon}  {label}", key=f"nav_{mode}",
                             type="primary" if is_active else "secondary",
                             use_container_width=True):
                    S.app_mode = mode
                    st.rerun()

        st.markdown("<div class='sec-hdr'>Session</div>",
                    unsafe_allow_html=True)
        if st.button("⏏ Disconnect", key="nav_disconnect",
                     use_container_width=True):
            for k, v in DEFAULTS.items():
                S[k] = v
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# MAIN CONTENT
# ═══════════════════════════════════════════════════════════════════════

def _nav_card(col, icon, title, desc, mode):
    with col:
        with st.container(border=True):
            st.markdown(
                f"<div style='text-align:center;font-size:26px;"
                f"padding:4px 0 2px 0'>{icon}</div>"
                f"<div style='text-align:center;font-size:14px;"
                f"font-weight:700;margin:2px 0 4px 0'>{title}</div>"
                f"<div style='text-align:center;font-size:11px;"
                f"color:#b2e8ee;margin:0 0 8px 0;line-height:1.4'>{desc}</div>",
                unsafe_allow_html=True)
            if st.button(f"Open", key=f"card_{mode}",
                         type="primary", use_container_width=True):
                S.app_mode = mode
                st.rerun()


# ── SPLASH ────────────────────────────────────────────────────────────
if S.app_mode == "splash":
    # ── Company header ───────────────────────────────────────────────
    import base64 as _b64, pathlib as _pl
    _logo_b64 = ""
    for _lp in ["assets/data_wrangler.png", "data_wrangler.png"]:
        if _pl.Path(_lp).exists():
            _logo_b64 = _b64.b64encode(_pl.Path(_lp).read_bytes()).decode()
            break

    _logo_html = (
        f"<img src=\"data:image/png;base64,{_logo_b64}\" "
        f"style=\"height:90px;width:auto\"/>"
        if _logo_b64 else "🛢"
    )

    st.markdown(f"""
        <div style="display:flex;align-items:center;gap:20px;
                    background:#0a5f6a;
                    padding:16px 24px;
                    border-radius:12px;
                    border-bottom:3px solid #c4915a;
                    margin-bottom:16px;
                    box-shadow:0 4px 20px rgba(0,0,0,0.3)">
            {_logo_html}
            <div>
                <div style="font-family:'Bebas Neue',sans-serif;
                            font-size:46px;color:#ffffff;
                            letter-spacing:3px;line-height:1;
                            text-shadow:1px 2px 6px rgba(0,0,0,0.5)">
                    DATA WRANGLER
                </div>
                <div style="font-size:14px;color:#c4915a;
                            font-family:'IBM Plex Mono',monospace;
                            font-weight:600;letter-spacing:2px;margin-top:2px">
                    DATA WRANGLER SOLUTIONS LLC
                </div>
                <div style="font-size:11px;color:#b2e8ee;
                            font-family:'IBM Plex Mono',monospace;
                            letter-spacing:1px;margin-top:4px">
                    PETROLEUM DATA PLATFORM &nbsp;·&nbsp;
                    SQL SERVER &nbsp;·&nbsp; ORACLE &nbsp;·&nbsp; SNOWFLAKE
                    &nbsp;·&nbsp; v3.0
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if not S.connected:
        st.info("🔌 Connect to a database using the sidebar to get started.")
    else:
        st.markdown(
            f"<p style='color:#3dd68c;font-size:12px;margin-bottom:12px'>"
            f"● Connected to {S.db_label}</p>",
            unsafe_allow_html=True)

        # Row 1
        c1, c2, c3 = st.columns(3)
        _nav_card(c1, "🗺",  "Mapping",
                  "Well map · spatial layers · AI filter · scout tickets",
                  "well_map")
        _nav_card(c2, "📥", "Import Data",
                  "ML column mapping · CSV · Excel · fingerprint",
                  "importer")
        _nav_card(c3, "📤", "Export Data",
                  "PPDM 3.9 · Petrel · ESRI (sidebar)",
                  "ppdm_export")

        # Row 2
        c4, c5, c6 = st.columns(3)
        _nav_card(c4, "🔍", "DB Explorer",
                  "Query · browse · export any DataView table",
                  "db_explorer")
        _nav_card(c5, "🗂️", "File Catalog",
                  "Scan · enrich · browse · view · extract · load",
                  "workbench")
        _nav_card(c6, "📋", "Reference Tables",
                  "Seed dv_r_well_status · dv_r_well_type · lookups",
                  "ref_tables")


# ── WELL MAP ──────────────────────────────────────────────────────────
elif S.app_mode == "well_map":
    try:
        import page_well_map
        fn = getattr(page_well_map, "run", None) or getattr(page_well_map, "render", None)
        if fn:
            fn(S.engine)
        else:
            st.error("page_well_map has no run() or render() function")
    except Exception as e:
        st.error(f"Well Map error: {e}")


# ── IMPORTER ──────────────────────────────────────────────────────────
elif S.app_mode == "importer":
    try:
        import page_dv_importer
        page_dv_importer.render(S.engine)
    except Exception as e:
        st.error(f"Importer error: {e}")


# ── PPDM EXPORT ───────────────────────────────────────────────────────
elif S.app_mode == "ppdm_export":
    try:
        import page_dv_export
        page_dv_export.render(S.engine)
    except Exception as e:
        st.error(f"Export error: {e}")


# ── DB EXPLORER ───────────────────────────────────────────────────────
elif S.app_mode == "db_explorer":
    try:
        # Make engine accessible both as attribute and dict key
        st.session_state["engine"] = S.engine
        import page_db_explorer
        page_db_explorer.render(S)
    except Exception as e:
        st.error(f"DB Explorer error: {e}")
        import traceback
        st.code(traceback.format_exc())


# ── FILE CATALOG ──────────────────────────────────────────────────────
elif S.app_mode == "file_inv":
    try:
        from modules.db import _detect_dialect
        _raw = _detect_dialect(S.engine) or "mssql"
        _dialect = {"sqlserver": "mssql", "sql_server": "mssql"}.get(_raw, _raw)
        import page_file_manager
        page_file_manager.render(S.engine, _dialect)
    except Exception as e:
        st.error(f"File Manager error: {e}")


# ── FILE CATALOG ─────────────────────────────────────────────────────
elif S.app_mode == "file_catalog":
    try:
        from modules.db import _detect_dialect
        _raw = _detect_dialect(S.engine) or "mssql"
        _dialect = {"sqlserver": "mssql", "sql_server": "mssql"}.get(_raw, _raw)
        import page_file_catalog
        page_file_catalog.run(S.engine, _dialect)
    except Exception as e:
        st.error(f"File Catalog error: {e}")


# ── WORKBENCH ─────────────────────────────────────────────────────────
elif S.app_mode == "workbench":
    try:
        from modules.db import _detect_dialect
        _raw = _detect_dialect(S.engine) or "mssql"
        _dialect = {"sqlserver": "mssql", "sql_server": "mssql"}.get(_raw, _raw)
        import page_workbench
        page_workbench.run(S.engine, _dialect)
    except Exception as e:
        st.error(f"File Catalog error: {e}")


# ── SPATIAL LAYERS ────────────────────────────────────────────────────
elif S.app_mode == "file_scan":
    try:
        from modules.db import _detect_dialect
        _raw = _detect_dialect(S.engine) or "mssql"
        _dialect = {"sqlserver": "mssql", "sql_server": "mssql"}.get(_raw, _raw)
        import page_file_manager
        page_file_manager.render(S.engine, _dialect)
    except Exception as e:
        st.error(f"File Manager error: {e}")


elif S.app_mode == "spatial":
    st.subheader("📐 Spatial Layers")
    st.caption("Register GeoJSON and shapefiles as map overlays. "
               "Layers registered here appear in the Well Map.")

    try:
        from modules.dv_spatial_loader import list_layers, delete_layer
        layers = list_layers(S.engine)

        if layers:
            st.markdown(f"**{len(layers)} registered layer(s)**")
            for lay in layers:
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
                    c1.markdown(f"**{lay['layer_name']}**  "
                                f"`{lay.get('layer_category','')}`")
                    c2.caption(f"{lay.get('source_type','')} · "
                               f"{lay.get('feature_count') or '?'} features")
                    c3.caption(lay.get("layer_type",""))
                    if c4.button("🗑", key=f"del_lay_{lay['layer_id']}",
                                 help="Delete layer"):
                        delete_layer(S.engine, lay["layer_id"])
                        st.rerun()
        else:
            st.info("No layers registered yet. Use the Well Map → "
                    "Registered Layers panel to add GeoJSON or shapefiles.")

    except Exception as e:
        st.error(f"Spatial layers error: {e}")


# ── REFERENCE TABLES ─────────────────────────────────────────────────
elif S.app_mode == "ref_tables":
    try:
        import page_standards_manager
        page_standards_manager.render(S.engine)
    except Exception as e:
        st.error(f"Standards Manager error: {e}")
        import traceback
        st.code(traceback.format_exc())

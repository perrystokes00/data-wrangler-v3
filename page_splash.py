"""
page_splash.py
==============
Data Wrangler — Splash Screen

Shown once per session on first load.
DataView v3 is the primary platform.
PPDM pipeline is available as a secondary tool.
"""
import streamlit as st


def render(S: dict) -> None:

    st.markdown("""
    <style>
    .splash-wrap {
        max-width: 900px; margin: 0 auto;
        padding: 20px 10px; font-family: sans-serif;
    }
    .splash-header { text-align: center; padding: 30px 20px 20px; }
    .splash-logo   { font-size: 52px; margin-bottom: 8px; }
    .splash-title  { font-size: 42px; font-weight: 800; color: #1a2744;
                     letter-spacing: -1px; margin: 0; }
    .splash-sub    { font-size: 18px; color: #4a6080; margin: 8px 0 0; }
    .splash-version {
        display: inline-block; background: #1a2744; color: #90caf9;
        font-size: 11px; font-weight: 700; padding: 3px 10px;
        border-radius: 20px; margin-top: 10px; letter-spacing: 1px;
    }
    .feature-grid {
        display: grid; grid-template-columns: 1fr 1fr;
        gap: 16px; margin: 20px 0;
    }
    .feature-card {
        background: #f8faff; border: 1px solid #dde3ed;
        border-left: 4px solid #1a6fdb; border-radius: 8px;
        padding: 18px 20px;
    }
    .feature-card.locked {
        opacity: 0.45; filter: grayscale(40%);
    }
    .feature-icon  { font-size: 28px; margin-bottom: 6px; }
    .feature-title { font-size: 16px; font-weight: 700;
                     color: #1a2744; margin: 0 0 4px; }
    .feature-desc  { font-size: 13px; color: #6b7280;
                     margin: 0; line-height: 1.5; }
    .connected-badge {
        display: inline-block; background: #1b5e20; color: #a5d6a7;
        font-size: 11px; font-weight: 700; padding: 3px 10px;
        border-radius: 20px; margin-left: 8px;
    }
    </style>
    """, unsafe_allow_html=True)

    connected = S.get("engine") is not None
    db_name   = S.get("splash_db", "DataView")

    # Load logo image
    import pathlib, base64
    _logo_path = pathlib.Path("assets/data_wrangler.png")
    _logo_html = ""
    if _logo_path.exists():
        _b64 = base64.b64encode(_logo_path.read_bytes()).decode()
        _logo_html = (
            f"<img src='data:image/png;base64,{_b64}' "
            f"style='width:120px;height:120px;object-fit:contain;"
            f"margin-bottom:12px;border-radius:12px'/>"
        )

    # ── Header ────────────────────────────────────────────────────────
    st.markdown(f"""
    <div class="splash-wrap">
      <div class="splash-header">
        {_logo_html}
        <div class="splash-title">Data Wrangler</div>
        <div class="splash-sub">Petroleum Data Management Platform</div>
        <div>
          <span class="splash-version">DataView v3 &nbsp;·&nbsp; PPDM 3.9</span>
          {"<span class='connected-badge'>● Connected — " + db_name + "</span>" if connected else ""}
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Login / connection form ────────────────────────────────────────
    if not connected:
        lc1, lc2, lc3 = st.columns([1, 2, 1])
        with lc2:
            if not S.get("show_login_form"):
                if st.button("🔐 Connect to Database", type="primary",
                             use_container_width=True, key="splash_show_login"):
                    S["show_login_form"] = True
                    st.rerun()
                st.markdown(
                    "<div style='text-align:center;color:#9ca3af;"
                    "font-size:12px;margin-top:8px'>"
                    "Connect to a database to unlock all features</div>",
                    unsafe_allow_html=True)
            else:
                with st.form("splash_connect_form"):
                    st.markdown("#### Connect to DataView")
                    server   = st.text_input("Server",
                                             value=r"127.0.0.1\SQLEXPRESS",
                                             key="splash_server")
                    database = st.text_input("Database", value="DataView",
                                             key="splash_database")
                    win_auth = st.checkbox("Windows Authentication",
                                           value=True, key="splash_win_auth")
                    username = password = ""
                    if not win_auth:
                        username = st.text_input("Username", key="splash_user")
                        password = st.text_input("Password", type="password",
                                                  key="splash_pass")
                    fc1, fc2 = st.columns(2)
                    submitted = fc1.form_submit_button(
                        "Connect", type="primary", use_container_width=True)
                    cancelled = fc2.form_submit_button(
                        "Cancel", use_container_width=True)

                if cancelled:
                    S["show_login_form"] = False
                    st.rerun()

                if submitted:
                    try:
                        import urllib.parse
                        from sqlalchemy import create_engine, text as _t
                        if win_auth:
                            cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                                  f"SERVER={server};DATABASE={database};"
                                  f"Trusted_Connection=yes;")
                        else:
                            cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                                  f"SERVER={server};DATABASE={database};"
                                  f"UID={username};PWD={password};")
                        eng = create_engine(
                            "mssql+pyodbc:///?odbc_connect="
                            + urllib.parse.quote_plus(cs),
                            fast_executemany=True,
                        )
                        with eng.connect() as con:
                            con.execute(_t("SELECT 1"))
                        S["engine"]           = eng
                        S["splash_db"]        = database
                        S["show_login_form"]  = False
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Connection failed: {exc}")

    # ── Feature cards ─────────────────────────────────────────────────
    card_class = "feature-card" if connected else "feature-card locked"
    st.markdown(f"""
    <div class="splash-wrap">
      <div class="feature-grid">
        <div class="{card_class}">
          <div class="feature-icon">🗺</div>
          <div class="feature-title">Map Window</div>
          <div class="feature-desc">Live well map with trajectories, production
            bubbles, formation tops, DST intervals and shapefile overlays.</div>
        </div>
        <div class="{card_class}">
          <div class="feature-icon">🎫</div>
          <div class="feature-title">Scout Tickets</div>
          <div class="feature-desc">Auto-generated scout tickets. Print PDFs,
            batch export and multi-sheet Excel for selected wells.</div>
        </div>
        <div class="{card_class}">
          <div class="feature-icon">🗂</div>
          <div class="feature-title">Document Catalog</div>
          <div class="feature-desc">Crawl vaults, classify PDFs and office
            files, extract and load data directly into DataView.</div>
        </div>
        <div class="{card_class}">
          <div class="feature-icon">📊</div>
          <div class="feature-title">DataView Schema</div>
          <div class="feature-desc">46-table petroleum schema covering wells,
            surveys, formation tops, completions and production.</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Launch buttons (only when connected) ──────────────────────────
    lc1, lc2, lc3 = st.columns([1, 2, 1])
    with lc2:
        if connected:
            if st.button("🗺 Launch Map Window", type="primary",
                         use_container_width=True, key="splash_launch_map"):
                S["show_splash"] = False
                S["app_mode"]    = "well_map"
                st.rerun()

            st.markdown("<div style='height:8px'></div>",
                        unsafe_allow_html=True)

            if st.button("⚙ Open Pipeline (PPDM 3.9)", type="secondary",
                         use_container_width=True,
                         key="splash_launch_pipeline"):
                S["show_splash"] = False
                S["app_mode"]    = "pipeline"
                st.rerun()
        else:
            st.markdown(
                "<div style='text-align:center;color:#9ca3af;"
                "font-size:12px;padding:10px 0'>"
                "Connect to a database to launch</div>",
                unsafe_allow_html=True)

        st.markdown("""
        <div style='text-align:center;color:#9ca3af;
                    font-size:11px;margin-top:16px'>
          SQL Server &nbsp;·&nbsp; Oracle &nbsp;·&nbsp; Snowflake
          &nbsp;·&nbsp; Permian &nbsp;·&nbsp; STACK/SCOOP &nbsp;·&nbsp; Williston
        </div>
        """, unsafe_allow_html=True)

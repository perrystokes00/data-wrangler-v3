"""
map_app.py
==========
DataView v3 — Standalone Map Window

Runs on port 8503. Connects to DataView using same .env as the main app.
Launch with run_map.bat or:
    streamlit run map_app.py --server.port 8503

Open in a second browser window and drag to second monitor.
"""
import os
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="DataView Map",
    page_icon="🗺",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Load .env ─────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── Build engine from .env ────────────────────────────────────────────
@st.cache_resource
def _get_engine():
    import urllib.parse
    from sqlalchemy import create_engine

    server   = os.getenv("DB_SERVER", r"127.0.0.1\SQLEXPRESS")
    database = os.getenv("DB_NAME",   "DataView")
    driver   = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
    win_auth = os.getenv("DB_WINDOWS_AUTH", "1") in ("1", "true", "yes")

    if win_auth:
        cs = (f"DRIVER={{{driver}}};SERVER={server};"
              f"DATABASE={database};Trusted_Connection=yes;")
    else:
        user = os.getenv("DB_USERNAME", "")
        pwd  = os.getenv("DB_PASSWORD", "")
        cs   = (f"DRIVER={{{driver}}};SERVER={server};"
                f"DATABASE={database};UID={user};PWD={pwd};")

    try:
        engine = create_engine(
            "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(cs),
            fast_executemany=True,
        )
        with engine.connect() as con:
            from sqlalchemy import text
            con.execute(text("SELECT 1"))
        return engine, None
    except Exception as exc:
        return None, str(exc)


engine, err = _get_engine()

if err:
    st.error(f"Could not connect to DataView: {err}")
    st.info("Check your .env file — DB_SERVER, DB_NAME, DB_WINDOWS_AUTH")
    st.stop()

# ── Run map page ───────────────────────────────────────────────────────
import page_well_map
page_well_map.run(engine)

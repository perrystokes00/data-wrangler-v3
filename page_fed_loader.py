"""
page_fed_loader.py
==================
Federation Loader — Streamlit page.

Flow: Upload -> Parse -> Match & Map (in a form, so editing the grid does NOT
re-run the app) -> Apply -> Save fingerprint -> Stage to SQL Server + validate
-> Push to Snowflake RAW_<ST>.WELL.

Wire into app.py:
    add "📦 Federation Loader" to the sidebar radio list, then:

        elif page == "📦 Federation Loader":
            import page_fed_loader
            page_fed_loader.render()
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

import fed_loader_core as C

FP_DIR = Path("fed_fingerprints")
LEGAL_TYPES = ["", "PLSS", "ABSTRACT", "WARRANT", "OCS", "OTHER"]

# Standard target schema + the standardized match key, in load order.
RAW_COLUMNS = C.TARGET_FIELDS + ["API_14"]


# ── cached parse (so editing the grid never re-reads the file) ──────
@st.cache_data(show_spinner=False)
def _parse(name: str, data: bytes) -> pd.DataFrame | None:
    low = name.lower()
    if low.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(data))
    if low.endswith(".csv"):
        return pd.read_csv(io.BytesIO(data), dtype=str, low_memory=False)
    if low.endswith(".zip"):
        try:
            import geopandas as gpd
        except ImportError:
            return None
        import tempfile
        p = Path(tempfile.gettempdir()) / "fed_upload.zip"
        p.write_bytes(data)
        with zipfile.ZipFile(p) as z:
            shp = next((n for n in z.namelist() if n.lower().endswith(".shp")), None)
        if not shp:
            return None
        gdf = gpd.read_file(f"zip://{p}!{shp}")
        return pd.DataFrame(gdf.drop(columns=gdf.geometry.name, errors="ignore"))
    return None


# ── fingerprint persistence ─────────────────────────────────────────
def _load_fp(sig):
    f = FP_DIR / f"{sig}.json"
    return json.loads(f.read_text()) if f.exists() else None


def _save_fp(sig, payload):
    FP_DIR.mkdir(exist_ok=True)
    (FP_DIR / f"{sig}.json").write_text(json.dumps(payload, indent=2))


# ── connections (built lazily, only when an action runs) ────────────
_COL_LENS = {"UWI": 60, "API_NUM": 40, "WELL_NAME": 255, "WELL_NUM": 40,
             "OPERATOR_NAME": 255, "FIELD_NAME": 255, "COUNTY": 100,
             "PROVINCE_STATE": 20, "WELL_STATUS": 60, "WELL_TYPE": 60,
             "SPUD_DATE": 20, "COMPLETION_DATE": 20, "PLUG_DATE": 20,
             "FINAL_TD": 40, "PRODUCING_FORMATION": 120, "AREA": 100, "API_14": 14}

_SERVER = "127.0.0.1\\SQLEXPRESS"
_DB = "wrangler"


def _run_sqlcmd(query):
    """Run a statement against SQL Express via sqlcmd (trusted, no pyodbc)."""
    import subprocess
    cmd = ["sqlcmd", "-S", _SERVER, "-d", _DB, "-E", "-b", "-Q", query]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "sqlcmd failed").strip()[:500])


def _stage(df, tbl):
    """Stage to SQL Server with no pyodbc anywhere: sqlcmd creates an all-NVARCHAR
    heap, bcp bulk-streams the rows. Rows are written with ASCII Unit/Record
    separators (US/RS) as terminators — those control chars never occur in well
    data, so operator names with commas/quotes load cleanly with no escaping.
    Both tools ship together in Microsoft's SQL command-line utilities.
    Returns (method_label, seconds)."""
    import os, time, shutil, tempfile, subprocess
    missing = [t for t in ("sqlcmd", "bcp") if not shutil.which(t)]
    if missing:
        raise RuntimeError(
            f"{' and '.join(missing)} not found on PATH. Install Microsoft "
            "'Command Line Utilities for SQL Server' (sqlcmd + bcp ship together).")

    t0 = time.time()
    cols = list(df.columns)
    coldef = ", ".join(f"[{c}] NVARCHAR({_COL_LENS.get(c, 50)})" for c in cols)
    _run_sqlcmd(f"IF OBJECT_ID('dbo.{tbl}','U') IS NOT NULL DROP TABLE dbo.{tbl}; "
                f"CREATE TABLE dbo.{tbl} ({coldef});")

    FT, RT = "\x1f", "\x1e"          # ASCII Unit / Record separators
    fd, path = tempfile.mkstemp(suffix=".dat")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            for row in df.itertuples(index=False, name=None):
                f.write(FT.join(
                    "" if (v is None or v != v) else str(v).replace(FT, " ").replace(RT, " ")
                    for v in row))
                f.write(RT)
        cmd = ["bcp", f"{_DB}.dbo.{tbl}", "in", path,
               "-S", _SERVER, "-T", "-c", "-C", "65001",
               "-t", FT, "-r", RT, "-b", "10000"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "bcp failed").strip()[:500])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return "bcp + sqlcmd (no pyodbc)", time.time() - t0


def _snowflake_conn():
    import os
    import snowflake.connector
    return snowflake.connector.connect(
        account=os.environ.get("SNOWFLAKE_ACCOUNT", "YDWXNCV-VL88062"),
        user=os.environ.get("SNOWFLAKE_USER", "PMSTOKES00"),
        password=os.environ.get("SNOWFLAKE_PASSWORD", ""),
        database="WELL_FEDERATION", warehouse="WV_WH", role="ACCOUNTADMIN",
    )


_SF_DDL = """CREATE TABLE WELL (
    UWI VARCHAR(60), API_NUM VARCHAR(40), WELL_NAME VARCHAR(255),
    WELL_NUM VARCHAR(40), OPERATOR_NAME VARCHAR(255), FIELD_NAME VARCHAR(255),
    SURFACE_LATITUDE FLOAT, SURFACE_LONGITUDE FLOAT,
    BOTTOM_LATITUDE FLOAT, BOTTOM_LONGITUDE FLOAT,
    COUNTY VARCHAR(100), PROVINCE_STATE VARCHAR(20),
    WELL_STATUS VARCHAR(60), WELL_TYPE VARCHAR(60),
    SPUD_DATE VARCHAR(20), COMPLETION_DATE VARCHAR(20), PLUG_DATE VARCHAR(20),
    FINAL_TD VARCHAR(40), TVD FLOAT, GROUND_ELEVATION FLOAT, KB_ELEVATION FLOAT,
    PRODUCING_FORMATION VARCHAR(120), AREA VARCHAR(100), API_14 VARCHAR(14)
)"""


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric columns -> float; everything else -> trimmed string/None."""
    out = df.copy()
    num = ["SURFACE_LATITUDE", "SURFACE_LONGITUDE", "BOTTOM_LATITUDE",
           "BOTTOM_LONGITUDE", "TVD", "GROUND_ELEVATION", "KB_ELEVATION"]
    for c in out.columns:
        if c in num:
            out[c] = pd.to_numeric(out[c], errors="coerce")
        else:
            out[c] = out[c].apply(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v))
                                  else str(v).strip() or None)
    return out


def _push_snowflake(df, state):
    from snowflake.connector.pandas_tools import write_pandas
    schema = f"RAW_{re.sub(r'[^A-Z0-9]', '', state.upper())}"
    conn = _snowflake_conn()
    cur = conn.cursor()
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS WELL_FEDERATION.{schema}")
    cur.execute(f"USE SCHEMA WELL_FEDERATION.{schema}")
    cur.execute("DROP TABLE IF EXISTS WELL")
    cur.execute(_SF_DDL)
    ok, nchunks, nrows, _ = write_pandas(conn, df[RAW_COLUMNS], "WELL",
                                         database="WELL_FEDERATION", schema=schema,
                                         auto_create_table=False, chunk_size=50000)
    cur.close()
    conn.close()
    return schema, nrows


# ── the page ────────────────────────────────────────────────────────
def render():
    st.header("📦 Federation Loader")
    st.caption("Upload a state's well file, map it once (the mapping is "
               "remembered), then stage → validate → load into the federation.")

    uploaded = st.file_uploader("Upload source file", type=["xlsx", "xls", "csv", "zip"])
    if uploaded is None:
        st.info("Upload an Excel, CSV, or zipped shapefile to begin.")
        return

    df = _parse(uploaded.name, uploaded.getvalue())
    if df is None or df.empty:
        st.error("Couldn't parse that file (for shapefile zips, geopandas must be installed).")
        return

    sig = C.source_fingerprint(df.columns)
    saved = _load_fp(sig)
    st.success(f"Parsed **{len(df):,} rows**, {len(df.columns)} columns.")
    if saved:
        st.info(f"✓ Recognized this source (`{sig}`) — replaying saved mapping.")
    with st.expander("Preview source rows"):
        st.dataframe(df.head(10), use_container_width=True)

    suggested = (saved or {}).get("mapping") or C.suggest_mapping(df.columns)
    src_options = [""] + list(df.columns)

    # ── grid + constants live INSIDE a form: editing them does not rerun ──
    with st.form("fed_form"):
        st.subheader("Match & map")
        grid = pd.DataFrame({
            "Target field": C.TARGET_FIELDS,
            "Source column": [suggested.get(t) or "" for t in C.TARGET_FIELDS],
        })
        edited = st.data_editor(
            grid, hide_index=True, use_container_width=True,
            disabled=["Target field"],
            column_config={"Source column": st.column_config.SelectboxColumn(
                "Source column", options=src_options, required=False)},
            key=f"grid_{sig}",
        )
        c1, c2, c3 = st.columns(3)
        state_code = c1.text_input("State (e.g. CO)", value=(saved or {}).get("province_state", ""))
        source_id = c2.text_input("Source ID (e.g. CO_ECMC)", value=(saved or {}).get("source_id", ""))
        legal = c3.selectbox("Legal survey type", LEGAL_TYPES,
                             index=LEGAL_TYPES.index((saved or {}).get("legal_survey_type", ""))
                             if (saved or {}).get("legal_survey_type", "") in LEGAL_TYPES else 0)
        u1, u2 = st.columns(2)
        std_uwi = u1.checkbox("Build standardized 14-char API", value=(saved or {}).get("std_uwi", True))
        api_state = u2.text_input("API state code (blank = auto from state)",
                                  value=(saved or {}).get("api_state", ""))
        st.markdown("**Filters** (optional)")
        f1, f2, f3 = st.columns([2, 2, 1])
        drop_field = f1.selectbox("Drop rows where field…", [""] + C.TARGET_FIELDS,
                                  index=([""] + C.TARGET_FIELDS).index((saved or {}).get("drop_field", ""))
                                  if (saved or {}).get("drop_field", "") in ([""] + C.TARGET_FIELDS) else 0)
        drop_values = f2.text_input("…is one of (comma-sep, e.g. LO)",
                                    value=(saved or {}).get("drop_values", ""))
        dedupe = f3.checkbox("Dedupe UWI", value=(saved or {}).get("dedupe", True))
        applied = st.form_submit_button("✓ Apply mapping", type="primary")

    if applied:
        st.session_state[f"map_{sig}"] = {
            "mapping": {r["Target field"]: (r["Source column"] or None) for _, r in edited.iterrows()},
            "province_state": state_code, "source_id": source_id,
            "legal_survey_type": legal, "std_uwi": std_uwi,
            "api_state": api_state or C.api_state_code(state_code) or "",
            "drop_field": drop_field, "drop_values": drop_values, "dedupe": dedupe,
        }

    cfg = st.session_state.get(f"map_{sig}")
    if not cfg:
        st.info("Set the mapping and constants above, then click **Apply mapping**.")
        return

    # normalized preview + validation (on the full df)
    norm = C.apply_mapping(df, cfg["mapping"], province_state=cfg["province_state"],
                           std_uwi=cfg["std_uwi"], api_state=cfg["api_state"],
                           county_ref=C.load_county_ref())
    norm = _coerce(norm)
    raw_n = len(norm)
    if cfg.get("drop_field") and cfg.get("drop_values"):
        norm = C.filter_rows(norm, cfg["drop_field"],
                             [v.strip() for v in cfg["drop_values"].split(",")])
    if cfg.get("dedupe"):
        norm = norm.drop_duplicates(subset=["UWI"])
    if len(norm) != raw_n:
        st.caption(f"Filtered/deduped: {raw_n:,} → {len(norm):,} rows.")
    st.subheader("Normalized preview")
    st.dataframe(norm[["UWI", "API_NUM", "API_14", "SURFACE_LATITUDE",
                       "SURFACE_LONGITUDE", "COUNTY", "PROVINCE_STATE",
                       "WELL_TYPE", "PRODUCING_FORMATION"]].head(8),
                 use_container_width=True)
    checks = C.validate(norm)
    st.write({k: f"{v:,}" if isinstance(v, int) else v for k, v in checks.items()})

    st.divider()
    b1, b2, b3 = st.columns(3)

    if b1.button("💾 Save mapping"):
        if not cfg["province_state"] or not cfg["source_id"]:
            st.warning("Set State and Source ID first.")
        else:
            _save_fp(sig, {**cfg, "columns": list(df.columns)})
            st.success(f"Saved fingerprint `{sig}`.")

    if b2.button("🗄️ Stage to SQL Server + validate"):
        try:
            tbl = "stg_" + re.sub(r"[^a-z0-9]", "_", (cfg["source_id"] or "src").lower())
            with st.spinner(f"Writing {len(norm):,} rows to {tbl}…"):
                method, secs = _stage(norm[RAW_COLUMNS], tbl)
            st.success(f"Staged to SQL Server `{tbl}` ({len(norm):,} rows) "
                       f"via {method} in {secs:.1f}s. Validate it there, then push to Snowflake.")
        except Exception as e:
            st.error(f"Staging failed: {e}")

    if b3.button("❄️ Push to Snowflake RAW", type="primary"):
        if not cfg["province_state"]:
            st.warning("Set State first.")
        else:
            try:
                with st.spinner("Loading to Snowflake…"):
                    schema, nrows = _push_snowflake(norm, cfg["province_state"])
                st.success(f"Loaded {nrows:,} rows into WELL_FEDERATION.{schema}.WELL. "
                           f"Next: add the {cfg['source_id']} branch to the view + re-CTAS.")
            except Exception as e:
                st.error(f"Snowflake load failed: {e}")

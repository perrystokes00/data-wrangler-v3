"""
page_catalog_search.py
======================
General-purpose search across file_catalog.GLOBAL_FILE_CATALOG.

Covers all document types cataloged by Data Wrangler:
  Well Logs   — LAS, DLIS, LIS
  Seismic     — SEG-Y, P190
  Spatial     — Shapefile, GeoJSON
  Documents   — PDF, Excel, Word
  Other       — any file inventoried via the scan

Search fields: FILE_NAME, WELL_NAME, UWI, OPERATOR, SUMMARY_DESCRIPTION
Filters:       DOC_TYPE / FILE_EXT, CATALOG_STATUS, PPDM_LOADED_IND, date range
"""
import streamlit as st
import pandas as pd
from sqlalchemy import text
from pathlib import Path


# ── Table name per dialect ────────────────────────────────────────────────────
def _tbl(dialect: str) -> str:
    if dialect == "oracle":    return "FILE_CATALOG_GLOBAL_FILE_CATALOG"
    if dialect == "snowflake": return '"FILE_CATALOG"."GLOBAL_FILE_CATALOG"'
    return "file_catalog.GLOBAL_FILE_CATALOG"


def _top(n: int, dialect: str) -> str:
    return f"TOP {n}" if dialect == "mssql" else ""

def _limit(n: int, dialect: str) -> str:
    return f"LIMIT {n}" if dialect != "mssql" else ""


# ── Document type groups ──────────────────────────────────────────────────────
DOC_TYPE_GROUPS = {
    "All":          [],
    "Well Logs":    ["LAS", "DLIS", "LIS"],
    "Seismic":      ["SEGY", "P190", "SEG-Y"],
    "Spatial":      ["SHP_WELL", "SHP_FIELD", "SHP_LEASE", "SHP_SEISMIC_2D",
                     "SHP_SEISMIC_3D", "SHP_PIPELINE", "SHP_FACILITY",
                     "SHP_BOUNDARY", "SHAPEFILE"],
    "PDF Reports":  ["DIRECTIONAL_SURVEY", "FORMATION_TOPS", "CORE",
                     "DST", "MUD_LOG", "COMPLETION_REPORT"],
    "Office Docs":  ["EXCEL", "WORD"],
    "Unknown":      ["UNKNOWN"],
}

EXT_GROUPS = {
    "Well Logs":   [".las", ".dlis", ".dlf", ".dis", ".lis"],
    "Seismic":     [".segy", ".sgy", ".seg", ".p190", ".p1", ".p90"],
    "Spatial":     [".shp", ".geojson", ".gpkg", ".kml"],
    "PDF Reports": [".pdf"],
    "Office Docs": [".xlsx", ".xls", ".xlsm", ".docx", ".doc"],
}


def run(engine=None, dialect: str = "mssql"):
    if st.button("← File Catalog", key="search_back"):
        st.session_state["file_catalog_domain"] = None
        st.session_state.app_mode = "file_catalog"
        st.rerun()

    st.title("🔍 Catalog Search")
    st.caption(
        "Search all cataloged documents — well logs, seismic, shapefiles, "
        "PDFs, Excel and Word files."
    )

    if engine is None:
        st.warning("No database connection — connect via the pipeline first.")
        return

    # ── Search controls ───────────────────────────────────────────────────────
    c1, c2 = st.columns([3, 1])
    with c1:
        q = st.text_input(
            "Search",
            placeholder="Well name, UWI, filename, operator or keyword…",
            key="cs_query",
        )
    with c2:
        max_results = st.selectbox(
            "Max results", [50, 100, 250, 500], key="cs_max"
        )

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        doc_group = st.selectbox(
            "Document type",
            list(DOC_TYPE_GROUPS.keys()),
            key="cs_doctype"
        )
    with f2:
        status_filter = st.selectbox(
            "Catalog status",
            ["All", "CATALOGED", "PENDING", "SKIPPED"],
            key="cs_status"
        )
    with f3:
        ppdm_filter = st.selectbox(
            "PPDM loaded",
            ["All", "Yes", "No"],
            key="cs_ppdm"
        )
    with f4:
        sort_by = st.selectbox(
            "Sort by",
            ["Date cataloged ↓", "File name ↑", "Well name ↑", "Type"],
            key="cs_sort"
        )

    # ── Build query ───────────────────────────────────────────────────────────
    if st.button("🔍 Search", type="primary", key="cs_btn") or q:
        _run_search(engine, dialect, q, doc_group, status_filter,
                    ppdm_filter, sort_by, max_results)


def _run_search(engine, dialect, q, doc_group, status_filter,
                ppdm_filter, sort_by, max_results):
    tbl    = _tbl(dialect)
    params = {}
    wheres = []

    # Free text
    if q and q.strip():
        pct = f"%{q.strip()}%"
        params["q"] = pct
        wheres.append(
            "(FILE_NAME LIKE :q OR WELL_NAME LIKE :q OR UWI LIKE :q "
            "OR OPERATOR LIKE :q OR SUMMARY_DESCRIPTION LIKE :q)"
        )

    # Document type group — try DOC_TYPE column first, fall back to FILE_EXT
    types = DOC_TYPE_GROUPS.get(doc_group, [])
    exts  = EXT_GROUPS.get(doc_group, [])
    if types or exts:
        clauses = []
        if types:
            placeholders = ", ".join(f":dt{i}" for i in range(len(types)))
            for i, t in enumerate(types):
                params[f"dt{i}"] = t
            clauses.append(
                f"COALESCE(DOC_TYPE, REPORT_TYPE, '') IN ({placeholders})"
            )
        if exts:
            placeholders = ", ".join(f":ex{i}" for i in range(len(exts)))
            for i, e in enumerate(exts):
                params[f"ex{i}"] = e
            clauses.append(f"LOWER(FILE_EXT) IN ({placeholders})")
        wheres.append("(" + " OR ".join(clauses) + ")")

    # Status
    if status_filter != "All":
        params["status"] = status_filter
        wheres.append("CATALOG_STATUS = :status")

    # PPDM loaded
    if ppdm_filter == "Yes":
        wheres.append("PPDM_LOADED_IND = 'Y'")
    elif ppdm_filter == "No":
        wheres.append("(PPDM_LOADED_IND = 'N' OR PPDM_LOADED_IND IS NULL)")

    # Sort
    order = {
        "Date cataloged ↓": "ROW_CREATED_DATE DESC",
        "File name ↑":      "FILE_NAME ASC",
        "Well name ↑":      "WELL_NAME ASC",
        "Type":             "COALESCE(DOC_TYPE, FILE_EXT) ASC, FILE_NAME ASC",
    }.get(sort_by, "ROW_CREATED_DATE DESC")

    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    top_sql   = _top(max_results, dialect)
    lim_sql   = _limit(max_results, dialect)

    sql = f"""
        SELECT {top_sql}
            INVENTORY_ID,
            COALESCE(DOC_TYPE, REPORT_TYPE, FILE_EXT, '?') AS DOC_TYPE,
            FILE_NAME,
            WELL_NAME,
            UWI,
            OPERATOR,
            COALESCE(SUMMARY_DESCRIPTION, '') AS SUMMARY,
            CATALOG_STATUS,
            COALESCE(PPDM_LOADED_IND, 'N')   AS PPDM_LOADED,
            PPDM_TABLE_TARGET,
            FILE_PATH,
            FILE_SIZE_KB,
            ROW_CREATED_DATE
        FROM {tbl}
        {where_sql}
        ORDER BY {order}
        {lim_sql}
    """

    try:
        with engine.connect() as con:
            rows = con.execute(text(sql), params).fetchall()
    except Exception as e:
        st.error(f"Search failed: {e}")
        return

    if not rows:
        st.info("No results found.")
        return

    df = pd.DataFrame(rows, columns=[
        "ID", "Type", "File", "Well", "UWI", "Operator",
        "Summary", "Status", "PPDM", "PPDM Target",
        "Path", "KB", "Cataloged"
    ])

    st.caption(f"**{len(df):,}** result(s)"
               + (f" (showing first {max_results})" if len(df) == max_results else ""))

    # ── Results table ─────────────────────────────────────────────────────────
    # Add digital data indicator
    _LOADABLE = {"DIRECTIONAL_SURVEY","FORMATION_TOPS","CORE","DST",
                 "RFT_MDT","SCOUT_TICKET","WELL_TEST","CASING_CEMENTING"}
    _EXTRACT  = {"DAILY_DRILLING_REPORT","PETROPHYSICAL","END_OF_WELL"}

    def _dd_badge(rt):
        if rt in _LOADABLE:  return "✅ Load to PPDM"
        if rt in _EXTRACT:   return "📊 Extract only"
        ext = rt.lower() if rt else ""
        if any(ext.endswith(e) for e in [".las",".dlis",".sgy",".segy",".p190"]):
            return "✅ Load to PPDM"
        return "📄 View only"

    df["Digital Data"] = df["Type"].apply(
        lambda t: _dd_badge(t.split(" ", 1)[-1].strip() if " " in t else t)
    )

    display_df = df[[
        "Type", "File", "Well", "UWI", "Operator",
        "Summary", "Digital Data", "Status", "PPDM", "KB", "Cataloged"
    ]].copy()
    # Ensure all object columns are str to avoid Arrow serialization errors
    for _c in display_df.select_dtypes(include="object").columns:
        display_df[_c] = display_df[_c].astype(str).replace("None", "—").replace("nan", "—")

    # Status badges
    display_df["Status"] = display_df["Status"].map(
        lambda s: {"CATALOGED": "✅ Cataloged",
                   "PENDING":   "⏳ Pending",
                   "SKIPPED":   "⏭ Skipped"}.get(s, s or "—")
    )
    display_df["PPDM"] = display_df["PPDM"].map(
        lambda v: "✅ Yes" if v == "Y" else "—"
    )

    st.dataframe(
        display_df,
        hide_index=True,
        use_container_width=True,
        height=min(38 + len(display_df) * 35, 500),
        column_config={
            "Type":     st.column_config.TextColumn(width="small"),
            "File":     st.column_config.TextColumn(width="medium"),
            "Well":     st.column_config.TextColumn(width="medium"),
            "UWI":      st.column_config.TextColumn(width="medium"),
            "Summary":  st.column_config.TextColumn(width="large"),
            "Status":   st.column_config.TextColumn(width="small"),
            "PPDM":     st.column_config.TextColumn(width="small"),
            "KB":       st.column_config.NumberColumn(width="small", format="%.1f"),
            "Cataloged":st.column_config.DatetimeColumn(width="small",
                                                         format="YYYY-MM-DD"),
        },
    )

    # ── Detail expander for selected row ─────────────────────────────────────
    st.divider()
    st.markdown("**File detail**")
    file_opts = {f"{r['File']}  —  {r['Well'] or ''}  {r['UWI'] or ''}": i
                 for i, r in df.iterrows()}
    sel_label = st.selectbox("Select file to inspect",
                             ["— select —"] + list(file_opts.keys()),
                             key="cs_sel")

    if sel_label and sel_label != "— select —":
        row = df.iloc[file_opts[sel_label]]
        with st.container(border=True):
            d1, d2, d3 = st.columns(3)
            d1.markdown(f"**File**  \n`{row['File']}`")
            d2.markdown(f"**Well**  \n{row['Well'] or '—'}")
            d3.markdown(f"**UWI**  \n{row['UWI'] or '—'}")

            d4, d5, d6 = st.columns(3)
            d4.markdown(f"**Type**  \n{row['Type']}")
            d5.markdown(f"**PPDM Target**  \n{row['PPDM Target'] or '—'}")
            d6.markdown(f"**Size**  \n{row['KB']:.1f} KB")

            if row["Summary"]:
                st.info(row["Summary"])

            st.caption(f"`{row['Path']}`")

            # Quick-open shortcuts
            ext = Path(str(row["Path"])).suffix.lower()
            c_open, c_domain = st.columns(2)
            with c_open:
                if st.button("📂 Open folder", key=f"cs_open_{row['ID']}"):
                    import subprocess, os
                    folder = str(Path(row["Path"]).parent)
                    try:
                        if os.name == "nt":
                            subprocess.Popen(["explorer", folder])
                        else:
                            subprocess.Popen(["xdg-open", folder])
                    except Exception as _oe:
                        st.warning(f"Could not open folder: {_oe}")

            with c_domain:
                # Route to the right catalog page
                _ext_domain = {
                    ".las": "wells", ".dlis": "wells", ".lis": "wells",
                    ".segy": "seismic", ".sgy": "seismic", ".p190": "seismic",
                    ".shp": "spatial", ".geojson": "spatial",
                    ".pdf": "pdf",
                    ".xlsx": "docs", ".xls": "docs",
                    ".docx": "docs", ".doc": "docs",
                }.get(ext)
                if _ext_domain:
                    if st.button(f"→ Open in catalog",
                                 key=f"cs_goto_{row['ID']}"):
                        st.session_state["file_catalog_domain"] = _ext_domain
                        st.rerun()

    # ── Export ────────────────────────────────────────────────────────────────
    st.download_button(
        "⬇ Export results CSV",
        data=display_df.to_csv(index=False),
        file_name="catalog_search_results.csv",
        mime="text/csv",
        key="cs_export",
    )

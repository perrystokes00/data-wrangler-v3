"""
page_pdf_catalog.py  --  PDF, Shapefile, Word/Excel Catalog
============================================================
Flow: Scan -> View & Extract -> Flat File -> Batch Load

All three file type groups follow the same pattern:
  1. Scan    -- crawl folder, classify files
  2. View & Extract -- view file, extract data, catalog good files
  3. Flat File -- export headers for well creation
  4. Batch Load -- re-extract from catalog once wells exist
"""
import base64
import streamlit as st
from pathlib import Path

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    from modules.doc_catalog_store import catalog_document as _catalog_document
    _STORE_OK = True
except ImportError:
    _STORE_OK = False
    def _catalog_document(**kw): return {"ok": False, "error": "doc_catalog_store missing"}

try:
    from modules.pdf_survey_catalog import (
        scan_directory as _pdf_scan_dir,
        classify_pdf,
        extract_stations, validate_stations, load_to_ppdm,
        RT_DIRECTIONAL, RT_MUDLOG, RT_FORMATION,
        RT_COMPLETION, RT_UNKNOWN,
        RT_RFT, RT_SCOUT, RT_DDR, RT_WELL_TEST,
        RT_PETRO, RT_EOWR, RT_CASING,
        extended_classify_pdf,
        extract_rft_data, extract_scout_ticket, extract_ddr,
        extract_well_test, extract_petrophysical,
        extract_eowr, extract_casing_cement,
    )
    _PDF_OK = True
except ImportError as _ce:
    _PDF_OK = False
    _PDF_ERR = str(_ce)
    RT_DIRECTIONAL = "DIRECTIONAL_SURVEY"; RT_MUDLOG = "MUD_LOG"
    RT_FORMATION = "FORMATION_TOPS"; RT_COMPLETION = "COMPLETION"
    RT_UNKNOWN = "UNKNOWN"; RT_RFT = RT_SCOUT = RT_DDR = "UNKNOWN"
    RT_WELL_TEST = RT_PETRO = RT_EOWR = RT_CASING = "UNKNOWN"
    def _pdf_scan_dir(*a, **kw): return []
    def classify_pdf(*a, **kw): return {"report_type": RT_UNKNOWN}
    def extract_stations(*a, **kw): return {"stations": [], "error": "missing"}
    def extended_classify_pdf(*a, **kw): return {"report_type": RT_UNKNOWN}
    def validate_stations(*a, **kw): return {"valid": False, "errors": [], "warnings": []}
    def load_to_ppdm(*a, **kw): return {"loaded": 0, "errors": []}
    def extract_rft_data(*a, **kw): return {}
    def extract_scout_ticket(*a, **kw): return {}
    def extract_ddr(*a, **kw): return {}
    def extract_well_test(*a, **kw): return {}
    def extract_petrophysical(*a, **kw): return {}
    def extract_eowr(*a, **kw): return {}
    def extract_casing_cement(*a, **kw): return {}

try:
    from modules.shapefile_catalog import (
        scan_directory as _shp_scan_dir,
        classify_shapefile,
        load_to_ppdm as _shp_load_to_ppdm,
    )
    _SHP_OK = True
except ImportError as _se:
    _SHP_OK = False
    _SHP_ERR = str(_se)
    def _shp_scan_dir(*a, **kw): return []
    def classify_shapefile(*a, **kw): return {}
    def _shp_load_to_ppdm(*a, **kw): return {"loaded": 0, "errors": []}

try:
    from modules.file_summarizer import summarize as _summarize
    _SUM_OK = True
except ImportError as _oe:
    _SUM_OK = False
    _SUM_ERR = str(_oe)
    def _summarize(*a, **kw): return {}

def _scroll_top():
    """Inject JS to scroll the Streamlit app back to the top."""
    st.components.v1.html(
        "<script>window.parent.document.querySelector("
        "'.main').scrollTo({top:0,behavior:'instant'});</script>",
        height=0
    )


# ── Constants ──────────────────────────────────────────────────────────────────
RT_CORE = "CORE"
RT_DST  = "DST"

PDF_ICONS = {
    RT_DIRECTIONAL: "📐", RT_MUDLOG: "📊", RT_FORMATION: "🪨",
    RT_COMPLETION:  "🔧", RT_CORE:   "🧪", RT_DST:       "💧",
    RT_UNKNOWN:     "❓", RT_RFT:    "💉", RT_SCOUT:     "🎫",
    RT_DDR:         "📋", RT_WELL_TEST: "🧪", RT_PETRO:  "📈",
    RT_EOWR:        "📝", RT_CASING: "🔩",
}
PDF_LABELS = {
    RT_DIRECTIONAL: "Directional Survey",  RT_MUDLOG:    "Mud Log",
    RT_FORMATION:   "Formation Tops",      RT_COMPLETION:"Completion Report",
    RT_CORE:        "Core Data",           RT_DST:       "Drill Stem Test",
    RT_UNKNOWN:     "Unknown / Other",     RT_RFT:       "RFT / MDT",
    RT_SCOUT:       "Scout Ticket",        RT_DDR:       "Daily Drilling Report",
    RT_WELL_TEST:   "Well Test Report",    RT_PETRO:     "Petrophysical Report",
    RT_EOWR:        "End of Well Report",  RT_CASING:    "Casing & Cementing",
}
PDF_EXTRACTABLE = {
    RT_DIRECTIONAL, RT_FORMATION, RT_CORE, RT_DST,
    RT_RFT, RT_SCOUT, RT_DDR, RT_WELL_TEST,
    RT_PETRO, RT_EOWR, RT_CASING,
}

PDF_EXTS    = {".pdf"}
SHP_EXTS    = {".shp", ".geojson", ".gpkg", ".kml", ".kmz"}
OFFICE_EXTS = {".xlsx", ".xls", ".xlsm", ".docx", ".doc", ".csv", ".tsv"}



# =============================================================================
# Navigation helper
# =============================================================================

def _nav_select(files: list, prefix: str,
                name_key: str, path_key: str) -> tuple:
    """
    Prev / Next navigation through a file list.
    Returns (frow, fpath).
    Skips already-cataloged files when using Next.
    """
    n = len(files)
    idx_key = f"{prefix}_nav_idx"

    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0

    idx = st.session_state[idx_key]
    idx = max(0, min(idx, n - 1))

    # Navigation bar
    col_prev, col_info, col_next, col_jump = st.columns([1, 3, 1, 2])

    with col_prev:
        if st.button("◀ Prev", key=f"{prefix}_prev_btn",
                     disabled=(idx == 0)):
            st.session_state[idx_key] = idx - 1
            st.rerun()

    with col_next:
        if st.button("Next ▶", key=f"{prefix}_next_btn",
                     disabled=(idx >= n - 1)):
            st.session_state[idx_key] = idx + 1
            st.rerun()

    with col_info:
        frow = files[idx]
        _ckey = f"{prefix}_cataloged_{frow[path_key]}"
        is_cat = st.session_state.get(_ckey, False)
        cat_badge = " ✅" if is_cat else ""
        st.markdown(
            f"**{idx + 1} / {n}**{cat_badge}  "
            f"`{frow[name_key]}`"
        )

    with col_jump:
        # Quick jump selectbox
        names = [f["file_name"] for f in files]
        jumped = st.selectbox("Jump to", names, index=idx,
                              key=f"{prefix}_jump_sel",
                              label_visibility="collapsed")
        jump_idx = names.index(jumped)
        if jump_idx != idx:
            st.session_state[idx_key] = jump_idx
            st.rerun()

    frow  = files[idx]
    fpath = frow[path_key]
    return frow, fpath


def _advance_nav(prefix: str):
    """
    After cataloging, advance to the next uncataloged file.
    If all are cataloged, wrap to index 0.
    """
    files = st.session_state.get(f"{prefix}_classified", [])
    if not files:
        return
    idx_key = f"{prefix}_nav_idx"
    cur = st.session_state.get(idx_key, 0)
    n   = len(files)
    # Search forward for next uncataloged
    for offset in range(1, n):
        candidate = (cur + offset) % n
        f = files[candidate]
        _ckey = f"{prefix}_cataloged_{f['file_path']}"
        if not st.session_state.get(_ckey, False):
            st.session_state[idx_key] = candidate
            return
    # All cataloged — go to top
    st.session_state[idx_key] = 0

# =============================================================================
# Entry point
# =============================================================================

def run(engine=None, dialect: str = "mssql"):
    st.title("📂 File Catalog")
    st.caption("PDF · Shapefile · Word/Excel  —  Scan → View & Extract → Flat File → Batch Load")

    mode = st.radio("File type", ["📄 PDF", "🗺️ Shapefile", "📊 Excel / Word"],
                    horizontal=True, key="catalog_mode")

    st.divider()

    if mode == "📄 PDF":
        _run_pdf(engine, dialect)
    elif mode == "🗺️ Shapefile":
        _run_shapefile(engine, dialect)
    else:
        _run_office(engine, dialect)


# =============================================================================
# ── PDF ──────────────────────────────────────────────────────────────────────
# =============================================================================

def _run_pdf(engine, dialect):
    tabs = st.tabs(["🔍 Scan", "📄 View & Extract", "📋 Flat File", "🚀 Batch Load"])
    with tabs[0]: _pdf_scan()
    with tabs[1]: _pdf_view_extract(engine, dialect)
    with tabs[2]: _flat_file("pdf")
    with tabs[3]: _batch_load(engine, dialect, "pdf")


# ── PDF Scan ──────────────────────────────────────────────────────────────────

def _pdf_scan():
    import pandas as pd
    st.markdown("#### 🔍 Scan for PDF Files")
    scan_path = st.text_input("Folder to scan",
                              placeholder=r"C:\WellData\Reports",
                              key="pdf_scan_path")
    c1, c2 = st.columns(2)
    if c1.button("🔍 Scan", type="primary", key="pdf_scan_btn"):
        if not scan_path or not Path(scan_path).exists():
            st.error("Folder not found.")
        else:
            with st.spinner("Scanning..."):
                files = _pdf_scan_dir(scan_path)
            prog = st.progress(0, text="Classifying...")
            classified = []
            for i, f in enumerate(files):
                prog.progress((i + 1) / max(len(files), 1),
                              text=f"Classifying {f['file_name']}...")
                cl = classify_pdf(f["file_path"])
                if cl.get("report_type") == RT_UNKNOWN:
                    try:
                        ext = extended_classify_pdf(f["file_path"])
                        if ext.get("report_type") != RT_UNKNOWN:
                            cl["report_type"] = ext["report_type"]
                    except Exception:
                        pass
                cl.update({k: v for k, v in f.items() if k not in cl})
                classified.append(cl)
            prog.empty()
            st.session_state["pdf_classified"] = classified
            st.session_state.pop("pdf_flat_rows", None)
            st.rerun()

    if c2.button("🗑️ Clear", key="pdf_clear_btn"):
        for k in ["pdf_classified", "pdf_flat_rows"]:
            st.session_state.pop(k, None)
        st.rerun()

    files = st.session_state.get("pdf_classified", [])
    if not files:
        return

    st.divider()
    type_counts = {}
    for f in files:
        rt = f.get("report_type", RT_UNKNOWN)
        type_counts[rt] = type_counts.get(rt, 0) + 1
    present = [(rt, lbl) for rt, lbl in PDF_LABELS.items()
               if type_counts.get(rt, 0) > 0]
    if present:
        cols = st.columns(min(len(present), 6))
        for i, (rt, lbl) in enumerate(present):
            cols[i % 6].metric(f"{PDF_ICONS[rt]} {lbl}", type_counts[rt])
    st.divider()

    rows = []
    for f in files:
        rt = f.get("report_type", RT_UNKNOWN)
        rows.append({
            "Type":     f"{PDF_ICONS.get(rt,'*')} {PDF_LABELS.get(rt, rt)}",
            "File":     f["file_name"],
            "UWI":      f.get("uwi") or "--",
            "Well":     f.get("well_name") or "--",
            "Operator": f.get("operator") or "--",
            "Field":    f.get("field") or "--",
            "State":    f.get("state") or "--",
            "Lat":      f.get("latitude") or "--",
            "Lon":      f.get("longitude") or "--",
            "TD":       f.get("total_depth") or "--",
            "Conf.":    f"{f.get('confidence', 0) * 100:.0f}%",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.download_button("⬇ Export scan CSV", data=df.to_csv(index=False),
                       file_name="pdf_scan.csv", mime="text/csv",
                       key="pdf_scan_export")


# ── PDF View & Extract ────────────────────────────────────────────────────────

def _pdf_view_extract(engine, dialect):
    import pandas as pd

    files = st.session_state.get("pdf_classified", [])
    if not files:
        fpath = st.text_input("PDF path", placeholder=r"C:\WellData\survey.pdf",
                              key="pdf_manual_path")
        if not fpath:
            st.info("Run a scan first, or paste a file path above.")
            return
        if not Path(fpath).exists():
            st.error(f"File not found: `{fpath}`")
            return
        frow = {"file_path": fpath, "file_name": Path(fpath).name,
                "report_type": RT_UNKNOWN}
    else:
        frow, fpath = _nav_select(files, "pdf", "file_name", "file_path")

    rt = frow.get("report_type", RT_UNKNOWN)
    st.session_state["pdf_viewed_file"] = fpath
    st.caption(f"`{fpath}` · {Path(fpath).stat().st_size / 1024:.1f} KB")

    with st.expander("📄 View PDF", expanded=False):
        try:
            b64 = base64.b64encode(Path(fpath).read_bytes()).decode()
            h   = st.slider("Height (px)", 400, 1200, 700, 50, key="pdf_h")
            st.markdown(
                f'<iframe src="data:application/pdf;base64,{b64}" '
                f'width="100%" height="{h}px" style="border:none;border-radius:8px;"></iframe>',
                unsafe_allow_html=True)
        except Exception as e:
            st.error(f"PDF render failed: {e}")

    st.divider()
    st.markdown(f"**{PDF_ICONS.get(rt,'📄')} {PDF_LABELS.get(rt,'Document')}**")

    _attr_pairs = [
        ("UWI / API",     frow.get("uwi")),
        ("Well Name",     frow.get("well_name")),
        ("Operator",      frow.get("operator")),
        ("Field",         frow.get("field")),
        ("State",         frow.get("state")),
        ("County",        frow.get("county")),
        ("Latitude",      frow.get("latitude")),
        ("Longitude",     frow.get("longitude")),
        ("Total Depth",   frow.get("total_depth")),
        ("Spud Date",     frow.get("spud_date")),
        ("Rig Release",   frow.get("rig_release")),
        ("Survey Type",   frow.get("survey_type")),
        ("Contractor",    frow.get("contractor")),
        ("Confidence",    f"{int(frow.get('confidence', 0) * 100)}%"
                          if frow.get("confidence") else None),
        ("Station Count", str(frow.get("station_count", 0))
                          if frow.get("station_count") else None),
        ("Page Count",    str(frow.get("page_count", ""))),
    ]
    _hdf = pd.DataFrame(
        [{"Attribute": k, "Value": str(v)}
         for k, v in _attr_pairs if v and v not in ("None", "0", "")]
    )
    if not _hdf.empty:
        with st.expander("📋 Extracted header attributes", expanded=True):
            st.dataframe(_hdf, hide_index=True, use_container_width=True)

    st.divider()

    if rt == RT_DIRECTIONAL:
        _pdf_extract_directional(frow)
    elif rt == RT_FORMATION:
        _pdf_extract_formation(frow)
    elif rt == RT_CORE:
        _pdf_extract_core(frow)
    elif rt == RT_DST:
        _pdf_extract_dst(frow)
    elif rt == RT_RFT:
        _pdf_extract_rft(frow)
    elif rt == RT_SCOUT:
        _pdf_extract_scout(frow)
    elif rt == RT_DDR:
        _pdf_extract_ddr(frow)
    elif rt == RT_WELL_TEST:
        _pdf_extract_well_test(frow)
    elif rt == RT_PETRO:
        _pdf_extract_petro(frow)
    elif rt == RT_EOWR:
        _pdf_extract_eowr(frow)
    elif rt == RT_CASING:
        _pdf_extract_casing(frow)
    else:
        st.info("View only — no structured extraction for this report type.")
        with st.expander("📝 Raw text (first 3 pages)", expanded=False):
            try:
                import pdfplumber
                with pdfplumber.open(fpath) as pdf:
                    for i, page in enumerate(pdf.pages[:3]):
                        st.markdown(f"**Page {i + 1}**")
                        st.text((page.extract_text() or "(no text)")[:3000])
            except Exception as e:
                st.warning(f"Text extraction unavailable: {e}")

    st.divider()
    _catalog_section(engine, dialect, frow, "pdf")


# ── PDF extractors ────────────────────────────────────────────────────────────

def _pdf_extract_directional(frow):
    import pandas as pd
    fpath = frow["file_path"]
    stype = st.selectbox("Survey type",
                         ["MWD", "Gyro", "Magnetic", "Accelerometer"],
                         key="pdf_stype")
    _fkey = f"pdf_dir_{fpath}"

    if st.button("📐 Extract Stations", type="primary", key="pdf_dir_btn"):
        with st.spinner("Extracting..."):
            ext = extract_stations(fpath)
        st.session_state[_fkey] = ext

    ext = st.session_state.get(_fkey)
    if not ext:
        return
    if ext.get("error"):
        st.error(f"Extraction error: {ext['error']}")
        return
    stations = ext.get("stations", [])
    if not stations:
        st.warning("No stations extracted.")
        return
    val = validate_stations(stations)
    m1, m2, m3 = st.columns(3)
    m1.metric("Stations", len(stations))
    m2.metric("MD range", val.get("md_range", "--"))
    m3.metric("Status", "✅ Valid" if val["valid"] else "⚠️ Errors")
    for e in val.get("errors", []):   st.error(e)
    for w in val.get("warnings", []): st.warning(w)

    df = pd.DataFrame(stations)
    _co = [c for c in ["MD","INC","AZI","TVD","NS","EW","DLS","VSEC"] if c in df.columns]
    df = df[_co + [c for c in df.columns if c not in _co]]
    st.dataframe(df.round(2), hide_index=True, use_container_width=True, height=220)

    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        mds  = [s.get("MD",0)  for s in stations]
        incs = [s.get("INC",0) for s in stations]
        tvds = [s.get("TVD",0) for s in stations]
        ns   = [s.get("NS",0)  for s in stations]
        ew   = [s.get("EW",0)  for s in stations]
        N="#1A2B4A"; G="#C8922A"
        fig = make_subplots(rows=1, cols=3,
            subplot_titles=("Inc vs Depth","Plan View","Cross Section"),
            horizontal_spacing=0.08)
        for c, (x, y) in enumerate([(incs,mds),(ew,ns),(ew,[-t for t in tvds])],1):
            fig.add_trace(go.Scatter(x=x,y=y,mode="lines+markers",
                line=dict(color=N,width=2),marker=dict(size=4,color=G)),row=1,col=c)
        fig.update_yaxes(autorange="reversed",title_text="MD (ft)",row=1,col=1)
        fig.update_layout(height=280,margin=dict(l=10,r=10,t=30,b=10),
            showlegend=False,paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",font=dict(size=10))
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        pass

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇ Download CSV", data=df.to_csv(index=False),
            file_name="dir_survey_stations.csv", mime="text/csv", key="pdf_dir_dl")
    with c2:
        _save_flat_btn(frow, RT_DIRECTIONAL, stations, "pdf_dir_save")


def _pdf_extract_formation(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("🪨 Extract Formation Tops", type="primary", key="pdf_form_btn"):
        with st.spinner("Extracting..."):
            rows = _parse_formation_tops(fpath)
        st.session_state[f"pdf_form_{fpath}"] = rows
    rows = st.session_state.get(f"pdf_form_{fpath}")
    if rows is None: return
    if not rows: st.warning("No formation tops found."); return
    df = pd.DataFrame(rows)
    st.metric("Formations", len(df))
    st.dataframe(df, hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇ Download CSV", data=df.to_csv(index=False),
            file_name="formation_tops.csv", mime="text/csv", key="pdf_form_dl")
    with c2:
        _save_flat_btn(frow, RT_FORMATION, rows, "pdf_form_save")


def _pdf_extract_core(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("🧪 Extract Core Data", type="primary", key="pdf_core_btn"):
        with st.spinner("Extracting..."):
            rows = _parse_core_data(fpath)
        st.session_state[f"pdf_core_{fpath}"] = rows
    rows = st.session_state.get(f"pdf_core_{fpath}")
    if rows is None: return
    if not rows: st.warning("No core data found."); return
    df = pd.DataFrame(rows)
    st.metric("Core samples", len(df))
    st.dataframe(df, hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇ Download CSV", data=df.to_csv(index=False),
            file_name="core_data.csv", mime="text/csv", key="pdf_core_dl")
    with c2:
        _save_flat_btn(frow, RT_CORE, rows, "pdf_core_save")


def _pdf_extract_dst(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("💧 Extract DST Data", type="primary", key="pdf_dst_btn"):
        with st.spinner("Extracting..."):
            result = _parse_dst(fpath)
        st.session_state[f"pdf_dst_{fpath}"] = result
    result = st.session_state.get(f"pdf_dst_{fpath}")
    if result is None: return
    header = result.get("header", {}); rows = result.get("rows", [])
    if not header and not rows: st.warning("No DST data found."); return
    if header:
        st.dataframe(pd.DataFrame([{"Field":k,"Value":v}
            for k,v in header.items() if v]), hide_index=True, use_container_width=True)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, hide_index=True, use_container_width=True)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇ Download CSV", data=df.to_csv(index=False),
                file_name="dst_data.csv", mime="text/csv", key="pdf_dst_dl")
        with c2:
            _save_flat_btn(frow, RT_DST, rows, "pdf_dst_save")


def _pdf_extract_rft(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("💉 Extract RFT/MDT", type="primary", key="pdf_rft_btn"):
        with st.spinner("Extracting..."):
            result = extract_rft_data(fpath)
        st.session_state[f"pdf_rft_{fpath}"] = result
    result = st.session_state.get(f"pdf_rft_{fpath}")
    if result is None: return
    if result.get("error"): st.error(result["error"]); return
    rows = result.get("rows", [])
    if not rows: st.warning("No pressure measurements found."); return
    df = pd.DataFrame(rows).fillna("")
    st.metric("Measurements", len(df))
    st.dataframe(df, hide_index=True, use_container_width=True)
    samples = result.get("samples", [])
    if samples:
        with st.expander(f"🧪 Fluid Samples ({len(samples)})", expanded=False):
            st.dataframe(pd.DataFrame(samples).fillna(""),
                         hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇ Download CSV", data=df.to_csv(index=False),
            file_name="rft_data.csv", mime="text/csv", key="pdf_rft_dl")
    with c2:
        _save_flat_btn(frow, RT_RFT, rows, "pdf_rft_save")


def _pdf_extract_scout(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("🎫 Extract Scout Data", type="primary", key="pdf_scout_btn"):
        with st.spinner("Extracting..."):
            result = extract_scout_ticket(fpath)
        st.session_state[f"pdf_scout_{fpath}"] = result
    result = st.session_state.get(f"pdf_scout_{fpath}")
    if result is None: return
    if result.get("error"): st.error(result["error"]); return
    header = result.get("header", {})
    ip_rows = result.get("ip_rows", [])
    perf_rows = result.get("perf_rows", [])
    if header:
        st.dataframe(pd.DataFrame([{"Field":k,"Value":str(v)}
            for k,v in header.items() if v]), hide_index=True, use_container_width=True)
    if ip_rows:
        st.markdown("**Initial Production**")
        st.dataframe(pd.DataFrame(ip_rows).fillna(""),
                     hide_index=True, use_container_width=True)
    if perf_rows:
        with st.expander(f"💥 Perforation / Stimulation ({len(perf_rows)} stages)",
                         expanded=False):
            st.dataframe(pd.DataFrame(perf_rows).fillna(""),
                         hide_index=True, use_container_width=True)
    all_rows = ip_rows or perf_rows
    c1, c2 = st.columns(2)
    with c1:
        if all_rows:
            st.download_button("⬇ Download CSV",
                data=pd.DataFrame(all_rows).to_csv(index=False),
                file_name="scout_data.csv", mime="text/csv", key="pdf_scout_dl")
    with c2:
        _save_flat_btn(frow, RT_SCOUT, all_rows, "pdf_scout_save")


def _pdf_extract_ddr(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("📋 Extract DDR", type="primary", key="pdf_ddr_btn"):
        with st.spinner("Extracting..."):
            result = extract_ddr(fpath)
        st.session_state[f"pdf_ddr_{fpath}"] = result
    result = st.session_state.get(f"pdf_ddr_{fpath}")
    if result is None: return
    if result.get("error"): st.error(result["error"]); return
    ops = result.get("ops", [])
    if ops:
        st.dataframe(pd.DataFrame(ops).fillna(""),
                     hide_index=True, use_container_width=True)
    for sec, lbl in [("params","Drilling Parameters"),("mud","Mud Properties")]:
        if result.get(sec):
            with st.expander(lbl, expanded=False):
                st.dataframe(pd.DataFrame(result[sec]).fillna(""),
                             hide_index=True, use_container_width=True)
    _save_flat_btn(frow, RT_DDR, ops, "pdf_ddr_save")


def _pdf_extract_well_test(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("🧪 Extract Well Test", type="primary", key="pdf_wt_btn"):
        with st.spinner("Extracting..."):
            result = extract_well_test(fpath)
        st.session_state[f"pdf_wt_{fpath}"] = result
    result = st.session_state.get(f"pdf_wt_{fpath}")
    if result is None: return
    if result.get("error"): st.error(result["error"]); return
    flow_rows = result.get("flow_rows", [])
    reservoir = result.get("reservoir", result.get("analysis", {}))
    if reservoir:
        st.dataframe(pd.DataFrame([{"Parameter":k,"Value":str(v)}
            for k,v in reservoir.items() if v]),
            hide_index=True, use_container_width=True)
    if flow_rows:
        df = pd.DataFrame(flow_rows).fillna("")
        st.dataframe(df, hide_index=True, use_container_width=True)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇ Download CSV", data=df.to_csv(index=False),
                file_name="well_test.csv", mime="text/csv", key="pdf_wt_dl")
        with c2:
            _save_flat_btn(frow, RT_WELL_TEST, flow_rows, "pdf_wt_save")


def _pdf_extract_petro(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("📈 Extract Petrophysical", type="primary", key="pdf_petro_btn"):
        with st.spinner("Extracting..."):
            result = extract_petrophysical(fpath)
        st.session_state[f"pdf_petro_{fpath}"] = result
    result = st.session_state.get(f"pdf_petro_{fpath}")
    if result is None: return
    if result.get("error"): st.error(result["error"]); return
    zones = result.get("zones", [])
    interval = result.get("interval", [])
    if zones:
        df = pd.DataFrame(zones).fillna("")
        st.metric("Zones", len(df))
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("⬇ Download zones CSV", data=df.to_csv(index=False),
            file_name="petro_zones.csv", mime="text/csv", key="pdf_petro_dl")
    if interval:
        with st.expander(f"Interval log ({len(interval)} depths)", expanded=False):
            st.dataframe(pd.DataFrame(interval).fillna(""),
                         hide_index=True, use_container_width=True)
    _save_flat_btn(frow, RT_PETRO, zones or interval, "pdf_petro_save")


def _pdf_extract_eowr(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("📝 Extract EOWR", type="primary", key="pdf_eowr_btn"):
        with st.spinner("Extracting..."):
            result = extract_eowr(fpath)
        st.session_state[f"pdf_eowr_{fpath}"] = result
    result = st.session_state.get(f"pdf_eowr_{fpath}")
    if result is None: return
    if result.get("error"): st.error(result["error"]); return
    summary = result.get("summary", {})
    strat   = result.get("strat", [])
    npt     = result.get("npt", [])
    if summary:
        st.dataframe(pd.DataFrame([{"Field":k,"Value":str(v)}
            for k,v in summary.items() if v]),
            hide_index=True, use_container_width=True)
    if strat:
        st.markdown("**Stratigraphic tops**")
        df = pd.DataFrame(strat).fillna("")
        st.dataframe(df, hide_index=True, use_container_width=True)
        st.download_button("⬇ Download stratigraphy CSV",
            data=df.to_csv(index=False), file_name="eowr_strat.csv",
            mime="text/csv", key="pdf_eowr_dl")
    if npt:
        with st.expander(f"⚠️ NPT Events ({len(npt)})", expanded=False):
            st.dataframe(pd.DataFrame(npt).fillna(""),
                         hide_index=True, use_container_width=True)
    _save_flat_btn(frow, RT_EOWR, strat or npt, "pdf_eowr_save")


def _pdf_extract_casing(frow):
    import pandas as pd
    fpath = frow["file_path"]
    if st.button("🔩 Extract Casing", type="primary", key="pdf_cas_btn"):
        with st.spinner("Extracting..."):
            result = extract_casing_cement(fpath)
        st.session_state[f"pdf_cas_{fpath}"] = result
    result = st.session_state.get(f"pdf_cas_{fpath}")
    if result is None: return
    if result.get("error"): st.error(result["error"]); return
    for sec, lbl, key, fn in [
        ("casing","Casing programme","pdf_cas_dl","casing.csv"),
        ("cement","Cement job summary","pdf_cem_dl","cement.csv"),
        ("cbl","CBL evaluation","pdf_cbl_dl","cbl.csv"),
    ]:
        rows = result.get(sec, [])
        if rows:
            st.markdown(f"**{lbl}**")
            df = pd.DataFrame(rows).fillna("")
            st.dataframe(df, hide_index=True, use_container_width=True)
            st.download_button(f"⬇ Download {lbl} CSV",
                data=df.to_csv(index=False), file_name=fn,
                mime="text/csv", key=key)
    all_rows = result.get("casing",[]) + result.get("cement",[])
    _save_flat_btn(frow, RT_CASING, all_rows, "pdf_cas_save")


# =============================================================================
# ── SHAPEFILE ────────────────────────────────────────────────────────────────
# =============================================================================

def _run_shapefile(engine, dialect):
    tabs = st.tabs(["🔍 Scan", "🗺️ View & Extract", "📋 Flat File", "🚀 Batch Load"])
    with tabs[0]: _shp_scan()
    with tabs[1]: _shp_view_extract(engine, dialect)
    with tabs[2]: _flat_file("shp")
    with tabs[3]: _batch_load(engine, dialect, "shp")


def _shp_scan():
    import pandas as pd
    st.markdown("#### 🔍 Scan for Shapefiles")
    scan_path = st.text_input("Folder to scan",
                              placeholder=r"C:\WellData\Shapefiles",
                              key="shp_scan_path")
    c1, c2 = st.columns(2)
    if c1.button("🔍 Scan", type="primary", key="shp_scan_btn"):
        if not scan_path or not Path(scan_path).exists():
            st.error("Folder not found.")
        else:
            with st.spinner("Scanning and classifying..."):
                files = []
                for root, dirs, fnames in __import__("os").walk(scan_path):
                    for fn in fnames:
                        ext = Path(fn).suffix.lower()
                        if ext in SHP_EXTS:
                            fp = str(Path(root) / fn)
                            try:
                                cl = classify_shapefile(fp)
                                cl["file_path"] = fp
                                cl["file_name"] = fn
                                cl["file_ext"]  = ext
                            except Exception as e:
                                cl = {"file_path": fp, "file_name": fn,
                                      "file_ext": ext, "error": str(e)}
                            files.append(cl)
            st.session_state["shp_classified"] = files
            st.session_state.pop("shp_flat_rows", None)
            st.rerun()
    if c2.button("🗑️ Clear", key="shp_clear_btn"):
        st.session_state.pop("shp_classified", None)
        st.session_state.pop("shp_flat_rows", None)
        st.rerun()

    files = st.session_state.get("shp_classified", [])
    if not files: return
    st.divider()
    rows = []
    for f in files:
        rows.append({
            "File":          f.get("file_name",""),
            "Feature Type":  f.get("feature_type","--"),
            "PPDM Target":   f.get("ppdm_target","--"),
            "Geometry":      f.get("geometry_type","--"),
            "Features":      f.get("feature_count","--"),
            "CRS":           f.get("crs","--"),
            "Confidence":    f"{f.get('confidence',0)*100:.0f}%",
            "Error":         f.get("error",""),
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.download_button("⬇ Export scan CSV",
        data=pd.DataFrame(rows).to_csv(index=False),
        file_name="shp_scan.csv", mime="text/csv", key="shp_scan_export")


def _shp_view_extract(engine, dialect):
    import pandas as pd
    files = st.session_state.get("shp_classified", [])
    if not files:
        st.info("Run a scan first.")
        return
    frow, fpath = _nav_select(files, "shp", "file_name", "file_path")
    st.caption(f"`{fpath}`")

    # Header attributes
    _attr_pairs = [
        ("Feature Type",  frow.get("feature_type")),
        ("PPDM Target",   frow.get("ppdm_target")),
        ("Geometry Type", frow.get("geometry_type")),
        ("Feature Count", str(frow.get("feature_count",""))),
        ("CRS",           frow.get("crs")),
        ("EPSG",          str(frow.get("crs_epsg",""))),
        ("Confidence",    f"{frow.get('confidence',0)*100:.0f}%"),
    ]
    if frow.get("bounds"):
        b = frow["bounds"]
        _attr_pairs.append(("Extent",
            f"{b.get('minx',0):.3f}° – {b.get('maxx',0):.3f}° lon, "
            f"{b.get('miny',0):.3f}° – {b.get('maxy',0):.3f}° lat"))
    _attr_pairs.append(("Attributes",
        ", ".join(frow.get("attributes",[])[:10]) or "--"))

    _hdf = pd.DataFrame(
        [{"Attribute": k, "Value": str(v)}
         for k, v in _attr_pairs if v and v not in ("None","0","")]
    )
    if not _hdf.empty:
        with st.expander("📋 File attributes", expanded=True):
            st.dataframe(_hdf, hide_index=True, use_container_width=True)

    st.divider()

    # Re-classify with full detail
    if st.button("🗺️ Classify & Preview", type="primary", key="shp_classify_btn"):
        with st.spinner("Classifying..."):
            try:
                cl = classify_shapefile(fpath)
                st.session_state[f"shp_cl_{fpath}"] = cl
            except Exception as e:
                st.error(f"Classification failed: {e}")

    cl = st.session_state.get(f"shp_cl_{fpath}", frow)

    if cl.get("attributes"):
        st.markdown(f"**{len(cl['attributes'])} attribute columns:**")
        st.code(", ".join(cl["attributes"]))

    if cl.get("ppdm_target"):
        st.info(f"PPDM target: **{cl['ppdm_target']}**")

    if cl.get("sample_rows"):
        st.markdown("**Sample rows:**")
        st.dataframe(pd.DataFrame(cl["sample_rows"]),
                     hide_index=True, use_container_width=True)

    c1, c2 = st.columns(2)
    with c2:
        _save_flat_btn(frow, "SHAPEFILE", [], "shp_save_flat")

    st.divider()
    _catalog_section(engine, dialect, frow, "shp")


# =============================================================================
# ── EXCEL / WORD ──────────────────────────────────────────────────────────────
# =============================================================================

def _run_office(engine, dialect):
    tabs = st.tabs(["🔍 Scan", "📊 View & Extract", "📋 Flat File", "🚀 Batch Load"])
    with tabs[0]: _office_scan()
    with tabs[1]: _office_view_extract(engine, dialect)
    with tabs[2]: _flat_file("office")
    with tabs[3]: _batch_load(engine, dialect, "office")


def _office_scan():
    import pandas as pd
    import os
    st.markdown("#### 🔍 Scan for Excel / Word Files")
    scan_path = st.text_input("Folder to scan",
                              placeholder=r"C:\WellData\Reports",
                              key="office_scan_path")
    c1, c2 = st.columns(2)
    if c1.button("🔍 Scan", type="primary", key="office_scan_btn"):
        if not scan_path or not Path(scan_path).exists():
            st.error("Folder not found.")
        else:
            with st.spinner("Scanning..."):
                files = []
                for root, dirs, fnames in os.walk(scan_path):
                    for fn in fnames:
                        ext = Path(fn).suffix.lower()
                        if ext in OFFICE_EXTS:
                            fp = str(Path(root) / fn)
                            rec = {"file_path": fp, "file_name": fn,
                                   "file_ext": ext}
                            if _SUM_OK:
                                try:
                                    s = _summarize(fp)
                                    rec.update({
                                        "uwi":         s.get("uwi",""),
                                        "well_name":   s.get("well_name",""),
                                        "ppdm_hints":  ", ".join(s.get("ppdm_hints",[])),
                                        "description": s.get("description",""),
                                        "error":       s.get("error",""),
                                    })
                                except Exception as e:
                                    rec["error"] = str(e)
                            files.append(rec)
            st.session_state["office_classified"] = files
            st.session_state.pop("office_flat_rows", None)
            st.rerun()
    if c2.button("🗑️ Clear", key="office_clear_btn"):
        st.session_state.pop("office_classified", None)
        st.session_state.pop("office_flat_rows", None)
        st.rerun()

    files = st.session_state.get("office_classified", [])
    if not files: return
    st.divider()
    rows = []
    for f in files:
        rows.append({
            "File":        f.get("file_name",""),
            "Type":        f.get("file_ext",""),
            "UWI":         f.get("uwi","") or "--",
            "Well Name":   f.get("well_name","") or "--",
            "PPDM Hints":  f.get("ppdm_hints","") or "--",
            "Description": (f.get("description","") or "")[:60],
            "Error":       f.get("error","") or "",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.download_button("⬇ Export scan CSV",
        data=pd.DataFrame(rows).to_csv(index=False),
        file_name="office_scan.csv", mime="text/csv", key="office_scan_export")


def _office_view_extract(engine, dialect):
    import pandas as pd
    files = st.session_state.get("office_classified", [])
    if not files:
        st.info("Run a scan first.")
        return
    frow, fpath = _nav_select(files, "office", "file_name", "file_path")
    st.caption(f"`{fpath}` · {Path(fpath).stat().st_size / 1024:.1f} KB")

    # Header attributes
    _attr_pairs = [
        ("UWI / API",    frow.get("uwi")),
        ("Well Name",    frow.get("well_name")),
        ("PPDM Hints",   frow.get("ppdm_hints")),
        ("Description",  frow.get("description")),
        ("File Type",    frow.get("file_ext")),
    ]
    _hdf = pd.DataFrame(
        [{"Attribute": k, "Value": str(v)}
         for k, v in _attr_pairs if v and v not in ("None","")]
    )
    if not _hdf.empty:
        with st.expander("📋 File attributes", expanded=True):
            st.dataframe(_hdf, hide_index=True, use_container_width=True)

    st.divider()

    # Summarize / extract
    if st.button("📊 Summarize & Extract", type="primary", key="office_extract_btn"):
        with st.spinner("Summarizing..."):
            try:
                s = _summarize(fpath)
                st.session_state[f"office_sum_{fpath}"] = s
            except Exception as e:
                st.error(f"Summarize failed: {e}")

    s = st.session_state.get(f"office_sum_{fpath}")
    if s is None: 
        st.divider()
        _catalog_section(engine, dialect, frow, "office")
        return

    if s.get("error"):
        st.error(f"Extraction error: {s['error']}")

    if s.get("warnings"):
        for w in s["warnings"]:
            st.warning(w)

    # Key fields
    kf = s.get("key_fields", {})
    _kf_rows = [{"Field": k, "Value": str(v)}
                for k, v in kf.items()
                if not isinstance(v, (list, dict)) and v not in (None, "", 0)]
    if _kf_rows:
        st.markdown("**Key fields**")
        st.dataframe(pd.DataFrame(_kf_rows), hide_index=True, use_container_width=True)

    # Sheet detail (Excel)
    if kf.get("sheet_detail"):
        st.markdown("**Sheets**")
        for sd in kf["sheet_detail"][:8]:
            st.info(f"**{sd.get('sheet','')}** · {sd.get('table_type','')} · "
                    f"{sd.get('rows',0):,} rows · → {sd.get('ppdm','?')}")

    # Table detail (Word)
    if kf.get("tables_detail"):
        st.markdown("**Tables**")
        for td in kf["tables_detail"][:8]:
            st.info(f"**Table {td.get('table_idx',0)+1}** · "
                    f"{td.get('table_type','')} · {td.get('rows',0)} rows · "
                    f"→ {td.get('ppdm','?')}")

    if s.get("ppdm_hints"):
        st.success(f"PPDM targets: **{', '.join(s['ppdm_hints'])}**")

    # Build extract rows for flat file (scalar summary)
    extract_rows = [{"field": k, "value": str(v)}
                    for k, v in kf.items()
                    if not isinstance(v, (list, dict)) and v not in (None, "", 0)]

    # Enrich frow with summarize results for flat file
    frow_enriched = {**frow,
                     "uwi":        s.get("uwi", frow.get("uwi","")),
                     "well_name":  s.get("well_name", frow.get("well_name","")),
                     "ppdm_hints": ", ".join(s.get("ppdm_hints",[])),
                     "description":s.get("description","")}

    c1, c2 = st.columns(2)
    with c1:
        if extract_rows:
            st.download_button("⬇ Download key fields CSV",
                data=pd.DataFrame(extract_rows).to_csv(index=False),
                file_name="office_extract.csv", mime="text/csv",
                key="office_extract_dl")
    with c2:
        _save_flat_btn(frow_enriched, "OFFICE", extract_rows, "office_save_flat")

    st.divider()
    _catalog_section(engine, dialect, frow_enriched, "office")


# =============================================================================
# Shared: Catalog section, Flat File tab, Batch Load tab
# =============================================================================

def _catalog_section(engine, dialect, frow, prefix: str):
    """Compact catalog panel — always at bottom of View & Extract."""
    st.markdown("#### 🗂️ Catalog")

    if engine is None:
        st.info("Connect to a database to catalog files.")
        return

    fpath = frow.get("file_path", "")
    _ckey = f"{prefix}_cataloged_{fpath}"
    is_cataloged = st.session_state.get(_ckey, False)

    if is_cataloged:
        st.success("✅ Cataloged in GLOBAL_FILE_CATALOG")
        if st.button("Remove from catalog", key=f"{prefix}_uncat_btn"):
            st.session_state[_ckey] = False
            st.rerun()
    else:
        st.caption("Review the extracted data above, then catalog this file if it looks correct.")
        if st.button("📁 Catalog File", type="primary",
                     use_container_width=True, key=f"{prefix}_cat_btn"):
            try:
                r = _catalog_document(
                    engine=engine, dialect=dialect, file_path=fpath,
                    doc_type=frow.get("report_type", frow.get("feature_type","UNKNOWN")),
                    meta={"uwi":       frow.get("uwi",""),
                          "well_name": frow.get("well_name",""),
                          "operator":  frow.get("operator","")},
                    records=[], source="FILE_CATALOG")
                if r.get("ok"):
                    st.session_state[_ckey] = True
                    _advance_nav(prefix)
                    _scroll_top()
                    st.rerun()
                else:
                    st.error(f"Catalog failed: {r.get('error')}")
            except Exception as e:
                st.error(f"Catalog failed: {e}")


def _save_flat_btn(frow: dict, extract_type: str, rows: list, key: str):
    """Standard Save to Flat File button."""
    flat_key = _prefix_for(frow) + "_flat_rows"
    if st.button("💾 Save to Flat File", key=key,
                 help="Adds this file's header to the flat file export"):
        flat = st.session_state.get(flat_key, [])
        rec  = _flat_record(frow, extract_type, rows)
        if not any(r["file_path"] == rec["file_path"] for r in flat):
            flat.append(rec)
            st.session_state[flat_key] = flat
        n = len(st.session_state.get(flat_key, []))
        st.success(f"Saved — {n} file(s) in flat file.")


def _prefix_for(frow: dict) -> str:
    ext = Path(frow.get("file_path","x.pdf")).suffix.lower()
    if ext in SHP_EXTS:    return "shp"
    if ext in OFFICE_EXTS: return "office"
    return "pdf"


def _flat_record(frow: dict, extract_type: str, rows: list) -> dict:
    return {
        "file_path":    frow.get("file_path",""),
        "file_name":    frow.get("file_name",""),
        "file_ext":     frow.get("file_ext",""),
        "extract_type": extract_type,
        "uwi":          frow.get("uwi",""),
        "well_name":    frow.get("well_name",""),
        "operator":     frow.get("operator",""),
        "field":        frow.get("field",""),
        "state":        frow.get("state",""),
        "county":       frow.get("county",""),
        "latitude":     frow.get("latitude",""),
        "longitude":    frow.get("longitude",""),
        "total_depth":  frow.get("total_depth",""),
        "spud_date":    frow.get("spud_date",""),
        "rig_release":  frow.get("rig_release",""),
        "survey_type":  frow.get("survey_type",""),
        "contractor":   frow.get("contractor",""),
        "feature_type": frow.get("feature_type",""),
        "ppdm_target":  frow.get("ppdm_target",""),
        "geometry_type":frow.get("geometry_type",""),
        "ppdm_hints":   frow.get("ppdm_hints",""),
        "description":  frow.get("description",""),
        "confidence":   frow.get("confidence",""),
        "record_count": len(rows),
    }


def _flat_file(prefix: str):
    """Tab 3 -- Flat File (shared by all three modes)."""
    import pandas as pd
    flat_key = f"{prefix}_flat_rows"
    cls_key  = {"pdf":"pdf_classified","shp":"shp_classified",
                "office":"office_classified"}[prefix]

    st.markdown("#### 📋 Header Flat File")
    st.caption(
        "All classified files appear here. "
        "Export as CSV, create wells externally, then use Batch Load."
    )

    flat = st.session_state.get(flat_key, [])

    # Auto-populate from scan results
    classified = st.session_state.get(cls_key, [])
    if classified:
        existing = {r["file_path"] for r in flat}
        for f in classified:
            if f["file_path"] not in existing:
                flat.append(_flat_record(f, f.get("report_type",""), []))
        st.session_state[flat_key] = flat

    if not flat:
        st.info("No data yet. Run a scan to populate.")
        return

    df = pd.DataFrame(flat)

    # Quick stats
    has_uwi = has_lat = has_lon = 0
    if "uwi" in df.columns:
        has_uwi = df["uwi"].astype(str).str.strip().astype(bool).sum()
    if "latitude" in df.columns and "longitude" in df.columns:
        has_lat = df["latitude"].astype(str).str.strip().astype(bool).sum()
        has_lon = df["longitude"].astype(str).str.strip().astype(bool).sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total files",   len(df))
    m2.metric("Has UWI",       f"{has_uwi} / {len(df)}")
    m3.metric("Has Latitude",  f"{has_lat} / {len(df)}")
    m4.metric("Has Longitude", f"{has_lon} / {len(df)}")

    st.dataframe(df, hide_index=True, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇ Export flat file CSV",
            data=df.to_csv(index=False),
            file_name=f"{prefix}_header_flat_file.csv",
            mime="text/csv", key=f"{prefix}_flat_dl")
    with c2:
        if st.button("🗑️ Clear flat file", key=f"{prefix}_flat_clear"):
            st.session_state.pop(flat_key, None)
            st.rerun()


def _batch_load(engine, dialect, prefix: str):
    """Tab 4 -- Batch Load (shared by all three modes)."""
    import pandas as pd
    import re

    st.markdown("#### 🚀 Batch Load")
    st.caption(
        "Re-extracts and loads all cataloged files whose UWI exists in dv_well. "
        "Run after creating wells from the flat file."
    )

    if engine is None:
        st.warning("No database connection.")
        return

    ext_filter = {
        "pdf":    "'.pdf'",
        "shp":    "'.shp','.geojson','.gpkg','.kml','.kmz'",
        "office": "'.xlsx','.xls','.xlsm','.docx','.doc','.csv','.tsv'",
    }[prefix]

    label = {"pdf":"PDF","shp":"Shapefile","office":"Excel/Word"}[prefix]

    if st.button(f"🔍 Load {label} catalog", type="secondary",
                 key=f"{prefix}_batch_check"):
        st.session_state.pop(f"{prefix}_batch_preview", None)
        try:
            from sqlalchemy import text as _t
            with engine.connect() as con:
                rows = con.execute(_t(f"""
                    SELECT INVENTORY_ID, FILE_PATH, FILE_NAME,
                           MATCHED_UWI, CATALOG_READINESS, CATALOG_SCORE,
                           FILE_EXT
                    FROM file_catalog.GLOBAL_FILE_CATALOG
                    WHERE FILE_EXT IN ({ext_filter})
                    AND CATALOG_STATUS = 'CATALOGED'
                    ORDER BY FILE_NAME
                """)).fetchall()
            st.session_state[f"{prefix}_batch_catalog"] = rows
        except Exception as e:
            st.error(f"Catalog query failed: {e}")
            return

    catalog_rows = st.session_state.get(f"{prefix}_batch_catalog", [])
    if not catalog_rows:
        st.info(f"Click 'Load {label} catalog' to check cataloged files.")
        return

    def _norm(v):
        return re.sub(r"[-\s/]", "", str(v or "")).upper()

    preview = []
    try:
        from sqlalchemy import text as _t
        with engine.connect() as con:
            for row in catalog_rows:
                inv_id, fpath, fname, uwi, readiness, score, fext = row

                # Check well exists
                well_match = None
                if uwi:
                    _r = con.execute(_t(
                        "SELECT uwi FROM dataview.dv_well WHERE uwi=:u"
                    ), {"u": uwi}).fetchone()
                    if _r:
                        well_match = _r[0]
                    else:
                        _r2 = con.execute(_t(
                            "SELECT uwi FROM dataview.dv_well "
                            "WHERE REPLACE(REPLACE(REPLACE(uwi,'-',''),' ',''),'/','')=:n"
                        ), {"n": _norm(uwi)}).fetchone()
                        if _r2:
                            well_match = _r2[0]

                if well_match:
                    status = "✅ Ready"
                elif not uwi:
                    status = "⚠️ No UWI"
                else:
                    status = "❌ Well not found"

                preview.append({
                    "File":       fname,
                    "UWI":        uwi or "--",
                    "Well Match": well_match or "--",
                    "Status":     status,
                    "Readiness":  readiness or "--",
                    "_fpath":     fpath,
                    "_fext":      fext,
                    "_uwi":       well_match,
                })
        st.session_state[f"{prefix}_batch_preview"] = preview
    except Exception as e:
        st.error(f"Well check failed: {e}")
        return

    preview = st.session_state.get(f"{prefix}_batch_preview", [])
    if not preview:
        return

    ready   = sum(1 for p in preview if p["Status"] == "✅ Ready")
    no_well = sum(1 for p in preview if p["Status"] != "✅ Ready")

    m1, m2, m3 = st.columns(3)
    m1.metric("Cataloged files",  len(preview))
    m2.metric("✅ Ready to load",  ready)
    m3.metric("❌ No well match",  no_well)

    display_cols = ["File","UWI","Well Match","Status","Readiness"]
    st.dataframe(pd.DataFrame([{c: p[c] for c in display_cols} for p in preview]),
                 hide_index=True, use_container_width=True)

    if ready == 0:
        st.warning("No files are ready to load. Create wells from the flat file first.")
        return

    st.divider()

    _to_load = [p for p in preview if p["Status"] == "✅ Ready"]
    st.caption(f"{len(_to_load)} files ready for batch load.")

    if not st.button(f"🚀 Run Batch Load — {len(_to_load)} files",
                     type="primary", key=f"{prefix}_batch_run"):
        return

    prog = st.progress(0.0, text="Starting...")
    loaded = skipped = errors = 0
    err_msgs = []

    for i, p in enumerate(_to_load):
        prog.progress((i + 1) / len(_to_load), text=f"Loading {p['File']}...")
        fpath = p["_fpath"]
        fext  = p["_fext"]
        uwi   = p["_uwi"]
        well_info = {"uwi": uwi, "well_name": "", "operator": ""}

        try:
            if fext == ".pdf":
                cl = classify_pdf(fpath)
                well_info["well_name"] = cl.get("well_name","")
                well_info["operator"]  = cl.get("operator","")
                rt = cl.get("report_type", RT_UNKNOWN)
                rows = _batch_extract_pdf(fpath, rt)
                if not rows:
                    skipped += 1
                    continue
                _do_load(engine, dialect, rt, well_info, rows, fpath)
                loaded += 1

            elif fext in SHP_EXTS:
                cl = classify_shapefile(fpath)
                rows = cl.get("sample_rows", [])
                if not rows:
                    skipped += 1
                    continue
                r = _shp_load_to_ppdm(
                    file_path=fpath, engine=engine, dialect=dialect,
                    well_info=well_info)
                errs = r.get("errors", [])
                if errs:
                    errors += 1
                    err_msgs.append(f"{p['File']}: {'; '.join(str(e) for e in errs[:2])}")
                else:
                    loaded += 1

            elif fext in OFFICE_EXTS:
                s = _summarize(fpath)
                if s.get("error"):
                    errors += 1
                    err_msgs.append(f"{p['File']}: {s['error']}")
                    continue
                # Office files are summarized but not yet loadable to PPDM
                # — mark as processed, load via ETL pipeline separately
                skipped += 1

        except Exception as ex:
            errors += 1
            err_msgs.append(f"{p['File']}: {ex}")

    prog.empty()
    r1, r2, r3 = st.columns(3)
    r1.metric("✅ Loaded",  loaded)
    r2.metric("⏭️ Skipped", skipped)
    r3.metric("❌ Errors",  errors)
    if err_msgs:
        with st.expander(f"⚠️ {len(err_msgs)} error(s)", expanded=True):
            for m in err_msgs[:30]:
                st.text(m)


# =============================================================================
# Batch extract helpers
# =============================================================================

def _batch_extract_pdf(fpath: str, rt: str) -> list:
    """Re-extract structured rows from a PDF by report type."""
    try:
        if rt == RT_DIRECTIONAL:
            r = extract_stations(fpath)
            return r.get("stations", [])
        elif rt == RT_RFT:
            return extract_rft_data(fpath).get("rows", [])
        elif rt == RT_SCOUT:
            r = extract_scout_ticket(fpath)
            return r.get("ip_rows") or r.get("perf_rows") or []
        elif rt == RT_DDR:
            return extract_ddr(fpath).get("ops", [])
        elif rt == RT_WELL_TEST:
            return extract_well_test(fpath).get("flow_rows", [])
        elif rt in (RT_PETRO, "PETROPHYSICAL"):
            r = extract_petrophysical(fpath)
            return r.get("zones") or r.get("interval") or []
        elif rt == RT_EOWR:
            return extract_eowr(fpath).get("strat", [])
        elif rt == RT_CASING:
            r = extract_casing_cement(fpath)
            return r.get("casing", []) + r.get("cement", [])
        elif rt == RT_FORMATION:
            return _parse_formation_tops(fpath)
        elif rt == RT_CORE:
            return _parse_core_data(fpath)
        elif rt == RT_DST:
            return _parse_dst(fpath).get("rows", [])
    except Exception:
        pass
    return []


def _do_load(engine, dialect, rt, well_info, rows, fpath):
    """Route to correct PPDM loader and display result."""
    try:
        if rt == RT_DIRECTIONAL:
            r = load_to_ppdm(well_info=well_info, stations=rows,
                             engine=engine, dialect=dialect)
        else:
            from modules.pdf_db_loader import (
                load_formation_tops, load_well_test, load_rft,
                load_core, load_casing, load_scout,
            )
            kw = dict(engine=engine, dialect=dialect,
                      well_info=well_info, rows=rows)
            if rt == RT_FORMATION:               r = load_formation_tops(**kw)
            elif rt in (RT_DST, RT_WELL_TEST):   r = load_well_test(**kw)
            elif rt == RT_RFT:                   r = load_rft(**kw)
            elif rt == RT_CORE:                  r = load_core(**kw)
            elif rt == RT_CASING:                r = load_casing(**kw)
            elif rt == RT_SCOUT:                 r = load_scout(**kw)
            else:
                st.warning(f"Load not implemented for {rt} — use CSV export.")
                return
        errs = r.get("errors", [])
        if errs:
            st.error(f"Load errors: {'; '.join(str(e) for e in errs[:3])}")
        else:
            st.success(f"✅ Loaded {r.get('loaded', 0)} records")
    except Exception as e:
        st.error(f"Load failed: {e}")


# =============================================================================
# PDF parsers
# =============================================================================

def _parse_formation_tops(file_path: str) -> list:
    import re
    rows = []
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table: continue
                    hdrs = [str(c).strip().upper() for c in (table[0] or [])]
                    fc = next((i for i,h in enumerate(hdrs)
                        if any(k in h for k in ["FORM","ZONE","PICK","NAME"])),None)
                    dc = next((i for i,h in enumerate(hdrs)
                        if any(k in h for k in ["TOP","DEPTH","MD","TVD"])),None)
                    if fc is not None and dc is not None:
                        for row in table[1:]:
                            if not row: continue
                            fn = str(row[fc]).strip()
                            dp = str(row[dc]).strip()
                            if fn and dp and fn.upper() != "NONE":
                                try:
                                    rows.append({"FORMATION_NAME": fn,
                                        "DEPTH_TOP_MD": float(re.sub(r"[^\d.]","",dp))})
                                except ValueError: pass
    except Exception: pass
    seen = set()
    return [r for r in rows
            if (k := (r["FORMATION_NAME"].upper(), r["DEPTH_TOP_MD"])) not in seen
            and not seen.add(k)]


def _parse_core_data(file_path: str) -> list:
    import re
    rows = []
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table or len(table) < 2: continue
                    hdrs = [str(c).strip().upper() for c in (table[0] or [])]
                    def _col(kws): return next((i for i,h in enumerate(hdrs)
                        if any(k in h for k in kws)), None)
                    dc=_col(["DEPTH","MD","TOP"]); pc=_col(["POR","PHI","PORO"])
                    kc=_col(["PERM","KH","KA"]); sc=_col(["SW","SAT","WATER"])
                    if dc is None: continue
                    for row in table[1:]:
                        if not row: continue
                        def _v(idx):
                            if idx is None or idx >= len(row): return None
                            v = re.sub(r"[^\d.\-]","",str(row[idx]))
                            try: return float(v) if v else None
                            except ValueError: return None
                        d = _v(dc)
                        if d is None: continue
                        rows.append({"DEPTH":d,"POROSITY":_v(pc),
                                     "PERMEABILITY":_v(kc),"SW":_v(sc)})
    except Exception: pass
    return rows


def _parse_dst(file_path: str) -> dict:
    import re
    header = {}; rows = []
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            full = "\n".join((p.extract_text() or "") for p in pdf.pages)
        for field, pat in {
            "WELL_NAME":    r"WELL[:\s]+([^\n]+)",
            "ISIP":         r"ISIP[:\s]+([\d.]+)",
            "MAX_PRESSURE": r"MAX(?:IMUM)?\s+(?:SHUT.IN\s+)?PRESSURE[:\s]+([\d.]+)",
        }.items():
            m = re.search(pat, full, re.IGNORECASE)
            if m: header[field] = m.group(1).strip()
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table: continue
                    hdrs = [str(c).strip().upper() for c in (table[0] or [])]
                    tc = next((i for i,h in enumerate(hdrs)
                        if any(k in h for k in ["TIME","HR","MIN"])),None)
                    pc = next((i for i,h in enumerate(hdrs)
                        if any(k in h for k in ["PRESS","PSI","KPA","BHP"])),None)
                    if tc is None or pc is None: continue
                    for row in table[1:]:
                        if not row: continue
                        try:
                            p = float(re.sub(r"[^\d.]","",str(row[pc]))) if row[pc] else None
                            if p: rows.append({"TIME": str(row[tc]).strip(), "PRESSURE": p})
                        except Exception: pass
    except Exception: pass
    return {"header": header, "rows": rows}

"""
page_pdf_catalog.py
===================
PDF Catalog UI — scan, view, classify, extract and optionally load to the database.

Supported report types:
  📐 Directional Survey  → WELL_DIR_SURVEY / WELL_DIR_SRVY_STATION
  🪨 Formation Tops      → WELL_FORMATION
  🧪 Core Data           → WELL_CORE / WELL_CORE_ANALYSIS
  💧 Drill Stem Test     → WELL_TEST / WELL_TEST_RESULT
  📊 Mud Log             → (viewer only — no structured extract)
  ❓ Unknown             → viewer only
"""
import base64
import streamlit as st

try:
    from modules.doc_catalog_store import render_catalog_widget as _render_catalog_widget_fn
    _STORE_OK = True
except ImportError:
    _STORE_OK = False
from pathlib import Path

try:
    from modules.pdf_survey_catalog import (
        scan_directory, classify_pdf, extract_stations,
        validate_stations, load_to_ppdm, summarize_scan,
        RT_DIRECTIONAL, RT_MUDLOG, RT_FORMATION,
        RT_COMPLETION, RT_UNKNOWN,
        # Extended types
        RT_RFT, RT_SCOUT, RT_DDR, RT_WELL_TEST,
        RT_PETRO, RT_EOWR, RT_CASING,
        extended_classify_pdf,
        extract_rft_data, extract_scout_ticket, extract_ddr,
        extract_well_test, extract_petrophysical,
        extract_eowr, extract_casing_cement,
    )
    _CATALOG_OK = True
except ImportError as _ce:
    _CATALOG_OK = False
    _CATALOG_ERR = str(_ce)
    # Stubs so the rest of the module doesn't crash on import failure
    RT_DIRECTIONAL = "DIRECTIONAL_SURVEY"
    RT_MUDLOG      = "MUD_LOG"
    RT_FORMATION   = "FORMATION_TOPS"
    RT_COMPLETION  = "COMPLETION"
    RT_UNKNOWN     = "UNKNOWN"
    RT_RFT = RT_SCOUT = RT_DDR = RT_WELL_TEST = "UNKNOWN"
    RT_PETRO = RT_EOWR = RT_CASING = "UNKNOWN"
    # Stub functions
    def scan_directory(*a, **kw): return []
    def classify_pdf(*a, **kw): return {"report_type": RT_UNKNOWN}
    def extract_stations(*a, **kw): return {"stations": [], "error": _CATALOG_ERR}
    def extended_classify_pdf(*a, **kw): return {"report_type": RT_UNKNOWN}
    def summarize_scan(*a, **kw): return {}
    def load_to_ppdm(*a, **kw): return {"loaded": 0, "errors": [_CATALOG_ERR]}
    def extract_rft_data(*a, **kw): return []
    def extract_scout_ticket(*a, **kw): return {}
    def extract_ddr(*a, **kw): return []
    def extract_well_test(*a, **kw): return []
    def extract_petrophysical(*a, **kw): return []
    def extract_eowr(*a, **kw): return []
    def extract_casing_cement(*a, **kw): return []
    def validate_stations(*a, **kw): return []

# Types defined in this module
RT_CORE = "CORE"
RT_DST  = "DST"

REPORT_ICONS = {
    RT_DIRECTIONAL: "📐",
    RT_MUDLOG:      "📊",
    RT_FORMATION:   "🪨",
    RT_COMPLETION:  "🔧",
    RT_CORE:        "🧪",
    RT_DST:         "💧",
    RT_UNKNOWN:     "❓",
    RT_RFT:         "💉",
    RT_SCOUT:       "🎫",
    RT_DDR:         "📋",
    RT_WELL_TEST:   "🧪",
    RT_PETRO:       "📈",
    RT_EOWR:        "📝",
    RT_CASING:      "🔩",
}
REPORT_LABELS = {
    RT_DIRECTIONAL: "Directional Survey",
    RT_MUDLOG:      "Mud Log",
    RT_FORMATION:   "Formation Tops",
    RT_COMPLETION:  "Completion Report",
    RT_CORE:        "Core Data",
    RT_DST:         "Drill Stem Test",
    RT_UNKNOWN:     "Unknown / Other",
    RT_RFT:         "RFT / MDT Pressure Test",
    RT_SCOUT:       "Scout Ticket",
    RT_DDR:         "Daily Drilling Report",
    RT_WELL_TEST:   "Well Test Report",
    RT_PETRO:       "Petrophysical Report",
    RT_EOWR:        "End of Well Report",
    RT_CASING:      "Casing & Cementing Record",
}

# Which types have structured extraction
_EXTRACTABLE = {
    RT_DIRECTIONAL, RT_FORMATION, RT_CORE, RT_DST,
    RT_RFT, RT_SCOUT, RT_DDR, RT_WELL_TEST,
    RT_PETRO, RT_EOWR, RT_CASING,
}

# Which types can be loaded directly to PPDM (have a working loader)
_PPDM_LOADABLE = {
    RT_DIRECTIONAL, RT_FORMATION, RT_CORE, RT_DST,
    RT_RFT, RT_SCOUT, RT_WELL_TEST, RT_CASING,
}

# Which types are viewable only (text content but no structured extract)
_VIEWABLE_ONLY = {RT_MUDLOG, RT_COMPLETION, RT_UNKNOWN}

def _digital_data_badge(rt: str) -> str:
    if rt in _PPDM_LOADABLE:
        return "✅ Load to DB"
    elif rt in _EXTRACTABLE:
        return "📊 Extract only"
    elif rt in _VIEWABLE_ONLY:
        return "📄 View only"
    return "❓ Unknown"


def run(engine=None, dialect: str = "mssql"):
    import pandas as pd
    st.title("📄 PDF Catalog")
    st.caption(
        "Scan a folder to classify PDFs, then view, extract and load to the database."
    )

    if not _CATALOG_OK:
        st.error(f"PDF catalog module missing: `{_CATALOG_ERR}`")
        return

    # ── Two buttons ───────────────────────────────────────────────────
    b1, b2, _ = st.columns([2, 2, 4])
    if b1.button("🔍 Scan & Classify", type="secondary",
                 use_container_width=True):
        st.session_state["pdf_mode"] = "scan"
    if b2.button("📄 View & Load", type="primary",
                 use_container_width=True):
        st.session_state["pdf_mode"] = "view_load"

    mode = st.session_state.get("pdf_mode", "scan")
    st.divider()

    # ── SCAN ─────────────────────────────────────────────────────────
    if mode == "scan":
        _render_scan()
        return

    # ── VIEW & LOAD ───────────────────────────────────────────────────
    # Step 1: Select file
    files = st.session_state.get("pdf_classified", [])
    if files:
        opts  = {f["file_name"]: f for f in files}
        sel   = st.selectbox("Select PDF", list(opts.keys()),
                             key="pdf_view_sel")
        frow  = opts[sel]
        fpath = frow["file_path"]
    else:
        fpath = st.text_input(
            "PDF path",
            placeholder=r"C:\WellData\Reports\survey.pdf",
            key="pdf_manual_path")
        if fpath and not Path(fpath).exists():
            st.error(f"File not found: `{fpath}`")
            return
        frow = {"file_path": fpath, "file_name": Path(fpath).name,
                "report_type": RT_UNKNOWN, "well_name": "", "uwi": "",
                "operator": "", "field": ""}

    if not fpath:
        st.info("Select a file above.")
        return

    st.session_state["pdf_viewed_file"] = fpath
    st.caption(f"`{fpath}` · {Path(fpath).stat().st_size/1024:.1f} KB")

    # Step 2: PDF viewer (collapsible)
    with st.expander("📄 View PDF", expanded=False):
        try:
            pdf_bytes = Path(fpath).read_bytes()
            b64 = base64.b64encode(pdf_bytes).decode()
            h = st.slider("Height (px)", 400, 1200, 700, 50, key="pdf_h")
            st.markdown(
                f'<iframe src="data:application/pdf;base64,{b64}" '
                f'width="100%" height="{h}px" style="border:none;border-radius:8px;"></iframe>',
                unsafe_allow_html=True)
        except Exception as e:
            st.error(f"PDF render failed: {e}")

    st.divider()

    # Step 3: Well identification (one place only)
    st.markdown("**Well identification**")
    w1, w2, w3 = st.columns(3)
    uwi       = w1.text_input("UWI",       value=frow.get("uwi",""),      key="pdf_uwi")
    well_name = w2.text_input("Well name", value=frow.get("well_name",""),key="pdf_wn")
    operator  = w3.text_input("Operator",  value=frow.get("operator",""), key="pdf_op")

    # ── Extracted header attributes (always shown) ──────────────────────────
    import pandas as pd
    classified = next(
        (f for f in st.session_state.get("pdf_classified", [])
         if f.get("file_path") == st.session_state.get("pdf_viewed_file")),
        frow)

    _header_attrs = [
        ("Report Type",    classified.get("report_type", "—")),
        ("Confidence",     f"{int(classified.get('confidence', 0)*100)}%"
                           if classified.get("confidence") else "—"),
        ("Field",          classified.get("field") or "—"),
        ("State",          classified.get("state") or "—"),
        ("Contractor",     classified.get("contractor") or "—"),
        ("Survey Type",    classified.get("survey_type") or "—"),
        ("Total Depth",    classified.get("total_depth") or "—"),
        ("Station Count",  str(classified.get("station_count", 0))),
        ("Latitude",       classified.get("latitude") or "—"),
        ("Longitude",      classified.get("longitude") or "—"),
        ("Page Count",     str(classified.get("page_count", "—"))),
    ]
    _hdf = pd.DataFrame(
        [{"Attribute": k, "Value": str(v)} for k, v in _header_attrs if v not in (None, "—", "0")],
    )
    if not _hdf.empty:
        with st.expander("📋 Extracted header attributes", expanded=True):
            st.dataframe(_hdf, hide_index=True, use_container_width=True)

    # ── Optional UWI verification against dv_well ────────────────────────────
    if uwi and engine:
        try:
            from sqlalchemy import text as _t
            with engine.connect() as _c:
                _row = _c.execute(_t("""
                    SELECT w.well_name,
                           ba.ba_name AS operator_name,
                           f.field_name,
                           w.surface_latitude, w.surface_longitude, w.final_td
                    FROM dataview.dv_well w
                    LEFT JOIN dataview.dv_business_associate ba
                        ON ba.ba_id = w.operator_ba_id
                    LEFT JOIN dataview.dv_field f
                        ON f.field_id = w.field_id
                    WHERE w.uwi = :u
                """), {"u": uwi}).fetchone()

            def _fmt(v):
                if v is None: return "—"
                try:
                    return f"{float(v):.4f}" if "." in str(v) else str(v)
                except Exception:
                    return str(v)

            def _match(a, b):
                if not a and not b: return "—"
                if not a or not b:  return "⚠️"
                return "✅" if str(a).strip() == str(b).strip() else "⚠️"

            if _row:
                st.success(f"✅ UWI matched in dv_well — **{_row[0] or '—'}**")
                rows_cmp = [
                    {"Attribute": "UWI",              "PDF / Survey": uwi,                                           "DB (dv_well)": uwi,            "Match": "✅"},
                    {"Attribute": "Well Name",         "PDF / Survey": classified.get("well_name") or well_name or "—", "DB (dv_well)": _row[0] or "—", "Match": _match(classified.get("well_name") or well_name, _row[0])},
                    {"Attribute": "Operator",          "PDF / Survey": classified.get("operator")  or operator  or "—", "DB (dv_well)": _row[1] or "—", "Match": _match(classified.get("operator")  or operator,  _row[1])},
                    {"Attribute": "Field",             "PDF / Survey": classified.get("field")     or "—",              "DB (dv_well)": _row[2] or "—", "Match": _match(classified.get("field"),     _row[2])},
                    {"Attribute": "Surface Latitude",  "PDF / Survey": classified.get("latitude")  or "—",              "DB (dv_well)": _fmt(_row[3]),  "Match": _match(classified.get("latitude"),  _fmt(_row[3]))},
                    {"Attribute": "Surface Longitude", "PDF / Survey": classified.get("longitude") or "—",              "DB (dv_well)": _fmt(_row[4]),  "Match": _match(classified.get("longitude"), _fmt(_row[4]))},
                    {"Attribute": "Final TD",          "PDF / Survey": classified.get("total_depth") or "—",            "DB (dv_well)": _fmt(_row[5]),  "Match": _match(classified.get("total_depth"), _fmt(_row[5]))},
                ]
                with st.expander("🔗 DB comparison", expanded=False):
                    st.dataframe(pd.DataFrame(rows_cmp),
                                 use_container_width=True, hide_index=True,
                                 column_config={"Match": st.column_config.TextColumn(width="small")})
            else:
                st.info(f"ℹ️ UWI `{uwi}` not in dv_well — load continues without well linkage.")
        except Exception as _e:
            st.caption(f"DB check skipped: {_e}")

    st.divider()

    # Step 4: Auto-extract
    _render_extract_inline(engine, dialect, frow, uwi, well_name, operator)


# ─────────────────────────────────────────────────────────────────────────────
# Scan tab
# ─────────────────────────────────────────────────────────────────────────────

def _render_scan():
    import pandas as pd
    st.markdown("#### 🔍 Scan for PDF Files")
    st.caption("Scans all .pdf files recursively — classifies by content where possible.")

    scan_path = st.text_input(
        "Folder to scan",
        placeholder=r"C:\WellData\Reports",
        key="pdf_scan_path"
    )

    c1, c2 = st.columns(2)
    if c1.button("🔍 Scan PDFs", type="primary", key="pdf_scan_btn"):
        if not scan_path or not Path(scan_path).exists():
            st.error("Folder not found.")
        else:
            with st.spinner("Scanning…"):
                files = scan_directory(scan_path)

            prog = st.progress(0, text="Classifying…")
            classified = []
            for i, f in enumerate(files):
                prog.progress(
                    (i + 1) / max(len(files), 1),
                    text=f"Classifying {f['file_name']}…"
                )
                cl = classify_pdf(f["file_path"])
                # Always run extended classifier — it covers all 13 types
                # and may upgrade a base classification to something more specific
                _ext = _extended_classify(f["file_path"])
                if cl.get("report_type") == RT_UNKNOWN and _ext != RT_UNKNOWN:
                    cl["report_type"] = _ext
                elif cl.get("report_type") == RT_UNKNOWN:
                    cl["report_type"] = RT_UNKNOWN
                cl.update({k: v for k, v in f.items() if k not in cl})
                classified.append(cl)

            prog.empty()
            st.session_state["pdf_classified"] = classified
            st.rerun()

    if c2.button("🗑️ Clear", key="pdf_clear"):
        st.session_state.pop("pdf_classified", None)
        st.rerun()

    if "pdf_classified" not in st.session_state:
        return

    files   = st.session_state["pdf_classified"]
    summary = summarize_scan(files)

    st.divider()
    cols = st.columns(len(REPORT_LABELS))
    type_counts = {}
    for f in files:
        rt = f.get("report_type", RT_UNKNOWN)
        type_counts[rt] = type_counts.get(rt, 0) + 1
    for i, (rt, label) in enumerate(REPORT_LABELS.items()):
        cols[i].metric(f"{REPORT_ICONS[rt]} {label}", type_counts.get(rt, 0))

    st.divider()
    rows = []
    for f in files:
        rt = f.get("report_type", RT_UNKNOWN)
        rows.append({
            "Type":         f"{REPORT_ICONS.get(rt,'•')} {REPORT_LABELS.get(rt, rt)}",
            "File":         f["file_name"],
            "Well":         f.get("well_name", "—"),
            "UWI":          f.get("uwi", "—"),
            "Operator":     f.get("operator", "—"),
            "Pages":        str(f.get("page_count", "?")),
            "Conf.":        f"{f.get('confidence', 0)*100:.0f}%",
            "Digital Data": _digital_data_badge(rt),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True,
        column_config={
            "Type":         st.column_config.TextColumn(width="medium"),
            "File":         st.column_config.TextColumn(width="medium"),
            "Well":         st.column_config.TextColumn(width="medium"),
            "Conf.":        st.column_config.TextColumn(width="small"),
            "Pages":        st.column_config.TextColumn(width="small"),
            "Digital Data": st.column_config.TextColumn(width="medium"),
        })

    st.download_button(
        "⬇ Export scan CSV",
        data=df.to_csv(index=False),
        file_name="pdf_scan.csv",
        mime="text/csv",
        key="pdf_export_scan",
    )


def _extended_classify(file_path: str) -> str:
    """Run extended classifier for all 7 additional report types."""
    try:
        r = extended_classify_pdf(file_path)
        return r.get("report_type", RT_UNKNOWN)
    except Exception:
        pass
    return RT_UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# View tab
# ─────────────────────────────────────────────────────────────────────────────


def _render_extract_inline(engine, dialect, frow: dict, uwi: str,
                           well_name: str, operator: str):
    """
    Clean extract + catalog + load panel.
    Uses file already selected — no redundant file selector.
    """
    import pandas as pd
    fpath   = frow.get("file_path", "")
    rt      = frow.get("report_type", RT_UNKNOWN)
    st.markdown(f"**{REPORT_ICONS.get(rt,'📄')} {REPORT_LABELS.get(rt, 'Document')}**")

    # UWI override — lets user correct the matched UWI before loading
    _uwi_ovr_key = f"uwi_override_{fpath}"
    well_info = {
        "uwi":          uwi,
        "well_name":    well_name,
        "operator":     operator,
        "latitude":     frow.get("latitude"),
        "longitude":    frow.get("longitude"),
        "total_depth":  frow.get("total_depth"),
        "uwi_override": st.session_state.get(_uwi_ovr_key, ""),
    }

    # Auto-extract based on report type
    cache_key = f"pdf_rows_{fpath}"
    if cache_key not in st.session_state:
        with st.spinner("🔍 Extracting..."):
            try:
                rows, err = _extract_by_type(fpath, rt, well_info)
                st.session_state[cache_key] = (rows, err)
            except Exception as e:
                st.session_state[cache_key] = ([], str(e))

    rows, err = st.session_state.get(cache_key, ([], None))

    if err:
        st.error(f"Extraction failed: {err}")
    elif rows:
        # ── Primary data table ────────────────────────────────────────────────
        st.caption(f"{len(rows):,} records extracted")
        _df = pd.DataFrame(rows).fillna("").applymap(
            lambda x: str(x) if x is not None else "—"
        )
        # Reorder columns in logical survey order
        _col_order = [c for c in ["MD","INC","AZI","TVD","NS","EW","DLS","VSEC"]
                      if c in _df.columns]
        _df = _df[_col_order + [c for c in _df.columns if c not in _col_order]]
        st.dataframe(_df, use_container_width=True, hide_index=True)

        # ── Supplementary panels per report type ──────────────────────────────
        _full = st.session_state.get("pdf_extract_full", {})
        if rt == RT_EOWR:
            _summary = _full.get("summary", {})
            if _summary:
                with st.expander("📋 Well Summary", expanded=True):
                    _sdf = pd.DataFrame([{"Field": k, "Value": str(v)}
                                         for k, v in _summary.items() if v])
                    st.dataframe(_sdf, hide_index=True, use_container_width=True)
            _npt = _full.get("npt", [])
            if _npt:
                with st.expander(f"⚠️ NPT Events ({len(_npt)})", expanded=False):
                    st.dataframe(pd.DataFrame(_npt).fillna(""),
                                 hide_index=True, use_container_width=True)
        elif rt == RT_SCOUT:
            _hdr = _full.get("header", {})
            if _hdr:
                with st.expander("📋 Well Header", expanded=True):
                    _hdf = pd.DataFrame([{"Field": k, "Value": str(v)}
                                         for k, v in _hdr.items() if v])
                    st.dataframe(_hdf, hide_index=True, use_container_width=True)
            _perf = _full.get("perf_rows", [])
            if _perf:
                with st.expander(f"💥 Perforation / Stimulation ({len(_perf)} stages)",
                                 expanded=False):
                    st.dataframe(pd.DataFrame(_perf).fillna(""),
                                 hide_index=True, use_container_width=True)
        elif rt == RT_DDR:
            _params = _full.get("params", [])
            if _params:
                with st.expander("⚙️ Drilling Parameters", expanded=False):
                    st.dataframe(pd.DataFrame(_params).fillna(""),
                                 hide_index=True, use_container_width=True)
            _mud = _full.get("mud", [])
            if _mud:
                with st.expander("🪣 Mud Properties", expanded=False):
                    st.dataframe(pd.DataFrame(_mud).fillna(""),
                                 hide_index=True, use_container_width=True)
        elif rt == RT_WELL_TEST:
            _res = _full.get("reservoir", {})
            if _res:
                with st.expander("📊 Reservoir Analysis", expanded=True):
                    _rdf = pd.DataFrame([{"Parameter": k, "Value": str(v)}
                                         for k, v in _res.items() if v])
                    st.dataframe(_rdf, hide_index=True, use_container_width=True)
        elif rt in (RT_PETRO, "PETROPHYSICAL"):
            _interval = _full.get("interval", [])
            if _interval:
                with st.expander(f"📈 Interval Detail ({len(_interval)} depths)",
                                 expanded=False):
                    st.dataframe(pd.DataFrame(_interval).fillna(""),
                                 hide_index=True, use_container_width=True)
        elif rt == RT_RFT:
            _samples = _full.get("samples", [])
            if _samples:
                with st.expander(f"🧪 Fluid Samples ({len(_samples)})",
                                 expanded=False):
                    st.dataframe(pd.DataFrame(_samples).fillna(""),
                                 hide_index=True, use_container_width=True)
        elif rt == RT_CASING:
            _cement = _full.get("cement", [])
            if _cement:
                with st.expander("🏗️ Cement Job Summary", expanded=False):
                    st.dataframe(pd.DataFrame(_cement).fillna(""),
                                 hide_index=True, use_container_width=True)
            _cbl = _full.get("cbl", [])
            if _cbl:
                with st.expander("📡 CBL/VDL Evaluation", expanded=False):
                    st.dataframe(pd.DataFrame(_cbl).fillna(""),
                                 hide_index=True, use_container_width=True)
    else:
        st.info("No structured data extracted — document may be image-only or unsupported type.")

    if st.button("🔄 Re-extract", key="pdf_reextract"):
        st.session_state.pop(cache_key, None)
        st.rerun()

    st.divider()

    # Catalog + Load buttons
    _cat_key = f"pdf_cataloged_{fpath}"
    is_cataloged = st.session_state.get(_cat_key, False)

    ca1, ca2 = st.columns(2)

    if ca1.button("📁 Catalog File",
                  type="secondary" if is_cataloged else "primary",
                  use_container_width=True, key="pdf_cat_btn"):
        try:
            from modules.doc_catalog_store import catalog_document
            r = catalog_document(
                engine=engine, dialect=dialect, file_path=fpath, doc_type=rt,
                meta=well_info, records=rows, source="PDF_CATALOG")
            if r.get("ok"):
                st.session_state[_cat_key] = True
                st.success("✅ Cataloged in GLOBAL_FILE_CATALOG")
                st.rerun()
            else:
                st.error(f"Catalog failed: {r.get('error')}")
        except Exception as e:
            st.error(f"Catalog failed: {e}")

    if is_cataloged:
        st.caption("✅ Cataloged")
        if rows and ca2.button(
                f"🚀 Load to DB — {len(rows)} records",
                type="primary", use_container_width=True,
                key="pdf_load_btn"):
            _do_load(engine, dialect, rt, well_info, rows, fpath)
    else:
        ca2.button(f"🚀 Load to DB", disabled=True,
                   use_container_width=True, key="pdf_load_btn_dis",
                   help="Catalog the file first")


def _extract_by_type(fpath: str, rt: str,
                     well_info: dict) -> tuple[list, str | None]:
    """
    Extract structured data from PDF by report type.
    Each extractor returns a dict of named sub-lists — we pick the
    primary display list and store the full result in session state
    for the type-specific UI panels to use.
    Returns (rows_for_dataframe, error_or_None).
    """
    try:
        from modules.pdf_survey_catalog import (
            extract_stations, extract_rft_data, extract_scout_ticket,
            extract_ddr, extract_well_test, extract_petrophysical,
            extract_eowr, extract_casing_cement,
        )

        if rt == RT_DIRECTIONAL:
            r = extract_stations(fpath)
            st.session_state["pdf_extract_full"] = r
            return r.get("stations", []), r.get("error")

        elif rt == RT_RFT:
            r = extract_rft_data(fpath)
            st.session_state["pdf_extract_full"] = r
            # Primary display: pressure measurement rows
            return r.get("rows", []), r.get("error")

        elif rt == RT_SCOUT:
            r = extract_scout_ticket(fpath)
            st.session_state["pdf_extract_full"] = r
            # Primary display: IP rows (most useful at a glance)
            rows = r.get("ip_rows") or r.get("perf_rows") or []
            return rows, r.get("error")

        elif rt == RT_DDR:
            r = extract_ddr(fpath)
            st.session_state["pdf_extract_full"] = r
            # Primary display: 24-hr operations table
            return r.get("ops", []), r.get("error")

        elif rt == RT_WELL_TEST:
            r = extract_well_test(fpath)
            st.session_state["pdf_extract_full"] = r
            # Primary display: flow test periods
            return r.get("flow_rows", []), r.get("error")

        elif rt in (RT_PETRO, "PETROPHYSICAL"):
            r = extract_petrophysical(fpath)
            st.session_state["pdf_extract_full"] = r
            # Primary display: zone summary
            return r.get("zones", []), r.get("error")

        elif rt == RT_EOWR:
            r = extract_eowr(fpath)
            st.session_state["pdf_extract_full"] = r
            # Primary display: stratigraphic summary
            return r.get("strat", []), r.get("error")

        elif rt == RT_CASING:
            r = extract_casing_cement(fpath)
            st.session_state["pdf_extract_full"] = r
            # Primary display: casing programme
            return r.get("casing", []), r.get("error")

        else:
            # General fallback — pdfplumber table extraction
            import pdfplumber
            rows = []
            with pdfplumber.open(fpath) as pdf:
                for page in pdf.pages:
                    for tbl in (page.extract_tables() or []):
                        if tbl and len(tbl) > 1:
                            hdrs = [str(h or f"col{j}").strip()
                                    for j, h in enumerate(tbl[0])]
                            for row in tbl[1:]:
                                if any(c for c in row):
                                    rows.append(dict(zip(hdrs,
                                        [str(c or "").strip() for c in row])))
            st.session_state["pdf_extract_full"] = {"rows": rows}
            return rows, None

    except Exception as e:
        return [], str(e)


def _do_load(engine, dialect, rt, well_info, rows, fpath):
    """Load extracted rows to dataview tables by report type."""
    try:
        if rt == RT_DIRECTIONAL:
            from modules.pdf_survey_catalog import load_to_ppdm
            r = load_to_ppdm(well_info=well_info, stations=rows,
                             engine=engine, dialect=dialect)

        elif rt == RT_FORMATION:
            from modules.pdf_db_loader import load_formation_tops
            r = load_formation_tops(engine=engine, dialect=dialect,
                                    well_info=well_info, rows=rows)

        elif rt == RT_RFT:
            from modules.pdf_db_loader import load_rft
            r = load_rft(engine=engine, dialect=dialect,
                         well_info=well_info, rows=rows)

        elif rt == RT_WELL_TEST:
            from modules.pdf_db_loader import load_well_test
            r = load_well_test(engine=engine, dialect=dialect,
                               well_info=well_info, rows=rows)

        elif rt == RT_CORE:
            from modules.pdf_db_loader import load_core
            r = load_core(engine=engine, dialect=dialect,
                          well_info=well_info, rows=rows)

        elif rt == RT_CASING:
            from modules.pdf_db_loader import load_casing
            r = load_casing(engine=engine, dialect=dialect,
                            well_info=well_info, rows=rows)

        elif rt == RT_SCOUT:
            from modules.pdf_db_loader import load_scout
            r = load_scout(engine=engine, dialect=dialect,
                           well_info=well_info, rows=rows)

        else:
            st.warning(f"Load not yet implemented for type: {rt}")
            return

        loaded = r.get("loaded", r.get("rows_inserted", 0))
        errors = r.get("errors", [])
        if errors:
            st.error(f"Load errors: {'; '.join(str(e) for e in errors[:3])}")
        else:
            st.success(f"✅ Loaded {loaded} records to DB")

    except Exception as e:
        st.error(f"Load failed: {e}")


def _render_viewer():
    st.markdown("#### 📄 PDF Viewer")

    if "pdf_classified" not in st.session_state:
        st.info("Run a scan first, or paste a file path below.")

    # File selector — from scan or manual path
    source = st.radio("File source", ["From scan", "Enter path"],
                      horizontal=True, key="pdf_view_src")

    file_path = None
    if source == "From scan":
        files = st.session_state.get("pdf_classified", [])
        if not files:
            st.info("No scan results yet.")
            return
        opts = {f["file_name"]: f["file_path"] for f in files}
        sel  = st.selectbox("Select file", list(opts.keys()), key="pdf_view_sel")
        file_path = opts[sel]
        # Carry selection through to Extract tab
        st.session_state["pdf_viewed_file"] = file_path
    else:
        manual = st.text_input(
            "Full path to PDF",
            placeholder=r"C:\WellData\Reports\well_123_survey.pdf",
            key="pdf_view_manual"
        )
        if manual and Path(manual).exists():
            file_path = manual
        elif manual:
            st.error(f"File not found: `{manual}`")

    if not file_path:
        return

    # Show file info
    p = Path(file_path)
    st.caption(f"`{file_path}` · {p.stat().st_size / 1024:.1f} KB")

    # Inline PDF viewer via base64 iframe
    try:
        pdf_bytes = Path(file_path).read_bytes()
        b64 = base64.b64encode(pdf_bytes).decode()
        pdf_height = st.slider("Viewer height (px)", 400, 1200, 700,
                               step=50, key="pdf_view_height")
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'width="100%" height="{pdf_height}px" '
            f'style="border:none;border-radius:8px;"></iframe>',
            unsafe_allow_html=True,
        )
    except Exception as _ve:
        st.error(f"Could not render PDF: {_ve}")
        st.info("Try downloading the file instead.")

    # Download button as fallback
    try:
        st.download_button(
            "⬇ Download PDF",
            data=Path(file_path).read_bytes(),
            file_name=Path(file_path).name,
            mime="application/pdf",
            key="pdf_view_dl",
        )
    except Exception:
        pass

    # Raw text extraction (collapsed)
    with st.expander("📝 Extracted text (first 3 pages)", expanded=False):
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages[:3]):
                    txt = page.extract_text() or "(no text on this page)"
                    st.markdown(f"**Page {i+1}**")
                    st.text(txt[:3000])
        except Exception as _te:
            st.warning(f"Text extraction unavailable: {_te}")


# ─────────────────────────────────────────────────────────────────────────────
# Extract tab
# ─────────────────────────────────────────────────────────────────────────────

def _render_extract(engine, dialect):
    import pandas as pd
    if not st.session_state.get("pdf_view_load_mode"):
        st.markdown("#### ⚙️ Extract & Validate")
    st.caption(
        "Extracts structured data from the selected PDF. "
        "Supports directional surveys, formation tops, core, DST, RFT/MDT, "
        "scout tickets, DDR, well tests, petrophysical, EOWR and casing records."
    )

    if "pdf_classified" not in st.session_state:
        st.info("Run a scan first.")
        return

    extractable = [f for f in st.session_state["pdf_classified"]
                   if f.get("report_type") in _EXTRACTABLE]
    if not extractable:
        st.warning("No extractable reports found in scan results. "
                   "Run a scan first, or check that PDFs were classified correctly.")
        return

    # Always use the viewed file — no second selector
    _viewed = st.session_state.get("pdf_viewed_file")
    if not _viewed:
        st.info("Select and view a file first.")
        return
    # Find the matching file record from scan results
    opts = {f["file_path"]: f for f in extractable}
    _opt_keys = [_viewed]
    _default_idx = 0

    # Auto-use the viewed file — no second selector
    sel = _viewed
    f   = opts.get(_viewed, {
        "file_path":   _viewed,
        "file_name":   Path(_viewed).name,
        "report_type": RT_UNKNOWN,
        "well_name":   "",
        "uwi":         "",
    })
    rt  = f.get("report_type", RT_UNKNOWN)

    st.caption(f"Type: **{REPORT_LABELS.get(rt, rt)}** · `{f['file_path']}`")

    # Well header fields (editable) + UWI verification
    st.markdown("**Well identification**")
    h1, h2, h3 = st.columns(3)
    uwi       = h1.text_input("UWI",       value=f.get("uwi",""),       key="pdf_uwi")
    well_name = h2.text_input("Well Name", value=f.get("well_name",""), key="pdf_wn")
    operator  = h3.text_input("Operator",  value=f.get("operator",""),  key="pdf_op")
    h4, h5 = st.columns(2)
    field  = h4.text_input("Field", value=f.get("field",""), key="pdf_fld")
    state  = h5.text_input("State", value=f.get("state",""), key="pdf_st")

    # ── Extracted header attributes (always shown) ──────────────────────────
    import pandas as _pd2
    _load_header_attrs = [
        ("Report Type",   f.get("report_type", "—")),
        ("Confidence",    f"{int(f.get('confidence', 0)*100)}%"
                          if f.get("confidence") else "—"),
        ("Field",         f.get("field") or "—"),
        ("State",         f.get("state") or "—"),
        ("Contractor",    f.get("contractor") or "—"),
        ("Survey Type",   f.get("survey_type") or "—"),
        ("Total Depth",   f.get("total_depth") or "—"),
        ("Station Count", str(f.get("station_count", 0))),
        ("Latitude",      f.get("latitude") or "—"),
        ("Longitude",     f.get("longitude") or "—"),
        ("Page Count",    str(f.get("page_count", "—"))),
    ]
    _lhdf = _pd2.DataFrame(
        [{"Attribute": k, "Value": str(v)}
         for k, v in _load_header_attrs if v not in (None, "—", "0")]
    )
    if not _lhdf.empty:
        with st.expander("📋 Extracted header attributes", expanded=True):
            st.dataframe(_lhdf, hide_index=True, use_container_width=True)

    # ── UWI resolution against dv_well ──────────────────────────────────────
    _uwi_ovr_key = f"uwi_override_{f.get('file_path','')}"
    _resolved_uwi = None
    _uwi_status   = None

    if uwi and engine is not None:
        try:
            from sqlalchemy import text as _text
            import re as _re
            def _norm(v):
                return _re.sub(r"[\-\s/]", "", str(v or "")).upper()

            with engine.connect() as _con:
                # 1. Exact match
                _row = _con.execute(_text(
                    "SELECT uwi, well_name FROM dataview.dv_well WHERE uwi = :u"
                ), {"u": uwi}).fetchone()
                if _row:
                    _resolved_uwi = _row[0]
                    _uwi_status = ("exact", _row)
                else:
                    # 2. Normalized match (strip dashes/spaces)
                    _norm_uwi = _norm(uwi)
                    _row2 = _con.execute(_text(
                        "SELECT uwi, well_name FROM dataview.dv_well "
                        "WHERE REPLACE(REPLACE(REPLACE(uwi,'-',''),' ',''),'/','') = :n"
                    ), {"n": _norm_uwi}).fetchone()
                    if _row2:
                        _resolved_uwi = _row2[0]
                        _uwi_status = ("normalized", _row2)

            if _uwi_status and _uwi_status[0] == "exact":
                st.success(f"✅ UWI exact match — **{_uwi_status[1][1] or _resolved_uwi}**")
            elif _uwi_status and _uwi_status[0] == "normalized":
                st.warning(
                    f"⚠️ UWI normalized match: `{uwi}` → `{_resolved_uwi}` "
                    f"(**{_uwi_status[1][1] or _resolved_uwi}**) — confirm below"
                )
            else:
                _has_coords = bool(f.get("latitude") and f.get("longitude"))
                if _has_coords:
                    st.info(
                        f"ℹ️ UWI `{uwi}` not in dv_well — "
                        f"well will be **auto-created** from header (lat/lon available)"
                    )
                else:
                    st.warning(
                        f"⚠️ UWI `{uwi}` not in dv_well and no lat/lon in header. "
                        f"Enter override UWI below or add well manually."
                    )
        except Exception as _e:
            st.caption(f"DB check skipped: {_e}")

    # Override field — always shown so user can correct mismatches
    _ovr_val = st.session_state.get(_uwi_ovr_key, "")
    _ovr_new = st.text_input(
        "UWI override (leave blank to use auto-matched UWI)",
        value=_ovr_val,
        placeholder="e.g. 42-135-22222-00-00",
        key=f"uwi_ovr_{f.get('file_path','')}",
        help="Type a different UWI here to override the auto-match. "
             "The loader will use this value instead."
    )
    if _ovr_new != _ovr_val:
        st.session_state[_uwi_ovr_key] = _ovr_new

    st.divider()

    # ── Type-specific extraction ──────────────────────────────────────────────
    if rt == RT_DIRECTIONAL:
        _extract_directional(f, uwi, well_name, operator, field, state)
    elif rt == RT_FORMATION:
        _extract_formation(f, uwi, well_name)
    elif rt == RT_CORE:
        _extract_core(f, uwi, well_name)
    elif rt == RT_DST:
        _extract_dst(f, uwi, well_name)
    elif rt == RT_RFT:
        _extract_rft(f, uwi, well_name)
    elif rt == RT_SCOUT:
        _extract_scout(f, uwi, well_name)
    elif rt == RT_DDR:
        _extract_ddr_ui(f, uwi, well_name)
    elif rt == RT_WELL_TEST:
        _extract_well_test_ui(f, uwi, well_name)
    elif rt == RT_PETRO:
        _extract_petro_ui(f, uwi, well_name)
    elif rt == RT_EOWR:
        _extract_eowr_ui(f, uwi, well_name)
    elif rt == RT_CASING:
        _extract_casing_ui(f, uwi, well_name)
    else:
        st.info("No structured extraction available for this report type. "
                "Use the View tab to read the PDF content.")


def _extract_directional(f, uwi, well_name, operator, field, state):
    import pandas as pd
    stype = st.selectbox("Survey type",
                         ["MWD", "Gyro", "Magnetic", "Accelerometer"],
                         key="pdf_stype")

    # Key extraction results to the specific file so switching files clears stale state
    _file_key = f"pdf_extract_{f.get('file_id', f['file_name'])}"

    if st.button("📐 Extract Stations", type="primary", key="pdf_extract_btn"):
        with st.spinner("Extracting…"):
            ext = extract_stations(f["file_path"])
        st.session_state[_file_key]              = ext
        st.session_state["pdf_extract"]          = ext
        st.session_state["pdf_extract_type"]     = RT_DIRECTIONAL
        st.session_state["pdf_extract_file"]     = f["file_path"]

    # Only show results if they belong to the currently selected file
    if st.session_state.get("pdf_extract_file") != f["file_path"]:
        return
    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_DIRECTIONAL:
        return
    if ext.get("error"):
        st.error(f"Extraction error: {ext['error']}")
        return

    stations = ext.get("stations", [])

    if not stations:
        st.error("No stations extracted. Check the View tab to confirm the PDF "
                 "contains a text-based survey table (not a scanned image).")
        cols_found = ext.get("columns_found", [])
        if cols_found:
            st.caption(f"Columns detected: **{', '.join(cols_found)}** — "
                       "header found but no data rows parsed.")
        else:
            st.caption("No column header detected. The PDF layout may not be supported.")
        return

    val = validate_stations(stations)

    m1, m2, m3 = st.columns(3)
    m1.metric("Stations", len(stations))
    m2.metric("MD range", val.get("md_range", "—"))
    m3.metric("Status", "✅ Valid" if val["valid"] else "⚠️ Errors")

    for e in val.get("errors", []):   st.error(e)
    for w in val.get("warnings", []): st.warning(w)

    st.caption(f"Columns detected: **{', '.join(ext.get('columns_found', []))}**")

    df = pd.DataFrame(stations)
    st.dataframe(df.round(2), hide_index=True,
                 use_container_width=True, height=220)

    # Trajectory plots
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        mds  = [s.get("MD",0)  for s in stations]
        incs = [s.get("INC",0) for s in stations]
        tvds = [s.get("TVD",0) for s in stations]
        ns   = [s.get("NS",0)  for s in stations]
        ew   = [s.get("EW",0)  for s in stations]
        NAVY = "#1A2B4A"; GOLD = "#C8922A"
        fig  = make_subplots(rows=1, cols=3,
            subplot_titles=("Inc vs Depth","Plan View","Cross Section"),
            horizontal_spacing=0.08)
        fig.add_trace(go.Scatter(x=incs, y=mds, mode='lines+markers',
            line=dict(color=NAVY,width=2), marker=dict(size=4,color=GOLD),
            hovertemplate="MD:%{y:.0f} ft  Inc:%{x:.1f}°<extra></extra>"),
            row=1,col=1)
        fig.add_trace(go.Scatter(x=ew, y=ns, mode='lines+markers',
            line=dict(color=NAVY,width=2), marker=dict(size=4,color=GOLD),
            hovertemplate="E/W:%{x:.0f}  N/S:%{y:.0f}<extra></extra>"),
            row=1,col=2)
        fig.add_trace(go.Scatter(x=ew, y=[-t for t in tvds],
            mode='lines+markers',
            line=dict(color=NAVY,width=2), marker=dict(size=4,color=GOLD),
            customdata=tvds,
            hovertemplate="E/W:%{x:.0f}  TVD:%{customdata:.0f}<extra></extra>"),
            row=1,col=3)
        fig.update_yaxes(autorange="reversed", title_text="MD (ft)", row=1, col=1)
        fig.update_xaxes(title_text="Inc (°)", row=1, col=1)
        fig.update_xaxes(title_text="Easting (ft)", row=1, col=2)
        fig.update_yaxes(title_text="Northing (ft)", row=1, col=2)
        fig.update_xaxes(title_text="Easting (ft)", row=1, col=3)
        fig.update_yaxes(title_text="TVD (ft)", row=1, col=3)
        fig.update_layout(height=320, margin=dict(l=10,r=10,t=30,b=10),
            showlegend=False, paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)', font=dict(size=10))
        fig.update_xaxes(gridcolor='rgba(128,128,128,0.15)')
        fig.update_yaxes(gridcolor='rgba(128,128,128,0.15)')
        st.plotly_chart(fig, use_container_width=True)
    except Exception as _pe:
        st.caption(f"Plot unavailable: {_pe}")

    st.session_state["pdf_well_info"] = {
        "uwi": uwi, "well_name": well_name,
        "operator": operator, "field": field,
        "state": state, "survey_type": stype,
    }
    st.session_state["pdf_stations"]     = stations
    st.session_state["pdf_valid"]        = val["valid"]
    st.session_state["pdf_load_type"]    = RT_DIRECTIONAL
    st.download_button("⬇ Export stations CSV",
        data=df.to_csv(index=False), file_name="dir_survey_stations.csv",
        mime="text/csv", key="pdf_dir_dl")

    _render_catalog_widget(f, RT_DIRECTIONAL,
        {"uwi": uwi, "well_name": well_name, "operator": operator},
        stations, f.get("page_count", 0))


def _extract_formation(f, uwi, well_name):
    import pandas as pd
    st.markdown("**Formation Tops extraction**")

    if st.button("🪨 Extract Formation Tops", type="primary", key="pdf_form_btn"):
        with st.spinner("Extracting…"):
            rows = _parse_formation_tops(f["file_path"])
        st.session_state["pdf_extract"]      = {"rows": rows}
        st.session_state["pdf_extract_type"] = RT_FORMATION

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_FORMATION:
        return

    rows = ext.get("rows", [])
    if not rows:
        st.warning("No formation tops found. The PDF may use a non-standard layout.")
        return

    df = pd.DataFrame(rows)
    st.metric("Formations found", len(df))
    st.dataframe(df, hide_index=True, use_container_width=True,
                 height=min(38 + len(df)*35, 400))

    st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name}
    st.session_state["pdf_stations"]   = rows
    st.session_state["pdf_valid"]      = True
    st.session_state["pdf_load_type"]  = RT_FORMATION
    st.download_button("⬇ Export formation tops CSV",
        data=df.to_csv(index=False), file_name="formation_tops.csv",
        mime="text/csv", key="pdf_form_dl")

    _render_catalog_widget(f, RT_FORMATION,
        {"uwi": uwi, "well_name": well_name}, rows, f.get("page_count", 0))


def _extract_core(f, uwi, well_name):
    import pandas as pd
    st.markdown("**Core Data extraction**")

    if st.button("🧪 Extract Core Data", type="primary", key="pdf_core_btn"):
        with st.spinner("Extracting…"):
            rows = _parse_core_data(f["file_path"])
        st.session_state["pdf_extract"]      = {"rows": rows}
        st.session_state["pdf_extract_type"] = RT_CORE

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_CORE:
        return

    rows = ext.get("rows", [])
    if not rows:
        st.warning("No core data table found. The PDF may use a scanned image layout.")
        return

    df = pd.DataFrame(rows)
    st.metric("Core samples", len(df))
    st.dataframe(df, hide_index=True, use_container_width=True,
                 height=min(38 + len(df)*35, 400))

    # Quick porosity/permeability plot
    try:
        import plotly.graph_objects as go
        NAVY = "#1A2B4A"; GOLD = "#C8922A"
        depths = [r.get("DEPTH_TOP") or r.get("DEPTH") for r in rows]
        pors   = [r.get("POROSITY") for r in rows]
        perms  = [r.get("PERMEABILITY") for r in rows]
        fig = go.Figure()
        if any(p is not None for p in pors):
            fig.add_trace(go.Scatter(x=pors, y=depths, mode='markers+lines',
                name="Porosity (%)", line=dict(color=NAVY),
                hovertemplate="Depth: %{y}<br>Por: %{x:.1f}%<extra></extra>"))
        if any(p is not None for p in perms):
            fig.add_trace(go.Scatter(x=perms, y=depths, mode='markers+lines',
                name="Perm (mD)", line=dict(color=GOLD),
                xaxis="x2",
                hovertemplate="Depth: %{y}<br>Perm: %{x:.2f} mD<extra></extra>"))
        fig.update_yaxes(autorange="reversed", title_text="Depth")
        fig.update_layout(height=350, margin=dict(l=10,r=10,t=30,b=10),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(size=10), title="Core Analysis")
        fig.update_xaxes(gridcolor='rgba(128,128,128,0.15)')
        fig.update_yaxes(gridcolor='rgba(128,128,128,0.15)')
        st.plotly_chart(fig, use_container_width=True)
    except Exception as _pe:
        st.caption(f"Plot unavailable: {_pe}")

    st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name}
    st.session_state["pdf_stations"]   = rows
    st.session_state["pdf_valid"]      = True
    st.session_state["pdf_load_type"]  = RT_CORE
    st.download_button("⬇ Export core data CSV",
        data=df.to_csv(index=False), file_name="core_data.csv",
        mime="text/csv", key="pdf_core_dl")

    _render_catalog_widget(f, RT_CORE,
        {"uwi": uwi, "well_name": well_name}, rows, f.get("page_count", 0))


def _extract_dst(f, uwi, well_name):
    import pandas as pd
    st.markdown("**Drill Stem Test extraction**")

    if st.button("💧 Extract DST Data", type="primary", key="pdf_dst_btn"):
        with st.spinner("Extracting…"):
            result = _parse_dst(f["file_path"])
        st.session_state["pdf_extract"]      = result
        st.session_state["pdf_extract_type"] = RT_DST

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_DST:
        return

    header = ext.get("header", {})
    rows   = ext.get("rows", [])

    if not header and not rows:
        st.warning("No DST data found. The PDF may use a scanned image layout.")
        return

    # Header summary
    if header:
        st.markdown("**Test header**")
        hdf = pd.DataFrame([{"Field": k, "Value": v}
                             for k, v in header.items() if v])
        st.dataframe(hdf, hide_index=True, use_container_width=True,
                     height=min(38 + len(hdf)*35, 280))

    # Pressure/rate table
    if rows:
        st.markdown("**Pressure / rate data**")
        df = pd.DataFrame(rows)
        st.metric("Data points", len(df))
        st.dataframe(df, hide_index=True, use_container_width=True,
                     height=min(38 + len(df)*35, 350))

        # Pressure vs time plot
        try:
            import plotly.graph_objects as go
            times = [r.get("TIME") for r in rows]
            press = [r.get("PRESSURE") for r in rows]
            if any(p is not None for p in press):
                fig = go.Figure(go.Scatter(
                    x=times, y=press, mode='lines+markers',
                    line=dict(color="#1A2B4A", width=2),
                    marker=dict(size=4, color="#C8922A"),
                    hovertemplate="Time: %{x}<br>Pressure: %{y:.0f} psi<extra></extra>",
                ))
                fig.update_layout(height=300,
                    xaxis_title="Time", yaxis_title="Pressure (psi)",
                    margin=dict(l=10,r=10,t=10,b=10),
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)', font=dict(size=10))
                fig.update_xaxes(gridcolor='rgba(128,128,128,0.15)')
                fig.update_yaxes(gridcolor='rgba(128,128,128,0.15)')
                st.plotly_chart(fig, use_container_width=True)
        except Exception as _pe:
            st.caption(f"Plot unavailable: {_pe}")

        st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name,
                                               **header}
        st.session_state["pdf_stations"]   = rows
        st.session_state["pdf_valid"]      = True
        st.session_state["pdf_load_type"]  = RT_DST
        st.download_button("⬇ Export DST data CSV",
            data=df.to_csv(index=False), file_name="dst_data.csv",
            mime="text/csv", key="pdf_dst_dl")

        _render_catalog_widget(f, RT_DST,
            {"uwi": uwi, "well_name": well_name}, rows, f.get("page_count", 0))


# ── RFT / MDT ─────────────────────────────────────────────────────────────────

def _extract_rft(f, uwi, well_name):
    import pandas as pd
    st.markdown("**RFT / MDT Pressure Measurements**")
    if st.button("💉 Extract RFT/MDT Data", type="primary", key="pdf_rft_btn"):
        with st.spinner("Extracting…"):
            result = extract_rft_data(f["file_path"])
        st.session_state["pdf_extract"]      = result
        st.session_state["pdf_extract_type"] = RT_RFT

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_RFT:
        return
    if ext.get("error"):
        st.error(f"Extraction error: {ext['error']}")
        return

    rows = ext.get("rows", [])
    if not rows:
        st.warning("No pressure measurements found.")
        return

    df = pd.DataFrame(rows)
    df = df.applymap(lambda x: str(x) if x is not None else "—")
    st.metric("Measurements", len(df))
    st.dataframe(df, hide_index=True, use_container_width=True,
                 height=min(38 + len(df)*35, 400))
    st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name}
    st.session_state["pdf_stations"]   = rows
    st.session_state["pdf_valid"]      = True
    st.session_state["pdf_load_type"]  = RT_RFT
    st.download_button("⬇ Export CSV", data=df.to_csv(index=False),
        file_name="rft_data.csv", mime="text/csv", key="pdf_rft_dl")
    _render_catalog_widget(f, RT_RFT,
        {"uwi": uwi, "well_name": well_name}, rows, f.get("page_count", 0))


# ── Scout Ticket ──────────────────────────────────────────────────────────────

def _extract_scout(f, uwi, well_name):
    import pandas as pd
    st.markdown("**Scout Ticket**")
    if st.button("🎫 Extract Scout Data", type="primary", key="pdf_scout_btn"):
        with st.spinner("Extracting…"):
            result = extract_scout_ticket(f["file_path"])
        st.session_state["pdf_extract"]      = result
        st.session_state["pdf_extract_type"] = RT_SCOUT

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_SCOUT:
        return
    if ext.get("error"):
        st.error(f"Extraction error: {ext['error']}")
        return

    header = ext.get("header", {})
    ip_rows = ext.get("ip_rows", [])

    if header:
        st.markdown("**Well header**")
        hdf = pd.DataFrame([{"Field": k, "Value": str(v)} for k, v in header.items() if v])
        st.dataframe(hdf, hide_index=True, use_container_width=True,
                     height=min(38 + len(hdf)*35, 280))

    if ip_rows:
        st.markdown("**Initial Production**")
        df = pd.DataFrame(ip_rows)
        df = df.applymap(lambda x: str(x) if x is not None else "—")
        st.dataframe(df, hide_index=True, use_container_width=True,
                     height=min(38 + len(df)*35, 300))
        st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name, **header}
        st.session_state["pdf_stations"]   = ip_rows
        st.session_state["pdf_valid"]      = True
        st.session_state["pdf_load_type"]  = RT_SCOUT
        st.download_button("⬇ Export IP CSV", data=df.to_csv(index=False),
            file_name="scout_ip.csv", mime="text/csv", key="pdf_scout_dl")
    _render_catalog_widget(f, RT_SCOUT,
        {"uwi": uwi, "well_name": well_name}, ip_rows, f.get("page_count", 0))


# ── Daily Drilling Report ─────────────────────────────────────────────────────

def _extract_ddr_ui(f, uwi, well_name):
    import pandas as pd
    st.markdown("**Daily Drilling Report**")
    if st.button("📋 Extract DDR Data", type="primary", key="pdf_ddr_btn"):
        with st.spinner("Extracting…"):
            result = extract_ddr(f["file_path"])
        st.session_state["pdf_extract"]      = result
        st.session_state["pdf_extract_type"] = RT_DDR

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_DDR:
        return
    if ext.get("error"):
        st.error(f"Extraction error: {ext['error']}")
        return

    hdr = ext.get("header", {})
    if hdr:
        st.markdown("**Report header**")
        hdf = pd.DataFrame([{"Field": k, "Value": str(v)} for k, v in hdr.items()])
        st.dataframe(hdf, hide_index=True, use_container_width=True, height=200)

    for section, label in [("ops","Operations"), ("params","Drilling Parameters"), ("mud","Mud Properties")]:
        rows = ext.get(section, [])
        if rows:
            st.markdown(f"**{label}**")
            df = pd.DataFrame(rows).applymap(lambda x: str(x) if x is not None else "—")
            st.dataframe(df, hide_index=True, use_container_width=True,
                         height=min(38 + len(df)*35, 300))

    all_rows = ext.get("ops", [])
    st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name}
    st.session_state["pdf_stations"]   = all_rows
    st.session_state["pdf_valid"]      = True
    st.session_state["pdf_load_type"]  = RT_DDR
    _render_catalog_widget(f, RT_DDR,
        {"uwi": uwi, "well_name": well_name}, all_rows, f.get("page_count", 0))


# ── Well Test ─────────────────────────────────────────────────────────────────

def _extract_well_test_ui(f, uwi, well_name):
    import pandas as pd
    st.markdown("**Well Test / Production Test**")
    if st.button("🧪 Extract Well Test Data", type="primary", key="pdf_wt_btn"):
        with st.spinner("Extracting…"):
            result = extract_well_test(f["file_path"])
        st.session_state["pdf_extract"]      = result
        st.session_state["pdf_extract_type"] = RT_WELL_TEST

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_WELL_TEST:
        return
    if ext.get("error"):
        st.error(f"Extraction error: {ext['error']}")
        return

    analysis  = ext.get("analysis", {})
    flow_rows = ext.get("flow_rows", [])

    if analysis:
        st.markdown("**Reservoir analysis**")
        adf = pd.DataFrame([{"Parameter": k, "Value": str(v)}
                            for k, v in analysis.items()])
        st.dataframe(adf, hide_index=True, use_container_width=True,
                     height=min(38 + len(adf)*35, 320))

    if flow_rows:
        st.markdown("**Flow periods**")
        df = pd.DataFrame(flow_rows).applymap(lambda x: str(x) if x is not None else "—")
        st.dataframe(df, hide_index=True, use_container_width=True,
                     height=min(38 + len(df)*35, 300))
        st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name}
        st.session_state["pdf_stations"]   = flow_rows
        st.session_state["pdf_valid"]      = True
        st.session_state["pdf_load_type"]  = RT_WELL_TEST
        st.download_button("⬇ Export flow periods CSV",
            data=df.to_csv(index=False), file_name="well_test.csv",
            mime="text/csv", key="pdf_wt_dl")
    _render_catalog_widget(f, RT_WELL_TEST,
        {"uwi": uwi, "well_name": well_name, **analysis},
        flow_rows, f.get("page_count", 0))


# ── Petrophysical ─────────────────────────────────────────────────────────────

def _extract_petro_ui(f, uwi, well_name):
    import pandas as pd
    st.markdown("**Petrophysical Interpretation**")
    if st.button("📈 Extract Petrophysical Data", type="primary", key="pdf_petro_btn"):
        with st.spinner("Extracting…"):
            result = extract_petrophysical(f["file_path"])
        st.session_state["pdf_extract"]      = result
        st.session_state["pdf_extract_type"] = RT_PETRO

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_PETRO:
        return
    if ext.get("error"):
        st.error(f"Extraction error: {ext['error']}")
        return

    zones    = ext.get("zones", [])
    interval = ext.get("interval", [])

    if zones:
        st.markdown("**Zone summary**")
        df = pd.DataFrame(zones).applymap(lambda x: str(x) if x is not None else "—")
        st.metric("Zones", len(df))
        st.dataframe(df, hide_index=True, use_container_width=True,
                     height=min(38 + len(df)*35, 350))
        st.download_button("⬇ Export zone summary CSV",
            data=df.to_csv(index=False), file_name="petro_zones.csv",
            mime="text/csv", key="pdf_petro_dl")

    if interval:
        st.markdown("**Interval log data**")
        df2 = pd.DataFrame(interval).applymap(lambda x: str(x) if x is not None else "—")
        st.dataframe(df2, hide_index=True, use_container_width=True,
                     height=min(38 + len(df2)*35, 350))

    all_rows = zones or interval
    st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name}
    st.session_state["pdf_stations"]   = all_rows
    st.session_state["pdf_valid"]      = bool(all_rows)
    st.session_state["pdf_load_type"]  = RT_PETRO
    _render_catalog_widget(f, RT_PETRO,
        {"uwi": uwi, "well_name": well_name}, all_rows, f.get("page_count", 0))


# ── End of Well Report ────────────────────────────────────────────────────────

def _extract_eowr_ui(f, uwi, well_name):
    import pandas as pd
    st.markdown("**End of Well Report**")
    if st.button("📝 Extract EOWR Data", type="primary", key="pdf_eowr_btn"):
        with st.spinner("Extracting…"):
            result = extract_eowr(f["file_path"])
        st.session_state["pdf_extract"]      = result
        st.session_state["pdf_extract_type"] = RT_EOWR

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_EOWR:
        return
    if ext.get("error"):
        st.error(f"Extraction error: {ext['error']}")
        return

    summary = ext.get("summary", {})
    strat   = ext.get("strat", [])
    npt     = ext.get("npt", [])

    if summary:
        st.markdown("**Well summary**")
        sdf = pd.DataFrame([{"Field": k, "Value": str(v)} for k,v in summary.items()])
        st.dataframe(sdf, hide_index=True, use_container_width=True,
                     height=min(38 + len(sdf)*35, 320))

    if strat:
        st.markdown("**Stratigraphic tops**")
        df = pd.DataFrame(strat).applymap(lambda x: str(x) if x is not None else "—")
        st.dataframe(df, hide_index=True, use_container_width=True,
                     height=min(38 + len(df)*35, 350))
        st.download_button("⬇ Export stratigraphy CSV",
            data=df.to_csv(index=False), file_name="eowr_strat.csv",
            mime="text/csv", key="pdf_eowr_strat_dl")

    if npt:
        st.markdown("**NPT events**")
        df2 = pd.DataFrame(npt).applymap(lambda x: str(x) if x is not None else "—")
        st.dataframe(df2, hide_index=True, use_container_width=True,
                     height=min(38 + len(df2)*35, 280))

    all_rows = strat or npt
    st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name, **summary}
    st.session_state["pdf_stations"]   = all_rows
    st.session_state["pdf_valid"]      = bool(all_rows)
    st.session_state["pdf_load_type"]  = RT_EOWR
    _render_catalog_widget(f, RT_EOWR,
        {"uwi": uwi, "well_name": well_name}, all_rows, f.get("page_count", 0))


# ── Casing & Cementing ────────────────────────────────────────────────────────

def _extract_casing_ui(f, uwi, well_name):
    import pandas as pd
    st.markdown("**Casing & Cementing Record**")
    if st.button("🔩 Extract Casing Data", type="primary", key="pdf_cas_btn"):
        with st.spinner("Extracting…"):
            result = extract_casing_cement(f["file_path"])
        st.session_state["pdf_extract"]      = result
        st.session_state["pdf_extract_type"] = RT_CASING

    ext = st.session_state.get("pdf_extract")
    if not ext or st.session_state.get("pdf_extract_type") != RT_CASING:
        return
    if ext.get("error"):
        st.error(f"Extraction error: {ext['error']}")
        return

    for section, label, dl_key, fn in [
        ("casing",  "Casing programme",  "pdf_cas_dl",  "casing.csv"),
        ("cement",  "Cement job summary","pdf_cem_dl",  "cement.csv"),
        ("cbl",     "CBL evaluation",    "pdf_cbl_dl",  "cbl.csv"),
    ]:
        rows = ext.get(section, [])
        if rows:
            st.markdown(f"**{label}**")
            df = pd.DataFrame(rows).applymap(lambda x: str(x) if x is not None else "—")
            st.dataframe(df, hide_index=True, use_container_width=True,
                         height=min(38 + len(df)*35, 280))
            st.download_button(f"⬇ Export {label} CSV",
                data=df.to_csv(index=False), file_name=fn,
                mime="text/csv", key=dl_key)

    all_rows = ext.get("casing", []) + ext.get("cement", [])
    st.session_state["pdf_well_info"]  = {"uwi": uwi, "well_name": well_name}
    st.session_state["pdf_stations"]   = all_rows
    st.session_state["pdf_valid"]      = bool(all_rows)
    st.session_state["pdf_load_type"]  = RT_CASING
    _render_catalog_widget(f, RT_CASING,
        {"uwi": uwi, "well_name": well_name}, all_rows, f.get("page_count", 0))




def _render_load(engine, dialect):
    import pandas as pd
    if not st.session_state.get("pdf_view_load_mode"):
        st.markdown("#### 🚀 Load to DB")
    st.caption("Optional — only load when extraction and validation look correct.")

    if engine is None:
        st.warning("⚠️ No database connection — connect via the pipeline first.")
        return
    if "pdf_stations" not in st.session_state:
        st.info("Extract data first in the Extract & Validate tab.")
        return

    rows      = st.session_state["pdf_stations"]
    well_info = st.session_state.get("pdf_well_info", {})
    valid     = st.session_state.get("pdf_valid", False)
    load_type = st.session_state.get("pdf_load_type", RT_UNKNOWN)

    st.markdown(f"**Ready to load:** {REPORT_ICONS.get(load_type,'')} "
                f"{REPORT_LABELS.get(load_type, load_type)}")

    # Summary table
    info_rows = [
        {"Field": "UWI",       "Value": well_info.get("uwi","—")},
        {"Field": "Well Name", "Value": well_info.get("well_name","—")},
        {"Field": "Operator",  "Value": well_info.get("operator","—")},
        {"Field": "Records",   "Value": str(len(rows))},
        {"Field": "Valid",     "Value": "✅ Yes" if valid else "⚠️ Has errors"},
    ]
    if load_type == RT_DIRECTIONAL:
        info_rows.append({"Field": "PPDM Target",
                          "Value": "WELL_DIR_SURVEY + WELL_DIR_SRVY_STATION"})
    elif load_type == RT_FORMATION:
        info_rows.append({"Field": "PPDM Target", "Value": "WELL_FORMATION"})
    elif load_type == RT_CORE:
        info_rows.append({"Field": "PPDM Target",
                          "Value": "WELL_CORE + WELL_CORE_ANALYSIS"})
    elif load_type == RT_DST:
        info_rows.append({"Field": "PPDM Target",
                          "Value": "WELL_TEST + WELL_TEST_RESULT"})

    st.dataframe(pd.DataFrame(info_rows), hide_index=True,
                 use_container_width=True, height=len(info_rows)*38+38)

    if not valid:
        st.warning("⚠️ Validation errors found — review in Extract tab before loading.")

    # ── UWI verification ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("**Well identification**")

    _uwi = well_info.get("uwi", "").strip()
    _uwi_override = st.text_input(
        "UWI",
        value=_uwi,
        key="pdf_load_uwi",
        help="Must match an existing UWI in dbo.WELL. Override if the "
             "extracted value is wrong or in a different format."
    )

    _chk_col, _status_col = st.columns([1, 3])
    with _chk_col:
        if st.button("🔎 Check DB", key="pdf_chk_uwi"):
            if _uwi_override.strip():
                try:
                    from sqlalchemy import text as _sqlt
                    with engine.connect() as _con:
                        _row = _con.execute(_sqlt(
                            "SELECT WELL_NAME, OPERATOR FROM dbo.WELL "
                            "WHERE UWI = :u"
                        ), {"u": _uwi_override.strip()}).fetchone()
                    st.session_state["pdf_uwi_check"] = (
                        _row, _uwi_override.strip()
                    )
                except Exception as _ue:
                    st.error(str(_ue))

    with _status_col:
        _chk = st.session_state.get("pdf_uwi_check")
        if _chk:
            _chk_row, _chk_uwi = _chk
            if _chk_row:
                st.success(
                    f"✅ **{_chk_uwi}** found — "
                    f"{_chk_row[0] or ''} · {_chk_row[1] or ''}"
                )
            else:
                st.error(f"❌ **{_chk_uwi}** not found in dbo.WELL")
                # Fuzzy search suggestion
                with st.expander("🔍 Search PPDM wells", expanded=True):
                    _q = st.text_input(
                        "Search by UWI or well name",
                        value=well_info.get("well_name", ""),
                        key="pdf_well_search"
                    )
                    if st.button("Search", key="pdf_well_search_btn") and _q:
                        try:
                            from sqlalchemy import text as _sqlt
                            with engine.connect() as _con:
                                _results = _con.execute(_sqlt(
                                    "SELECT TOP 10 UWI, WELL_NAME, OPERATOR "
                                    "FROM dbo.WELL "
                                    "WHERE UWI LIKE :q OR WELL_NAME LIKE :q "
                                    "ORDER BY WELL_NAME"
                                ), {"q": f"%{_q}%"}).fetchall()
                            st.session_state["pdf_well_results"] = _results
                        except Exception as _se:
                            st.error(str(_se))

                    _results = st.session_state.get("pdf_well_results", [])
                    if _results:
                        _opts = {
                            f"{r[0]}  —  {r[1] or ''}  {r[2] or ''}": r[0]
                            for r in _results
                        }
                        _picked = st.selectbox(
                            "Select well",
                            ["— pick one —"] + list(_opts.keys()),
                            key="pdf_well_pick"
                        )
                        if _picked != "— pick one —":
                            _picked_uwi = _opts[_picked]
                            st.info(f"Selected: `{_picked_uwi}` — "
                                    f"update the UWI field above and re-check.")

    # Update well_info UWI from override
    well_info = {**well_info, "uwi": _uwi_override.strip()}
    st.session_state["pdf_well_info"] = well_info

    st.divider()
    source = st.selectbox(
        "Source",
        ["DATA_LOADER", "LAS_LOADER", "LAS_IMPORT", "OPERATOR", "IHS",
         "DIGITIZED", "ESTIMATED", "CALCULATED", "INDUSTRY", "PPDM"],
        key="pdf_src_tag",
        help="Must match a value in dbo.r_source."
    )

    if not well_info.get("uwi"):
        st.error("UWI is required — enter a valid UWI above before loading.")
    else:
        # ── Step 1: Catalog the file ──────────────────────────────────
        _file_path = st.session_state.get("pdf_viewed_file", "")
        _is_cataloged = st.session_state.get(
            f"pdf_cataloged_{_file_path}", False)

        if not _is_cataloged:
            if st.button("📁 Catalog File", type="secondary",
                         use_container_width=True, key="pdf_catalog_btn"):
                try:
                    from modules.doc_catalog_store import catalog_document
                    _uwi = well_info.get("uwi", "")
                    r = catalog_document(
                        engine=engine, dialect=dialect,
                        file_path=_file_path,
                        doc_type=load_type,
                        meta={
                            "uwi":       _uwi,
                            "well_name": well_info.get("well_name", ""),
                            "operator":  well_info.get("operator", ""),
                        },
                        records=rows,
                        source="PDF_CATALOG",
                    )
                    if r.get("ok"):
                        st.session_state[f"pdf_cataloged_{_file_path}"] = True
                        st.success("✅ File cataloged in GLOBAL_FILE_CATALOG")
                        st.rerun()
                    else:
                        st.error(f"Catalog failed: {r.get('error')}")
                except Exception as e:
                    st.error(f"Catalog failed: {e}")
        else:
            st.success("✅ File cataloged — optionally load data to DB below")

        # ── Step 2: Load to DB (only after cataloging) ────────────────
        if _is_cataloged and st.button(
            f"🚀 Load to DB — {len(rows)} records",
            type="primary",
            use_container_width=True,
            key="pdf_load_btn"
        ):
            with st.spinner("Loading…"):
                if load_type == RT_DIRECTIONAL:
                    result = load_to_ppdm(
                        well_info=well_info, stations=rows,
                        engine=engine, dialect=dialect,
                        source=source, dry_run=False,
                    )
                else:
                    result = _generic_load(
                        load_type, well_info, rows,
                        engine, dialect, source, dry_run=False,
                    )

            if result.get("errors"):
                for e in result["errors"]:
                    st.error(e)
            else:
                st.success(
                    f"✅ Loaded **{result.get('loaded', 0)}** records to PPDM "
                    f"for UWI `{well_info.get('uwi')}`."
                )


def _generic_load(load_type, well_info, rows, engine, dialect, source, dry_run=False):
    """Route to the correct PPDM loader based on report type."""
    if dry_run:
        return {"ok": True, "loaded": len(rows), "errors": []}

    try:
        from modules.pdf_db_loader import (
            load_formation_tops, load_well_test, load_rft,
            load_core, load_casing, load_scout,
        )
    except ImportError as _ie:
        return {"ok": False, "loaded": 0,
                "errors": [f"pdf_db_loader not found: {_ie}"]}

    kwargs = dict(engine=engine, dialect=dialect, well_info=well_info,
                  rows=rows, source=source)

    if load_type == RT_FORMATION:
        return load_formation_tops(**kwargs)
    elif load_type in (RT_DST, RT_WELL_TEST):
        return load_well_test(**kwargs,
                              test_type="DST" if load_type == RT_DST else "PRODUCTION")
    elif load_type == RT_RFT:
        return load_rft(**kwargs)
    elif load_type == RT_CORE:
        return load_core(**kwargs)
    elif load_type == RT_CASING:
        return load_casing(**kwargs)
    elif load_type == RT_SCOUT:
        return load_scout(**kwargs)
    else:
        return {"ok": False, "loaded": 0, "errors": [
            f"No PPDM loader implemented for {load_type} — use CSV export."
        ]}


# ─────────────────────────────────────────────────────────────────────────────
# Catalog widget — delegates to doc_catalog_store.render_catalog_widget
# ─────────────────────────────────────────────────────────────────────────────

def _render_catalog_widget(f: dict, report_type: str, well_info: dict,
                            records: list, page_count: int):
    if not _STORE_OK:
        return
    _meta = {**well_info, "page_count": page_count}
    _render_catalog_widget_fn(
        file_path=f["file_path"],
        doc_type=report_type,
        meta=_meta,
        records=records,
        widget_key=f"pdf_{f.get('file_id','')}",
        source="PDF_CATALOG",
    )


# ─────────────────────────────────────────────────────────────────────────────
# PDF parsers — best-effort text extraction
# ─────────────────────────────────────────────────────────────────────────────

def _parse_formation_tops(file_path: str) -> list[dict]:
    """Extract formation name / top depth rows from a PDF using pdfplumber."""
    import re
    rows = []
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                # Try structured table extraction first
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    headers = [str(c).strip().upper() for c in (table[0] or [])]
                    form_col = next((i for i, h in enumerate(headers)
                                     if any(k in h for k in
                                            ["FORM","ZONE","PICK","NAME"])), None)
                    depth_col = next((i for i, h in enumerate(headers)
                                      if any(k in h for k in
                                             ["TOP","DEPTH","MD","TVD"])), None)
                    if form_col is not None and depth_col is not None:
                        for row in table[1:]:
                            if not row:
                                continue
                            fname = str(row[form_col]).strip()
                            depth = str(row[depth_col]).strip()
                            if fname and depth and fname.upper() != "NONE":
                                try:
                                    rows.append({
                                        "FORMATION_NAME": fname,
                                        "DEPTH_TOP_MD":   float(re.sub(r"[^\d.]", "", depth)),
                                    })
                                except ValueError:
                                    pass

                # Fallback: regex on raw text
                if not rows:
                    text = page.extract_text() or ""
                    for line in text.splitlines():
                        m = re.match(
                            r"([A-Za-z][A-Za-z0-9 _\-]+?)\s+"
                            r"(\d{3,6}(?:\.\d+)?)\s*(?:ft|m)?", line.strip()
                        )
                        if m:
                            rows.append({
                                "FORMATION_NAME": m.group(1).strip(),
                                "DEPTH_TOP_MD":   float(m.group(2)),
                            })
    except Exception:
        pass
    # Deduplicate
    seen = set()
    deduped = []
    for r in rows:
        k = (r["FORMATION_NAME"].upper(), r["DEPTH_TOP_MD"])
        if k not in seen:
            seen.add(k)
            deduped.append(r)
    return deduped


def _parse_core_data(file_path: str) -> list[dict]:
    """Extract core plug analysis rows (depth, porosity, permeability, Sw)."""
    import re
    rows = []
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    headers = [str(c).strip().upper() for c in (table[0] or [])]

                    def _col(keywords):
                        return next((i for i, h in enumerate(headers)
                                     if any(k in h for k in keywords)), None)

                    depth_c = _col(["DEPTH","MD","TOP"])
                    por_c   = _col(["POR","PHI","PORO"])
                    perm_c  = _col(["PERM","KH","KA","KAIR","KGAS"])
                    sw_c    = _col(["SW","SAT","WATER"])

                    if depth_c is None:
                        continue

                    for row in table[1:]:
                        if not row:
                            continue
                        def _val(idx):
                            if idx is None or idx >= len(row):
                                return None
                            v = re.sub(r"[^\d.\-]", "", str(row[idx]))
                            try:
                                return float(v) if v else None
                            except ValueError:
                                return None

                        depth = _val(depth_c)
                        if depth is None:
                            continue
                        rows.append({
                            "DEPTH":        depth,
                            "POROSITY":     _val(por_c),
                            "PERMEABILITY": _val(perm_c),
                            "SW":           _val(sw_c),
                        })
    except Exception:
        pass
    return rows


def _parse_dst(file_path: str) -> dict:
    """Extract DST header and pressure/time readings."""
    import re
    header = {}
    rows   = []
    try:
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            full_text = "\n".join(
                (p.extract_text() or "") for p in pdf.pages
            )

        # Header fields
        patterns = {
            "WELL_NAME":    r"WELL[:\s]+([^\n]+)",
            "INTERVAL_TOP": r"(?:PERFORATIONS?|INTERVAL)[:\s]+(\d+)",
            "INTERVAL_BOT": r"(?:PERFORATIONS?|INTERVAL)[:\s]+\d+\s*[-–to]+\s*(\d+)",
            "ISIP":         r"ISIP[:\s]+([\d.]+)",
            "FSICP":        r"FSICP[:\s]+([\d.]+)",
            "MAX_PRESSURE": r"MAX(?:IMUM)?\s+(?:SHUT.IN\s+)?PRESSURE[:\s]+([\d.]+)",
        }
        for field, pat in patterns.items():
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                header[field] = m.group(1).strip()

        # Pressure/time table
        for page in pdfplumber.open(file_path).pages:
            for table in (page.extract_tables() or []):
                if not table:
                    continue
                hdrs = [str(c).strip().upper() for c in (table[0] or [])]
                time_c  = next((i for i, h in enumerate(hdrs)
                                if any(k in h for k in ["TIME","HR","MIN"])), None)
                press_c = next((i for i, h in enumerate(hdrs)
                                if any(k in h for k in
                                       ["PRESS","PSI","KPA","BHP"])), None)
                if time_c is None or press_c is None:
                    continue
                for row in table[1:]:
                    if not row:
                        continue
                    try:
                        t = str(row[time_c]).strip()
                        p = float(re.sub(r"[^\d.]", "",
                                         str(row[press_c]))) if row[press_c] else None
                        if p is not None:
                            rows.append({"TIME": t, "PRESSURE": p})
                    except Exception:
                        pass
    except Exception:
        pass
    return {"header": header, "rows": rows}

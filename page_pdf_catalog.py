"""
page_pdf_catalog.py
===================
PDF Catalog UI — scan, classify, extract and load directional surveys.
"""
import streamlit as st
from pathlib import Path

from modules.pdf_survey_catalog import (
    scan_directory, classify_pdf, extract_stations,
    validate_stations, load_to_ppdm, summarize_scan,
    RT_DIRECTIONAL, RT_MUDLOG, RT_FORMATION,
    RT_COMPLETION, RT_UNKNOWN,
)

REPORT_ICONS = {
    RT_DIRECTIONAL: "📐",
    RT_MUDLOG:      "📊",
    RT_FORMATION:   "🪨",
    RT_COMPLETION:  "🔧",
    RT_UNKNOWN:     "❓",
}
REPORT_LABELS = {
    RT_DIRECTIONAL: "Directional Survey",
    RT_MUDLOG:      "Mud Log",
    RT_FORMATION:   "Formation Tops",
    RT_COMPLETION:  "Completion Report",
    RT_UNKNOWN:     "Unknown",
}


def run(engine=None, dialect: str = "mssql"):
    import pandas as pd
    st.title("📄 PDF Survey Catalog")
    st.caption(
        "Scan, classify and extract directional survey data from PDF reports. "
        "Loads to PPDM dbo.WELL_DIR_SURVEY and dbo.WELL_DIR_SRVY_STATION."
    )

    tab_scan, tab_extract, tab_load = st.tabs([
        "🔍 Scan & Classify", "📐 Extract & Validate", "🚀 Load to PPDM"
    ])

    # ── SCAN ──────────────────────────────────────────────────────────────────
    with tab_scan:
        st.markdown("#### 🔍 Scan for PDF Reports")
        scan_path = st.text_input(
            "Folder to scan",
            placeholder=r"C:\WellData\Surveys",
            key="pdf_scan_path"
        )

        if st.button("🔍 Scan PDFs", type="primary", key="pdf_scan_btn"):
            if not scan_path or not Path(scan_path).exists():
                st.error("Folder not found.")
            else:
                with st.spinner("Scanning…"):
                    files = scan_directory(scan_path)

                prog = st.progress(0, text="Classifying…")
                classified = []
                for i, f in enumerate(files):
                    prog.progress((i+1)/max(len(files),1),
                                  text=f"Classifying {f['file_name']}…")
                    cl = classify_pdf(f["file_path"])
                    cl.update({k:v for k,v in f.items()
                                if k not in cl})
                    classified.append(cl)

                prog.empty()
                st.session_state["pdf_classified"] = classified
                st.rerun()

        if "pdf_classified" in st.session_state:
            files   = st.session_state["pdf_classified"]
            summary = summarize_scan(files)

            st.divider()
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total PDFs",     summary["total_files"])
            c2.metric("📐 Surveys",     summary["surveys"])
            c3.metric("Ready to load",  summary["ready_to_load"])
            c4.metric("❓ Unknown",     summary["unknown"])

            rows = []
            for f in files:
                rt   = f.get("report_type", RT_UNKNOWN)
                rows.append({
                    "Type":      f"{REPORT_ICONS.get(rt,'•')} {REPORT_LABELS.get(rt,rt)}",
                    "File":      f["file_name"],
                    "Well":      f.get("well_name","—"),
                    "UWI":       f.get("uwi","—"),
                    "Operator":  f.get("operator","—"),
                    "Stations":  f.get("station_count","?"),
                    "Pages":     f.get("page_count",0),
                    "Conf.":     f"{f.get('confidence',0)*100:.0f}%",
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True, use_container_width=True)

    # ── EXTRACT & VALIDATE ────────────────────────────────────────────────────
    with tab_extract:
        st.markdown("#### 📐 Extract & Validate Stations")

        if "pdf_classified" not in st.session_state:
            st.info("Run a scan first.")
        else:
            surveys = [f for f in st.session_state["pdf_classified"]
                       if f.get("report_type") == RT_DIRECTIONAL]

            if not surveys:
                st.warning("No directional surveys found in scan results.")
            else:
                labels = {
                    f"{f['file_name']}  —  {f.get('well_name','?')}  "
                    f"({f.get('station_count','?')} stations)": f
                    for f in surveys
                }
                sel = st.selectbox("Select survey PDF", list(labels.keys()),
                                   key="pdf_ext_sel")
                f   = labels[sel]

                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("**Well header (auto-extracted)**")
                    # Editable well info
                    uwi       = st.text_input("UWI",       value=f.get("uwi",""),      key="pdf_uwi")
                    well_name = st.text_input("Well Name", value=f.get("well_name",""),key="pdf_wn")
                    operator  = st.text_input("Operator",  value=f.get("operator",""), key="pdf_op")
                    field     = st.text_input("Field",     value=f.get("field",""),    key="pdf_fld")
                    state     = st.text_input("State",     value=f.get("state",""),    key="pdf_st")
                    stype     = st.selectbox("Survey type",
                                             ["MWD","Gyro","Magnetic","Accelerometer"],
                                             key="pdf_stype")

                with col_b:
                    st.markdown("**Extract stations**")
                    if st.button("📐 Extract Stations",
                                  type="primary", key="pdf_extract_btn"):
                        with st.spinner("Extracting…"):
                            ext = extract_stations(f["file_path"])
                        st.session_state["pdf_extract"] = ext
                        st.session_state["pdf_extract_file"] = f["file_path"]

                    if "pdf_extract" in st.session_state:
                        ext = st.session_state["pdf_extract"]
                        if ext.get("error"):
                            st.error(f"Extraction error: {ext['error']}")
                        else:
                            stations = ext.get("stations", [])
                            val = validate_stations(stations)

                            # Metrics
                            m1,m2 = st.columns(2)
                            m1.metric("Stations extracted", len(stations))
                            m2.metric("MD range", val.get("md_range","—"))

                            if val["errors"]:
                                for e in val["errors"]:
                                    st.error(e)
                            if val["warnings"]:
                                for w in val["warnings"]:
                                    st.warning(w)
                            if val["valid"] and not val["warnings"]:
                                st.success("✅ All stations valid")

                            # Columns detected
                            st.caption(
                                f"Columns detected: "
                                f"**{', '.join(ext.get('columns_found',[]))}**"
                            )

                            # Station table
                            if stations:
                                df = pd.DataFrame(stations)
                                st.dataframe(
                                    df.round(2),
                                    hide_index=True,
                                    use_container_width=True,
                                    height=300,
                                )

                                # Save updated well info back
                                st.session_state["pdf_well_info"] = {
                                    "uwi":         uwi,
                                    "well_name":   well_name,
                                    "operator":    operator,
                                    "field":       field,
                                    "state":       state,
                                    "survey_type": stype,
                                }
                                st.session_state["pdf_stations"] = stations
                                st.session_state["pdf_valid"]    = val["valid"]

    # ── LOAD TO PPDM ─────────────────────────────────────────────────────────
    with tab_load:
        st.markdown("#### 🚀 Load to PPDM")

        if engine is None:
            st.warning("⚠️ No database connection — connect via pipeline first.")
        elif "pdf_stations" not in st.session_state:
            st.info("Extract stations first in the Extract & Validate tab.")
        else:
            stations  = st.session_state["pdf_stations"]
            well_info = st.session_state.get("pdf_well_info", {})
            valid     = st.session_state.get("pdf_valid", False)

            st.markdown("**Ready to load:**")
            col_a, col_b = st.columns(2)
            col_a.write({
                "UWI":      well_info.get("uwi","—"),
                "Well":     well_info.get("well_name","—"),
                "Operator": well_info.get("operator","—"),
            })
            col_b.write({
                "Stations":  len(stations),
                "Survey":    well_info.get("survey_type","MWD"),
                "Valid":     "✅ Yes" if valid else "⚠️ Has errors",
            })

            if not valid:
                st.warning(
                    "⚠️ Validation errors found — review in Extract tab. "
                    "You can still load but data may be incorrect."
                )

            source  = st.text_input("Source tag", value="PDF_SURVEY",
                                     key="pdf_src_tag")
            dry_run = st.checkbox("Dry run (preview — no DB writes)",
                                   value=True, key="pdf_dry_run")

            if st.button("🚀 Load Survey to PPDM",
                          type="primary", key="pdf_load_btn"):
                with st.spinner("Loading…"):
                    result = load_to_ppdm(
                        well_info = well_info,
                        stations  = stations,
                        engine    = engine,
                        dialect   = dialect,
                        source    = source,
                        dry_run   = dry_run,
                    )

                if result.get("errors"):
                    for e in result["errors"]:
                        st.error(e)
                elif dry_run:
                    st.info(
                        f"🔍 Dry run — would load **{result['loaded']}** stations "
                        f"for UWI `{well_info.get('uwi')}`. "
                        f"Uncheck Dry run to write to PPDM."
                    )
                else:
                    st.success(
                        f"✅ Survey loaded — **{result['loaded']}** stations "
                        f"written to PPDM. Survey ID: `{result['survey_id']}`"
                    )

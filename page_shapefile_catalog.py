"""
page_shapefile_catalog.py
=========================
Shapefile Catalog UI — scan, classify, map columns, load to PPDM.
Wired into app.py as a nav card in File Inventory.
"""
import streamlit as st
import pandas as pd
import json
from pathlib import Path

from modules.shapefile_catalog import (
    scan_directory, classify_shapefile, load_to_ppdm,
    detect_duplicates, summarize_scan,
    FT_WELL, FT_FIELD, FT_LEASE, FT_SEISMIC_2D, FT_SEISMIC_3D,
    FT_PIPELINE, FT_FACILITY, FT_BOUNDARY, FT_OTHER, FT_REVIEW,
    PPDM_TARGETS, COLUMN_PATTERNS,
)

FEATURE_ICONS = {
    FT_WELL:       "🛢️",
    FT_FIELD:      "🟩",
    FT_LEASE:      "📋",
    FT_SEISMIC_2D: "〰️",
    FT_SEISMIC_3D: "🟦",
    FT_PIPELINE:   "⛽",
    FT_FACILITY:   "🏭",
    FT_BOUNDARY:   "🗺️",
    FT_OTHER:      "❓",
    FT_REVIEW:     "⚠️",
}

FEATURE_LABELS = {
    FT_WELL:       "Wells",
    FT_FIELD:      "Fields",
    FT_LEASE:      "Leases / Tracts",
    FT_SEISMIC_2D: "Seismic 2D Lines",
    FT_SEISMIC_3D: "Seismic 3D Surveys",
    FT_PIPELINE:   "Pipelines",
    FT_FACILITY:   "Facilities",
    FT_BOUNDARY:   "Boundaries",
    FT_OTHER:      "Other",
    FT_REVIEW:     "Needs Review",
}


def run(engine=None, dialect: str = "mssql"):
    """Main entry point for Shapefile Catalog page."""
    st.title("🗺️ Shapefile Catalog")
    st.caption(
        "Scan, classify and load ESRI Shapefiles, GeoJSON and GeoPackage "
        "files into PPDM 3.9. Supports Wells, Fields, Leases, Seismic and more."
    )

    tab_scan, tab_classify, tab_load, tab_dupes = st.tabs([
        "🔍 Scan", "📋 Classify & Map", "🚀 Load to PPDM", "🔄 Duplicates"
    ])

    # ── SCAN ──────────────────────────────────────────────────────────────────
    with tab_scan:
        st.markdown("#### 🔍 Scan for Spatial Files")
        st.caption(
            "Point to a root folder — Data Wrangler will recursively find "
            "all .shp, .geojson, .gpkg and .kml files and classify them."
        )

        scan_path = st.text_input(
            "Root folder to scan",
            value=st.session_state.get("shp_scan_path", ""),
            placeholder=r"C:\GIS\ProjectData",
            key="shp_scan_path_input"
        )

        c1, c2 = st.columns(2)
        if c1.button("🔍 Scan for Shapefiles", type="primary",
                      key="shp_scan_btn"):
            if not scan_path or not Path(scan_path).exists():
                st.error("Folder not found — check the path.")
            else:
                st.session_state["shp_scan_path"] = scan_path
                prog = st.progress(0, text="Scanning…")
                count_box = st.empty()

                with st.spinner("Scanning…"):
                    files = scan_directory(scan_path)

                prog.progress(0.5, text="Classifying…")
                classified = []
                for i, f in enumerate(files):
                    prog.progress(
                        0.5 + 0.5*(i+1)/max(len(files),1),
                        text=f"Classifying {f['file_name']}…"
                    )
                    cl = classify_shapefile(f["file_path"])
                    cl.update(f)
                    classified.append(cl)

                prog.empty()
                st.session_state["shp_classified"] = classified
                st.rerun()

        if c2.button("🗑️ Clear Results", key="shp_clear"):
            st.session_state.pop("shp_classified", None)
            st.rerun()

        # Results
        if "shp_classified" in st.session_state:
            files = st.session_state["shp_classified"]
            summary = summarize_scan(files)

            st.divider()
            st.markdown(f"**{summary['total_files']:,} files found · "
                        f"{summary['total_features']:,} total features**")

            # Summary cards
            cols = st.columns(5)
            type_counts = summary["by_type"]
            for i, (ft, cnt) in enumerate(type_counts.items()):
                with cols[i % 5]:
                    st.metric(
                        f"{FEATURE_ICONS.get(ft,'•')} {FEATURE_LABELS.get(ft,ft)}",
                        cnt
                    )

            st.divider()

            # File table
            rows = []
            for f in files:
                rows.append({
                    "Type":     f"{FEATURE_ICONS.get(f['feature_type'],'•')} "
                                f"{FEATURE_LABELS.get(f['feature_type'],f['feature_type'])}",
                    "File":     f["file_name"],
                    "Features": f.get("feature_count", "?"),
                    "Geometry": f.get("geometry_type","?"),
                    "CRS":      f.get("crs_epsg","?"),
                    "PPDM":     f.get("ppdm_target","—"),
                    "Conf.":    f"{f.get('confidence',0)*100:.0f}%",
                    "Size KB":  f.get("file_size_kb","?"),
                    "Folder":   f.get("parent_folder",""),
                })
            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True, use_container_width=True,
                column_config={
                    "Type":     st.column_config.TextColumn(width="medium"),
                    "File":     st.column_config.TextColumn(width="medium"),
                    "Features": st.column_config.NumberColumn(width="small"),
                    "Conf.":    st.column_config.TextColumn(width="small"),
                })

            # Export scan results
            st.download_button(
                "⬇ Export scan CSV",
                data=df.to_csv(index=False),
                file_name="shapefile_scan.csv",
                mime="text/csv",
                key="shp_export_scan"
            )

    # ── CLASSIFY & MAP ────────────────────────────────────────────────────────
    with tab_classify:
        st.markdown("#### 📋 Classify & Map Columns")

        if "shp_classified" not in st.session_state:
            st.info("Run a scan first.")
        else:
            files = st.session_state["shp_classified"]

            # Filter options
            c1, c2 = st.columns(2)
            type_filter = c1.selectbox(
                "Filter by type",
                ["All"] + list(FEATURE_LABELS.values()),
                key="shp_type_filter"
            )
            conf_filter = c2.selectbox(
                "Filter by confidence",
                ["All", "High (>80%)", "Medium (50-80%)", "Low (<50%)"],
                key="shp_conf_filter"
            )

            # Apply filters
            filtered = files
            if type_filter != "All":
                rev_map = {v: k for k,v in FEATURE_LABELS.items()}
                ft_key  = rev_map.get(type_filter)
                filtered = [f for f in filtered
                            if f.get("feature_type") == ft_key]
            if conf_filter == "High (>80%)":
                filtered = [f for f in filtered
                            if f.get("confidence",0) >= 0.8]
            elif conf_filter == "Medium (50-80%)":
                filtered = [f for f in filtered
                            if 0.5 <= f.get("confidence",0) < 0.8]
            elif conf_filter == "Low (<50%)":
                filtered = [f for f in filtered
                            if f.get("confidence",0) < 0.5]

            st.caption(f"Showing {len(filtered)} of {len(files)} files")

            for f in filtered:
                ft    = f.get("feature_type", FT_REVIEW)
                icon  = FEATURE_ICONS.get(ft,"•")
                label = FEATURE_LABELS.get(ft, ft)
                conf  = f.get("confidence",0)
                conf_badge = ("🟢" if conf >= 0.8
                              else "🟡" if conf >= 0.5
                              else "🔴")

                with st.expander(
                    f"{icon} {f['file_name']}  "
                    f"·  {label}  "
                    f"·  {f.get('feature_count','?')} features  "
                    f"·  {conf_badge} {conf*100:.0f}%",
                    expanded=False
                ):
                    col_a, col_b = st.columns(2)

                    with col_a:
                        st.markdown("**File info**")
                        st.caption(f"`{f['file_path']}`")
                        st.write({
                            "Geometry":  f.get("geometry_type","?"),
                            "CRS":       f.get("crs","?"),
                            "EPSG":      f.get("crs_epsg","?"),
                            "Features":  f.get("feature_count","?"),
                        })

                        # Override feature type
                        new_type = st.selectbox(
                            "Feature type",
                            list(FEATURE_LABELS.keys()),
                            index=list(FEATURE_LABELS.keys()).index(ft),
                            format_func=lambda x: f"{FEATURE_ICONS.get(x,'')} {FEATURE_LABELS.get(x,x)}",
                            key=f"shp_ft_{f['file_id']}"
                        )
                        if new_type != ft:
                            f["feature_type"]  = new_type
                            f["ppdm_target"]   = PPDM_TARGETS[new_type]
                            st.session_state["shp_classified"] = files

                    with col_b:
                        st.markdown("**Column mapping**")
                        attrs  = f.get("attributes", [])
                        colmap = f.get("column_map", {})

                        if attrs:
                            st.caption("Auto-detected mappings — override if needed:")
                            for ppdm_col in list(COLUMN_PATTERNS.keys()):
                                current = colmap.get(ppdm_col, "—")
                                options = ["—"] + attrs
                                sel = st.selectbox(
                                    ppdm_col,
                                    options,
                                    index=options.index(current)
                                          if current in options else 0,
                                    key=f"shp_map_{f['file_id']}_{ppdm_col}"
                                )
                                if sel != "—":
                                    f["column_map"][ppdm_col] = sel
                                elif ppdm_col in f["column_map"]:
                                    del f["column_map"][ppdm_col]
                        else:
                            st.info("No attributes found.")

                    st.markdown("**Available attributes:**")
                    st.code(", ".join(attrs) if attrs else "none")

                    if f.get("bounds"):
                        b = f["bounds"]
                        st.caption(
                            f"Extent: {b['minx']:.3f}°W–{b['maxx']:.3f}°E  "
                            f"{b['miny']:.3f}°S–{b['maxy']:.3f}°N"
                        )

    # ── LOAD TO PPDM ─────────────────────────────────────────────────────────
    with tab_load:
        st.markdown("#### 🚀 Load to PPDM")

        if engine is None:
            st.warning("⚠️ No database connection — connect via the pipeline first.")
        elif "shp_classified" not in st.session_state:
            st.info("Run a scan first.")
        else:
            files = st.session_state["shp_classified"]
            loadable = [f for f in files
                        if f.get("ppdm_target")
                        and f.get("feature_type") != FT_REVIEW]

            st.caption(
                f"**{len(loadable)}** files ready to load · "
                f"**{len(files)-len(loadable)}** need review"
            )

            # Source tag
            source = st.text_input(
                "Source tag",
                value="SHAPEFILE",
                help="Written to ROW_CREATED_BY in PPDM",
                key="shp_source_tag"
            )

            c1, c2 = st.columns(2)
            dry_run = c1.checkbox("Dry run (preview only — no DB writes)",
                                   value=True, key="shp_dry_run")
            load_all = c2.checkbox("Load all files", value=False,
                                    key="shp_load_all")

            # File selector
            if not load_all:
                file_labels = {
                    f"{f['file_name']} ({FEATURE_LABELS.get(f['feature_type'],'')} · "
                    f"{f.get('feature_count','?')} features)": f
                    for f in loadable
                }
                sel_label = st.selectbox(
                    "Select file to load",
                    list(file_labels.keys()),
                    key="shp_load_sel"
                )
                to_load = [file_labels[sel_label]] if sel_label else []
            else:
                to_load = loadable

            if st.button(
                f"{'🔍 Preview' if dry_run else '🚀 Load'} "
                f"{len(to_load)} file(s)",
                type="primary", key="shp_load_btn",
                disabled=len(to_load) == 0
            ):
                results = []
                prog = st.progress(0)
                for i, f in enumerate(to_load):
                    prog.progress((i+1)/len(to_load),
                                  text=f"Loading {f['file_name']}…")
                    try:
                        r = load_to_ppdm(
                            file_path=f["file_path"],
                            feature_type=f["feature_type"],
                            col_map=f.get("column_map", {}),
                            engine=engine,
                            dialect=dialect,
                            source=source,
                            dry_run=dry_run,
                        )
                        results.append({
                            "File":     f["file_name"],
                            "Type":     FEATURE_LABELS.get(f["feature_type"],""),
                            "PPDM":     f.get("ppdm_target",""),
                            "Loaded":   r.get("loaded", 0),
                            "Skipped":  r.get("skipped", 0),
                            "Errors":   len(r.get("errors", [])),
                            "Status":   "✅ OK" if not r.get("errors") else "⚠️ Errors",
                        })
                        if r.get("errors"):
                            for err in r["errors"][:3]:
                                st.warning(f"  {f['file_name']}: {err}")
                    except Exception as e:
                        results.append({
                            "File": f["file_name"], "Type":"", "PPDM":"",
                            "Loaded":0, "Skipped":0, "Errors":1,
                            "Status": f"❌ {e}"
                        })

                prog.empty()
                df = pd.DataFrame(results)
                st.dataframe(df, hide_index=True, use_container_width=True)

                total_loaded  = df["Loaded"].sum()
                total_skipped = df["Skipped"].sum()
                total_errors  = df["Errors"].sum()

                if dry_run:
                    st.info(
                        f"🔍 Dry run — would load **{total_loaded:,}** features, "
                        f"skip **{total_skipped:,}** (already exist or no key). "
                        f"Uncheck Dry run to write to PPDM."
                    )
                else:
                    st.success(
                        f"✅ **{total_loaded:,}** features loaded · "
                        f"**{total_skipped:,}** skipped · "
                        f"**{total_errors}** errors"
                    )

    # ── DUPLICATES ────────────────────────────────────────────────────────────
    with tab_dupes:
        st.markdown("#### 🔄 Duplicate Detection")
        st.caption(
            "Files of the same feature type with overlapping spatial extents "
            "may contain duplicate data. Review before loading."
        )

        if "shp_classified" not in st.session_state:
            st.info("Run a scan first.")
        else:
            files = st.session_state["shp_classified"]

            if st.button("🔍 Detect Duplicates", type="primary",
                          key="shp_dupe_btn"):
                with st.spinner("Checking spatial overlaps…"):
                    dupes = detect_duplicates(files)
                st.session_state["shp_dupes"] = dupes

            if "shp_dupes" in st.session_state:
                dupes = st.session_state["shp_dupes"]
                if not dupes:
                    st.success("✅ No overlapping files detected.")
                else:
                    st.warning(
                        f"⚠️ **{len(dupes)}** potential duplicate pair(s) found:"
                    )
                    rows = [{
                        "File 1":    Path(d["file_1"]).name,
                        "File 2":    Path(d["file_2"]).name,
                        "Type":      FEATURE_LABELS.get(d["type"], d["type"]),
                        "Overlap X": f"{d['overlap_x']:.3f}°",
                        "Overlap Y": f"{d['overlap_y']:.3f}°",
                    } for d in dupes]
                    st.dataframe(pd.DataFrame(rows),
                                 hide_index=True,
                                 use_container_width=True)
                    st.caption(
                        "Review each pair — keep the most authoritative source "
                        "and skip the other during loading."
                    )

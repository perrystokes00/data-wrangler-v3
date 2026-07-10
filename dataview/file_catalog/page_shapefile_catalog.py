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

try:
    from dataview.file_catalog.doc_catalog_store import render_catalog_widget as _doc_catalog_widget
    _DOC_STORE_OK = True
except ImportError:
    _DOC_STORE_OK = False

try:
    from modules.shapefile_mapping_cache import (
        save_shp_mapping, restore_shp_mapping, shp_fingerprint
    )
    _SHP_CACHE_OK = True
except ImportError:
    _SHP_CACHE_OK = False

from dataview.mapping.shapefile_catalog import (
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
                    # ── Map preview FIRST (Folium) ────────────────────────────
                    try:
                        import geopandas as gpd
                        import folium
                        from streamlit_folium import st_folium
                        import json as _json

                        _gdf = gpd.read_file(f["file_path"])
                        try:
                            _gdf = _gdf.to_crs("EPSG:4326")
                        except Exception:
                            pass

                        _geom_type = f.get("geometry_type", "")
                        _colmap    = f.get("column_map", {})
                        _non_geom  = [c for c in _gdf.columns if c != "geometry"]
                        _hover_col = (_colmap.get("WELL_NAME") or _colmap.get("UWI") or
                                      (_non_geom[0] if _non_geom else None))

                        # Map centre from bounds
                        _bounds = _gdf.total_bounds  # (minx, miny, maxx, maxy)
                        _cx = (_bounds[0] + _bounds[2]) / 2
                        _cy = (_bounds[1] + _bounds[3]) / 2

                        _m = folium.Map(
                            location=[_cy, _cx],
                            zoom_start=6,
                            tiles="OpenStreetMap",
                        )
                        try:
                            _m.fit_bounds([[_bounds[1], _bounds[0]],
                                           [_bounds[3], _bounds[2]]])
                        except Exception:
                            pass

                        # Tooltip fields
                        _tt_fields = [_hover_col] if _hover_col and _hover_col in _gdf.columns else _non_geom[:3]
                        _tooltip = folium.GeoJsonTooltip(
                            fields=_tt_fields, aliases=_tt_fields, localize=True
                        ) if _tt_fields else None

                        _has_points = any(g in ("Point", "MultiPoint")
                                          for g in _gdf.geometry.geom_type.unique())
                        _has_lines  = any(g in ("LineString", "MultiLineString")
                                          for g in _gdf.geometry.geom_type.unique())
                        _has_polys  = any(g in ("Polygon", "MultiPolygon")
                                          for g in _gdf.geometry.geom_type.unique())

                        # Also handle lat/lon columns for point layers with no geometry
                        _lat_col = _colmap.get("LATITUDE")
                        _lon_col = _colmap.get("LONGITUDE")
                        if (not _has_points and _lat_col and _lon_col
                                and _lat_col in _gdf.columns and _lon_col in _gdf.columns):
                            _gdf["_lat"] = pd.to_numeric(_gdf[_lat_col], errors="coerce")
                            _gdf["_lon"] = pd.to_numeric(_gdf[_lon_col], errors="coerce")
                            _pts = _gdf.dropna(subset=["_lat", "_lon"])
                            for _, _r in _pts.iterrows():
                                _tip = str(_r[_hover_col]) if _hover_col and _hover_col in _pts.columns else ""
                                folium.CircleMarker(
                                    location=[_r["_lat"], _r["_lon"]],
                                    radius=5, color="#1A2B4A",
                                    fill=True, fill_color="#1A2B4A", fill_opacity=0.8,
                                    tooltip=_tip,
                                ).add_to(_m)

                        if _has_points:
                            _pts_gdf = _gdf[_gdf.geometry.geom_type.isin(
                                ["Point", "MultiPoint"])]
                            folium.GeoJson(
                                _json.loads(_pts_gdf.to_json()),
                                tooltip=_tooltip,
                                marker=folium.CircleMarker(
                                    radius=5, fill=True,
                                    fill_color="#1A2B4A", fill_opacity=0.8,
                                    color="#1A2B4A", weight=1,
                                ),
                                name="Points",
                            ).add_to(_m)

                        if _has_lines:
                            _lines_gdf = _gdf[_gdf.geometry.geom_type.isin(
                                ["LineString", "MultiLineString"])]
                            folium.GeoJson(
                                _json.loads(_lines_gdf.to_json()),
                                style_function=lambda _: {
                                    "color": "#534AB7", "weight": 2, "opacity": 0.8
                                },
                                tooltip=_tooltip,
                                name="Lines",
                            ).add_to(_m)

                        if _has_polys:
                            _polys_gdf = _gdf[_gdf.geometry.geom_type.isin(
                                ["Polygon", "MultiPolygon"])]
                            folium.GeoJson(
                                _json.loads(_polys_gdf.to_json()),
                                style_function=lambda _: {
                                    "fillColor": "#1D9E75",
                                    "color": "#0e6b4a",
                                    "weight": 1.5,
                                    "fillOpacity": 0.4,
                                },
                                tooltip=_tooltip,
                                name="Polygons",
                            ).add_to(_m)

                        folium.LayerControl().add_to(_m)
                        st_folium(_m, use_container_width=True, height=320,
                                  returned_objects=[])

                    except Exception as _me:
                        st.caption(f"Map preview unavailable: {_me}")

                    # ── Header attributes (always shown) ─────────────────────
                    _shp_attrs = [
                        ("Geometry Type",  f.get("geometry_type", "—")),
                        ("CRS",            f.get("crs", "—")),
                        ("EPSG",           str(f.get("crs_epsg", "—"))),
                        ("Feature Count",  str(f.get("feature_count", "—"))),
                        ("PPDM Target",    f.get("ppdm_target") or "—"),
                        ("Confidence",     f"{int(f.get('confidence',0)*100)}%"),
                        ("Attributes",     ", ".join(f.get("attributes", [])[:8])
                                           or "—"),
                    ]
                    if f.get("bounds"):
                        b = f["bounds"]
                        _shp_attrs.append((
                            "Extent",
                            f"{b['minx']:.3f}°–{b['maxx']:.3f}° lon, "
                            f"{b['miny']:.3f}°–{b['maxy']:.3f}° lat"
                        ))
                    _shp_hdf = pd.DataFrame(
                        [{"Attribute": k, "Value": v} for k, v in _shp_attrs]
                    )
                    with st.expander("📋 File attributes", expanded=True):
                        st.caption(f"`{f['file_path']}`")
                        st.dataframe(_shp_hdf, hide_index=True,
                                     use_container_width=True)

                    # ── File info + column mapping ────────────────────────────
                    col_a, col_b = st.columns(2)

                    with col_a:
                        st.markdown("**File info**")
                        st.caption(f"`{f['file_path']}`")
                        _info_df = pd.DataFrame([
                            {"Field": "Geometry", "Value": str(f.get("geometry_type", "?"))},
                            {"Field": "CRS",      "Value": str(f.get("crs", "?"))},
                            {"Field": "EPSG",     "Value": str(f.get("crs_epsg", "?"))},
                            {"Field": "Features", "Value": str(f.get("feature_count", "?"))},
                        ])
                        st.dataframe(_info_df, hide_index=True,
                                     use_container_width=True, height=178)

                        if f.get("bounds"):
                            b = f["bounds"]
                            st.caption(
                                f"Extent: {b['minx']:.3f}°W–{b['maxx']:.3f}°E  "
                                f"{b['miny']:.3f}°S–{b['maxy']:.3f}°N"
                            )

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
                            # ── Fingerprint restore ───────────────────────────
                            _fp_key = f"shp_fp_restored_{f['file_id']}"
                            if _SHP_CACHE_OK and _fp_key not in st.session_state:
                                _restored = restore_shp_mapping(f["file_name"], attrs)
                                if _restored:
                                    f["column_map"].update(_restored)
                                    st.session_state["shp_classified"] = files
                                    st.toast(
                                        f"↩ Mapping restored ({len(_restored)} column(s))",
                                        icon="✅"
                                    )
                                st.session_state[_fp_key] = True

                            st.caption("Auto-detected — override if needed:")
                            _src_options = ["— skip —"] + attrs
                            _grid_rows = []
                            for _ppdm_col in list(COLUMN_PATTERNS.keys()):
                                _cur = colmap.get(_ppdm_col, "— skip —")
                                if _cur not in _src_options:
                                    _cur = "— skip —"
                                _grid_rows.append({
                                    "PPDM Column": _ppdm_col,
                                    "Source Column": _cur,
                                })
                            _grid_df = pd.DataFrame(_grid_rows)
                            _edited = st.data_editor(
                                _grid_df,
                                column_config={
                                    "PPDM Column": st.column_config.TextColumn(
                                        disabled=True, width="medium"
                                    ),
                                    "Source Column": st.column_config.SelectboxColumn(
                                        options=_src_options,
                                        required=True,
                                        width="medium",
                                    ),
                                },
                                use_container_width=True,
                                hide_index=True,
                                height=min(38 + len(_grid_rows) * 35, 380),
                                key=f"shp_map_grid_{f['file_id']}",
                            )
                            # Write edits back to column_map and save fingerprint
                            _changed = False
                            for _, _r in _edited.iterrows():
                                _pc = _r["PPDM Column"]
                                _sc = _r["Source Column"]
                                if _sc and _sc != "— skip —":
                                    if f["column_map"].get(_pc) != _sc:
                                        _changed = True
                                    f["column_map"][_pc] = _sc
                                elif _pc in f["column_map"]:
                                    del f["column_map"][_pc]
                                    _changed = True
                            if _changed:
                                st.session_state["shp_classified"] = files
                                if _SHP_CACHE_OK:
                                    save_shp_mapping(
                                        f["file_name"], attrs, f["column_map"]
                                    )
                        else:
                            st.info("No attributes found.")

                    # ── File Inventory ────────────────────────────────────────
                    if _DOC_STORE_OK:
                        _ft = f.get("feature_type", "")
                        _doc_type = f"SHP_{_ft}" if _ft else "UNKNOWN"
                        _shp_meta = {
                            "well_name":     f.get("well_name"),
                            "uwi":           f.get("uwi"),
                            "operator":      f.get("operator"),
                            "feature_count": f.get("feature_count"),
                            "geometry_type": f.get("geometry_type"),
                        }
                        _doc_catalog_widget(
                            file_path=f["file_path"],
                            doc_type=_doc_type,
                            meta=_shp_meta,
                            records=[],
                            widget_key=f"shp_{f['file_id']}",
                            source="SHP_CATALOG",
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

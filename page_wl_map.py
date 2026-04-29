"""
page_wl_map.py

Well Log File → UWI Mapping Page

Staging workflow for bulk DLIS / LIS (and LAS) cataloguing:
  1. Scan — scan a directory, auto fuzzy-match filenames/headers to UWIs
  2. Manifest — upload a CSV/Excel manifest (filename → UWI)
  3. Review — editable grid to confirm/override/skip matches
  4. Catalog — catalog confirmed rows, then clear staging
"""

import pandas as pd
import streamlit as st

try:
    from modules.wl_file_map import (
        scan_directory,
        import_manifest,
        save_map,
        load_map,
        update_uwi,
        confirm_rows,
        catalog_confirmed,
        clear_catalogued,
        skip_rows,
        ensure_map_table,
        preview_rename,
        rename_files,
    )
    from modules.las_catalog import list_repositories
    from modules.las_loader import fetch_ppdm_uwis
    _AVAILABLE = True
except ImportError as _err:
    _AVAILABLE = False
    _IMPORT_ERROR = str(_err)


def run():
    st.title("🗺 Well Log File Mapping")
    st.caption(
        "Stage DLIS, LIS, and LAS files → assign UWIs → bulk catalog.  "
        "Files are never modified."
    )

    if not _AVAILABLE:
        st.error(f"Dependencies missing:\n\n`{_IMPORT_ERROR}`")
        return

    engine = _get_engine()
    if engine is None:
        st.warning("No database connection. Connect via the main pipeline first.")
        return

    # Ensure staging table exists
    try:
        created = ensure_map_table(engine)
        if created:
            st.success("Created WL_FILE_UWI_MAP staging table.")
    except Exception as e:
        st.error(f"Could not create staging table: {e}")
        return

    tab_scan, tab_manifest, tab_review = st.tabs([
        "🔍 Scan", "📋 Manifest", "✅ Review & Catalog"
    ])

    with tab_scan:
        _render_scan(engine)

    with tab_manifest:
        _render_manifest(engine)

    with tab_review:
        _render_review(engine)


# ─────────────────────────────────────────────────────────────────────────────
# SCAN TAB
# ─────────────────────────────────────────────────────────────────────────────

def _render_scan(engine):
    st.subheader("Scan directory")
    st.markdown(
        "Scans a folder for well log files, extracts header well IDs, "
        "and fuzzy-matches against PPDM wells. Review matches in the "
        "**Review & Catalog** tab."
    )

    try:
        repos = list_repositories(engine)
    except Exception as e:
        st.error(str(e))
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        folder = st.text_input(
            "Directory path", key="map_scan_folder",
            placeholder=r"e.g. C:\Data\DLIS_Delivery",
        )
    with col2:
        fmt = st.selectbox("Format", ["DLIS", "LIS", "LAS"], key="map_scan_fmt")

    # Repository selector
    if not repos.empty:
        repo_options = {
            f"{r['REPOSITORY_NAME']} ({r['BASE_PATH']})": r["REPOSITORY_ID"]
            for _, r in repos.iterrows()
        }
        repo_options = {"(none — assign later)": ""} | repo_options
        selected_repo = st.selectbox(
            "Repository", options=list(repo_options.keys()),
            key="map_scan_repo"
        )
        repository_id = repo_options[selected_repo]
    else:
        st.warning("No repositories registered. Register one in the Well Log Catalog.")
        repository_id = ""

    if not folder:
        return

    # Preview file count
    try:
        from pathlib import Path
        ext_map = {
            "DLIS": ["*.dlis", "*.DLIS"],
            "LIS":  ["*.lis",  "*.LIS"],
            "LAS":  ["*.las",  "*.LAS"],
        }
        files = []
        for pat in ext_map.get(fmt, []):
            files.extend(Path(folder).glob(pat))
        st.info(f"{len(files)} {fmt} file(s) found in directory.")
    except Exception:
        files = []

    max_workers = st.select_slider(
        "Parallel threads", options=[1, 2, 4, 6, 8], value=4,
        key="map_scan_workers",
        help="More threads = faster scanning but higher memory use. "
             "4 is a good default for most machines."
    )

    if st.button(
        f"🔍 Scan {len(files)} file(s)",
        type="primary", key="map_scan_btn",
        disabled=len(files) == 0,
    ):
        with st.spinner("Loading PPDM wells…"):
            try:
                ppdm_uwis = fetch_ppdm_uwis(engine)
            except Exception as e:
                st.error(str(e))
                return

        progress = st.progress(0, text="Starting scan…")
        status   = st.empty()

        def _scan_progress(completed, total, filename):
            progress.progress(
                min(completed / total, 1.0),
                text=f"Scanning {filename} ({completed}/{total})…"
            )
            status.caption(filename)

        try:
            scan_df = scan_directory(
                folder, fmt, ppdm_uwis,
                repository_id=repository_id,
                max_workers=max_workers,
                progress_callback=_scan_progress,
            )
            progress.progress(1.0, text="Done.")
            status.empty()
        except Exception as e:
            st.error(str(e))
            return

        if scan_df.empty:
            st.info("No files found.")
            return

        # Save to staging
        try:
            saved = save_map(engine, scan_df)
            st.session_state["map_scan_preview"] = scan_df
        except Exception as e:
            st.error(str(e))
            return

        matched   = scan_df["UWI"].notna().sum()
        unmatched = scan_df["UWI"].isna().sum()
        st.success(
            f"✅ {saved} file(s) added to staging  |  "
            f"{matched} matched  |  {unmatched} need manual UWI"
        )

    # Preview with inline override
    if "map_scan_preview" in st.session_state:
        preview = st.session_state["map_scan_preview"]

        matched   = preview["UWI"].notna().sum()
        unmatched = preview["UWI"].isna().sum()

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total files",  len(preview))
        c2.metric("Matched",      matched,   delta=None)
        c3.metric("Unmatched",    unmatched, delta=None,
                  delta_color="inverse" if unmatched > 0 else "off")

        # Split matched / unmatched for clarity
        tab_matched, tab_unmatched = st.tabs([
            f"✅ Matched ({matched})", f"❓ Unmatched ({unmatched})"
        ])

        with tab_matched:
            if matched == 0:
                st.info("No matched files yet.")
            else:
                matched_df = preview[preview["UWI"].notna()].copy()
                display_cols = [
                    "FILE_NAME", "UWI", "MATCH_WELL_NAME",
                    "MATCH_METHOD", "MATCH_SCORE", "HEADER_WELL_ID"
                ]
                st.dataframe(
                    matched_df[[c for c in display_cols if c in matched_df.columns]], hide_index=True,
                )

        with tab_unmatched:
            if unmatched == 0:
                st.success("All files matched!")
            else:
                unmatched_df = preview[preview["UWI"].isna()].copy()
                st.markdown(
                    "These files could not be matched automatically. "
                    "Assign a UWI below and click **Apply overrides** to update the staging table."
                )

                # Load PPDM UWIs for override dropdown
                try:
                    ppdm_uwis = fetch_ppdm_uwis(engine)
                    uwi_options = [""] + [r["UWI"] for r in ppdm_uwis]
                    uwi_label   = {r["UWI"]: f"{r['UWI']} — {r['WELL_NAME']}"
                                   for r in ppdm_uwis}
                except Exception:
                    uwi_options = [""]
                    uwi_label   = {}

                overrides = {}
                for _, row in unmatched_df.iterrows():
                    col_fn, col_hi, col_sel = st.columns([3, 2, 3])
                    with col_fn:
                        st.text(row["FILE_NAME"])
                    with col_hi:
                        st.caption(f"Header: {row.get('HEADER_WELL_ID') or '—'}")
                    with col_sel:
                        chosen = st.selectbox(
                            "UWI",
                            options=uwi_options,
                            format_func=lambda u: uwi_label.get(u, u) if u else "— select —",
                            key=f"map_ovr_{row['MAP_ID']}",
                            label_visibility="collapsed",
                        )
                        if chosen:
                            overrides[row["MAP_ID"]] = {
                                "uwi":       chosen,
                                "well_name": ppdm_uwis[[r["UWI"] for r in ppdm_uwis].index(chosen)]["WELL_NAME"]
                                             if chosen in [r["UWI"] for r in ppdm_uwis] else "",
                            }

                if overrides and st.button(
                    f"✔ Apply {len(overrides)} override(s)",
                    type="primary", key="map_apply_overrides_btn"
                ):
                    try:
                        for mid, vals in overrides.items():
                            update_uwi(engine, mid, vals["uwi"], vals["well_name"])
                        st.success(f"✅ {len(overrides)} UWI(s) assigned.")
                        # Refresh preview from DB
                        updated = load_map(engine)
                        st.session_state["map_scan_preview"] = updated[
                            updated["FILE_NAME"].isin(preview["FILE_NAME"])
                        ].reset_index(drop=True)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# MANIFEST TAB
# ─────────────────────────────────────────────────────────────────────────────

def _render_manifest(engine):
    st.subheader("Import manifest")
    st.markdown(
        "Upload a CSV or Excel file that maps filenames to UWIs. "
        "Manifest rows are marked CONFIRMED immediately — no fuzzy matching needed."
    )

    try:
        repos = list_repositories(engine)
    except Exception as e:
        st.error(str(e))
        return

    uploaded = st.file_uploader(
        "Manifest file", type=["csv", "xlsx", "xls"],
        key="map_manifest_upload"
    )

    if uploaded is None:
        st.info("Upload a CSV or Excel file with at least a filename column and a UWI column.")
        return

    # Preview the file to let user pick columns
    try:
        import tempfile, os
        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name

        if suffix.lower() in (".xlsx", ".xls"):
            preview_df = pd.read_excel(tmp_path, nrows=5)
        else:
            preview_df = pd.read_csv(tmp_path, nrows=5)

        st.markdown("**Preview (first 5 rows):**")
        st.dataframe(preview_df, hide_index=True)

        cols = list(preview_df.columns)
        col1, col2, col3 = st.columns(3)
        with col1:
            filename_col = st.selectbox("Filename column", cols, key="map_fn_col")
        with col2:
            uwi_col = st.selectbox("UWI column", cols, key="map_uwi_col")
        with col3:
            fmt = st.selectbox("Format", ["DLIS", "LIS", "LAS"], key="map_mfmt")

        folder = st.text_input(
            "Files base directory", key="map_manifest_folder",
            placeholder=r"e.g. C:\Data\DLIS_Delivery",
        )

        # Repository
        if not repos.empty:
            repo_options = {"(none — assign later)": ""} | {
                f"{r['REPOSITORY_NAME']} ({r['BASE_PATH']})": r["REPOSITORY_ID"]
                for _, r in repos.iterrows()
            }
            selected_repo = st.selectbox(
                "Repository", options=list(repo_options.keys()),
                key="map_manifest_repo"
            )
            repository_id = repo_options[selected_repo]
        else:
            repository_id = ""

        if st.button("📥 Import manifest", type="primary",
                      key="map_manifest_btn",
                      disabled=not folder):
            with st.spinner("Importing…"):
                try:
                    map_df = import_manifest(
                        tmp_path, filename_col, uwi_col,
                        folder, fmt, repository_id,
                    )
                    saved = save_map(engine, map_df)
                    st.success(
                        f"✅ {saved} row(s) imported — "
                        f"all marked CONFIRMED. Review in the Review tab."
                    )
                except Exception as e:
                    st.error(str(e))

        os.unlink(tmp_path)

    except Exception as e:
        st.error(f"Could not read manifest: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW & CATALOG TAB
# ─────────────────────────────────────────────────────────────────────────────

def _render_review(engine):
    st.subheader("Review & Catalog")
    from modules.wl_file_map import _now_str

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        fmt_filter = st.selectbox(
            "Format", ["All", "DLIS", "LIS", "LAS"], key="map_rev_fmt"
        )
    with col2:
        status_filter = st.selectbox(
            "Status", ["All", "PENDING", "CONFIRMED", "SKIPPED", "CATALOGUED"],
            key="map_rev_status"
        )

    fmt_arg    = "" if fmt_filter    == "All" else fmt_filter
    status_arg = "" if status_filter == "All" else status_filter

    try:
        df = load_map(engine, fmt=fmt_arg, status=status_arg)
    except Exception as e:
        st.error(str(e))
        return

    if df.empty:
        st.info("No staging rows found. Use the Scan or Manifest tab to add files.")
        return

    st.markdown(f"**{len(df)} file(s) in staging**")

    # Summary bar
    counts = df["STATUS"].value_counts().to_dict()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pending",    counts.get("PENDING",    0))
    c2.metric("Confirmed",  counts.get("CONFIRMED",  0))
    c3.metric("Skipped",    counts.get("SKIPPED",    0))
    c4.metric("Catalogued", counts.get("CATALOGUED", 0))

    st.divider()

    # Load PPDM UWIs for override dropdowns
    try:
        ppdm_uwis = fetch_ppdm_uwis(engine)
        uwi_options = [""] + [r["UWI"] for r in ppdm_uwis]
    except Exception:
        uwi_options = [""]

    # Editable grid
    st.markdown("**Review matches — override UWI or skip as needed:**")

    display_df = df[[
        "MAP_ID", "FILE_NAME", "FILE_FORMAT", "UWI",
        "MATCH_WELL_NAME", "MATCH_METHOD", "MATCH_SCORE",
        "HEADER_WELL_ID", "STATUS", "REMARK"
    ]].copy()

    edited = st.data_editor(
        display_df,
        hide_index=True,
        column_config={
            "MAP_ID":          st.column_config.Column(disabled=True, width="small"),
            "FILE_NAME":       st.column_config.Column(disabled=True),
            "FILE_FORMAT":     st.column_config.Column(disabled=True, width="small"),
            "MATCH_WELL_NAME": st.column_config.Column(disabled=True),
            "MATCH_METHOD":    st.column_config.Column(disabled=True, width="small"),
            "MATCH_SCORE":     st.column_config.NumberColumn(disabled=True, width="small"),
            "HEADER_WELL_ID":  st.column_config.Column(disabled=True),
            "UWI": st.column_config.SelectboxColumn(
                "UWI", options=uwi_options, width="medium"
            ),
            "STATUS": st.column_config.SelectboxColumn(
                "STATUS",
                options=["PENDING", "CONFIRMED", "SKIPPED"],
                width="small",
            ),
            "REMARK": st.column_config.TextColumn(width="medium"),
        },
        key="map_review_grid",
    )

    # Save edits button
    # ── Repository assignment ─────────────────────────────────────────
    # Required before cataloguing — rows without REPOSITORY_ID are skipped
    st.divider()
    st.markdown("**Assign repository**")

    try:
        repos = list_repositories(engine)
        if not repos.empty:
            repo_opts = {
                f"{r['REPOSITORY_NAME']} ({r['BASE_PATH']})": r["REPOSITORY_ID"]
                for _, r in repos.iterrows()
            }
            repo_id_to_name = {v: k for k, v in repo_opts.items()}

            # Show current repository assignment summary
            missing_repo = df["REPOSITORY_ID"].isna().sum()
            assigned = df["REPOSITORY_ID"].notna().sum()
            if missing_repo > 0:
                st.warning(
                    f"{missing_repo} row(s) have no repository — "
                    "they will be skipped when cataloguing."
                )
            if assigned > 0:
                current = df["REPOSITORY_ID"].dropna().mode()
                current_name = repo_id_to_name.get(
                    current.iloc[0] if not current.empty else "", "mixed"
                )
                st.caption(f"Current: {current_name}")

            col_repo, col_assign_all, col_assign_missing = st.columns([3, 1, 1])
            with col_repo:
                selected_repo_label = st.selectbox(
                    "Repository to assign", options=list(repo_opts.keys()),
                    key="map_rev_repo"
                )
            with col_assign_all:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                if st.button("Assign to ALL", type="primary",
                              key="map_assign_repo_all_btn",
                              help="Overwrites any existing repository assignment"):
                    repo_id = repo_opts[selected_repo_label]
                    from sqlalchemy import text
                    with engine.begin() as con:
                        con.execute(text("""
                            UPDATE [las_catalog].[WL_FILE_UWI_MAP]
                            SET REPOSITORY_ID    = :repo,
                                ROW_CHANGED_BY   = 'DATA_WRANGLER',
                                ROW_CHANGED_DATE = :now
                            WHERE STATUS IN ('PENDING', 'CONFIRMED')
                        """), {"repo": repo_id, "now": _now_str()})
                    st.success("Repository updated for all active rows.")
                    st.rerun()
            with col_assign_missing:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                if st.button("Assign missing",
                              key="map_assign_repo_missing_btn",
                              disabled=missing_repo == 0,
                              help="Only fills rows with no repository set"):
                    repo_id = repo_opts[selected_repo_label]
                    from sqlalchemy import text
                    with engine.begin() as con:
                        con.execute(text("""
                            UPDATE [las_catalog].[WL_FILE_UWI_MAP]
                            SET REPOSITORY_ID    = :repo,
                                ROW_CHANGED_BY   = 'DATA_WRANGLER',
                                ROW_CHANGED_DATE = :now
                            WHERE STATUS IN ('PENDING', 'CONFIRMED')
                              AND REPOSITORY_ID IS NULL
                        """), {"repo": repo_id, "now": _now_str()})
                    st.success(f"Repository assigned to {missing_repo} unassigned row(s).")
                    st.rerun()
        else:
            st.warning("No repositories registered. Register one in the Well Log Catalog first.")
    except Exception as e:
        st.error(str(e))

    st.divider()
    col_save, col_confirm, col_catalog, col_clear = st.columns(4)

    with col_save:
        if st.button("💾 Save edits", key="map_save_btn"):
            try:
                # Merge edits back — update UWI, STATUS, REMARK
                merged = df.copy()
                merged.set_index("MAP_ID", inplace=True)
                for _, erow in edited.iterrows():
                    mid = erow["MAP_ID"]
                    if mid in merged.index:
                        merged.at[mid, "UWI"]    = erow["UWI"]
                        merged.at[mid, "STATUS"] = erow["STATUS"]
                        merged.at[mid, "REMARK"] = erow["REMARK"]
                merged.reset_index(inplace=True)
                saved = save_map(engine, merged)
                st.success(f"✅ {saved} row(s) saved.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    with col_confirm:
        pending_ids = df[df["STATUS"] == "PENDING"]["MAP_ID"].tolist()
        if st.button(
            f"✔ Confirm all matched ({len([i for i in pending_ids if df.loc[df['MAP_ID']==i, 'UWI'].iloc[0]])})",
            key="map_confirm_btn",
            disabled=len(pending_ids) == 0,
        ):
            try:
                # Confirm pending rows that have a UWI
                ids_with_uwi = df[
                    (df["STATUS"] == "PENDING") & df["UWI"].notna()
                ]["MAP_ID"].tolist()
                n = confirm_rows(engine, ids_with_uwi)
                st.success(f"✅ {n} row(s) confirmed.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    with col_catalog:
        confirmed_count = counts.get("CONFIRMED", 0)
        if st.button(
            f"🚀 Catalog {confirmed_count} confirmed",
            type="primary",
            key="map_catalog_btn",
            disabled=confirmed_count == 0,
        ):
            with st.spinner(f"Cataloguing {confirmed_count} file(s)…"):
                try:
                    result = catalog_confirmed(engine)
                    if result["errors"] == 0:
                        st.success(
                            f"✅ {result['catalogued']} catalogued"
                        )
                    else:
                        st.warning(
                            f"{result['catalogued']} catalogued · "
                            f"{result['errors']} error(s)"
                        )
                    if result["details"]:
                        with st.expander("Details", expanded=result["errors"] > 0):
                            st.dataframe(
                                pd.DataFrame(result["details"]), hide_index=True,
                            )
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

    with col_clear:
        catalogued_count = counts.get("CATALOGUED", 0)
        if st.button(
            f"🧹 Clear {catalogued_count} catalogued",
            key="map_clear_btn",
            disabled=catalogued_count == 0,
        ):
            try:
                n = clear_catalogued(engine)
                st.success(f"Cleared {n} row(s).")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    # ── Rename section ────────────────────────────────────────────────
    confirmed_count = counts.get("CONFIRMED", 0)
    if confirmed_count > 0:
        st.divider()
        with st.expander("✏️ Rename files with UWI prefix", expanded=False):
            st.markdown(
                "Prepends the assigned UWI to the filename before cataloguing, "
                "so the fuzzy matcher can identify the file in future scans. "
                "e.g. Chevron_A12a.DLIS becomes 17-031-10035-0000_Chevron_A12a.DLIS. "
                "Files are renamed in place. Original files are replaced."
            )

            # Preview
            try:
                preview_df = preview_rename(engine)
            except Exception as e:
                st.error(str(e))
                preview_df = pd.DataFrame()

            if not preview_df.empty:
                to_rename = preview_df[~preview_df["ALREADY_RENAMED"]]
                already   = preview_df[preview_df["ALREADY_RENAMED"]]

                if not to_rename.empty:
                    st.markdown(f"**{len(to_rename)} file(s) will be renamed:**")
                    st.dataframe(
                        to_rename[["FILE_NAME", "NEW_FILE_NAME", "UWI"]], hide_index=True,
                    )
                if not already.empty:
                    st.caption(
                        f"{len(already)} file(s) already have UWI prefix — will be skipped."
                    )

                col_dry, col_rename = st.columns([1, 1])
                with col_dry:
                    if st.button("👁 Dry run", key="map_rename_dry_btn",
                                  disabled=to_rename.empty):
                        try:
                            r = rename_files(engine, dry_run=True)
                            st.info(
                                f"Would rename {r['renamed']} file(s), "
                                f"skip {r['skipped']} already prefixed."
                            )
                        except Exception as e:
                            st.error(str(e))

                with col_rename:
                    if st.button(
                        f"✏️ Rename {len(to_rename)} file(s)",
                        type="primary",
                        key="map_rename_btn",
                        disabled=to_rename.empty,
                    ):
                        try:
                            r = rename_files(engine, dry_run=False)
                            if r["errors"] == 0:
                                st.success(
                                    f"✅ {r['renamed']} renamed, "
                                    f"{r['skipped']} skipped."
                                )
                            else:
                                st.warning(
                                    f"{r['renamed']} renamed · "
                                    f"{r['skipped']} skipped · "
                                    f"{r['errors']} error(s)"
                                )
                            if r["details"]:
                                with st.expander("Details", expanded=r["errors"] > 0):
                                    st.dataframe(
                                        pd.DataFrame(r["details"]),
                                        hide_index=True,
                                    )
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))
            else:
                st.info("No confirmed rows with UWI to rename.")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_engine():
    engine = st.session_state.get("engine")
    if engine is not None:
        return engine
    try:
        from modules.db_pool import get_engine
        return get_engine()
    except ImportError:
        return None

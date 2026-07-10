"""
page_file_browser.py — Data Wrangler File Browser
===================================================
Standalone end-user page for searching, previewing and copying
cataloged petroleum files (LAS, DLIS, LIS, SEG-Y, P190).

No admin tools — search, select, copy. That's it.
"""

import os
import shutil
import streamlit as st
import pandas as pd
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_engine():
    """Get engine from session state."""
    import streamlit as _st
    # Try session state first (set by pipeline connection)
    for key in ("engine", "_engine", "db_engine"):
        eng = _st.session_state.get(key)
        if eng is not None:
            return eng
    # Fallback to db_pool
    try:
        from dataview.core.db_pool import get_engine
        return get_engine()
    except Exception:
        return None


def _search_all(engine,
                fmt_filter:  str  = "All",
                uwi:         str  = "",
                well_name:   str  = "",
                survey_name: str  = "",
                max_rows:    int  = 500) -> pd.DataFrame:
    from sqlalchemy import text
    rows  = []
    errors = []

    def _full_path_case(base_col, file_col):
        return (f"CASE WHEN {base_col} IS NULL THEN {file_col} "
                f"WHEN RIGHT({base_col},1)='\\\\' THEN {base_col}+{file_col} "
                f"ELSE {base_col}+'\\\\'+{file_col} END")

    # ── LAS ──────────────────────────────────────────────────────────────────
    if fmt_filter in ("All", "LAS"):
        try:
            uwi_cl  = "AND f.uwi LIKE :uwi"       if uwi       else ""
            well_cl = "AND f.well_name LIKE :wn"   if well_name else ""
            sql = f"""
                SELECT TOP {max_rows}
                    f.LAS_FILE_ID AS FILE_ID, 'LAS' AS FILE_FORMAT,
                    f.FILE_NAME, f.uwi, f.well_name, NULL AS SURVEY_NAME,
                    f.FILE_SIZE_KB, f.CATALOG_DATE,
                    {_full_path_case('r.BASE_PATH','f.FILE_NAME')} AS FULL_PATH,
                    r.REPOSITORY_NAME
                FROM [las_catalog].[LAS_FILE] f
                LEFT JOIN [las_catalog].[WL_REPOSITORY] r ON f.REPOSITORY_ID=r.REPOSITORY_ID
                WHERE 1=1 {uwi_cl} {well_cl}
                ORDER BY f.CATALOG_DATE DESC
            """
            params = {}
            if uwi:       params["uwi"] = f"%{uwi}%"
            if well_name: params["wn"]  = f"%{well_name}%"
            with engine.connect() as con:
                rows += [dict(r._mapping) for r in con.execute(text(sql), params).fetchall()]
        except Exception as e:
            errors.append(f"LAS: {e}")

    # ── DLIS ─────────────────────────────────────────────────────────────────
    if fmt_filter in ("All", "DLIS"):
        try:
            uwi_cl = "AND f.uwi LIKE :uwi" if uwi else ""
            sql = f"""
                SELECT TOP {max_rows}
                    f.DLIS_FILE_ID AS FILE_ID, 'DLIS' AS FILE_FORMAT,
                    f.FILE_NAME, f.uwi, NULL AS well_name, NULL AS SURVEY_NAME,
                    f.FILE_SIZE_KB, f.CATALOG_DATE,
                    {_full_path_case('r.BASE_PATH','f.FILE_NAME')} AS FULL_PATH,
                    r.REPOSITORY_NAME
                FROM [las_catalog].[DLIS_FILE] f
                LEFT JOIN [las_catalog].[WL_REPOSITORY] r ON f.REPOSITORY_ID=r.REPOSITORY_ID
                WHERE 1=1 {uwi_cl}
                ORDER BY f.CATALOG_DATE DESC
            """
            params = {"uwi": f"%{uwi}%"} if uwi else {}
            with engine.connect() as con:
                rows += [dict(r._mapping) for r in con.execute(text(sql), params).fetchall()]
        except Exception as e:
            errors.append(f"DLIS: {e}")

    # ── LIS ──────────────────────────────────────────────────────────────────
    if fmt_filter in ("All", "LIS"):
        try:
            uwi_cl = "AND f.uwi LIKE :uwi" if uwi else ""
            sql = f"""
                SELECT TOP {max_rows}
                    f.LIS_FILE_ID AS FILE_ID, 'LIS' AS FILE_FORMAT,
                    f.FILE_NAME, f.uwi, NULL AS well_name, NULL AS SURVEY_NAME,
                    f.FILE_SIZE_KB, f.CATALOG_DATE,
                    {_full_path_case('r.BASE_PATH','f.FILE_NAME')} AS FULL_PATH,
                    r.REPOSITORY_NAME
                FROM [las_catalog].[LIS_FILE] f
                LEFT JOIN [las_catalog].[WL_REPOSITORY] r ON f.REPOSITORY_ID=r.REPOSITORY_ID
                WHERE 1=1 {uwi_cl}
                ORDER BY f.CATALOG_DATE DESC
            """
            params = {"uwi": f"%{uwi}%"} if uwi else {}
            with engine.connect() as con:
                rows += [dict(r._mapping) for r in con.execute(text(sql), params).fetchall()]
        except Exception as e:
            errors.append(f"LIS: {e}")

    # ── SEG-Y / P190 ─────────────────────────────────────────────────────────
    if fmt_filter in ("All", "SEG-Y", "P190"):
        try:
            fmt_cl = ""
            if fmt_filter == "SEG-Y":
                fmt_cl = "AND f.FILE_FORMAT IN ('SEGY','SEG-Y')"
            elif fmt_filter == "P190":
                fmt_cl = "AND f.FILE_FORMAT = 'P190'"
            sv_cl = "AND f.SURVEY_NAME LIKE :sv" if survey_name else ""
            sql = f"""
                SELECT TOP {max_rows}
                    f.SEIS_FILE_ID AS FILE_ID, f.FILE_FORMAT,
                    f.FILE_NAME, NULL AS uwi, NULL AS well_name,
                    f.SURVEY_NAME, f.FILE_SIZE_KB, f.CATALOG_DATE,
                    f.FILE_NAME AS FULL_PATH, r.REPOSITORY_NAME
                FROM [las_catalog].[SEIS_FILE_CATALOG] f
                LEFT JOIN [las_catalog].[WL_REPOSITORY] r ON f.REPOSITORY_ID=r.REPOSITORY_ID
                WHERE 1=1 {fmt_cl} {sv_cl}
                ORDER BY f.CATALOG_DATE DESC
            """
            params = {"sv": f"%{survey_name}%"} if survey_name else {}
            with engine.connect() as con:
                rows += [dict(r._mapping) for r in con.execute(text(sql), params).fetchall()]
        except Exception as e:
            errors.append(f"Seismic: {e}")

    if errors:
        import streamlit as _st
        for err in errors:
            _st.warning(f"⚠️ Query error — {err}")

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    for col in ["uwi", "well_name", "SURVEY_NAME", "REPOSITORY_NAME"]:
        if col not in df.columns:
            df[col] = None
    df["FILE_SIZE_MB"] = (df["FILE_SIZE_KB"].fillna(0) / 1024).round(2)
    df["DISPLAY_NAME"] = df.apply(
        lambda r: r["well_name"] or r["SURVEY_NAME"] or r["uwi"] or "—", axis=1
    )
    return df

def _copy_files(file_paths: list[str], dest_folder: str,
                overwrite: bool = False) -> dict:
    """Copy a list of files to dest_folder. Returns result summary."""
    os.makedirs(dest_folder, exist_ok=True)
    copied = skipped = missing = errors = 0
    details = []

    for src in file_paths:
        src_path = Path(src)
        if not src_path.exists():
            missing += 1
            details.append({"File": src_path.name, "Status": "❌ Not found"})
            continue
        dst_path = Path(dest_folder) / src_path.name
        if dst_path.exists() and not overwrite:
            skipped += 1
            details.append({"File": src_path.name, "Status": "⏭ Skipped (exists)"})
            continue
        try:
            shutil.copy2(str(src_path), str(dst_path))
            copied += 1
            details.append({"File": src_path.name, "Status": "✅ Copied"})
        except Exception as e:
            errors += 1
            details.append({"File": src_path.name, "Status": f"❌ {e}"})

    return {
        "copied": copied, "skipped": skipped,
        "missing": missing, "errors": errors,
        "details": details,
    }


# ── Main render ───────────────────────────────────────────────────────────────

def render(engine=None):
    st.title("📋 Browse & Export")
    st.caption(
        "Search cataloged files or the file inventory. "
        "Preview headers and plots. Copy files or export DB data."
    )

    if engine is None:
        engine = _get_engine()
    if engine is None:
        st.warning("⚠️ No database connection. Connect via the pipeline first.")
        return

    tab_catalog, tab_inventory, tab_wells, tab_seis, tab_ppdm = st.tabs([
        "📦 File Catalog", "🗂 File Inventory",
        "🛢 Well Search", "🌊 Seismic Search", "📊 DB Export"
    ])

    with tab_catalog:
        _render_catalog_search(engine)

    with tab_inventory:
        _render_inventory_search(engine)

    with tab_wells:
        _render_well_search(engine)

    with tab_seis:
        _render_seis_search(engine)

    with tab_ppdm:
        _render_ppdm_export(engine)


def _render_catalog_search(engine):
    """Search the file catalog (cataloged files)."""

    # ── Search filters ────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown("#### 🔍 Search")
        c1, c2, c3, c4 = st.columns(4)
        fmt = c1.selectbox(
            "Format", ["All", "LAS", "DLIS", "LIS", "SEG-Y", "P190"],
            key="fb_fmt"
        )
        uwi       = c2.text_input("uwi",         key="fb_uwi",
                                   placeholder="e.g. 42-001-00001")
        well_name = c3.text_input("Well name",    key="fb_well",
                                   placeholder="e.g. ANADARKO")
        survey    = c4.text_input("Survey name",  key="fb_survey",
                                   placeholder="e.g. CENTRAL")

        c5, c6 = st.columns([1, 3])
        max_rows = c5.number_input("Max results", min_value=10, max_value=5000,
                                    value=200, step=50, key="fb_maxrows")
        search_btn = c6.button("🔍 Search", type="primary",
                                use_container_width=False, key="fb_search")

    if search_btn or "fb_results" in st.session_state:
        if search_btn:
            with st.spinner("Searching catalog…"):
                df = _search_all(engine, fmt_filter=fmt, uwi=uwi,
                                 well_name=well_name, survey_name=survey,
                                 max_rows=int(max_rows))
            st.session_state["fb_results"] = df
        else:
            df = st.session_state["fb_results"]

        if df.empty:
            st.info("No files found matching your search.")
            return

        st.divider()
        st.markdown(f"**{len(df):,} file(s) found**")

        # ── Results table with Select checkbox column ─────────────────────────
        sel_df = df[["FILE_FORMAT","FILE_NAME","DISPLAY_NAME","uwi",
                      "FILE_SIZE_MB","REPOSITORY_NAME","CATALOG_DATE",
                      "FULL_PATH"]].copy()
        sel_df.insert(0, "Select", False)

        edited = st.data_editor(
            sel_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key="fb_table",
            column_config={
                "Select":        st.column_config.CheckboxColumn("✓", width="small"),
                "FILE_FORMAT":   st.column_config.TextColumn("Format", width="small"),
                "FILE_NAME":     st.column_config.TextColumn("File Name"),
                "DISPLAY_NAME":  st.column_config.TextColumn("Well / Survey"),
                "uwi":           st.column_config.TextColumn("uwi"),
                "FILE_SIZE_MB":  st.column_config.NumberColumn("MB", format="%.2f", width="small"),
                "REPOSITORY_NAME": st.column_config.TextColumn("Repository"),
                "CATALOG_DATE":  st.column_config.TextColumn("Cataloged", width="medium"),
                "FULL_PATH":     st.column_config.TextColumn("Full Path"),
            },
        )

        selected_rows = edited[edited["Select"] == True]
        n_sel = len(selected_rows)
        mb_sel = selected_rows["FILE_SIZE_MB"].sum()

        ca, cb, cc = st.columns([2, 2, 4])
        if ca.button("☑ Select All", key="fb_sel_all", use_container_width=True):
            edited["Select"] = True
        if cb.button("☐ Clear All", key="fb_sel_none", use_container_width=True):
            edited["Select"] = False
        if n_sel:
            cc.caption(f"**{n_sel}** file(s) selected · **{mb_sel:.1f} MB** total")

        # ── File preview ──────────────────────────────────────────────────────
        st.divider()
        st.markdown("#### 🔍 Preview File")
        preview_opts = {
            f"{row['FILE_FORMAT']} — {row['FILE_NAME']}": i
            for i, row in df.iterrows()
        }
        prev_sel = st.selectbox(
            "Select file to preview",
            ["— select a file —"] + list(preview_opts.keys()),
            key="fb_preview_sel"
        )
        if prev_sel != "— select a file —":
            idx = preview_opts[prev_sel]
            row = df.iloc[idx]
            fp  = str(row.get("FULL_PATH","")).strip()
            if not fp or fp in ("None","nan",""):
                st.warning("No file path stored for this entry.")
            else:
                try:
                    from dataview.file_catalog import page_file_workbench as _pwb
                    _pwb.render_workbench(
                        file_path=fp,
                        fmt=None,
                        key=f"fb_prev_{idx}",
                        show_edit=False,
                    )
                except Exception as e:
                    st.error(f"Preview error: {e}")

        # ── Copy options ──────────────────────────────────────────────────────
        st.divider()
        st.markdown("#### 📂 Copy to folder")
        c_dest, c_ow, c_btn = st.columns([4, 1, 1])
        dest = c_dest.text_input(
            "Destination folder", key="fb_dest",
            placeholder=r"e.g. C:\Downloads\WellLogs"
        )
        overwrite = c_ow.checkbox("Overwrite", value=False, key="fb_overwrite")
        copy_btn  = c_btn.button(
            f"📋 Copy {n_sel} file(s)",
            type="primary", key="fb_copy",
            use_container_width=True,
            disabled=not (n_sel > 0 and dest.strip())
        )

        if copy_btn:
            file_paths = selected_rows["FULL_PATH"].tolist()
            missing_paths = [p for p in file_paths
                             if not p or str(p).strip() in ("", "None", "nan")]
            if missing_paths:
                st.warning(f"⚠️ {len(missing_paths)} file(s) have no stored path "
                           f"and will be skipped.")
                file_paths = [p for p in file_paths
                              if p and str(p).strip() not in ("", "None", "nan")]

            if not file_paths:
                st.error("No valid file paths to copy.")
            else:
                prog = st.progress(0, text="Copying…")
                result = _copy_files(file_paths, dest.strip(), overwrite=overwrite)
                prog.progress(1.0, text="Done")

                if result["errors"] == 0 and result["missing"] == 0:
                    st.success(
                        f"✅ {result['copied']} copied · "
                        f"{result['skipped']} skipped"
                    )
                else:
                    st.warning(
                        f"{result['copied']} copied · "
                        f"{result['skipped']} skipped · "
                        f"{result['missing']} not found · "
                        f"{result['errors']} error(s)"
                    )

                with st.expander("📋 Copy details", expanded=result["errors"] > 0):
                    st.dataframe(
                        pd.DataFrame(result["details"]),
                        hide_index=True,
                        use_container_width=True
                    )



def _render_inventory_search(engine):
    """Search the global file inventory (all scanned files)."""
    import pandas as pd
    from sqlalchemy import text

    st.markdown("#### 🗂 Search File Inventory")
    st.caption("Search all scanned files — cataloged or not. Based on GLOBAL_FILE_CATALOG.")

    c1,c2,c3 = st.columns(3)
    q_name   = c1.text_input("File name", key="inv_q_name",
                              placeholder="e.g. ANADARKO")
    q_ext    = c2.selectbox("Extension",
                             ["All",".las",".dlis",".lis",".segy",".sgy",".p190"],
                             key="inv_q_ext")
    q_status = c3.selectbox("Status",
                             ["All","UNCATALOGED","ASSIGNED","CATALOGED","SKIPPED"],
                             key="inv_q_status")

    if st.button("🔍 Search Inventory", type="primary", key="inv_search_btn"):
        try:
            where  = ["1=1"]
            params = {}
            if q_name.strip():
                where.append("FILE_NAME LIKE :nm")
                params["nm"] = f"%{q_name.strip()}%"
            if q_ext != "All":
                where.append("FILE_EXT=:ext")
                params["ext"] = q_ext
            if q_status != "All":
                where.append("CATALOG_STATUS=:st")
                params["st"] = q_status
            with engine.connect() as con:
                rows = con.execute(text(
                    f"SELECT TOP 500 FILE_NAME, FILE_EXT, FILE_TYPE_GROUP, "
                    f"FILE_SIZE_KB, FILE_PATH, CATALOG_STATUS, SCAN_DATE "
                    f"FROM file_catalog.GLOBAL_FILE_CATALOG "
                    f"WHERE {' AND '.join(where)} "
                    f"ORDER BY SCAN_DATE DESC"
                ), params).fetchall()
            if not rows:
                st.info("No results found.")
                return
            df = pd.DataFrame(rows, columns=[
                "File Name","Ext","Type","Size KB","Path","Status","Scan Date"
            ])
            df["Size KB"] = df["Size KB"].fillna(0).round(1)
            st.caption(f"**{len(df):,}** file(s) found")
            st.dataframe(df, hide_index=True, use_container_width=True)
            st.download_button(
                "⬇ Export CSV", df.to_csv(index=False),
                file_name="inventory_search.csv", mime="text/csv",
                key="inv_dl_csv"
            )
        except Exception as e:
            st.error(str(e))


def _render_ppdm_export(engine):
    """Export DB table data to CSV or Excel."""
    import pandas as pd
    from sqlalchemy import text

    st.markdown("#### 🛢 Export DB Data")
    st.caption("Export well and seismic data from the PPDM schema to CSV or Excel.")

    PPDM_TABLES = {
        "WELL":       ("dataview.dv_well",       "uwi, well_name, OPERATOR, field_name, "
                                          "COUNTRY_NAME, PROVINCE_STATE, STATUS_TYPE, "
                                          "SURF_LONGITUDE, SURF_LATITUDE"),
        "WELL_LOG":   ("dbo.WELL_LOG",   "uwi, WELL_LOG_ID, LOG_NAME, LOG_TYPE, "
                                          "LOG_DATE, SERVICE_COMPANY"),
        "SEIS_SET":   ("dataview.dv_seis_set",   "SEIS_SET_ID, SEIS_SET_NAME, SEIS_SET_TYPE, "
                                          "SURVEY_TYPE, COUNTRY_NAME, OPERATOR"),
        "SEIS_LINE":  ("dbo.SEIS_LINE",  "SEIS_SET_ID, LINE_NAME, LINE_TYPE, "
                                          "RECORD_TYPE, SHOT_POINT_MIN, SHOT_POINT_MAX"),
    }

    c1, c2 = st.columns(2)
    tbl_sel = c1.selectbox("PPDM Table", list(PPDM_TABLES.keys()),
                            key="ppdm_tbl_sel")
    fmt_sel = c2.selectbox("Export format", ["CSV","Excel"], key="ppdm_fmt_sel")

    tbl_name, default_cols = PPDM_TABLES[tbl_sel]

    # Optional filter
    with st.expander("⚙️ Filter (optional)", expanded=False):
        filter_col = st.text_input("Column to filter on", key="ppdm_filter_col",
                                    placeholder="e.g. COUNTRY_NAME")
        filter_val = st.text_input("Value (partial match)", key="ppdm_filter_val",
                                    placeholder="e.g. AUSTRALIA")
        max_rows   = st.number_input("Max rows", min_value=10, max_value=100000,
                                      value=5000, step=1000, key="ppdm_max_rows")

    if st.button("🔍 Preview & Export", type="primary", key="ppdm_export_btn"):
        try:
            where  = "WHERE 1=1"
            params = {}
            if filter_col.strip() and filter_val.strip():
                where = f"WHERE [{filter_col.strip()}] LIKE :fv"
                params["fv"] = f"%{filter_val.strip()}%"

            with engine.connect() as con:
                rows = con.execute(text(
                    f"SELECT TOP {int(max_rows)} {default_cols} "
                    f"FROM {tbl_name} {where}"
                ), params).fetchall()

            if not rows:
                st.info("No rows found.")
                return

            df = pd.DataFrame(rows,
                              columns=[c.strip() for c in default_cols.split(",")])
            st.caption(f"**{len(df):,}** row(s) from `{tbl_name}`")
            st.dataframe(df, hide_index=True, use_container_width=True)

            # Export
            if fmt_sel == "CSV":
                st.download_button(
                    f"⬇ Download {tbl_sel}.csv",
                    data=df.to_csv(index=False),
                    file_name=f"{tbl_sel.lower()}_export.csv",
                    mime="text/csv",
                    key="ppdm_dl_csv"
                )
            else:
                import io
                buf = io.BytesIO()
                df.to_excel(buf, index=False, sheet_name=tbl_sel)
                buf.seek(0)
                st.download_button(
                    f"⬇ Download {tbl_sel}.xlsx",
                    data=buf.getvalue(),
                    file_name=f"{tbl_sel.lower()}_export.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="ppdm_dl_xlsx"
                )
        except Exception as e:
            st.error(str(e))



# ─────────────────────────────────────────────────────────────────────────────
# Well search — dataview.dv_well with file preview
# ─────────────────────────────────────────────────────────────────────────────

def _render_well_search(engine):
    """
    Search well files across three scenarios:
    1. Cataloged + DB matched  — LAS/DLIS/LIS with uwi in dataview.dv_well
    2. Cataloged + unmatched uwi — cataloged but uwi not in dataview.dv_well
    3. Inventory only            — in GLOBAL_FILE_CATALOG, not yet cataloged
    """
    import pandas as pd
    from sqlalchemy import text

    st.markdown("#### 🛢 Well File Search")
    st.caption(
        "Search across cataloged files and the file inventory. "
        "Shows the uwi stored in the file header and whether it exists in DB."
    )

    # ── Filters ───────────────────────────────────────────────────────────────
    c1,c2,c3,c4 = st.columns(4)
    q_uwi   = c1.text_input("uwi (file or PPDM)", key="ws_uwi_1",
                              placeholder="e.g. 42-001-00001")
    q_well  = c2.text_input("Well name",          key="ws_well_1",
                              placeholder="e.g. ANADARKO")
    q_fmt   = c3.selectbox("Format", ["All","LAS","DLIS","LIS"],
                            key="ws_fmt")
    q_scope = c4.selectbox("Show",
                            ["All files","Matched only",
                             "Unmatched uwi","Inventory only"],
                            key="ws_scope")
    c5,c6   = st.columns([1,3])
    max_r   = c5.number_input("Max results", 10, 5000, 200, key="ws_max_1")
    search  = c6.button("🔍 Search", type="primary", key="ws_btn_1")

    if search or "ws_results" in st.session_state:
        if search:
            try:
                rows_all = []

                # ── 1 & 2: Cataloged files (LAS/DLIS/LIS) ────────────────────
                for tbl, fmt, pk in [
                    ("las_catalog.LAS_FILE",  "LAS",  "LAS_FILE_ID"),
                    ("las_catalog.DLIS_FILE", "DLIS", "DLIS_FILE_ID"),
                    ("las_catalog.LIS_FILE",  "LIS",  "LIS_FILE_ID"),
                ]:
                    if q_fmt not in ("All", fmt):
                        continue
                    where  = ["1=1"]
                    params = {}
                    if q_uwi.strip():
                        where.append("(f.uwi LIKE :uwi OR w.uwi LIKE :uwi)")
                        params["uwi"] = f"%{q_uwi.strip()}%"
                    if q_well.strip():
                        where.append(
                            "(f.well_name LIKE :wn OR w.well_name LIKE :wn)"
                            if fmt == "LAS" else "f.uwi LIKE :wn"
                        )
                        params["wn"] = f"%{q_well.strip()}%"

                    try:
                        well_name_col = "f.well_name" if fmt == "LAS" else "NULL"
                        with engine.connect() as con:
                            r = con.execute(text(f"""
                                SELECT TOP {int(max_r)}
                                    '{fmt}'          AS FORMAT,
                                    f.FILE_NAME,
                                    f.uwi            AS FILE_uwi,
                                    {well_name_col}  AS FILE_well_name,
                                    f.FILE_SIZE_KB,
                                    f.CATALOG_DATE,
                                    w.uwi            AS PPDM_uwi,
                                    w.well_name      AS PPDM_well_name,
                                    CASE WHEN w.uwi IS NOT NULL
                                         THEN '✅ Matched'
                                         WHEN f.uwi IS NOT NULL
                                         THEN '⚠️ Unmatched'
                                         ELSE '❓ No uwi'
                                    END              AS MATCH_STATUS
                                FROM {tbl} f
                                LEFT JOIN dataview.dv_well w ON w.uwi = f.uwi
                                WHERE {' AND '.join(where)}
                                ORDER BY f.CATALOG_DATE DESC
                            """), params).fetchall()
                        rows_all += [list(row) for row in r]
                    except Exception:
                        pass

                # ── 3: Inventory-only files (not yet cataloged) ───────────────
                if q_fmt in ("All","LAS","DLIS","LIS"):
                    try:
                        inv_where  = [
                            "CATALOG_STATUS NOT IN ('CATALOGED','SKIPPED')",
                            "FILE_TYPE_GROUP='Well Logs'"
                        ]
                        inv_params = {}
                        if q_uwi.strip():
                            inv_where.append("FILE_NAME LIKE :uwi")
                            inv_params["uwi"] = f"%{q_uwi.strip()}%"
                        if q_fmt != "All":
                            inv_where.append(f"FILE_EXT='.{q_fmt.lower()}'")

                        with engine.connect() as con:
                            r = con.execute(text(f"""
                                SELECT TOP {int(max_r)}
                                    UPPER(REPLACE(FILE_EXT,'.','')) AS FORMAT,
                                    FILE_NAME,
                                    NULL AS FILE_uwi,
                                    NULL AS FILE_well_name,
                                    FILE_SIZE_KB,
                                    SCAN_DATE AS CATALOG_DATE,
                                    NULL AS PPDM_uwi,
                                    NULL AS PPDM_well_name,
                                    '📂 Not cataloged' AS MATCH_STATUS
                                FROM file_catalog.GLOBAL_FILE_CATALOG
                                WHERE {' AND '.join(inv_where)}
                                ORDER BY SCAN_DATE DESC
                            """), inv_params).fetchall()
                        rows_all += [list(row) for row in r]
                    except Exception:
                        pass

                df = pd.DataFrame(rows_all, columns=[
                    "Format","File Name","File uwi","File Well Name",
                    "Size KB","Date","DB uwi","DB Well Name","Status"
                ]) if rows_all else pd.DataFrame()

                if not df.empty:
                    df["Size MB"] = (df["Size KB"].fillna(0)/1024).round(2)
                    df = df.drop(columns=["Size KB"])

                    # Apply scope filter
                    if q_scope == "Matched only":
                        df = df[df["Status"] == "✅ Matched"]
                    elif q_scope == "Unmatched uwi":
                        df = df[df["Status"] == "⚠️ Unmatched"]
                    elif q_scope == "Inventory only":
                        df = df[df["Status"] == "📂 Not cataloged"]

                st.session_state["ws_results"] = df
            except Exception as e:
                st.error(str(e)); return
        else:
            df = st.session_state.get("ws_results", pd.DataFrame())

        if df.empty:
            st.info("No files found matching your search.")
            return

        # ── Summary metrics ───────────────────────────────────────────────────
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Total",          len(df))
        m2.metric("✅ DB matched", len(df[df["Status"]=="✅ Matched"]))
        m3.metric("⚠️ Unmatched",    len(df[df["Status"]=="⚠️ Unmatched"]))
        m4.metric("📂 Not cataloged",len(df[df["Status"]=="📂 Not cataloged"]))

        st.dataframe(df, hide_index=True, use_container_width=True,
                     column_config={
                         "Status": st.column_config.TextColumn(width="small"),
                         "Size MB": st.column_config.NumberColumn(
                             format="%.2f", width="small"),
                     })

        st.download_button("⬇ Export CSV", df.to_csv(index=False),
                           file_name="well_file_search.csv",
                           mime="text/csv", key="ws_dl_1")

        # ── File preview ──────────────────────────────────────────────────────
        st.divider()
        cat_files = df[df["Status"] != "📂 Not cataloged"]
        if not cat_files.empty:
            prev = st.selectbox(
                "🔍 Preview cataloged file",
                ["— select —"] + cat_files["File Name"].tolist(),
                key="ws_prev_sel_1"
            )
            if prev != "— select —":
                row = cat_files[cat_files["File Name"]==prev].iloc[0]
                try:
                    from dataview.file_catalog import page_file_workbench as _pwb
                    _pwb.render_workbench(
                        file_path=row["File Name"],
                        key=f"ws_prev_{prev[:20]}",
                        show_edit=False,
                    )
                except Exception as e:
                    st.error(f"Preview: {e}")

        # ── Multi-file catalog grid (for inventory/unmatched files) ──────────
        uncataloged = df[df["Status"] == "📂 Not cataloged"]
        if not uncataloged.empty:
            st.divider()
            st.markdown("#### 📥 Catalog Inventory Files")
            st.caption(
                "Select inventory files to catalog. Edit uwi and well name "
                "inline. One repository applies to the whole batch."
            )

            # Repository selector
            try:
                from sqlalchemy import text as _t2
                with engine.connect() as con:
                    repos = con.execute(_t2(
                        "SELECT REPOSITORY_ID, REPOSITORY_NAME "
                        "FROM [las_catalog].[WL_REPOSITORY] "
                        "ORDER BY REPOSITORY_NAME"
                    )).fetchall()
                repo_opts = {"(none)": ""} | {r[1]: r[0] for r in repos}
            except Exception:
                repo_opts = {"(none)": ""}

            repo_label = st.selectbox("Repository for batch",
                                       list(repo_opts.keys()),
                                       key="ws_cat_repo")
            repo_id = repo_opts[repo_label]

            # Editable catalog grid
            cat_df = uncataloged[["File Name","Format","File uwi",
                                   "File Well Name"]].copy()
            cat_df.insert(0, "☑ Catalog", False)
            cat_df["uwi (edit)"]       = cat_df["File uwi"].fillna("")
            cat_df["Well Name (edit)"] = cat_df["File Well Name"].fillna("")
            cat_df["Override / Notes"] = ""

            edited_w = st.data_editor(
                cat_df[["☑ Catalog","Format","File Name",
                         "uwi (edit)","Well Name (edit)","Override / Notes"]],
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key="ws_cat_grid",
                column_config={
                    "☑ Catalog": st.column_config.CheckboxColumn(
                        "Catalog", width="small"),
                    "Format":    st.column_config.TextColumn(width="small"),
                    "uwi (edit)": st.column_config.TextColumn(
                        "uwi", help="Edit before cataloging"),
                    "Well Name (edit)": st.column_config.TextColumn(
                        "Well Name", help="Edit before cataloging"),
                    "Override / Notes": st.column_config.TextColumn("Notes"),
                }
            )

            sel_w  = edited_w[edited_w["☑ Catalog"] == True]
            n_selw = len(sel_w)
            st.caption(f"**{n_selw}** file(s) selected")

            if st.button(f"📥 Catalog {n_selw} file(s)", type="primary",
                          key="ws_cat_btn",
                          disabled=n_selw == 0 or not repo_id):
                results_w = []
                prog_w = st.progress(0)
                for i, (_, row) in enumerate(sel_w.iterrows()):
                    prog_w.progress((i+1)/n_selw)
                    fn  = row["File Name"]
                    fmt = str(row["Format"]).upper()
                    uwi = str(row["uwi (edit)"]).strip()
                    fp  = str(df[df["File Name"]==fn]["File Name"].iloc[0])
                    res = {"File": fn, "Status": ""}
                    try:
                        if fmt == "LAS":
                            from dataview.file_catalog.las_catalog import catalog_file as _cf
                            r = _cf(engine, fp, repo_id, uwi=uwi)
                        elif fmt == "DLIS":
                            from dataview.file_catalog.dlis_catalog import catalog_dlis_file as _cf
                            r = _cf(engine, fp, repo_id, uwi=uwi)
                        elif fmt == "LIS":
                            from dataview.file_catalog.dlis_catalog import catalog_lis_file as _cf
                            r = _cf(engine, fp, repo_id, uwi=uwi)
                        else:
                            r = {"ok": False, "error": f"Unknown format: {fmt}"}
                        res["Status"] = (f"✅ {r.get('action')}"
                                         if r.get("ok")
                                         else f"❌ {r.get('error','')}")
                    except Exception as e:
                        res["Status"] = f"❌ {e}"
                    results_w.append(res)

                prog_w.empty()
                res_df_w = pd.DataFrame(results_w)
                ok  = len(res_df_w[res_df_w["Status"].str.startswith("✅")])
                err = len(res_df_w[res_df_w["Status"].str.startswith("❌")])
                if err == 0:
                    st.success(f"✅ {ok} file(s) cataloged.")
                else:
                    st.warning(f"{ok} cataloged · {err} error(s)")
                with st.expander("Results", expanded=err > 0):
                    st.dataframe(res_df_w, hide_index=True,
                                 use_container_width=True)
                st.session_state.pop("ws_results", None)
                st.rerun()

        # ── Copy ──────────────────────────────────────────────────────────────
        st.divider()
        dest = st.text_input("📂 Copy selected files to folder",
                              key="ws_dest_1",
                              placeholder=r"e.g. C:\Downloads\WellLogs")
        sel_files = st.multiselect(
            "Files to copy",
            df["File Name"].tolist(),
            key="ws_copy_sel"
        )
        if st.button(f"📋 Copy {len(sel_files)} file(s)",
                      key="ws_copy_1", type="primary",
                      disabled=not (sel_files and dest.strip())):
            result = _copy_files(sel_files, dest.strip())
            if result["errors"] == 0:
                st.success(f"✅ {result['copied']} copied · "
                           f"{result['skipped']} skipped")
            else:
                st.warning(f"{result['copied']} copied · "
                           f"{result['errors']} error(s)")

    # Build SELECT with safe columns + joins to parent tables for readable names
    # PPDM 3.9 WELL uses surrogate FKs: ASSIGNED_FIELD, CURRENT_OPERATOR etc.
    safe_sql = f"""
        SELECT TOP {{max_r}}
            w.uwi,
            w.well_name,
            w.WELL_NUM,
            ba.LONG_NAME        AS OPERATOR_NAME,
            f.field_name        AS FIELD,
            w.PROVINCE_STATE,
            w.COUNTRY,
            w.WELL_STATUS,
            w.SPUD_DATE,
            w.FINAL_DRILL_DATE
        FROM dataview.dv_well w
        LEFT JOIN dataview.dv_business_associate ba
            ON ba.BUSINESS_ASSOCIATE_ID = w.CURRENT_OPERATOR
        LEFT JOIN dataview.dv_field f
            ON f.FIELD_ID = w.ASSIGNED_FIELD
        WHERE w.uwi IS NOT NULL
          {{where_clause}}
        ORDER BY w.well_name
    """
    display_cols = ["uwi","Well Name","Well #","Operator",
                    "Field","State","Country","Status",
                    "Spud Date","TD Date"]

    c1,c2,c3,c4 = st.columns(4)
    q_uwi  = c1.text_input("uwi",       key="ws_uwi_2",
                             placeholder="e.g. 42-001-00001")
    q_well = c2.text_input("Well name", key="ws_well_2",
                             placeholder="e.g. ANADARKO")
    q_field = c3.text_input("Field",    key="ws_field",
                             placeholder="e.g. PERMIAN")
    q_op   = c4.text_input("Operator",  key="ws_op",
                             placeholder="e.g. SHELL")

    c5,c6    = st.columns([1,3])
    max_rows = c5.number_input("Max results", 10, 2000, 100, key="ws_max_2")
    search   = c6.button("🔍 Search Wells", type="primary", key="ws_btn_2")

    if search or "ws_results" in st.session_state:
        if search:
            try:
                where_parts = []
                params = {}
                if q_uwi.strip():
                    where_parts.append("w.uwi LIKE :uwi")
                    params["uwi"] = f"%{q_uwi.strip()}%"
                if q_well.strip():
                    where_parts.append("w.well_name LIKE :wn")
                    params["wn"] = f"%{q_well.strip()}%"
                if q_field.strip():
                    where_parts.append("f.field_name LIKE :fld")
                    params["fld"] = f"%{q_field.strip()}%"
                if q_op.strip():
                    where_parts.append("ba.LONG_NAME LIKE :op")
                    params["op"] = f"%{q_op.strip()}%"

                where_clause = ("AND " + " AND ".join(where_parts)
                                if where_parts else "")
                sql = safe_sql.format(
                    max_r=int(max_rows),
                    where_clause=where_clause
                )
                try:
                    with engine.connect() as con:
                        rows = con.execute(text(sql), params).fetchall()
                    df = pd.DataFrame(rows, columns=display_cols)
                except Exception:
                    # Fallback — join may fail if BA or FIELD tables differ
                    # Use minimal safe query
                    where_clause2 = ("AND " + " AND ".join(
                        [p for p in where_parts
                         if "ba." not in p and "f." not in p]
                    ) if [p for p in where_parts
                          if "ba." not in p and "f." not in p] else "")
                    with engine.connect() as con:
                        rows = con.execute(text(
                            f"SELECT TOP {int(max_rows)} uwi, well_name "
                            f"FROM dataview.dv_well WHERE uwi IS NOT NULL "
                            f"{where_clause2} ORDER BY well_name"
                        ), {k:v for k,v in params.items()
                            if k in ("uwi","wn")}).fetchall()
                    df = pd.DataFrame(rows, columns=["uwi","Well Name"])

                st.session_state["ws_results"] = df
            except Exception as e:
                st.error(str(e)); return
        else:
            df = st.session_state.get("ws_results", pd.DataFrame())

        if df.empty or "Status" not in df.columns:
            st.info("No wells found.")
            return

        st.caption(f"**{len(df):,}** well(s) found")
        st.dataframe(df, hide_index=True, use_container_width=True)

        st.download_button("⬇ Export well list CSV",
                           data=df.to_csv(index=False),
                           file_name="well_search.csv",
                           mime="text/csv", key="ws_dl_2")

        # Show associated files
        st.divider()
        st.markdown("**Associated cataloged files**")
        sel_well = st.selectbox(
            "Select well to see files",
            ["— pick a well —"] + df["uwi"].tolist(),
            key="ws_pick_well"
        )
        if sel_well != "— pick a well —":
            try:
                files = []
                params2 = {"uwi": sel_well}
                with engine.connect() as con:
                    for tbl, fmt in [
                        ("las_catalog.LAS_FILE",  "LAS"),
                        ("las_catalog.DLIS_FILE", "DLIS"),
                        ("las_catalog.LIS_FILE",  "LIS"),
                    ]:
                        rows2 = con.execute(text(
                            f"SELECT '{fmt}', FILE_NAME, FILE_SIZE_KB, CATALOG_DATE "
                            f"FROM {tbl} WHERE uwi=:uwi"
                        ), params2).fetchall()
                        files += [{"Format":r[0],"File":r[1],
                                   "MB":round((r[2] or 0)/1024,2),
                                   "Cataloged":str(r[3])} for r in rows2]
                if files:
                    fdf = pd.DataFrame(files)
                    st.dataframe(fdf, hide_index=True, use_container_width=True)

                    prev = st.selectbox(
                        "🔍 Preview file",
                        ["— select —"] + [f"{r['Format']} — {r['File']}"
                                          for r in files],
                        key="ws_prev_sel_2"
                    )
                    if prev != "— select —":
                        idx   = [f"{r['Format']} — {r['File']}"
                                 for r in files].index(prev)
                        fname = files[idx]["File"]
                        try:
                            from dataview.file_catalog import page_file_workbench as _pwb
                            _pwb.render_workbench(
                                file_path=fname,
                                key=f"ws_prev_{idx}",
                                show_edit=False,
                            )
                        except Exception as e:
                            st.error(f"Preview: {e}")

                    st.divider()
                    dest = st.text_input("Copy files to folder",
                                          key="ws_dest_2",
                                          placeholder=r"e.g. C:\Downloads")
                    if st.button("📋 Copy all files for this well",
                                  key="ws_copy_2", type="primary",
                                  disabled=not dest.strip()):
                        result = _copy_files(
                            [f["File"] for f in files], dest.strip()
                        )
                        if result["errors"] == 0:
                            st.success(f"✅ {result['copied']} copied")
                        else:
                            st.warning(f"{result['copied']} copied · "
                                       f"{result['errors']} error(s)")
                else:
                    st.info(f"No cataloged files found for uwi `{sel_well}`.")
            except Exception as e:
                st.error(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Seismic search — dataview.dv_seis_set / SEIS_FILE_CATALOG with preview
# ─────────────────────────────────────────────────────────────────────────────

def _render_seis_search(engine):
    """
    Search seismic files across three scenarios:
    1. Cataloged + DB matched  — SEIS_FILE_CATALOG with SEIS_SET match
    2. Cataloged + unmatched     — cataloged but no matching SEIS_SET
    3. Inventory only            — in GLOBAL_FILE_CATALOG, not yet cataloged

    Also parses filenames for uwi, survey name and line name candidates.
    Supports multi-file catalog grid for batch cataloging.
    """
    import pandas as pd
    import re
    from pathlib import Path
    from sqlalchemy import text

    st.markdown("#### 🌊 Seismic File Search")
    st.caption(
        "Search cataloged seismic files and inventory. "
        "Filename patterns are parsed for survey name, line name and uwi. "
        "Select files and catalog them in bulk."
    )

    # ── Filters ───────────────────────────────────────────────────────────────
    c1,c2,c3,c4 = st.columns(4)
    q_sv   = c1.text_input("Survey / file name", key="ss_sv_1",
                             placeholder="e.g. CENTRAL_AUSTRALIA")
    q_fmt  = c2.selectbox("Format", ["All","SEGY","P190"], key="ss_fmt_1")
    q_scope = c3.selectbox("Show",
                            ["All files","Matched only",
                             "Unmatched","Inventory only"],
                            key="ss_scope")
    max_r  = c4.number_input("Max results", 10, 5000, 200, key="ss_max_1")
    search = st.button("🔍 Search", type="primary", key="ss_btn_1")

    if search or "ss_results" in st.session_state:
        if search:
            try:
                from dataview.file_catalog.seis_filename_parser import parse_seis_filename
            except ImportError:
                # Inline fallback if module not deployed yet
                _uwi_RE  = re.compile(r'\b(\d{10,})\b')
                _LINE_RE = re.compile(
                    r'(?i)\b((?:LINE|SL|XL|IL|CDP|INLINE|XLINE|SHOT)[-_]?\d+)\b')
                _SPLIT_RE = re.compile(r'[_\-\.\s]+')

                def parse_seis_filename(fn):
                    stem = Path(fn).stem
                    uwi  = (m := _uwi_RE.search(stem)) and m.group(1) or ""
                    line = (m := _LINE_RE.search(stem)) and m.group(1).upper() or ""
                    s    = _uwi_RE.sub("", _LINE_RE.sub("", stem))
                    words = [t.upper() for t in _SPLIT_RE.split(s)
                             if t and not t.isdigit() and len(t) >= 2]
                    sv   = "_".join(words)
                    return {"uwi": uwi, "survey_name": sv, "line_name": line}

            rows_all = []

            # ── Cataloged files ───────────────────────────────────────────────
            try:
                fmt_clause = ""
                if q_fmt == "SEGY":
                    fmt_clause = "AND s.FILE_FORMAT IN ('SEGY','SEG-Y')"
                elif q_fmt == "P190":
                    fmt_clause = "AND s.FILE_FORMAT = 'P190'"

                sv_clause  = ""
                sv_params  = {}
                if q_sv.strip():
                    sv_clause = "AND (s.SURVEY_NAME LIKE :sv OR s.FILE_NAME LIKE :sv)"
                    sv_params["sv"] = f"%{q_sv.strip()}%"

                with engine.connect() as con:
                    r = con.execute(text(f"""
                        SELECT TOP {int(max_r)}
                            s.FILE_FORMAT,
                            s.FILE_NAME,
                            s.SURVEY_NAME        AS CAT_SURVEY,
                            s.FILE_SIZE_KB,
                            s.CATALOG_DATE,
                            ss.SEIS_SET_ID,
                            ss.SEIS_SET_NAME      AS PPDM_SURVEY,
                            CASE WHEN ss.SEIS_SET_ID IS NOT NULL
                                 THEN '✅ Matched'
                                 WHEN s.SURVEY_NAME IS NOT NULL
                                 THEN '⚠️ Unmatched'
                                 ELSE '❓ No survey'
                            END                  AS MATCH_STATUS,
                            s.FILE_NAME          AS FULL_PATH
                        FROM las_catalog.SEIS_FILE_CATALOG s
                        LEFT JOIN dataview.dv_seis_set ss
                            ON ss.SEIS_SET_NAME = s.SURVEY_NAME
                               OR ss.SEIS_SET_ID = s.SURVEY_NAME
                        WHERE 1=1 {fmt_clause} {sv_clause}
                        ORDER BY s.CATALOG_DATE DESC
                    """), sv_params).fetchall()
                rows_all += [list(row) + ["cataloged"] for row in r]
            except Exception:
                pass

            # ── Inventory-only files ──────────────────────────────────────────
            try:
                inv_where  = [
                    "CATALOG_STATUS NOT IN ('CATALOGED','SKIPPED')",
                    "FILE_TYPE_GROUP='Seismic'"
                ]
                inv_params = {}
                if q_fmt == "SEGY":
                    inv_where.append("FILE_EXT IN ('.segy','.sgy','.seg')")
                elif q_fmt == "P190":
                    inv_where.append("FILE_EXT IN ('.p190','.p90','.p1')")
                if q_sv.strip():
                    inv_where.append("FILE_NAME LIKE :sv")
                    inv_params["sv"] = f"%{q_sv.strip()}%"

                with engine.connect() as con:
                    r = con.execute(text(f"""
                        SELECT TOP {int(max_r)}
                            UPPER(REPLACE(FILE_EXT,'.','')) AS FILE_FORMAT,
                            FILE_NAME,
                            NULL AS CAT_SURVEY,
                            FILE_SIZE_KB,
                            SCAN_DATE AS CATALOG_DATE,
                            NULL AS SEIS_SET_ID,
                            NULL AS PPDM_SURVEY,
                            '📂 Not cataloged' AS MATCH_STATUS,
                            FILE_PATH AS FULL_PATH
                        FROM file_catalog.GLOBAL_FILE_CATALOG
                        WHERE {' AND '.join(inv_where)}
                        ORDER BY SCAN_DATE DESC
                    """), inv_params).fetchall()
                rows_all += [list(row) + ["inventory"] for row in r]
            except Exception:
                pass

            if rows_all:
                df = pd.DataFrame(rows_all, columns=[
                    "Format","File Name","Catalog Survey",
                    "Size KB","Date","SEIS_SET_ID","DB Survey",
                    "Status","Full Path","Source"
                ])
                df["Size MB"] = (df["Size KB"].fillna(0)/1024).round(2)
                df = df.drop(columns=["Size KB"])

                # Parse filenames
                parsed = df["File Name"].apply(
                    lambda fn: pd.Series(parse_seis_filename(str(fn)))
                )
                df["Detected uwi"]    = parsed["uwi"]
                df["Detected Survey"] = parsed["survey_name"]
                df["Detected Line"]   = parsed["line_name"]

                # Apply scope filter
                if q_scope == "Matched only":
                    df = df[df["Status"] == "✅ Matched"]
                elif q_scope == "Unmatched":
                    df = df[df["Status"].isin(["⚠️ Unmatched","❓ No survey"])]
                elif q_scope == "Inventory only":
                    df = df[df["Status"] == "📂 Not cataloged"]
            else:
                df = pd.DataFrame()

            st.session_state["ss_results"] = df

        else:
            df = st.session_state.get("ss_results", pd.DataFrame())

        if df.empty or "Status" not in df.columns:
            st.info("No seismic files found.")
            return

        # ── Summary metrics ───────────────────────────────────────────────────
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Total",           len(df))
        m2.metric("✅ DB matched",  len(df[df["Status"]=="✅ Matched"]))
        m3.metric("⚠️ Unmatched",     len(df[df["Status"].isin(
                                           ["⚠️ Unmatched","❓ No survey"])]))
        m4.metric("📂 Not cataloged", len(df[df["Status"]=="📂 Not cataloged"]))

        # ── Results table ─────────────────────────────────────────────────────
        display = df[["Status","Format","File Name","Catalog Survey",
                      "DB Survey","Detected Survey","Detected Line",
                      "Detected uwi","Size MB","Date"]].copy()
        st.dataframe(display, hide_index=True, use_container_width=True,
                     column_config={
                         "Status":  st.column_config.TextColumn(width="small"),
                         "Size MB": st.column_config.NumberColumn(
                             format="%.2f", width="small"),
                     })

        st.download_button("⬇ Export CSV",
                           data=df.to_csv(index=False),
                           file_name="seis_file_search.csv",
                           mime="text/csv", key="ss_dl_1")

        # ── File preview ──────────────────────────────────────────────────────
        st.divider()
        if "Full Path" in df.columns:
            prev = st.selectbox(
                "🔍 Preview file",
                ["— select —"] + df["File Name"].tolist(),
                key="ss_prev_sel_1"
            )
            if prev != "— select —":
                row = df[df["File Name"] == prev].iloc[0]
                fp  = str(row.get("Full Path","")).strip()
                if fp and fp not in ("None","nan",""):
                    try:
                        from dataview.file_catalog import page_file_workbench as _pwb
                        _pwb.render_workbench(
                            file_path=fp,
                            key=f"ss_prev_{prev[:20]}",
                            show_edit=False,
                        )
                    except Exception as e:
                        st.error(f"Preview: {e}")

        # ── Multi-file catalog grid ───────────────────────────────────────────
        st.divider()
        st.markdown("#### 📥 Catalog Selected Files")
        st.caption(
            "Select files to catalog. Edit survey name, line name and uwi "
            "inline before cataloging. One repository applies to the whole batch."
        )

        # Repository selector
        try:
            from sqlalchemy import text as _t
            with engine.connect() as con:
                repos = con.execute(_t(
                    "SELECT REPOSITORY_ID, REPOSITORY_NAME, BASE_PATH "
                    "FROM [las_catalog].[WL_REPOSITORY] ORDER BY REPOSITORY_NAME"
                )).fetchall()
            repo_opts = {"(none)": ""} | {
                f"{r[1]} ({r[2]})": r[0] for r in repos
            }
        except Exception:
            repo_opts = {"(none)": ""}

        c_repo, c_seed = st.columns([3,1])
        repo_label = c_repo.selectbox("Repository for batch",
                                       list(repo_opts.keys()),
                                       key="ss_cat_repo")
        repo_id    = repo_opts[repo_label]
        seed_ppdm  = c_seed.checkbox("Seed DB", value=True,
                                      key="ss_cat_seed")

        # Build editable catalog grid
        cat_df = df[["File Name","Format",
                      "Detected Survey","Detected Line","Detected uwi",
                      "Full Path"]].copy()
        cat_df.insert(0, "☑ Catalog", False)
        cat_df["Survey Name (edit)"] = cat_df["Detected Survey"]
        cat_df["Line Name (edit)"]   = cat_df["Detected Line"]
        cat_df["uwi Override"]       = cat_df["Detected uwi"]
        cat_df["Override / Notes"]   = ""

        display_cat = cat_df[[
            "☑ Catalog","Format","File Name",
            "Survey Name (edit)","Line Name (edit)",
            "uwi Override","Override / Notes"
        ]].copy()

        edited = st.data_editor(
            display_cat,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key="ss_cat_grid",
            column_config={
                "☑ Catalog": st.column_config.CheckboxColumn(
                    "Catalog", width="small"),
                "Format":    st.column_config.TextColumn(width="small"),
                "File Name": st.column_config.TextColumn("File"),
                "Survey Name (edit)": st.column_config.TextColumn(
                    "Survey Name", help="Edit before cataloging"),
                "Line Name (edit)": st.column_config.TextColumn(
                    "Line Name", help="Edit before cataloging"),
                "uwi Override": st.column_config.TextColumn(
                    "uwi", help="Only for VSP/checkshot SEG-Y"),
                "Override / Notes": st.column_config.TextColumn(
                    "Notes", help="Optional notes"),
            }
        )

        sel = edited[edited["☑ Catalog"] == True]
        n_sel = len(sel)

        ca, cb = st.columns([3,1])
        ca.caption(f"**{n_sel}** file(s) selected for cataloging")

        if cb.button(f"📥 Catalog {n_sel} file(s)", type="primary",
                      key="ss_cat_btn",
                      disabled=n_sel == 0 or not repo_id):
            if not repo_id:
                st.error("Select a repository first.")
            else:
                results = []
                prog = st.progress(0, text="Cataloging…")
                for i, (_, row) in enumerate(sel.iterrows()):
                    prog.progress((i+1)/n_sel,
                                  text=f"Cataloging {row['File Name']}…")
                    fp     = str(cat_df.loc[
                        cat_df["File Name"]==row["File Name"],
                        "Full Path"].iloc[0]).strip()
                    fmt    = str(row["Format"]).upper()
                    sv     = str(row["Survey Name (edit)"]).strip()
                    line   = str(row["Line Name (edit)"]).strip()
                    uwi    = str(row["uwi Override"]).strip()
                    result = {"File": row["File Name"], "Status": ""}
                    try:
                        if fmt in ("SEGY","SEG-Y"):
                            from dataview.file_catalog.segy_catalog import catalog_segy_file
                            r = catalog_segy_file(
                                engine, fp, repo_id,
                                survey_name=sv or None,
                                seed_ppdm=seed_ppdm
                            )
                        elif fmt == "P190":
                            from dataview.file_catalog.p190_catalog import catalog_p190_file
                            r = catalog_p190_file(
                                engine, fp, repo_id,
                                survey_name=sv or None,
                                seed_ppdm=seed_ppdm
                            )
                        else:
                            r = {"ok": False, "error": f"Unknown format: {fmt}"}

                        if r.get("ok"):
                            result["Status"] = f"✅ {r.get('action','cataloged')}"
                            # Store headers
                            try:
                                from dataview.file_catalog.file_header_store import (
                                    store_segy_headers, store_p190_headers,
                                    ensure_header_tables
                                )
                                ensure_header_tables(engine)
                                if fmt in ("SEGY","SEG-Y"):
                                    store_segy_headers(engine, fp,
                                                       survey_name=sv or None)
                                else:
                                    store_p190_headers(engine, fp,
                                                       survey_name=sv or None)
                            except Exception:
                                pass
                        else:
                            result["Status"] = f"❌ {r.get('error','failed')}"
                    except Exception as e:
                        result["Status"] = f"❌ {e}"
                    results.append(result)

                prog.empty()
                res_df = pd.DataFrame(results)
                ok  = len(res_df[res_df["Status"].str.startswith("✅")])
                err = len(res_df[res_df["Status"].str.startswith("❌")])
                if err == 0:
                    st.success(f"✅ {ok} file(s) cataloged successfully.")
                else:
                    st.warning(f"{ok} cataloged · {err} error(s)")
                with st.expander("Results", expanded=err > 0):
                    st.dataframe(res_df, hide_index=True,
                                 use_container_width=True)
                # Clear results to force fresh search
                st.session_state.pop("ss_results", None)
                st.rerun()

        # ── Copy to folder ────────────────────────────────────────────────────
        st.divider()
        st.markdown("#### 📂 Copy to folder")
        dest = st.text_input("Destination", key="ss_dest_1",
                              placeholder=r"e.g. C:\Downloads\Seismic")
        copy_sel = st.multiselect(
            "Files to copy",
            df["File Name"].tolist(),
            key="ss_copy_sel"
        )
        if st.button(f"📋 Copy {len(copy_sel)} file(s)", key="ss_copy_btn",
                      type="primary",
                      disabled=not (copy_sel and dest.strip())):
            fps = []
            for fn in copy_sel:
                fp = str(df[df["File Name"]==fn]["Full Path"].iloc[0]).strip()
                if fp and fp not in ("None","nan",""):
                    fps.append(fp)
            result = _copy_files(fps, dest.strip())
            if result["errors"] == 0:
                st.success(f"✅ {result['copied']} copied")
            else:
                st.warning(f"{result['copied']} copied · "
                           f"{result['errors']} error(s)")

    c1,c2,c3 = st.columns(3)
    q_sv  = c1.text_input("Survey name", key="ss_sv_2",
                            placeholder="e.g. CENTRAL_AUSTRALIA")
    q_fmt = c2.selectbox("Format", ["All","SEGY","SEG-Y","P190"],
                          key="ss_fmt_2")
    max_r = c3.number_input("Max results", 10, 2000, 100, key="ss_max_2")
    search = st.button("🔍 Search", type="primary", key="ss_btn_2")

    if search or "ss_results" in st.session_state:
        if search:
            try:
                if "Catalog" in mode:
                    where  = ["1=1"]
                    params = {}
                    if q_sv.strip():
                        where.append("SURVEY_NAME LIKE :sv")
                        params["sv"] = f"%{q_sv.strip()}%"
                    if q_fmt != "All":
                        where.append("FILE_FORMAT=:fmt")
                        params["fmt"] = q_fmt
                    with engine.connect() as con:
                        rows = con.execute(text(
                            f"SELECT TOP {int(max_r)} "
                            f"FILE_FORMAT, FILE_NAME, SURVEY_NAME, "
                            f"FILE_SIZE_KB, CATALOG_DATE "
                            f"FROM las_catalog.SEIS_FILE_CATALOG "
                            f"WHERE {' AND '.join(where)} "
                            f"ORDER BY CATALOG_DATE DESC"
                        ), params).fetchall()
                    df = pd.DataFrame(rows, columns=[
                        "Format","File","Survey","Size KB","Cataloged"
                    ])
                    df["Size MB"] = (df["Size KB"].fillna(0)/1024).round(2)
                    df = df.drop(columns=["Size KB"])
                    st.session_state["ss_results"] = df
                    st.session_state["ss_mode_used"] = "catalog"
                else:
                    where  = ["1=1"]
                    params = {}
                    if q_sv.strip():
                        where.append(
                            "(SEIS_SET_NAME LIKE :sv OR SEIS_SET_ID LIKE :sv)"
                        )
                        params["sv"] = f"%{q_sv.strip()}%"
                    with engine.connect() as con:
                        rows = con.execute(text(
                            f"SELECT TOP {int(max_r)} "
                            f"SEIS_SET_ID, SEIS_SET_NAME, SEIS_SET_TYPE, "
                            f"SURVEY_TYPE, COUNTRY_NAME, OPERATOR "
                            f"FROM dataview.dv_seis_set "
                            f"WHERE {' AND '.join(where)} "
                            f"ORDER BY SEIS_SET_NAME"
                        ), params).fetchall()
                    df = pd.DataFrame(rows, columns=[
                        "Survey ID","Survey Name","Set Type",
                        "Survey Type","Country","Operator"
                    ])
                    st.session_state["ss_results"] = df
                    st.session_state["ss_mode_used"] = "ppdm"
            except Exception as e:
                st.error(str(e)); return
        else:
            df = st.session_state.get("ss_results", pd.DataFrame())

        if df.empty:
            st.info("No results found.")
            return

        st.caption(f"**{len(df):,}** result(s)")
        st.dataframe(df, hide_index=True, use_container_width=True)

        st.download_button("⬇ Export CSV",
                           data=df.to_csv(index=False),
                           file_name="seis_search.csv",
                           mime="text/csv", key="ss_dl_2")

        # File preview — catalog mode only
        if st.session_state.get("ss_mode_used") == "catalog" and "File" in df.columns:
            st.divider()
            prev = st.selectbox(
                "🔍 Preview file",
                ["— select —"] + df["File"].tolist(),
                key="ss_prev_sel_2"
            )
            if prev != "— select —":
                row = df[df["File"] == prev].iloc[0]
                fp  = str(row.get("File","")).strip()
                if fp:
                    try:
                        from dataview.file_catalog import page_file_workbench as _pwb
                        _pwb.render_workbench(
                            file_path=fp,
                            key=f"ss_prev_{prev[:20]}",
                            show_edit=False,
                        )
                    except Exception as e:
                        st.error(f"Preview: {e}")

            st.divider()
            dest = st.text_input("Copy selected files to folder",
                                  key="ss_dest_2",
                                  placeholder=r"e.g. C:\Downloads\Seismic")
            if st.button("📋 Copy all results", key="ss_copy",
                          type="primary", disabled=not dest.strip()):
                fps    = df["File"].tolist()
                result = _copy_files(fps, dest.strip())
                if result["errors"] == 0:
                    st.success(f"✅ {result['copied']} copied")
                else:
                    st.warning(f"{result['copied']} copied · "
                               f"{result['errors']} error(s)")

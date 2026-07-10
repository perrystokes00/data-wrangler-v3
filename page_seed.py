"""page_seed.py — Reference Table Seeding via CSV Folder."""
import pathlib
import streamlit as st
from ui_helpers import shdr


def render(S):
    shdr("🌱 Seed Reference Tables",
         "Load CSV files from a folder directly into PPDM reference tables. "
         "Table name is inferred from the filename.")

    _DEFAULT_SEED_DIR = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\claude_ppdm_oracle_old\seed_catalog"

    # ── Folder input ──────────────────────────────────────────────────
    _csv_dir = st.text_input(
        "Seed folder",
        value=getattr(S, "seed_csv_dir", _DEFAULT_SEED_DIR),
        key="seed_csv_dir_input",
        help="Folder containing seed CSV files — one file per reference table",
    )
    if _csv_dir != getattr(S, "seed_csv_dir", ""):
        S.seed_csv_dir = _csv_dir

    # ── Process pending jobs FIRST (outside folder scan) ─────────────
    if st.session_state.get("_seed_pending"):
        _pending = st.session_state.pop("_seed_pending")
        from page_bulk import _run_seed_job
        _csv_results = []
        _prog    = st.progress(0)
        _status  = st.empty()
        for _i, _item in enumerate(_pending):
            _fname = _item["fname"]
            _fpath = _item["fpath"]
            _table = _item["table"]
            _pk    = _item["pk"]
            _nrows = _item["nrows"]
            _status.text(f"[{_i+1}/{len(_pending)}] {_fname} → {_table}")
            if S.demo:
                _csv_results.append({
                    "File": _fname, "Table": _table,
                    "Inserted": _nrows, "Skipped": 0,
                    "OK": "Y", "Message": f"[Demo] Would insert {_nrows} rows",
                })
            else:
                _job = {
                    "file_path":    _fpath,
                    "target_table": _table,
                    "mode":         "insert",
                    "seed_mode":    True,
                    "pk_columns":   _pk,
                }
                try:
                    _res = _run_seed_job(_job, S.engine)
                    _csv_results.append({
                        "File":     _fname,
                        "Table":    _table,
                        "Inserted": _res.get("rows_inserted", 0),
                        "Skipped":  _res.get("rows_skipped",  0),
                        "OK":       "Y" if _res.get("ok") else "N",
                        "Message":  _res.get("message", ""),
                    })
                except Exception as _ex:
                    _csv_results.append({
                        "File": _fname, "Table": _table,
                        "Inserted": 0, "Skipped": 0,
                        "OK": "N", "Message": str(_ex)[:200],
                    })
            _prog.progress((_i + 1) / len(_pending))
        _status.empty()
        _prog.empty()
        S.seed_csv_results = _csv_results
        st.rerun()

    # ── Scan folder ───────────────────────────────────────────────────
    _COMPOSITE_PKS = {
        "R_WELL_STATUS":      ["STATUS_TYPE", "STATUS"],
        "R_WELLBORE_SYMBOLS": ["FLUID_TYPE",  "WELLBORE_STATUS"],
    }

    # FK dependency order — parents load before children
    _LOAD_ORDER = [
        "R_WELL_STATUS_TYPE",
        "R_WELL_STATUS",
        "R_WELL_CLASS",
        "R_WATER_DATUM",
        "R_LOCATION_TYPE",
        "R_SOURCE",
        "R_LEGAL_SURVEY_TYPE",
        "R_PPDM_ROW_QUALITY",
        "R_WELL_DATUM_TYPE",
        "R_WELL_LEVEL_TYPE",
        "R_WELL_PROFILE_TYPE",
        "R_WELL_SF_PLATFORM",
        "R_SOURCE_DOCUMENT",
        "PPDM_UNIT_OF_MEASURE",
    ]

    def _infer_table(stem):
        s = stem.lower()
        for prefix in ("seed_dbo_", "seed_", "dbo_"):
            if s.startswith(prefix):
                s = s[len(prefix):]
                break
        return s.upper()

    def _infer_pk(table, cols):
        if table in _COMPOSITE_PKS:
            return _COMPOSITE_PKS[table]
        for c in cols:
            if c.upper().endswith("_TYPE") or c.upper().endswith("_ID"):
                return [c]
        return [cols[0]] if cols else []

    _csv_path = pathlib.Path(_csv_dir) if _csv_dir else None
    if _csv_path and _csv_path.exists():
        def _sort_key(f):
            try:
                return _LOAD_ORDER.index(_infer_table(f.stem))
            except ValueError:
                return len(_LOAD_ORDER)
        _csv_files = sorted(_csv_path.glob("*.csv"), key=_sort_key)
    else:
        _csv_files = []

    if not _csv_dir:
        st.info("Enter a folder path above.")
        return
    if not _csv_path.exists():
        st.warning(f"Folder not found: `{_csv_dir}`")
        return
    if not _csv_files:
        st.warning("No CSV files found in that folder.")
        return

    import csv as _csv_mod
    import pandas as _pd

    _preview_rows = []
    _file_meta    = {}
    for _cf in _csv_files:
        _tbl = _infer_table(_cf.stem)
        try:
            with open(_cf, newline="", encoding="utf-8-sig") as _fh:
                _rows = list(_csv_mod.DictReader(_fh))
            _cols = list(_rows[0].keys()) if _rows else []
            _pk   = _infer_pk(_tbl, _cols)
            _file_meta[_cf.name] = {
                "fpath": str(_cf), "table": _tbl,
                "pk": _pk, "nrows": len(_rows),
            }
            _preview_rows.append({
                "Load": True, "File": _cf.name,
                "Table": _tbl, "PK": ", ".join(_pk), "Rows": len(_rows),
            })
        except Exception as _e:
            _preview_rows.append({
                "Load": False, "File": _cf.name,
                "Table": _tbl, "PK": "ERROR", "Rows": 0,
            })

    _edited = st.data_editor(
        _pd.DataFrame(_preview_rows),
        column_config={
            "Load":  st.column_config.CheckboxColumn("Load",  width="small"),
            "File":  st.column_config.TextColumn("File",  disabled=True, width="large"),
            "Table": st.column_config.TextColumn("Table", disabled=True, width="medium"),
            "PK":    st.column_config.TextColumn("PK",    disabled=True, width="medium"),
            "Rows":  st.column_config.NumberColumn("Rows", disabled=True, width="small"),
        },
        hide_index=True, use_container_width=True, key="seed_csv_grid",
    )

    _selected = [
        _preview_rows[i]["File"]
        for i, row in enumerate(_edited.itertuples(index=False))
        if bool(row[0])
    ]
    st.caption(f"{len(_selected)} of {len(_csv_files)} file(s) selected")

    if not S.engine and not S.demo:
        st.warning("Connect to the database (Stage 1) before loading.")
    elif _selected:
        if st.button(f"🌱 Load {len(_selected)} CSV file(s)",
                     type="primary", use_container_width=True,
                     key="seed_csv_load_btn"):
            st.session_state["_seed_pending"] = [
                {"fname": fn, "fpath": _file_meta[fn]["fpath"],
                 "table": _file_meta[fn]["table"], "pk": _file_meta[fn]["pk"],
                 "nrows": _file_meta[fn]["nrows"]}
                for fn in _selected
            ]
            st.rerun()

    # ── Results ───────────────────────────────────────────────────────
    if getattr(S, "seed_csv_results", None):
        _res   = S.seed_csv_results
        _n_ok  = sum(1 for r in _res if r["OK"] == "Y")
        _n_ins = sum(r["Inserted"] for r in _res)
        _n_err = len(_res) - _n_ok
        st.markdown("---")
        st.markdown(
            f"**{_n_ok}** tables OK &nbsp;·&nbsp; "
            f"**{_n_ins}** rows inserted &nbsp;·&nbsp; "
            f"**{_n_err}** errors"
        )
        st.dataframe(
            _pd.DataFrame(_res),
            use_container_width=True, hide_index=True,
            column_config={
                "OK":      st.column_config.TextColumn(width="small"),
                "File":    st.column_config.TextColumn(width="large"),
                "Table":   st.column_config.TextColumn(width="medium"),
                "Message": st.column_config.TextColumn(width="large"),
            }
        )
        if st.button("Clear results", key="clear_csv_results"):
            S.seed_csv_results = None
            st.rerun()

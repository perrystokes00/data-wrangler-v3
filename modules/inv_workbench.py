"""
modules/inv_workbench.py
========================
Viewer and cataloger for the My Work tab.
Dispatches to the right viewer/cataloger based on file extension.
Marks file CATALOGED or SKIPPED in GLOBAL_FILE_CATALOG.
"""

import streamlit as st
import page_file_workbench as _wb
import pandas as pd
from pathlib import Path
from sqlalchemy import text

LAS_EXTS  = {".las"}
DLIS_EXTS = {".dlis", ".dlf", ".dis"}
LIS_EXTS  = {".lis"}
SEGY_EXTS = {".segy", ".sgy", ".seg"}
P190_EXTS = {".p190", ".p1", ".p90", ".pa90"}
ALL_VIEWABLE = LAS_EXTS | DLIS_EXTS | LIS_EXTS | SEGY_EXTS | P190_EXTS


def _ext(fp): return Path(fp).suffix.lower()

def _gfc(dialect):
    if dialect == "oracle":    return "FILE_CATALOG_GLOBAL_FILE_CATALOG"
    if dialect == "snowflake": return '"FILE_CATALOG"."GLOBAL_FILE_CATALOG"'
    return "file_catalog.GLOBAL_FILE_CATALOG"

def _gff(dialect):
    if dialect == "oracle":    return "FILE_CATALOG_INVENTORY_GROUP_FILE"
    if dialect == "snowflake": return '"FILE_CATALOG"."INVENTORY_GROUP_FILE"'
    return "file_catalog.INVENTORY_GROUP_FILE"

def _now(dialect):
    return {"mssql":"GETDATE()","oracle":"SYSTIMESTAMP",
            "snowflake":"CURRENT_TIMESTAMP()"}.get(dialect,"GETDATE()")


def mark_cataloged(engine, dialect, inventory_id, group_file_id=None):
    with engine.begin() as conn:
        conn.execute(text(
            f"UPDATE {_gfc(dialect)} SET CATALOG_STATUS='CATALOGED' "
            f"WHERE INVENTORY_ID=:iid"
        ), {"iid": inventory_id})
        if group_file_id:
            try:
                conn.execute(text(
                    f"UPDATE {_gff(dialect)} SET CATALOGED_IND='Y', "
                    f"CATALOGED_DATE={_now(dialect)} WHERE GROUP_FILE_ID=:gfid"
                ), {"gfid": group_file_id})
            except Exception:
                pass  # column may not exist yet — handled by DDL migration


def mark_skipped(engine, dialect, inventory_id, group_file_id, reason):
    with engine.begin() as conn:
        conn.execute(text(
            f"UPDATE {_gfc(dialect)} SET CATALOG_STATUS='SKIPPED' "
            f"WHERE INVENTORY_ID=:iid"
        ), {"iid": inventory_id})
        if group_file_id:
            try:
                conn.execute(text(
                    f"UPDATE {_gff(dialect)} SET SKIPPED_IND='Y', "
                    f"SKIP_REASON=:reason WHERE GROUP_FILE_ID=:gfid"
                ), {"reason": reason, "gfid": group_file_id})
            except Exception:
                pass


def _get_repos(engine):
    try:
        from modules.las_catalog import list_repositories
        repos = list_repositories(engine)
        if not repos.empty:
            return {"(none — assign later)": ""} | {
                f"{r['REPOSITORY_NAME']} ({r['BASE_PATH']})": r["REPOSITORY_ID"]
                for _, r in repos.iterrows()
            }
    except Exception:
        pass
    return {"(none)": ""}


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

# ── Card CSS injected once per session ───────────────────────────────────────
_CARD_CSS = """
<style>
.wb-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px 24px 18px;
    margin-bottom: 14px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}
.wb-card-title {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #64748b;
    margin-bottom: 12px;
    border-bottom: 1px solid #f1f5f9;
    padding-bottom: 7px;
}
</style>
"""

def _card(title: str = ""):
    """Inject card CSS and render a card header."""
    st.markdown(_CARD_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="wb-card"><div class="wb-card-title">{title}</div>',
        unsafe_allow_html=True
    )

def _card_end():
    st.markdown('</div>', unsafe_allow_html=True)


def render_file_workbench(engine, dialect, inventory_id, file_path,
                           catalog_status, group_file_id=None, context_key=""):
    ext  = _ext(file_path)
    ukey = f"{context_key}_{inventory_id[:10]}"

    if catalog_status == "CATALOGED":
        st.success("✅ Already cataloged.")
        return
    if catalog_status == "SKIPPED":
        st.warning("⏭ Skipped.")
        return

    if not Path(file_path).exists():
        st.warning(f"⚠️ File not found at catalogued path:\n`{file_path}`")

        tab_update, tab_skip = st.tabs(["📂 Update Path", "⏭ Skip"])

        with tab_update:
            st.caption("If the file has moved or been renamed, enter the new path below.")
            new_path = st.text_input("Current file path", key=f"wb_new_path_{ukey}",
                                      placeholder=r"e.g. D:\Seismic\NewFolder\file.sgy")
            if st.button("✅ Update & Continue", key=f"wb_update_path_{ukey}",
                         type="primary", use_container_width=True):
                if not new_path.strip():
                    st.error("Enter the new file path.")
                elif not Path(new_path.strip()).exists():
                    st.error(f"File not found at: `{new_path.strip()}`")
                else:
                    try:
                        from sqlalchemy import text as _upd_text
                        with engine.begin() as con:
                            con.execute(_upd_text(
                                "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                                "SET FILE_PATH=:p, FILE_NAME=:n, ROW_CHANGED_DATE=" + _now(dialect) + " "
                                "WHERE INVENTORY_ID=:iid"
                            ), {"p": new_path.strip(),
                                "n": Path(new_path.strip()).name,
                                "iid": inventory_id})
                        st.success("✅ Path updated — reloading…")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

        with tab_skip:
            _render_skip(engine, dialect, inventory_id, group_file_id,
                         ukey, pre_reason="File not found on disk")
        return

    # ── Card 0: File Summary + Chart ─────────────────────────────────────────
    _card("📋 File Summary")
    try:
        from modules.file_summarizer import summarize as _fs
        _s = _fs(file_path)
        _c1, _c2, _c3 = st.columns(3)
        _c1.markdown(f"**Format:** {_s.get('format','?')}")
        _c2.markdown(f"**Well:** {_s.get('well_name') or '—'}")
        _c3.markdown(f"**UWI:** {_s.get('uwi') or '—'}")
        if _s.get("description"):
            st.caption(_s["description"])
        if _s.get("ppdm_hints"):
            st.success(f"**PPDM targets:** {' · '.join(_s['ppdm_hints'])}")
        for _w in _s.get("warnings", []):
            st.warning(_w)
        if _s.get("error"):
            st.error(_s["error"])

        # ── Charts per format ─────────────────────────────────────────────────
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            NAVY = "#1A2B4A"; GOLD = "#C8922A"
            _fmt = _s.get("format","")
            _kf  = _s.get("key_fields", {})

            # LAS — plot first 4 curves vs depth
            if _fmt == "LAS" and not _s.get("error"):
                try:
                    import lasio
                    _las = lasio.read(file_path, ignore_header_errors=True)
                    _depth = _las.index
                    _curves = [c for c in _las.curves
                               if c.mnemonic.upper() not in ("DEPT","DEPTH","MD")][:4]
                    if _curves and len(_depth) > 1:
                        _fig = make_subplots(rows=1, cols=len(_curves),
                            subplot_titles=[c.mnemonic for c in _curves],
                            shared_yaxes=True, horizontal_spacing=0.04)
                        _colors = [NAVY, GOLD, "#27AE60", "#C41E3A"]
                        for _i, _c in enumerate(_curves):
                            _vals = _las[_c.mnemonic]
                            import numpy as np
                            _mask = _vals != _las.well.get("NULL",
                                type('',(),{'value':-9999.25})()).value
                            _fig.add_trace(go.Scatter(
                                x=_vals[_mask], y=_depth[_mask],
                                mode='lines', line=dict(color=_colors[_i], width=1),
                                name=_c.mnemonic,
                                hovertemplate=f"{_c.mnemonic}: %{{x:.2f}}<br>Depth: %{{y:.0f}} ft<extra></extra>",
                            ), row=1, col=_i+1)
                        _fig.update_yaxes(autorange="reversed", title_text="Depth (ft)", col=1)
                        _fig.update_layout(height=350, margin=dict(l=10,r=10,t=30,b=10),
                            showlegend=False, paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)', font=dict(size=10))
                        _fig.update_xaxes(gridcolor='rgba(128,128,128,0.12)')
                        _fig.update_yaxes(gridcolor='rgba(128,128,128,0.12)')
                        st.plotly_chart(_fig, use_container_width=True)
                except Exception as _le:
                    st.caption(f"LAS plot unavailable: {_le}")

            # SEG-Y — show trace amplitude heatmap (first 100 traces)
            elif _fmt == "SEG-Y" and not _s.get("error"):
                try:
                    import segyio, numpy as np
                    with segyio.open(file_path, ignore_geometry=True) as _f:
                        _n = min(100, _f.tracecount)
                        _data = np.stack([_f.trace[i] for i in range(_n)])
                    _fig = go.Figure(go.Heatmap(
                        z=_data.T, colorscale='RdBu', zmid=0,
                        showscale=False,
                        hovertemplate="Trace: %{x}<br>Sample: %{y}<br>Amp: %{z:.1f}<extra></extra>",
                    ))
                    _fig.update_layout(
                        height=280, margin=dict(l=10,r=10,t=10,b=10),
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                        xaxis_title=f"Trace (first {_n})", yaxis_title="Sample",
                        font=dict(size=10),
                    )
                    st.plotly_chart(_fig, use_container_width=True)
                except Exception as _se:
                    st.caption(f"SEG-Y plot unavailable: {_se}")

            # Shapefile — scatter or outline map
            elif _fmt == "Shapefile" and not _s.get("error"):
                try:
                    import geopandas as gpd
                    _gdf = gpd.read_file(file_path).to_crs("EPSG:4326")
                    _gtype = _kf.get("geometry_type","")
                    if "Point" in _gtype:
                        _gdf["_lon"] = _gdf.geometry.x
                        _gdf["_lat"] = _gdf.geometry.y
                        _hcol = _kf.get("attributes",[None])[0]
                        _fig = go.Figure(go.Scattermap(
                            lon=_gdf["_lon"].tolist(), lat=_gdf["_lat"].tolist(),
                            mode='markers',
                            marker=dict(size=7, color=NAVY, opacity=0.8),
                            text=_gdf[_hcol].astype(str).tolist() if _hcol and _hcol in _gdf.columns else None,
                            hovertemplate="%{text}<extra></extra>" if _hcol else None,
                        ))
                        _cx = float(_gdf["_lon"].mean()); _cy = float(_gdf["_lat"].mean())
                        _fig.update_layout(
                            map=dict(style="open-street-map", center=dict(lon=_cx,lat=_cy), zoom=5),
                            height=300, margin=dict(l=0,r=0,t=0,b=0),
                            paper_bgcolor='rgba(0,0,0,0)',
                        )
                        st.plotly_chart(_fig, use_container_width=True)
                except Exception as _gme:
                    st.caption(f"Map preview unavailable: {_gme}")

        except ImportError:
            st.caption("Install plotly for visual previews")
        except Exception as _ce:
            st.caption(f"Chart unavailable: {_ce}")

    except Exception as _sum_err:
        st.caption(f"Summary unavailable: {_sum_err}")
    _card_end()

    # ── Card 1: Full file preview ─────────────────────────────────────────────
    _card("🔍 File Preview")
    try:
        import page_file_workbench as _pwb
        _pwb.render_workbench(file_path=file_path, fmt=None, key=ukey, show_edit=False)
    except Exception as _pwb_err:
        with st.expander("View decoded content", expanded=False):
            if ext in DLIS_EXTS:   _viewer_dlis(file_path, ukey)
            elif ext in LIS_EXTS:  _viewer_lis(file_path, ukey)
            elif ext in SEGY_EXTS: _viewer_segy(file_path, ukey)
            elif ext in P190_EXTS: _viewer_p190(file_path, ukey)
        st.caption(f"Full preview unavailable: {_pwb_err}")
    _card_end()

    # ── Card 2: Catalog ───────────────────────────────────────────────────────
    _card("📥 Catalog")
    if ext in LAS_EXTS:
        _cataloger_las(engine, dialect, inventory_id, file_path, group_file_id, ukey)
    elif ext in DLIS_EXTS:
        _cataloger_dlis(engine, dialect, inventory_id, file_path, group_file_id, ukey)
    elif ext in LIS_EXTS:
        _cataloger_lis(engine, dialect, inventory_id, file_path, group_file_id, ukey)
    elif ext in SEGY_EXTS:
        _cataloger_segy(engine, dialect, inventory_id, file_path, group_file_id, ukey)
    elif ext in P190_EXTS:
        _cataloger_p190(engine, dialect, inventory_id, file_path, group_file_id, ukey)
    else:
        if st.button("✅ Mark Cataloged", key=f"wb_manual_{ukey}"):
            mark_cataloged(engine, dialect, inventory_id, group_file_id)
            st.rerun()
    _card_end()

    # ── Card 3: Skip ──────────────────────────────────────────────────────────
    _card("⏭ Skip File")
    _render_skip(engine, dialect, inventory_id, group_file_id, ukey)
    _card_end()


SKIP_REASONS = [
    "— select a reason —",
    "Corrupt / unreadable file",
    "Duplicate file",
    "Wrong format",
    "Wrong well / no UWI match",
    "Empty file",
    "Out of scope",
    "Already in PPDM",
    "Other",
]

def _render_skip(engine, dialect, inventory_id, group_file_id,
                 ukey, pre_reason=""):
    # Pre-seed selectbox if a reason is provided (e.g. file not found)
    _sel_key = f"wb_skip_sel_{ukey}"
    if pre_reason and _sel_key not in st.session_state:
        match = next((r for r in SKIP_REASONS if r.lower() in pre_reason.lower()), "Other")
        st.session_state[_sel_key] = match

    selected = st.selectbox("Skip reason", SKIP_REASONS,
                            key=_sel_key)
    if selected == "Other":
        other = st.text_input("Specify reason",
                              key=f"wb_skip_other_{ukey}",
                              placeholder="Describe why this file is being skipped")
        reason = other.strip()
    elif selected == "— select a reason —":
        reason = ""
    else:
        reason = selected

    if st.button("⏭ Skip", key=f"wb_skip_{ukey}", type="secondary"):
        if not reason:
            st.error("Select or enter a reason before skipping.")
        else:
            mark_skipped(engine, dialect, inventory_id, group_file_id, reason)
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Viewers
# ─────────────────────────────────────────────────────────────────────────────

def _viewer_las(file_path, ukey):
    """Show raw LAS header text — delegates to shared workbench."""
    _wb._view_las_header(file_path)

def _viewer_dlis(file_path, ukey):
    """Decode DLIS binary and show human-readable text."""
    try:
        import warnings
        from dlisio import dlis
        lines = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with dlis.load(file_path) as lfs:
                for lf_idx, lf in enumerate(lfs):
                    lines.append(f"=== Logical File {lf_idx+1} ===")
                    for o in lf.origins:
                        lines.append(f"Origin: {o.name}")
                        for attr in ("well_name","field_name","company","country",
                                     "creation_time","producer_name","run_nr"):
                            v = getattr(o, attr, None)
                            if v:
                                lines.append(f"  {attr}: {v}")
                    ch_list = list(lf.channels)
                    lines.append(f"\nChannels ({len(ch_list)}):")
                    for ch in ch_list:
                        lines.append(
                            f"  {ch.name:<20s} unit={ch.units or '—':<8s} dim={ch.dimension}"
                        )
                    params = list(lf.parameters)
                    if params:
                        lines.append(f"\nParameters ({len(params)}):")
                        for p in params[:50]:
                            lines.append(f"  {p.name:<20s} = {p.values}")
        st.code("\n".join(lines), language=None)
    except Exception as e:
        st.error(f"DLIS viewer: {e}")

def _viewer_lis(file_path, ukey):
    """Decode LIS binary and show human-readable text."""
    try:
        import warnings
        from dlisio import lis
        lines = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with lis.load(file_path) as lfs:
                if not lfs:
                    st.warning("No logical files found in LIS file.")
                    return
                lf = lfs[0]
                try:
                    lines.append("=== Wellsite Data ===")
                    for rec in lf.wellsite_data():
                        for c in rec.components():
                            mnem = getattr(c, "mnemonic", "")
                            val  = getattr(c, "component", "")
                            if mnem:
                                lines.append(f"  {str(mnem):<12s} = {val}")
                except Exception:
                    lines.append("  (no wellsite data)")

                try:
                    specs = lf.data_format_specs()
                    if specs:
                        lines.append(f"\n=== Curves ({len(specs)} spec(s)) ===")
                        for spec in specs:
                            for ch in spec.entries:
                                mnem  = str(getattr(ch, "mnemonic", "?"))
                                units = str(getattr(ch, "units", "—"))
                                lines.append(f"  {mnem:<12s} unit={units:<8s}")
                except Exception:
                    lines.append("  (could not read curve specs)")

        if lines:
            st.code("\n".join(lines), language=None)
        else:
            st.info("No readable header data found in this LIS file.")
    except Exception as e:
        st.warning(f"⚠️ LIS binary decode failed: {e}")
        st.caption("This file may use an unsupported LIS variant. "
                   "Try opening it in a dedicated LIS viewer.")

def _viewer_segy(file_path, ukey):
    """Show decoded SEG-Y EBCDIC + binary header. Reads headers only — no trace scan."""
    try:
        import segyio
        with segyio.open(file_path, ignore_geometry=True, strict=False) as f:
            ebcdic  = f.text[0].decode("cp037", errors="replace")
            lines   = [ebcdic[i:i+80].rstrip() for i in range(0, len(ebcdic), 80)]
            bin_hdr = {str(k): int(v) for k,v in dict(f.bin).items() if int(v) != 0}
        st.code("\n".join(lines), language=None)
        with st.expander("Binary header fields"):
            st.json(bin_hdr)
    except Exception as segyio_err:
        # ── Fallback: read raw bytes and decode EBCDIC manually ──────────────
        # Works on any SEG-Y regardless of geometry or trace format
        try:
            with open(file_path, "rb") as f:
                raw = f.read(3600)   # textual header = first 3200 bytes
            text_hdr = raw[:3200]
            # Try EBCDIC (cp037) first, then ASCII
            try:
                ebcdic = text_hdr.decode("cp037", errors="replace")
            except Exception:
                ebcdic = text_hdr.decode("ascii", errors="replace")
            lines = [ebcdic[i:i+80].rstrip() for i in range(0, len(ebcdic), 80)]
            # Only show non-empty lines
            lines = [l for l in lines if l.strip()]
            st.caption(f"⚠️ segyio failed ({segyio_err}) — showing raw EBCDIC decode")
            st.code("\n".join(lines) if lines else "(empty header)", language=None)

            # Parse binary header fields (bytes 3200-3600)
            if len(raw) >= 3600:
                import struct
                bin_hdr_raw = raw[3200:3600]
                # Key binary header fields (byte offset, format, name)
                fields = [
                    (0,  ">i", "Job ID"),
                    (4,  ">i", "Line number"),
                    (8,  ">i", "Reel number"),
                    (12, ">h", "Traces per ensemble"),
                    (16, ">h", "Aux traces per ensemble"),
                    (20, ">h", "Sample interval (us)"),
                    (24, ">h", "Sample interval original (us)"),
                    (28, ">h", "Samples per trace"),
                    (30, ">h", "Samples per trace original"),
                    (32, ">h", "Data sample format code"),
                ]
                parsed = {}
                for offset, fmt, name in fields:
                    try:
                        sz   = struct.calcsize(fmt)
                        val  = struct.unpack(fmt, bin_hdr_raw[offset:offset+sz])[0]
                        if val != 0:
                            parsed[name] = val
                    except Exception:
                        pass
                if parsed:
                    with st.expander("Binary header fields"):
                        st.json(parsed)
        except Exception as e2:
            st.error(f"SEG-Y viewer failed: {e2}")

def _viewer_p190(file_path, ukey):
    """Show P190 raw text — H header records first, then all lines."""
    try:
        with open(file_path, "r", errors="replace") as f:
            lines = f.readlines()
        header = [l.rstrip() for l in lines if l.startswith("H")]
        body   = [l.rstrip() for l in lines[:500]]
        if header:
            st.markdown("**Header (H records):**")
            st.code("\n".join(header), language=None)
            with st.expander("All records (first 500 lines)"):
                st.code("\n".join(body), language=None)
        else:
            st.code("\n".join(body), language=None)
    except Exception as e:
        st.error(f"P190 viewer: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Catalogers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_well_names(engine) -> list[dict]:
    """Return [{uwi, well_name}] from PPDM WELL table."""
    try:
        from modules.las_loader import fetch_ppdm_uwis
        return fetch_ppdm_uwis(engine)
    except Exception:
        pass
    try:
        from sqlalchemy import text as _t
        with engine.connect() as conn:
            rows = conn.execute(_t(
                "SELECT UWI, WELL_NAME FROM dbo.WELL "
                "WHERE WELL_NAME IS NOT NULL AND UWI IS NOT NULL"
            )).fetchall()
        return [{"UWI": r[0], "WELL_NAME": r[1]} for r in rows]
    except Exception:
        return []


def _fuzzy_match_well_name(candidate: str, wells: list[dict],
                            cutoff: float = 0.55) -> dict | None:
    """Fuzzy match candidate against WELL_NAME. Returns best hit or None."""
    if not candidate or not wells:
        return None
    import difflib
    names = [w.get("WELL_NAME","") for w in wells if w.get("WELL_NAME")]
    matches = difflib.get_close_matches(candidate, names, n=1, cutoff=cutoff)
    if not matches:
        return None
    best = matches[0]
    uwi  = next((w["UWI"] for w in wells if w.get("WELL_NAME") == best), "")
    score = difflib.SequenceMatcher(None, candidate.lower(), best.lower()).ratio()
    return {"uwi": uwi, "well_name": best, "score": round(score, 2)}


def _auto_detect_repo(engine, file_path: str) -> tuple[str, str]:
    """
    Auto-detect repository from file path by matching against WL_REPOSITORY.BASE_PATH.
    Returns (repo_id, repo_name) or ("", "") if no match.
    """
    from sqlalchemy import text
    from pathlib import Path
    fp = str(Path(file_path).absolute()).lower()
    try:
        with engine.connect() as con:
            repos = con.execute(text(
                "SELECT REPOSITORY_ID, REPOSITORY_NAME, BASE_PATH "
                "FROM las_catalog.WL_REPOSITORY "
                "WHERE ACTIVE_IND='Y' ORDER BY LEN(BASE_PATH) DESC"
            )).fetchall()
        for rid, rname, base in repos:
            if base and fp.startswith(base.lower().rstrip("\\")):
                return rid, rname
    except Exception:
        pass
    return "", ""


def _repo_selector(engine, file_path: str, ukey: str) -> str:
    """
    Show repository selector pre-populated from auto-detection.
    Returns selected repository_id.
    """
    repos = _get_repos(engine)
    auto_id, auto_name = _auto_detect_repo(engine, file_path)

    # Find default index from auto-detected repo
    default_idx = 0
    keys = list(repos.keys())
    if auto_name and auto_name in repos:
        default_idx = keys.index(auto_name)
    elif auto_id:
        # Try matching by id
        for i, (k, v) in enumerate(repos.items()):
            if v == auto_id:
                default_idx = i
                break

    if auto_name:
        st.caption(f"📁 Auto-detected repository: **{auto_name}**")

    label = st.selectbox(
        "Repository", keys,
        index=default_idx,
        key=f"wb_repo_{ukey}",
        help="Auto-detected from file path. Override if needed."
    )
    return repos.get(label, "")


def _ppdm_well_picker(engine, ukey: str) -> str:
    """
    Search PPDM dbo.WELL and let cataloger pick a UWI.
    Returns chosen UWI string or "" if nothing selected.
    """
    from sqlalchemy import text
    with st.expander("🔍 Search PPDM wells", expanded=False):
        q = st.text_input("Search by UWI, well name, operator or field",
                           key=f"pwp_q_{ukey}", placeholder="e.g. ANADARKO or 42-001")
        if st.button("Search", key=f"pwp_btn_{ukey}") and q.strip():
            try:
                with engine.connect() as con:
                    rows = con.execute(text(
                        f"SELECT {_top(50, dialect)} "
                        f"UWI, WELL_NAME, OPERATOR, FIELD_NAME, "
                        f"PROVINCE_STATE, COUNTRY_NAME "
                        f"FROM dbo.WELL "
                        f"WHERE UWI LIKE :q OR WELL_NAME LIKE :q "
                        f"OR OPERATOR LIKE :q OR FIELD_NAME LIKE :q "
                        f"ORDER BY WELL_NAME {_limit(50, dialect)}"
                    ), {"q": f"%{q.strip()}%"}).fetchall()
                st.session_state[f"pwp_results_{ukey}"] = [
                    {"UWI": r[0], "Well": r[1], "Operator": r[2],
                     "Field": r[3], "State": r[4], "Country": r[5]}
                    for r in rows
                ]
            except Exception as e:
                st.error(str(e))

        results = st.session_state.get(f"pwp_results_{ukey}", [])
        if results:
            st.caption(f"{len(results)} result(s)")
            opts = {f"{r['UWI']}  —  {r['Well'] or ''}  {r['Operator'] or ''}": r["UWI"]
                    for r in results}
            chosen_label = st.selectbox("Select well", ["— pick one —"] + list(opts.keys()),
                                         key=f"pwp_pick_{ukey}")
            if chosen_label != "— pick one —":
                return opts[chosen_label]
    return ""


def _ppdm_survey_picker(engine, ukey: str) -> str:
    """
    Search PPDM dbo.SEIS_SET and let cataloger pick a survey.
    Returns chosen SEIS_SET_ID or "" if nothing selected.
    """
    from sqlalchemy import text
    with st.expander("🔍 Search PPDM seismic surveys", expanded=False):
        q = st.text_input("Search by survey name or ID",
                           key=f"psp_q_{ukey}", placeholder="e.g. CENTRAL_AUSTRALIA")
        if st.button("Search", key=f"psp_btn_{ukey}") and q.strip():
            try:
                with engine.connect() as con:
                    rows = con.execute(text(
                        f"SELECT {_top(50, dialect)} "
                        f"SEIS_SET_ID, SEIS_SET_NAME, SEIS_SET_TYPE, "
                        f"SURVEY_TYPE, COUNTRY_NAME, OPERATOR "
                        f"FROM dbo.SEIS_SET "
                        f"WHERE SEIS_SET_ID LIKE :q "
                        f"OR SEIS_SET_NAME LIKE :q "
                        f"OR COUNTRY_NAME LIKE :q "
                        f"ORDER BY SEIS_SET_NAME {_limit(50, dialect)}"
                    ), {"q": f"%{q.strip()}%"}).fetchall()
                st.session_state[f"psp_results_{ukey}"] = [
                    {"ID": r[0], "Name": r[1], "Type": r[2],
                     "Survey": r[3], "Country": r[4], "Operator": r[5]}
                    for r in rows
                ]
            except Exception as e:
                st.error(str(e))

        results = st.session_state.get(f"psp_results_{ukey}", [])
        if results:
            st.caption(f"{len(results)} result(s)")
            opts = {f"{r['ID']}  —  {r['Name'] or ''}  ({r['Country'] or ''})": r["ID"]
                    for r in results}
            chosen_label = st.selectbox("Select survey", ["— pick one —"] + list(opts.keys()),
                                         key=f"psp_pick_{ukey}")
            if chosen_label != "— pick one —":
                return opts[chosen_label]
    return ""


def _cataloger_las(engine, dialect, inventory_id, file_path, group_file_id, ukey):
    _FMT = "las"
    try:
        from modules.las_catalog import parse_las_header, catalog_file
    except ImportError as e:
        st.error(f"las_catalog not available: {e}"); return

    # Repository auto-detected, can be overridden
    repo_id = _repo_selector(engine, file_path, f"{ukey}_{_FMT}")

    # ── Auto-load header on first render (no button needed) ──────────────────
    if f"wb_raw_{ukey}" not in st.session_state:
        with st.spinner("Reading header…"):
            try:
                import lasio
                las = lasio.read(file_path, ignore_header_errors=True)
                raw_sections = {}
                for section_name, items in [
                    ("VERSION", las.version),
                    ("WELL",    las.well),
                    ("CURVES",  las.curves),
                    ("PARAMS",  las.params),
                ]:
                    raw_sections[section_name] = [
                        {"mnemonic": str(i.mnemonic), "unit": str(i.unit),
                         "value": str(i.value), "descr": str(i.descr)}
                        for i in items
                    ]
                st.session_state[f"wb_raw_{ukey}"] = raw_sections
                # Extract key fields for UWI resolution
                well_items = {r["mnemonic"].upper(): r["value"]
                              for r in raw_sections.get("WELL", [])}
                hdr_data = {
                    "uwi":        (well_items.get("UWI") or well_items.get("API") or "").strip(),
                    "well_name":  (well_items.get("WELL") or well_items.get("WELL_NAME") or "").strip(),
                    "version":    next((r["value"] for r in raw_sections.get("VERSION",[])
                                       if r["mnemonic"].upper()=="VERS"), ""),
                    "top_depth":  (well_items.get("STRT") or ""),
                    "base_depth": (well_items.get("STOP") or ""),
                    "curve_count": len(raw_sections.get("CURVES",[])),
                }
                st.session_state[f"wb_hdr_data_{ukey}"] = hdr_data
            except Exception as e:
                st.warning(f"Could not read header: {e}")

    hdr = st.session_state.get(f"wb_hdr_data_{ukey}", {})

    # ── Show header sections as compact tables ────────────────────────────────
    raw_sections = st.session_state.get(f"wb_raw_{ukey}", {})
    if raw_sections:
        _sec_tabs = st.tabs([f"📋 {s}" for s in raw_sections])
        for _tab, (_sec_name, _sec_rows) in zip(_sec_tabs, raw_sections.items()):
            with _tab:
                if _sec_rows:
                    _df = pd.DataFrame(_sec_rows)
                    # Drop empty columns
                    _df = _df.loc[:, (_df != "").any(axis=0)]
                    st.dataframe(_df, use_container_width=True, hide_index=True,
                                 height=min(38 + len(_df) * 35, 320))
                else:
                    st.caption("(empty)")

    # ── UWI resolution: filename > header > fuzzy match ───────────────────────
    from_filename = _extract_uwi_from_filename(file_path)
    from_header   = hdr.get("uwi", "").strip()
    override      = st.session_state.get(f"wb_uwi_override_{ukey}")

    widget_key = f"wb_uwi_{ukey}"
    if widget_key not in st.session_state:
        best = override or from_filename or from_header
        if not best:
            candidate = hdr.get("well_name","").strip() or _guess_name_from_filename(file_path)
            if candidate:
                match = _fuzzy_match_well_name(candidate, _fetch_well_names(engine))
                if match:
                    best = match["uwi"]
                    st.session_state[f"wb_uwi_match_{ukey}"] = match
        st.session_state[widget_key] = best or ""

    # ── Card: UWI & PPDM ──────────────────────────────────────────────────────
    _card("🔑 Well Identification")
    match_info = st.session_state.get(f"wb_uwi_match_{ukey}")
    _id_c1, _id_c2 = st.columns([3, 1])
    with _id_c1:
        if from_filename:
            st.caption(f"📄 UWI from filename: `{from_filename}`")
        elif from_header:
            st.caption(f"📋 UWI extracted from file header")
        elif match_info:
            st.caption(f"🔍 Fuzzy-matched to PPDM well: **{match_info['well_name']}**")
    with _id_c2:
        if match_info:
            _score = match_info["score"]
            _colour = "normal" if _score >= 0.8 else ("off" if _score >= 0.6 else "inverse")
            st.metric(
                "Match confidence",
                f"{_score:.0%}",
                help=(
                    "How closely the filename/header well name matched a PPDM well name. "
                    "≥80% = high confidence · 60–79% = review recommended · <60% = low confidence"
                ),
            )
        elif from_filename or from_header:
            st.metric("Match confidence", "100%", help="UWI sourced directly from file — no fuzzy matching needed.")

    uwi = st.text_input("UWI", key=widget_key)

    # PPDM well picker — shown when no confident match
    if not uwi.strip() or not match_info:
        picked = _ppdm_well_picker(engine, ukey)
        if picked:
            st.session_state[widget_key] = picked
            st.rerun()

    col_chk, col_status = st.columns([1, 3])
    with col_chk:
        if st.button("🔎 Check PPDM", key=f"wb_chk_{ukey}"):
            if uwi.strip():
                try:
                    from modules.las_catalog import well_exists
                    st.session_state[f"wb_ppdm_ok_{ukey}"] = (
                        well_exists(engine, uwi.strip()), uwi.strip()
                    )
                except Exception:
                    pass
    with col_status:
        chk = st.session_state.get(f"wb_ppdm_ok_{ukey}")
        if chk:
            ok, checked = chk
            if ok:
                st.success(f"✅ **{checked}** found in PPDM.")
            else:
                st.warning(f"⚠️ **{checked}** not in PPDM well header.")
    _card_end()

    # ── Card: Catalog action ───────────────────────────────────────────────────
    _card("📥 Catalog")
    # ── Step 4: Catalog — metadata snapshot only, no curve data ──────────────
    if st.button("📥 Catalog LAS", type="primary", key=f"wb_cat_{ukey}"):
        if not uwi.strip(): st.error("UWI required."); return
        try:
            from modules.las_catalog import catalog_file as _cat_las
            repo_id = _repo_selector(engine, file_path, f"{ukey}_{_FMT}")
            r = _cat_las(engine, file_path, repo_id, uwi=uwi.strip())
            if r["ok"]:
                mark_cataloged(engine, dialect, inventory_id, group_file_id)
                try:
                    from modules.file_header_store import store_las_headers
                    store_las_headers(engine, file_path, inventory_id,
                                      r.get("las_file_id"), uwi.strip())
                except Exception:
                    pass
                try:
                    from modules.audit_log import audit_catalog
                    _wbu = st.session_state.get("inv_user_id","")
                    _wbn = st.session_state.get("inv_user_name","")
                    audit_catalog(engine, {"user_id":_wbu,"full_name":_wbn},
                                 file_path, "LAS", action=r.get("action",""))
                except Exception: pass
                st.success(f"✅ LAS cataloged ({r['action']}) — {uwi.strip()}")
                st.rerun()
            else:
                st.error(f"Catalog failed: {r['error']}")
        except Exception as e:
            st.error(str(e))
    _card_end()


# ─────────────────────────────────────────────────────────────────────────────
# DLIS / LIS well matching helpers
# ─────────────────────────────────────────────────────────────────────────────

def _guess_name_from_filename(file_path: str) -> str:
    """Strip extension/underscores/leading numbers from filename stem."""
    import re
    from pathlib import Path
    stem = Path(file_path).stem
    name = re.sub(r"[_\-]+", " ", stem).strip()
    name = re.sub(r"^\d+\s*", "", name).strip()
    return name


def _extract_uwi_from_filename(file_path: str) -> str:
    """Try to extract a UWI/API number from the filename stem."""
    import re
    from pathlib import Path
    stem = Path(file_path).stem
    patterns = [
        re.compile(r"(\d{2}[-_]\d{3}[-_]\d{5}[-_]\d{4})"),
        re.compile(r"(\d{2}[-_]\d{3}[-_]\d{5})"),
        re.compile(r"(\d{14})"),
        re.compile(r"(42[-_]\d{3}[-_]\d{5}\d*)"),
    ]
    for variant in [stem, stem.replace("_", "-")]:
        for pat in patterns:
            m = pat.search(variant)
            if m:
                return m.group(1).replace("_", "-")
    return ""


def _extract_survey_from_filename(file_path: str) -> str:
    """Try to extract a survey name from the filename stem."""
    import re
    from pathlib import Path
    stem = Path(file_path).stem
    patterns = [
        re.compile(r"(?i)([A-Za-z0-9]+[-_]?3[Dd])"),
        re.compile(r"(?i)([A-Za-z0-9]+[-_]?2[Dd])"),
        re.compile(r"(?i)(survey[-_]?[A-Za-z0-9]+)"),
    ]
    for pat in patterns:
        m = pat.search(stem)
        if m:
            return m.group(0)
    return stem


def _run_dlis_well_match(engine, file_path: str, hdr: dict, ukey: str):
    """
    Try to find a PPDM UWI for a DLIS/LIS file:
    1. Well name from header (well_name, well_id)
    2. Filename stem
    3. difflib fuzzy match against PPDM WELL.WELL_NAME
    Stores result in session_state[wb_match_{ukey}].
    """
    import difflib

    # Build candidate list — UWI from filename takes priority
    candidates = []
    filename_uwi = _extract_uwi_from_filename(file_path)
    if filename_uwi:
        candidates.append(filename_uwi)
    for key in ("well_name", "well_id"):
        v = (hdr.get(key) or "").strip()
        if v and v not in candidates:
            candidates.append(v)
    filename_guess = _guess_name_from_filename(file_path)
    if filename_guess and filename_guess not in candidates:
        candidates.append(filename_guess)

    # Fetch PPDM wells
    wells = []
    try:
        from modules.las_loader import fetch_ppdm_uwis
        wells = fetch_ppdm_uwis(engine)
    except Exception:
        pass

    # Fuzzy match against WELL_NAME for each candidate
    match = None
    matched_on = ""
    if wells:
        well_names = [w["WELL_NAME"] for w in wells if w.get("WELL_NAME")]
        for cand in candidates:
            hits = difflib.get_close_matches(cand, well_names, n=1, cutoff=0.55)
            if hits:
                best_name = hits[0]
                best_well = next(w for w in wells if w["WELL_NAME"] == best_name)
                score = difflib.SequenceMatcher(
                    None, cand.lower(), best_name.lower()
                ).ratio()
                match = {
                    "uwi":       best_well["UWI"],
                    "well_name": best_name,
                    "score":     round(score, 2),
                }
                matched_on = cand
                break

    st.session_state[f"wb_match_{ukey}"] = {
        "candidates":  candidates,
        "matched_on":  matched_on,
        "match":       match,
        "filename":    filename_guess,
    }


def _render_dlis_uwi(engine, ukey: str) -> str:
    """
    Show match result and UWI input.
    Returns UWI to use (matched UWI, manual override, or filename).
    engine is passed to enable PPDM well search when no match found.
    """
    data  = st.session_state.get(f"wb_match_{ukey}", {})
    match = data.get("match")
    fname = data.get("filename", "")

    if match:
        st.success(
            f"✅ Matched **'{data.get('matched_on','')}'** → "
            f"**{match['well_name']}**  (UWI: `{match['uwi']}`, "
            f"score: {match['score']:.0%})"
        )
        default = match["uwi"]
    elif data.get("candidates"):
        st.warning(
            f"⚠️ No PPDM match for: *{', '.join(data['candidates'])}*  "
            f"— search PPDM below or enter UWI manually."
        )
        default = ""
    else:
        st.info("No well name in header or filename — search PPDM below or enter UWI manually.")
        default = ""

    uwi = st.text_input(
        "UWI (override if needed)", value=default,
        key=f"wb_uwi_{ukey}",
        placeholder="Leave blank to catalog under filename"
    )

    # PPDM well picker when no confident match
    if not match or not uwi.strip():
        picked = _ppdm_well_picker(engine, ukey + "_dlis")
        if picked:
            st.session_state[f"wb_uwi_{ukey}"] = picked
            st.rerun()

    if not uwi.strip() and fname:
        st.caption(f"📄 Will catalog under filename: **{fname}**")

    return uwi.strip() or fname


def _cataloger_dlis(engine, dialect, inventory_id, file_path, group_file_id, ukey):
    _FMT = "dlis"
    try:
        from modules.dlis_catalog import catalog_dlis_file, parse_dlis_header
    except ImportError as e:
        st.error(f"dlis_catalog not available: {e}"); return

    repo_id = _repo_selector(engine, file_path, f"{ukey}_{_FMT}")
    st.session_state[f"wb_repo_id_{ukey}"] = repo_id

    # Auto-load header on first render
    if f"wb_hdr_data_{ukey}" not in st.session_state:
        with st.spinner("Reading header…"):
            try:
                hdr = parse_dlis_header(file_path)
                st.session_state[f"wb_hdr_data_{ukey}"] = hdr
                _run_dlis_well_match(engine, file_path, hdr, ukey)
            except Exception as e:
                st.warning(f"Could not read header: {e}")

    hdr = st.session_state.get(f"wb_hdr_data_{ukey}", {})
    if hdr:
        for k,v in {"Well":hdr.get("well_name",""),"Well ID":hdr.get("well_id",""),
                    "Company":hdr.get("company",""),"Field":hdr.get("field_name","")}.items():
            st.text(f"{k}: {v or '—'}")

    uwi = _render_dlis_uwi(engine, ukey)

    if st.button("📥 Catalog DLIS", type="primary", key=f"wb_cat_{ukey}"):
        if not uwi.strip(): st.error("UWI or filename required."); return
        try:
            from modules.dlis_catalog import catalog_dlis_file as _cat_dlis
            repo_id = st.session_state.get(f"wb_repo_id_{ukey}", "")
            r = _cat_dlis(engine, file_path, repo_id, uwi=uwi.strip())
            if r["ok"]:
                mark_cataloged(engine, dialect, inventory_id, group_file_id)
                try:
                    from modules.file_header_store import store_dlis_headers
                    store_dlis_headers(engine, file_path, inventory_id,
                                       r.get("dlis_file_id"), uwi.strip())
                except Exception:
                    pass
                try:
                    from modules.audit_log import audit_catalog
                    _wbu = st.session_state.get("inv_user_id","")
                    _wbn = st.session_state.get("inv_user_name","")
                    audit_catalog(engine, {"user_id":_wbu,"full_name":_wbn},
                                 file_path, "DLIS", action=r.get("action",""))
                except Exception: pass
                st.success(f"✅ DLIS cataloged ({r['action']}) — {uwi.strip()}")
                st.rerun()
            else:
                st.error(f"Catalog failed: {r.get('error','')}")
        except Exception as e:
            st.error(str(e))


def _cataloger_lis(engine, dialect, inventory_id, file_path, group_file_id, ukey):
    _FMT = "lis"
    try:
        from modules.dlis_catalog import catalog_lis_file, parse_lis_header
    except ImportError as e:
        st.error(f"dlis_catalog not available: {e}"); return

    repo_id = _repo_selector(engine, file_path, f"{ukey}_{_FMT}")
    st.session_state[f"wb_repo_id_{ukey}"] = repo_id

    # Auto-load header on first render
    if f"wb_hdr_data_{ukey}" not in st.session_state:
        with st.spinner("Reading header…"):
            try:
                hdr = parse_lis_header(file_path)
                st.session_state[f"wb_hdr_data_{ukey}"] = hdr
                _run_dlis_well_match(engine, file_path, hdr, ukey)
            except Exception as e:
                st.warning(f"Could not read header: {e}")

    hdr = st.session_state.get(f"wb_hdr_data_{ukey}", {})
    if hdr:
        for k,v in {"Well":hdr.get("well_name",""),
                    "Company":hdr.get("company","")}.items():
            st.text(f"{k}: {v or '—'}")

    uwi = _render_dlis_uwi(engine, ukey)

    if st.button("📥 Catalog LIS", type="primary", key=f"wb_cat_{ukey}"):
        if not uwi.strip(): st.error("UWI or filename required."); return
        try:
            from modules.dlis_catalog import catalog_lis_file as _cat_lis
            repo_id = st.session_state.get(f"wb_repo_id_{ukey}", "")
            r = _cat_lis(engine, file_path, repo_id, uwi=uwi.strip())
            if r["ok"]:
                mark_cataloged(engine, dialect, inventory_id, group_file_id)
                try:
                    from modules.file_header_store import store_lis_headers
                    store_lis_headers(engine, file_path, inventory_id,
                                      r.get("lis_file_id"), uwi.strip())
                except Exception:
                    pass
                try:
                    from modules.audit_log import audit_catalog
                    _wbu = st.session_state.get("inv_user_id","")
                    _wbn = st.session_state.get("inv_user_name","")
                    audit_catalog(engine, {"user_id":_wbu,"full_name":_wbn},
                                 file_path, "LIS", action=r.get("action",""))
                except Exception: pass
                st.success(f"✅ LIS cataloged ({r['action']}) — {uwi.strip()}")
                st.rerun()
            else:
                st.error(f"Catalog failed: {r.get('error','')}")
        except Exception as e:
            st.error(str(e))


def _cataloger_segy(engine, dialect, inventory_id, file_path, group_file_id, ukey):
    _FMT = "segy"
    try:
        from modules.segy_catalog import catalog_segy_file
    except ImportError as e:
        st.error(f"segy_catalog not available: {e}"); return

    repo_id = _repo_selector(engine, file_path, f"{ukey}_{_FMT}")
    seed    = st.checkbox("Seed PPDM (SEIS_SET + SEIS_LINE)", key=f"wb_seed_{ukey}")

    survey_from_file = _extract_survey_from_filename(file_path)
    survey = st.text_input("Survey name", value=survey_from_file,
                            key=f"wb_survey_{ukey}_{_FMT}",
                            placeholder="e.g. CENTRAL_AUSTRALIA_3D")

    # PPDM survey picker when no survey name
    if not survey.strip():
        picked_sv = _ppdm_survey_picker(engine, ukey + "_segy")
        if picked_sv:
            st.session_state[f"wb_survey_{ukey}_{_FMT}"] = picked_sv
            st.rerun()

    if st.button("📥 Catalog SEG-Y", type="primary", key=f"wb_cat_{ukey}"):
        try:
            r = catalog_segy_file(
                engine, file_path, repo_id,
                survey_name=survey.strip() or None,
                seed_ppdm=seed
            )
            if r["ok"]:
                mark_cataloged(engine, dialect, inventory_id, group_file_id)
                try:
                    from modules.file_header_store import store_segy_headers
                    store_segy_headers(engine, file_path, inventory_id,
                                       r.get("seis_file_id"), survey.strip())
                except Exception:
                    pass
                try:
                    from modules.audit_log import audit_catalog
                    _wbu = st.session_state.get('inv_user_id','')
                    _wbn = st.session_state.get('inv_user_name','')
                    audit_catalog(engine, {'user_id':_wbu,'full_name':_wbn},
                                 file_path, 'SEGY', action=r.get('action',''))
                except Exception: pass
                st.success(f"✅ SEG-Y cataloged ({r['action']})"
                           + (f" — PPDM seeded" if r.get("seeded_ppdm") else ""))
                st.rerun()
            else:
                st.error(f"Catalog failed: {r.get('error','')}")
        except Exception as e:
            st.error(str(e))


def _cataloger_p190(engine, dialect, inventory_id, file_path, group_file_id, ukey):
    _FMT = "p190"
    try:
        from modules.p190_catalog import catalog_p190_file
    except ImportError as e:
        st.error(f"p190_catalog not available: {e}"); return

    repo_id = _repo_selector(engine, file_path, f"{ukey}_{_FMT}")
    seed    = st.checkbox("Seed PPDM (SEIS_SET + SEIS_LINE)", key=f"wb_seed_{ukey}")

    survey_from_file = _extract_survey_from_filename(file_path)
    survey = st.text_input("Survey name", value=survey_from_file,
                            key=f"wb_survey_{ukey}_{_FMT}",
                            placeholder="e.g. CENTRAL_AUSTRALIA_3D")

    # PPDM survey picker when no survey name
    if not survey.strip():
        picked_sv = _ppdm_survey_picker(engine, ukey + "_p190")
        if picked_sv:
            st.session_state[f"wb_survey_{ukey}_{_FMT}"] = picked_sv
            st.rerun()

    if st.button("📥 Catalog P190", type="primary", key=f"wb_cat_{ukey}"):
        try:
            r = catalog_p190_file(
                engine, file_path, repo_id,
                survey_name=survey.strip() or None,
                seed_ppdm=seed
            )
            if r["ok"]:
                mark_cataloged(engine, dialect, inventory_id, group_file_id)
                try:
                    from modules.file_header_store import store_p190_headers
                    store_p190_headers(engine, file_path, inventory_id,
                                       r.get("seis_file_id"), survey.strip())
                except Exception:
                    pass
                try:
                    from modules.audit_log import audit_catalog
                    _wbu = st.session_state.get("inv_user_id","")
                    _wbn = st.session_state.get("inv_user_name","")
                    audit_catalog(engine, {"user_id":_wbu,"full_name":_wbn},
                                 file_path, "P190", action=r.get("action",""))
                except Exception: pass
                st.success(f"✅ P190 cataloged ({r['action']})"
                           + (f" — PPDM seeded" if r.get("seeded_ppdm") else ""))
                st.rerun()
            else:
                st.error(f"Catalog failed: {r.get('error','')}")
        except Exception as e:
            st.error(str(e))


"""
page_dv_importer.py
===================
DataView v3 — Generalized Multi-Table Importer

UI: 4 collapsible sections
  1 · Upload & Detect   — file upload, ML target detection
  2 · Column Mapping    — editable grid (auto-collapsed on fingerprint)
  3 · Rules Engine      — constants, code maps (auto-collapsed on fingerprint)
  4 · Load              — always visible, progress bars, validation, promote

Performance: direct BULK INSERT from source file — no full pandas read for large files.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text

# ── Pipeline engine ───────────────────────────────────────────────────
try:
    from dv_pipeline import (
        _SchemaCache,
        detect_targets,
        build_stg_table,
        bulk_insert_stg,
        normalize_stg,
        validate_stg,
        apply_code_maps,
        seed_entities_from_stg,
        promote_stg,
        save_to_corpus,
    )
    _PIPELINE_AVAILABLE = True
    _PIPELINE_ERROR = ""
except ImportError as _e:
    _PIPELINE_AVAILABLE = False
    _PIPELINE_ERROR = str(_e)

# ── Standards seed ────────────────────────────────────────────────────
try:
    from dv_standards_seed import (
        seed_all_standards,
        map_kgs_status,
        WELL_TYPES,
        WELL_STATUSES,
    )
    _STANDARDS_AVAILABLE = True
except ImportError:
    _STANDARDS_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────
_FP_DIR    = Path("schema_registry") / "dv_importer_fingerprints"
CONF_AUTO  = 0.80
CONF_MAYBE = 0.45
_AUTO_COLS = {
    "active_ind", "row_created_by", "row_created_date",
    "row_changed_by", "row_changed_date", "source",
}
_SAMPLE_ROWS = 200  # rows read into pandas for ML + rules engine


# =============================================================================
# FINGERPRINT HELPERS
# =============================================================================

def _fp_key(cols: list[str]) -> str:
    import hashlib
    return hashlib.sha1(
        "|".join(sorted(c.upper() for c in cols)).encode()
    ).hexdigest()[:16]


def _save_fp(cols, mapping, target_table, label="", rules=None) -> str:
    _FP_DIR.mkdir(parents=True, exist_ok=True)
    key = _fp_key(cols)
    fp  = {"key": key, "label": label or target_table,
           "target_table": target_table, "cols": cols,
           "mapping": mapping, "rules": rules or {},
           "saved": datetime.utcnow().isoformat()}
    (_FP_DIR / f"{key}.json").write_text(
        json.dumps(fp, indent=2), encoding="utf-8")
    return key


def _load_fp(cols: list[str]) -> dict | None:
    path = _FP_DIR / f"{_fp_key(cols)}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _list_fps() -> list[dict]:
    if not _FP_DIR.exists():
        return []
    fps = []
    for p in sorted(_FP_DIR.glob("*.json")):
        try:
            fps.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return fps


# =============================================================================
# MAPPING HELPERS
# =============================================================================

def _get_dtype(table: str, col: str) -> str:
    if not _PIPELINE_AVAILABLE:
        return "str"
    for e in _SchemaCache.domain_for_table(table):
        if e["column_name"].lower() == col.lower():
            dt = e.get("data_type", "").upper()
            if any(t in dt for t in ("DATE", "TIME")):
                return "date"
            if any(t in dt for t in ("INT", "DECIMAL", "NUMERIC", "FLOAT")):
                return "num"
            return "str"
    return "str"


def _col_options(target_table: str) -> list[str]:
    if not _PIPELINE_AVAILABLE:
        return []
    return ["(skip)"] + [
        e["column_name"] for e in _SchemaCache.domain_for_table(target_table)
        if e["column_name"].lower() not in _AUTO_COLS
    ]


def _build_mapping(group, src_cols: list[str]) -> list[dict]:
    matched = {m.src_col: m for m in group.matches}
    return [{
        "src":        src,
        "target":     matched[src].tgt_col if src in matched else None,
        "data_type":  _get_dtype(group.table, matched[src].tgt_col) if src in matched else "str",
        "confidence": matched[src].score if src in matched else 0.0,
        "method":     matched[src].method if src in matched else "none",
    } for src in src_cols]


# =============================================================================
# RULES ENGINE
# =============================================================================

def _render_rules(df_sample, edited, target_table, engine, source_label) -> dict:
    rules = st.session_state.get("dvi_rules", {})
    mapped_targets = {m["target"] for m in edited if m.get("target")}

    st.markdown("**Constants & Defaults**")
    for col, label, default in [
        ("source",         "Source identifier",     source_label or "KGS"),
        ("country",        "Default country",        "USA"),
        ("province_state", "Default state/province", ""),
        ("elevation_ouom", "Elevation unit",         "FT"),
        ("final_td_ouom",  "Total depth unit",       "FT"),
        ("ba_type",        "BA type",                "COMPANY"),
    ]:
        existing = rules.get(f"const_{col}", {})
        c1, c2, c3 = st.columns([3, 2, 3])
        c1.caption(f"`{col}`")
        val  = c2.text_input(label, value=existing.get("value", default),
                             key=f"rc_{col}", label_visibility="collapsed",
                             placeholder=default)
        when = c3.selectbox("When", ["Always", "When null"],
                            index=0 if existing.get("when") == "always" else 1,
                            key=f"rcw_{col}", label_visibility="collapsed")
        if val.strip():
            rules[f"const_{col}"] = {"value": val.strip(),
                                      "when": "always" if when == "Always" else "null"}

    st.markdown("**FK Auto-Seeding**")
    for col, ref, label in [
        ("operator_ba_id",         "dv_business_associate", "Seed operators"),
        ("current_operator_ba_id", "dv_business_associate", "Seed current operators"),
        ("field_id",               "dv_field",              "Seed fields"),
    ]:
        is_mapped = col in mapped_targets
        enabled = st.checkbox(f"`{col}` → seed `{ref}`",
                              value=rules.get(f"seed_{col}", {}).get("enabled", is_mapped),
                              key=f"rs_{col}", disabled=not is_mapped)
        rules[f"seed_{col}"] = {"enabled": enabled and is_mapped}

    st.markdown("**Code Mappings**")
    _ref_counts = {}
    try:
        with engine.connect() as _c:
            for tbl, pk in {"dv_r_well_type": "well_type",
                             "dv_r_well_status": "well_status"}.items():
                _ref_counts[tbl] = _c.execute(
                    text(f"SELECT COUNT(*) FROM dataview.{tbl}")).scalar()
    except Exception:
        pass

    sc1, sc2 = st.columns([1, 3])
    with sc1:
        if st.button("🌱 Seed Ref Tables", key="re_seed"):
            if _STANDARDS_AVAILABLE:
                try:
                    for t, n in seed_all_standards(engine).items():
                        st.success(f"{t}: {n}") if n else None
                    st.session_state.dvi_standards_seeded = True
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
    with sc2:
        if _ref_counts:
            st.dataframe(pd.DataFrame([
                {"Table": t, "Rows": n, "Status": "✅" if n else "⚠️"}
                for t, n in _ref_counts.items()
            ]), hide_index=True, use_container_width=True)

    wt_src = next((m["src"] for m in edited if m.get("target") == "well_type"), None)
    ws_src = next((m["src"] for m in edited if m.get("target") == "well_status"), None)
    _is_composite = wt_src and ws_src and wt_src == ws_src

    def _ref_codes(tbl, pk):
        try:
            with engine.connect() as _c:
                return [r[0] for r in _c.execute(text(
                    f"SELECT {pk} FROM dataview.{tbl} WHERE active_ind='Y' ORDER BY {pk}"
                )).fetchall()]
        except Exception:
            return []

    type_codes   = _ref_codes("dv_r_well_type",  "well_type")   or ([wt for wt,*_ in WELL_TYPES]   if _STANDARDS_AVAILABLE else [])
    status_codes = _ref_codes("dv_r_well_status", "well_status") or ([ws for ws,*_ in WELL_STATUSES] if _STANDARDS_AVAILABLE else [])

    def _clamp(v, opts):
        return v if v in opts else ("UNKNOWN" if "UNKNOWN" in opts else (opts[0] if opts else v))

    if _is_composite and _STANDARDS_AVAILABLE and df_sample is not None:
        src_col = wt_src
        if src_col in df_sample.columns:
            unique_vals = sorted(
                df_sample[src_col].dropna().astype(str).str.strip().unique().tolist())[:60]
            if unique_vals and type_codes and status_codes:
                st.markdown(f"**🗂 STATUS composite** — `{src_col}` → `well_type` + `well_status`")
                ex_wt = rules.get("map_well_type",  {})
                ex_ws = rules.get("map_well_status", {})
                _rows = [{
                    "Source Value":  sv,
                    "→ well_type":   _clamp(ex_wt.get(sv, map_kgs_status(sv)[0] or "OTHER"), type_codes),
                    "→ well_status": _clamp(ex_ws.get(sv, map_kgs_status(sv)[1] or "ACTIVE"), status_codes),
                } for sv in unique_vals]
                with st.form("composite_map_form"):
                    _ed = st.data_editor(
                        pd.DataFrame(_rows),
                        column_config={
                            "→ well_type":   st.column_config.SelectboxColumn(
                                "→ well_type", options=type_codes, required=True),
                            "→ well_status": st.column_config.SelectboxColumn(
                                "→ well_status", options=status_codes, required=True),
                        },
                        hide_index=True, use_container_width=True,
                        key="re_composite", num_rows="fixed",
                    )
                    if st.form_submit_button("✅ Apply Mapping", use_container_width=True):
                        rules["map_well_type"]   = {r["Source Value"]: r["→ well_type"]
                                                    for _, r in _ed.iterrows()}
                        rules["map_well_status"] = {r["Source Value"]: r["→ well_status"]
                                                    for _, r in _ed.iterrows()}
                        st.session_state.dvi_rules = rules
                if "map_well_type" not in rules and _rows:
                    rules["map_well_type"]   = {r["Source Value"]: r["→ well_type"]   for r in _rows}
                    rules["map_well_status"] = {r["Source Value"]: r["→ well_status"] for r in _rows}

    st.session_state.dvi_rules = rules
    return rules


# =============================================================================
# TIMING HELPER
# =============================================================================

def _fmt_t(seconds: float) -> str:
    return f"{seconds:.1f}s" if seconds < 60 else f"{seconds/60:.1f}m"


# =============================================================================
# PIPELINE RUNNER
# =============================================================================

def _run_pipeline(engine, file_path, df_sample, src_cols, col_map,
                  target_table, source_name, uwi_src, rules,
                  auto_promote, total_rows):

    st.session_state.dvi_validation = None
    st.session_state.dvi_stg_table  = None
    st.session_state.dvi_result     = None

    t_start = time.time()
    timing  = {}
    progress = st.progress(0, text="Starting…")

    try:
        # Stage 2 — Staging table
        progress.progress(5, "📋 Creating staging table…")
        t   = time.time()
        stg = build_stg_table(engine, target_table, src_cols, source_name)
        st.session_state.dvi_stg_table = stg
        timing["staging"] = time.time() - t
        st.caption(f"  ✓ `dataview.{stg}` created — {_fmt_t(timing['staging'])}")

        # Stage 3 — BULK INSERT via pandas DataFrame
        progress.progress(15, f"⚡ Bulk loading {total_rows:,} rows…")
        t = time.time()
        df_full = st.session_state.get("dvi_df_full", df_sample)
        n = bulk_insert_stg(engine, df_full, stg, src_cols, source_name)
        timing["bulk_insert"] = time.time() - t
        st.caption(f"  ✓ {n:,} rows staged in {_fmt_t(timing['bulk_insert'])}")

        # Stage 4 — Normalize
        progress.progress(35, "🔧 Normalizing…")
        t    = time.time()
        norm = normalize_stg(engine, stg, df_sample, uwi_src_col=uwi_src)
        timing["normalize"] = time.time() - t
        st.caption(f"  ✓ {norm.get('transforms',0)} transforms — {_fmt_t(timing['normalize'])}")

        # Stage 5 — Validate
        progress.progress(50, "🔍 Validating…")
        t   = time.time()
        val = validate_stg(engine, stg, target_table, col_map)
        st.session_state.dvi_validation = val
        timing["validate"] = time.time() - t
        st.caption(f"  ✓ {val.rows_checked:,} rows · "
                   f"{val.error_count} errors · {val.warning_count} warnings — "
                   f"{_fmt_t(timing['validate'])}")

        if auto_promote and val.error_count == 0:
            _run_promote(engine, stg, target_table, col_map, rules,
                         val, source_name, promote=True,
                         progress=progress, timing=timing, t_start=t_start)
        else:
            progress.progress(100,
                f"✅ Ready to promote — {_fmt_t(time.time()-t_start)} elapsed")

    except Exception as e:
        progress.empty()
        st.error(f"Pipeline error: {e}")
        st.session_state.dvi_validation = None


def _run_promote(engine, stg, target_table, col_map, rules,
                 val, source_name, promote=True,
                 progress=None, timing=None, t_start=None):
    timing  = timing  or {}
    t_start = t_start or time.time()

    try:
        # Stage 6 — Code maps
        if progress: progress.progress(60, "🗂 Applying code maps…")
        t = time.time()
        apply_code_maps(engine, stg, col_map, rules)
        timing["code_maps"] = time.time() - t

        # Stage 7 — Seed entities
        if progress: progress.progress(72, "🌱 Seeding BAs and fields…")
        t = time.time()
        seed_r = seed_entities_from_stg(
            engine, stg, target_table, col_map, source_name,
            ba_type=rules.get("const_ba_type", {}).get("value", "COMPANY"),
        )
        timing["seed"] = time.time() - t
        st.caption(f"  ✓ {seed_r.get('ba_seeded',0)} BAs · "
                   f"{seed_r.get('fields_seeded',0)} fields — {_fmt_t(timing['seed'])}")

        if promote:
            # Stage 8 — Promote
            if progress: progress.progress(86, "🚀 Promoting…")
            t      = time.time()
            result = promote_stg(
                engine, stg, target_table, col_map, rules,
                bad_row_ids=val.reject_row_ids,
                source_name=source_name,
            )
            timing["promote"] = time.time() - t
            total = time.time() - t_start
            if progress:
                progress.progress(100, f"✅ Done — {_fmt_t(total)} total")

            st.session_state.dvi_result = {
                "ok": result.ok, "inserted": result.inserted,
                "rejected": result.rejected, "reject_file": result.reject_file,
                "error": result.error, "timing": timing, "total": total,
            }

            if result.ok:
                fp_label = st.session_state.get("dvi_fp_label_val", source_name)
                _save_fp(st.session_state.get("dvi_src_cols", []),
                         st.session_state.get("dvi_mapping", []),
                         target_table, label=fp_label, rules=rules)
                save_to_corpus(st.session_state.get("dvi_mapping", []),
                               source_agency=fp_label,
                               source_file=st.session_state.get("dvi_filename", ""))
        else:
            if progress: progress.progress(100, "Done")
            st.session_state.dvi_result = {
                "ok": True, "inserted": 0, "rejected": len(val.reject_row_ids),
                "reject_file": "", "error": "", "timing": timing,
                "total": time.time() - t_start,
            }

    except Exception as e:
        st.session_state.dvi_result = {
            "ok": False, "inserted": 0, "rejected": 0,
            "reject_file": "", "error": str(e),
            "timing": timing, "total": time.time() - t_start,
        }


# =============================================================================
# VALIDATION DISPLAY
# =============================================================================

def _show_validation(val):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows",        f"{val.rows_checked:,}")
    c2.metric("✅ Clean",    f"{val.clean_count:,}")
    c3.metric("❌ Errors",   f"{val.error_count:,}",
              delta=f"-{val.error_count:,}" if val.error_count else None,
              delta_color="inverse")
    c4.metric("⚠️ Warnings", f"{val.warning_count:,}")

    if val.issues:
        title = (f"✅ {val.warning_count} warnings — no blocking errors"
                 if val.error_count == 0
                 else f"❌ {val.error_count} errors + {val.warning_count} warnings")
        with st.expander(title, expanded=val.error_count > 0):
            for issue in val.issues:
                icon = "🔴" if issue["severity"] == "ERROR" else "🟡"
                st.markdown(
                    f"{icon} **{issue['severity']}** &nbsp;|&nbsp; "
                    f"`{issue['rule']}` &nbsp;|&nbsp; "
                    f"col: `{issue.get('ppdm_col','')}` &nbsp;|&nbsp; "
                    f"**{issue.get('count','')}** rows"
                )
                st.caption(f"&nbsp;&nbsp;&nbsp;&nbsp;{issue['message']}")
            st.markdown("---")
            st.download_button(
                "📥 Download validation report",
                data=val.to_df().to_csv(index=False).encode("utf-8"),
                file_name="dv_validation_report.csv",
                mime="text/csv", use_container_width=True,
            )
    elif val.rows_checked > 0:
        st.success("✅ All rows passed — ready to promote")


# =============================================================================
# MAIN RENDER
# =============================================================================

def render(engine=None):
    st.subheader("📥 DataView Importer")

    # ── Clear session button in sidebar ───────────────────────────────
    with st.sidebar:
        st.markdown("---")
        if st.button("🔄 Clear Importer Session", use_container_width=True,
                     help="Clears all importer state without restarting Streamlit"):
            # Clean up temp file if exists
            fp = st.session_state.get("dvi_file_path")
            if fp:
                try:
                    os.unlink(fp)
                except Exception:
                    pass
            # Clear all dvi_ session keys
            for k in [k for k in st.session_state if k.startswith("dvi_")]:
                del st.session_state[k]
            st.rerun()

    if engine is None:
        st.warning("Connect to a DataView database first.")
        return
    if not _PIPELINE_AVAILABLE:
        st.error(f"dv_pipeline.py not found: {_PIPELINE_ERROR}")
        return

    if _STANDARDS_AVAILABLE and "dvi_standards_seeded" not in st.session_state:
        try:
            seed_all_standards(engine)
            st.session_state.dvi_standards_seeded = True
        except Exception:
            pass

    # Session init
    for k, v in [
        ("dvi_filename",""), ("dvi_src_cols",[]), ("dvi_df_full",None),
        ("dvi_df_sample",None), ("dvi_total_rows",0), ("dvi_target",None),
        ("dvi_mapping",None), ("dvi_groups",None), ("dvi_fp_loaded",False),
        ("dvi_rules",{}), ("dvi_validation",None), ("dvi_stg_table",None),
        ("dvi_result",None), ("dvi_fp_label_val","KGS"),
    ]:
        if k not in st.session_state:
            st.session_state[k] = v

    # ── Section 0: Bulk Region Loaders (GOM, etc.) ────────────────────
    # Purpose-built bulk loaders for source-shaped data that doesn't go
    # through the generic column-mapping workflow below. Add new region
    # loaders here as they're built (Permian, KGS, BLM, RRC, etc.).
    # Collapsed by default — the column-mapping workflow remains the
    # primary path for ad-hoc CSV/Excel imports.
    with st.expander("🌊 0 · Bulk Region Loaders", expanded=False):
        try:
            import page_import_gom
            page_import_gom.render(engine)
        except Exception as e:
            st.error(f"GOM loader unavailable: {type(e).__name__}: {e}")

        st.divider()

        # GOM directional survey loader — BOEM Azimuth fixed-width file.
        # Sibling of the well header loader above; loads survey stations
        # into dataview_gom.directional_survey_point.
        try:
            import page_import_gom_dir_srvy
            page_import_gom_dir_srvy.render(engine)
        except Exception as e:
            st.error(
                f"GOM directional survey loader unavailable: "
                f"{type(e).__name__}: {e}"
            )

    st.divider()

    # ── Section 1: Upload & Detect ────────────────────────────────────
    with st.expander("📁 1 · Upload & Detect", expanded=True):

        uploaded = st.file_uploader(
            "Source file", type=["csv", "xlsx", "xls"],
            label_visibility="collapsed")

        if uploaded and uploaded.name != st.session_state.dvi_filename:
            try:
                ext       = uploaded.name.rsplit(".", 1)[-1].lower()
                raw_bytes = uploaded.read()

                with st.spinner(f"Reading {uploaded.name}…"):
                    if ext in ("xlsx", "xls"):
                        df_full = pd.read_excel(io.BytesIO(raw_bytes),
                                                dtype=str, keep_default_na=False)
                        df_full.columns = [c.strip() for c in df_full.columns]
                        df_sample  = df_full.head(_SAMPLE_ROWS)
                        src_cols   = list(df_full.columns)
                        total_rows = len(df_full)
                        file_path  = None
                    else:
                        text_data  = raw_bytes.decode("utf-8-sig", errors="replace")
                        first_line = text_data.split("\n")[0]
                        delim      = "|" if first_line.count("|") > first_line.count(",") else ","
                        # Read full CSV into memory for BULK INSERT
                        df_full    = pd.read_csv(io.StringIO(text_data), dtype=str,
                                                  sep=delim, keep_default_na=False)
                        df_full.columns = [c.strip() for c in df_full.columns]
                        df_sample  = df_full.head(_SAMPLE_ROWS)  # sample for ML/rules
                        src_cols   = list(df_full.columns)
                        total_rows = len(df_full)
                        file_path  = None
                        # Store full df for pipeline use
                        st.session_state.dvi_df_full = df_full

                st.session_state.update({
                    "dvi_filename":   uploaded.name,
                    "dvi_src_cols":   src_cols,
                    "dvi_df_sample":  df_sample,
                    "dvi_total_rows": total_rows,
                    "dvi_validation": None,
                    "dvi_stg_table":  None,
                    "dvi_result":     None,
                    "dvi_rules":      {},
                })

                fp = _load_fp(src_cols)
                if fp:
                    st.session_state.update({
                        "dvi_mapping":   fp["mapping"],
                        "dvi_target":    fp.get("target_table", "dv_well"),
                        "dvi_rules":     fp.get("rules", {}),
                        "dvi_fp_loaded": True,
                    })
                else:
                    with st.spinner("Detecting target table…"):
                        groups = detect_targets(src_cols, filename=uploaded.name)
                    st.session_state.update({
                        "dvi_groups":    groups,
                        "dvi_target":    groups[0].table if groups else "dv_well",
                        "dvi_mapping":   _build_mapping(groups[0], src_cols) if groups else [],
                        "dvi_fp_loaded": False,
                    })
                st.rerun()

            except Exception as e:
                st.error(f"Could not read file: {e}")
                return

        if st.session_state.dvi_filename:
            fp_loaded  = st.session_state.dvi_fp_loaded
            total_rows = st.session_state.dvi_total_rows
            src_cols   = st.session_state.dvi_src_cols

            st.success(
                f"✅ **{st.session_state.dvi_filename}** — "
                f"{total_rows:,} rows × {len(src_cols)} columns"
                + (" · 🔖 Fingerprint" if fp_loaded else ""))

            all_tables = _SchemaCache.loadable_tables()
            current    = st.session_state.dvi_target or "dv_well"
            tc1, tc2   = st.columns([4, 1])
            chosen = tc1.selectbox(
                "Target table", all_tables,
                index=all_tables.index(current) if current in all_tables else 0,
                key="dvi_target_sel")
            if not fp_loaded and st.session_state.dvi_groups:
                tc2.caption(f"🎯 {st.session_state.dvi_groups[0].confidence:.0%}")

            if chosen != st.session_state.dvi_target:
                st.session_state.dvi_target = chosen
                with st.spinner(f"Re-mapping for {chosen}…"):
                    groups = detect_targets(src_cols,
                                            filename=st.session_state.dvi_filename)
                grp = next((g for g in groups if g.table == chosen), None)
                if grp:
                    st.session_state.dvi_mapping = _build_mapping(grp, src_cols)
                st.session_state.dvi_fp_loaded = False
                st.rerun()

    if not st.session_state.dvi_filename:
        return

    target_table = st.session_state.dvi_target or "dv_well"
    mapping      = st.session_state.dvi_mapping or []
    df_sample    = st.session_state.dvi_df_sample
    src_cols     = st.session_state.dvi_src_cols
    fp_loaded    = st.session_state.dvi_fp_loaded

    # ── Section 2: Column Mapping ─────────────────────────────────────
    with st.expander("🗂 2 · Column Mapping", expanded=not fp_loaded):
        tgt_options = _col_options(target_table)
        valid_tgts  = set(tgt_options)
        orig_map    = {m["src"]: m for m in mapping}

        grid_df = pd.DataFrame([{
            "Source Column": m["src"],
            "Target Column": (m["target"] if m.get("target") in valid_tgts else "(skip)"),
            "Confidence":    ("🔵 corpus"  if m.get("method") == "corpus" and m.get("target")
                              else f"🟢 {m['confidence']:.0%}" if m["confidence"] >= CONF_AUTO and m.get("target")
                              else f"🟡 {m['confidence']:.0%}" if m["confidence"] >= CONF_MAYBE and m.get("target")
                              else "⬜ skip"),
        } for m in mapping])

        edited_grid = st.data_editor(
            grid_df,
            column_config={
                "Source Column": st.column_config.TextColumn(disabled=True, width="medium"),
                "Target Column": st.column_config.SelectboxColumn(options=tgt_options, width="medium"),
                "Confidence":    st.column_config.TextColumn(disabled=True, width="small"),
            },
            hide_index=True, use_container_width=True,
            num_rows="fixed", key="dvi_grid",
        )

        edited = [{
            "src":        row["Source Column"],
            "target":     row["Target Column"] if row["Target Column"] != "(skip)" else None,
            "data_type":  _get_dtype(target_table, row["Target Column"])
                          if row["Target Column"] != "(skip)" else "str",
            "confidence": orig_map.get(row["Source Column"], {}).get("confidence", 0),
            "method":     orig_map.get(row["Source Column"], {}).get("method", "keyword"),
        } for _, row in edited_grid.iterrows()]

        c1, c2 = st.columns(2)
        c1.metric("🟢 Mapped",  sum(1 for m in edited if m["target"]))
        c2.metric("⬜ Skipped", sum(1 for m in edited if not m["target"]))

        st.markdown("---")
        rc1, rc2 = st.columns([3, 1])
        use_emb = rc1.checkbox("Use sentence-transformers for re-mapping")
        if rc2.button("↺ Re-run ML", use_container_width=True):
            with st.spinner("Re-mapping…"):
                groups = detect_targets(src_cols,
                                        filename=st.session_state.dvi_filename,
                                        use_embeddings=use_emb)
            grp = next((g for g in groups if g.table == target_table), None)
            if grp:
                st.session_state.dvi_mapping = _build_mapping(grp, src_cols)
            st.rerun()

        fp_label = st.text_input(
            "Dataset label", value=st.session_state.get("dvi_fp_label_val", "KGS"),
            placeholder="e.g. KGS, RRC, NDIC", key="dvi_fp_label")
        st.session_state.dvi_fp_label_val = fp_label

        if st.button("💾 Save Mapping as Fingerprint", use_container_width=True):
            rules = st.session_state.get("dvi_rules", {})
            key   = _save_fp(src_cols, edited, target_table,
                             label=fp_label, rules=rules)
            save_to_corpus(edited, source_agency=fp_label,
                           source_file=st.session_state.dvi_filename)
            st.success(f"Saved — key `{key}`")

    # If fingerprint loaded, use saved mapping directly
    if fp_loaded:
        edited   = mapping
        fp_label = st.session_state.get("dvi_fp_label_val", "KGS")

    # ── Section 3: Rules Engine ───────────────────────────────────────
    # Note: cannot nest expanders — render inline with header
    st.markdown("#### ⚙️ 3 · Rules Engine")
    if fp_loaded:
        with st.expander("Rules loaded from fingerprint — click to review/edit",
                         expanded=False):
            fp_label = st.session_state.get("dvi_fp_label_val", "KGS")
            rules    = _render_rules(df_sample, edited, target_table, engine, fp_label)
    else:
        fp_label = st.session_state.get("dvi_fp_label_val", "KGS")
        rules    = _render_rules(df_sample, edited, target_table, engine, fp_label)

    # ── Section 4: Load ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🚀 Load")

    col_map     = {m["target"]: m["src"] for m in edited if m.get("target")}
    uwi_src     = col_map.get("uwi")
    source_name = rules.get("const_source", {}).get("value") or fp_label or "IMPORT"
    total_rows  = st.session_state.dvi_total_rows

    st.info(
        f"**{target_table}** · {total_rows:,} rows · source: **{source_name}**"
        + (f" · UWI: `{uwi_src}`" if uwi_src else " · ⚠️ no UWI mapped"))

    auto_promote = st.checkbox(
        "⚡ Auto-promote if validation passes (0 errors)",
        value=fp_loaded,
        help="Skips manual confirm step when no errors found")

    b1, b2 = st.columns([3, 1])
    run_clicked   = b1.button("🚀 Run Pipeline", type="primary",
                               use_container_width=True, disabled=not col_map)
    reset_clicked = b2.button("↺ Reset", use_container_width=True)

    if reset_clicked:
        for k in [k for k in st.session_state if k.startswith("dvi_")]:
            del st.session_state[k]
        # Clean up temp file
        fp = st.session_state.get("dvi_file_path")
        if fp:
            try:
                os.unlink(fp)
            except Exception:
                pass
        st.rerun()

    if run_clicked:
        st.session_state.dvi_validation = None
        st.session_state.dvi_result     = None
        # Pass ALL source columns in file order for staging
        # col_map handles target mapping at promote time
        _stg_cols = [m["src"] for m in edited if m.get("target")]
        _run_pipeline(
            engine, None, df_sample,
            _stg_cols, col_map,
            target_table, source_name, uwi_src,
            rules, auto_promote, total_rows,
        )

    # Validation report
    val = st.session_state.get("dvi_validation")
    stg = st.session_state.get("dvi_stg_table")

    if val and stg:
        _show_validation(val)

        if not (auto_promote and val.error_count == 0):
            st.markdown("---")
            reject_n = len(set(val.reject_row_ids))
            pc1, pc2 = st.columns([3, 1])
            if pc1.button(
                f"✅ Promote {val.clean_count:,} rows → `{target_table}`"
                + (f" · {reject_n:,} to rejection file" if reject_n else ""),
                type="primary", use_container_width=True,
                disabled=val.clean_count == 0):
                _run_promote(engine, stg, target_table, col_map,
                             rules, val, source_name, promote=True)
            if pc2.button("📁 Reject file only", use_container_width=True):
                _run_promote(engine, stg, target_table, col_map,
                             rules, val, source_name, promote=False)

    # Result
    result = st.session_state.get("dvi_result")
    if result:
        if result.get("ok"):
            total = result.get("total", 0)
            st.success(
                f"✅ **{result.get('inserted',0):,}** rows promoted · "
                f"**{result.get('rejected',0):,}** rejected · "
                f"⏱ **{_fmt_t(total)}** total")
            timing = result.get("timing", {})
            if timing:
                with st.expander("⏱ Stage timings", expanded=False):
                    for stage, secs in timing.items():
                        pct = secs / total * 100 if total else 0
                        st.caption(f"  {stage:<20} {_fmt_t(secs):>8}  ({pct:.0f}%)")
            if result.get("reject_file"):
                st.info(f"📁 Rejection file: `{result['reject_file']}`")
        else:
            st.error(f"Failed: {result.get('error','')}")

    # Fingerprints
    fps = _list_fps()
    if fps:
        with st.expander(f"💾 Saved Fingerprints ({len(fps)})", expanded=False):
            for fp in fps:
                st.caption(
                    f"**{fp.get('label','')}** · `{fp.get('target_table','?')}` · "
                    f"{fp.get('key','')} · {fp.get('saved','')[:10]} · "
                    f"{len(fp.get('cols',[]))} cols")

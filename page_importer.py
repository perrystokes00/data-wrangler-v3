"""
page_importer.py
================
DataView v3 — Universal Well Data Importer.
Clean rewrite — minimal imports at module level, everything else lazy.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# ── Path setup ────────────────────────────────────────────────────────
V3_ROOT = Path(__file__).parent
sys.path.insert(0, str(V3_ROOT))

# ── Constants ─────────────────────────────────────────────────────────
DB_OPTIONS  = ["DataView_Test", "DataView"]
CHUNK_SIZE  = 2000
SUPPORTED   = [".csv", ".txt", ".xlsx", ".xls", ".las", ".shp", ".json"]

SS_FMT      = "imp_fmt"
SS_ROWS     = "imp_rows"
SS_ERRORS   = "imp_errors"
SS_MAPPING  = "imp_mapping"
SS_FILE     = "imp_file_name"
SS_HISTORY  = "imp_history"

DV_FIELDS = [
    "— SKIP —",
    "uwi", "well_name", "well_num", "well_type", "well_status",
    "province_state", "country", "county",
    "operator_ba_id", "field_id",
    "final_td", "depth_datum",
    "spud_date", "completion_date", "api_num",
    "surface_latitude", "surface_longitude",
    "ground_elevation", "kb_elevation",
    "lease_name", "license_num",
    "active_ind", "source",
    "row_created_by", "row_changed_by",
    "_operator", "_field_name",
]

INSERT_COLS = [
    "uwi", "well_name", "well_type", "well_status",
    "province_state", "country", "county",
    "operator_ba_id", "field_id",
    "final_td", "depth_datum",
    "spud_date", "completion_date", "api_num",
    "surface_latitude", "surface_longitude",
    "active_ind", "source",
    "row_created_by", "row_changed_by",
]


# ── Main entry point ──────────────────────────────────────────────────

def render():
    st.title("📥 Universal Well Data Importer")
    st.caption("Drop any well data file — CSV, LAS, Excel, Shapefile, or fixed-width.")

    # Init session state
    for key in (SS_FMT, SS_ROWS, SS_ERRORS, SS_MAPPING, SS_FILE):
        if key not in st.session_state:
            st.session_state[key] = None
    if SS_HISTORY not in st.session_state:
        st.session_state[SS_HISTORY] = []

    # Load format library — show error inline if it fails
    lib = _get_library()
    if lib is None:
        st.error("Format library failed to load — check format_library/ folder exists.")
        return

    # ── Sidebar ───────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("---")
        st.caption("IMPORTER")
        st.caption("**Known Formats**")
        for fmt in lib.formats:
            icon = "🟢" if fmt["tier"] == 1 else "🟡"
            st.caption(f"{icon} {fmt['display_name']}")
        if st.session_state[SS_HISTORY]:
            st.markdown("---")
            st.caption("**Recent Loads**")
            for h in reversed(st.session_state[SS_HISTORY][-3:]):
                st.caption(f"{h['time']} · {h['file']} · {h['inserted']:,} rows · {h['db']}")

    # ── Tabs ──────────────────────────────────────────────────────────
    t1, t2, t3, t4 = st.tabs([
        "1 · Upload & Detect",
        "2 · Column Mapping",
        "3 · Load",
        "4 · Register Format",
    ])

    with t1:
        _tab_upload(lib)
    with t2:
        _tab_mapping()
    with t3:
        _tab_load()
    with t4:
        _tab_register(lib)


# ── Tab 1: Upload & Detect ────────────────────────────────────────────

def _tab_upload(lib):
    st.subheader("Upload File")

    uploaded = st.file_uploader(
        "Drop your well data file here",
        type=[e.lstrip(".") for e in SUPPORTED],
    )

    if not uploaded:
        st.info("Upload a file to begin.")
        _show_format_table(lib)
        return

    suffix = Path(uploaded.name).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    st.session_state[SS_FILE] = uploaded.name

    # Detect
    with st.spinner("Detecting format..."):
        fmt = lib.detect(tmp_path)

    if fmt:
        st.success(f"✅ Detected: **{fmt['display_name']}** (Tier {fmt['tier']})")
        st.session_state[SS_FMT] = fmt

        c1, c2, c3 = st.columns(3)
        c1.metric("Format", fmt["format_id"])
        c2.metric("Vendor",  fmt["vendor"])
        c3.metric("Tier",    fmt["tier"])

        # Parse
        with st.spinner("Parsing..."):
            try:
                rows, errors = lib.read(fmt, tmp_path)
            except Exception as e:
                st.error(f"Parse error: {e}")
                os.unlink(tmp_path)
                return

        st.session_state[SS_ROWS]   = rows
        st.session_state[SS_ERRORS] = errors

        c4, c5 = st.columns(2)
        c4.metric("Rows parsed",  f"{len(rows):,}")
        c5.metric("Parse errors", len(errors))

        if errors:
            with st.expander(f"⚠️ {len(errors)} parse errors"):
                for e in errors[:20]:
                    st.caption(e)

        if rows:
            preview_cols = [k for k in rows[0] if not k.startswith("_")]
            st.dataframe(
                pd.DataFrame(rows[:50])[preview_cols],
                use_container_width=True,
                height=280,
            )
            st.info("Go to **Column Mapping** tab to review, then **Load** to insert.")

    else:
        st.warning("⚠️ Format not recognised. Running ML column mapper...")
        st.session_state[SS_FMT] = None
        try:
            from importer.format_detective import detect as fd_detect
            from importer.column_mapper    import ColumnMapper
            dr     = fd_detect(tmp_path)
            mapper = ColumnMapper(
                schema_path=V3_ROOT / "schema_registry" / "dataview_schema_domain.json"
            )
            with st.spinner("Mapping columns..."):
                result = mapper.map(dr)
            st.session_state[SS_MAPPING] = result
            st.success(
                f"Mapped {len(result.auto_mapped)} automatically. "
                f"{len(result.flagged)} need review. "
                f"{len(result.unmapped)} unmapped."
            )
            st.info("Go to **Column Mapping** tab to review and confirm.")
        except Exception as e:
            st.error(f"ML mapping failed: {e}")

    try:
        os.unlink(tmp_path)
    except Exception:
        pass


# ── Tab 2: Column Mapping ─────────────────────────────────────────────

def _tab_mapping():
    st.subheader("Column Mapping")

    fmt    = st.session_state.get(SS_FMT)
    rows   = st.session_state.get(SS_ROWS) or []
    result = st.session_state.get(SS_MAPPING)

    if not fmt and not result:
        st.info("Upload a file first.")
        return

    if fmt:
        # Known format — editable grid pre-populated from registry
        st.success(f"✅ **{fmt['display_name']}** — registered Tier {fmt['tier']} format")

        inbound   = fmt.get("inbound", {})
        field_map = inbound.get("field_map", {})

        if field_map and field_map != "direct":
            data = []
            for src_col, tgt in field_map.items():
                data.append({
                    "Source Column": src_col,
                    "Target Field":  tgt if tgt else "— SKIP —",
                    "Sample Values": _sample(rows, src_col),
                })

            c1, c2 = st.columns(2)
            c1.metric("Mapped",  sum(1 for d in data if d["Target Field"] != "— SKIP —"))
            c2.metric("Skipped", sum(1 for d in data if d["Target Field"] == "— SKIP —"))

            st.caption("Override any mapping using the **Target Field** dropdown.")
            edited = st.data_editor(
                pd.DataFrame(data),
                column_config={
                    "Target Field":  st.column_config.SelectboxColumn(
                        "Target Field", options=DV_FIELDS, required=True, width="medium"),
                    "Source Column": st.column_config.TextColumn(
                        "Source Column", disabled=True, width="medium"),
                    "Sample Values": st.column_config.TextColumn(
                        "Sample Values", disabled=True, width="large"),
                },
                use_container_width=True,
                height=500,
                hide_index=True,
                key="grid_known",
            )

            if st.button("✅ Confirm Mapping", type="primary", key="btn_known"):
                override = {}
                for _, row in edited.iterrows():
                    tgt = row["Target Field"]
                    override[row["Source Column"]] = None if tgt == "— SKIP —" else tgt
                st.session_state["imp_map_override"] = override
                st.success("✅ Confirmed. Go to **Load** tab.")
        else:
            st.info("Direct passthrough — columns match schema 1:1.")
            st.caption(f"{len(rows):,} rows ready to load.")

    elif result:
        # ML-mapped unknown format
        st.warning("⚠️ Unknown format — review ML mapping below then confirm.")

        data = []
        for m in result.mappings:
            status = "✅ Auto" if m.auto else ("⚠️ Review" if m.flagged else "❌ Unmapped")
            data.append({
                "Source Column": m.source_col,
                "Target Field":  m.target_field if m.target_field else "— SKIP —",
                "Confidence":    f"{m.confidence:.0%}",
                "Status":        status,
                "Sample Values": ", ".join(m.sample_values[:3]),
            })

        c1, c2, c3 = st.columns(3)
        c1.metric("Auto",    sum(1 for d in data if d["Status"] == "✅ Auto"))
        c2.metric("Review",  sum(1 for d in data if d["Status"] == "⚠️ Review"))
        c3.metric("Unmapped",sum(1 for d in data if d["Status"] == "❌ Unmapped"))

        edited = st.data_editor(
            pd.DataFrame(data),
            column_config={
                "Target Field":  st.column_config.SelectboxColumn(
                    "Target Field", options=DV_FIELDS, required=True, width="medium"),
                "Source Column": st.column_config.TextColumn(
                    "Source Column", disabled=True, width="medium"),
                "Confidence":    st.column_config.TextColumn(
                    "Confidence",   disabled=True, width="small"),
                "Status":        st.column_config.TextColumn(
                    "Status",       disabled=True, width="small"),
                "Sample Values": st.column_config.TextColumn(
                    "Sample Values",disabled=True, width="large"),
            },
            use_container_width=True,
            height=500,
            hide_index=True,
            key="grid_ml",
        )

        if st.button("✅ Confirm Mapping", type="primary", key="btn_ml"):
            from importer.column_mapper import ColumnMapping
            new_mappings = []
            for _, row in edited.iterrows():
                tgt = row["Target Field"]
                tgt = None if tgt == "— SKIP —" else tgt
                try:
                    conf = float(str(row.get("Confidence", "0%")).strip("%")) / 100
                except ValueError:
                    conf = 0.0
                new_mappings.append(ColumnMapping(
                    source_col=row["Source Column"],
                    target_field=tgt,
                    confidence=conf,
                    method="confirmed",
                    auto=True,
                    flagged=False,
                ))
            result.mappings = new_mappings
            try:
                from importer.column_mapper import ColumnMapper
                mapper = ColumnMapper(
                    schema_path=V3_ROOT / "schema_registry" / "dataview_schema_domain.json"
                )
                mapper.confirm(result)
            except Exception:
                pass
            st.session_state[SS_MAPPING] = result
            st.success("✅ Confirmed and fingerprint saved. Go to **Load** tab.")


# ── Tab 3: Load ───────────────────────────────────────────────────────

def _tab_load():
    st.subheader("Load to Database")

    # DB selector — unique key, defaults to DataView_Test
    target_db = st.selectbox(
        "Target Database",
        DB_OPTIONS,
        key="imp_target_db",
        index=0,  # DataView_Test is first in list
    )

    db_color = "🟢" if "Test" in target_db else "🔴"
    st.info(f"{db_color} **Loading into: {target_db}**")

    rows  = st.session_state.get(SS_ROWS) or []
    fmt   = st.session_state.get(SS_FMT)
    fname = st.session_state.get(SS_FILE) or "unknown"

    if not rows:
        st.warning("No data ready — upload and parse a file in Tab 1 first.")
        return

    # Stats
    uwis    = [r.get("uwi") for r in rows if r.get("uwi")]
    unique  = len(set(uwis))
    dupes   = len(uwis) - unique

    c1, c2, c3 = st.columns(3)
    c1.metric("Rows parsed",     f"{len(rows):,}")
    c2.metric("Unique UWIs",     f"{unique:,}")
    c3.metric("Duplicates",      f"{dupes:,}")

    if dupes:
        st.caption("Duplicates will be deduplicated before load.")

    dry_run = st.checkbox("Dry run (no DB writes)", value=False)

    if st.button("🚀 Load Data", type="primary"):
        _execute_load(rows, fmt, target_db, fname, dry_run)


def _execute_load(rows, fmt, target_db, fname, dry_run):
    from dw_utils import make_engine, dedup

    rows = dedup(rows)

    if dry_run:
        st.info(f"DRY RUN — {len(rows):,} unique rows would load into {target_db}")
        st.dataframe(
            pd.DataFrame(rows[:10])[[k for k in rows[0] if not k.startswith("_")]],
            use_container_width=True,
        )
        return

    engine   = make_engine(target_db)
    progress = st.progress(0, text="Starting...")
    log_box  = st.empty()
    msgs     = []

    def log(msg):
        msgs.append(msg)
        log_box.text("\n".join(msgs[-8:]))

    # ── Seed reference + spatial + entity tables ──────────────────────
    try:
        from spatial_seeder import seed_spatial
        seed_spatial(engine, loader_tag="IMPORTER")
        log("✓ Spatial tables seeded")
    except Exception as e:
        log(f"⚠ Spatial seeding: {e}")

    try:
        from entity_seeder import seed_entities
        source_val = fmt.get("inbound", {}).get("source_value", "IMPORT") if fmt else "IMPORT"
        rows = seed_entities(rows, engine, source=source_val, loader_tag="IMPORTER")
        log("✓ Entities seeded")
    except Exception as e:
        log(f"⚠ Entity seeding: {e}")

    # ── Split new vs existing ─────────────────────────────────────────
    from sqlalchemy import text
    with engine.connect() as con:
        existing = set(
            pd.read_sql(text("SELECT uwi FROM dataview.dv_well"), con)["uwi"].tolist()
        )

    new_rows    = [r for r in rows if r.get("uwi") not in existing]
    update_rows = [r for r in rows if r.get("uwi") in existing]
    log(f"New: {len(new_rows):,}  |  Update: {len(update_rows):,}")

    inserted = errored = updated = 0

    # ── Insert new rows ───────────────────────────────────────────────
    if new_rows:
        col_list     = ", ".join(f"[{c}]" for c in INSERT_COLS)
        placeholders = ", ".join("?" * len(INSERT_COLS))
        sql = (
            f"IF NOT EXISTS (SELECT 1 FROM dataview.dv_well WHERE [uwi]=?)\n"
            f"INSERT INTO dataview.dv_well ({col_list}) VALUES ({placeholders})"
        )
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.fast_executemany = True
            for i in range(0, len(new_rows), CHUNK_SIZE):
                batch  = new_rows[i:i+CHUNK_SIZE]
                params = [
                    tuple([r["uwi"]] + [r.get(c) for c in INSERT_COLS])
                    for r in batch
                ]
                try:
                    cursor.executemany(sql, params)
                    raw_conn.commit()
                    inserted += len(batch)
                    pct = min(int(inserted / max(len(new_rows), 1) * 85), 85)
                    progress.progress(pct, text=f"Inserting {inserted:,} / {len(new_rows):,}...")
                    log(f"Inserted {inserted:,} / {len(new_rows):,}")
                except Exception as e:
                    raw_conn.rollback()
                    errored += len(batch)
                    log(f"Chunk error: {e}")
            cursor.close()
        finally:
            raw_conn.close()

    # ── Update existing rows ──────────────────────────────────────────
    if update_rows:
        update_sql = """
            UPDATE dataview.dv_well SET
                well_status       = COALESCE(?, well_status),
                final_td          = COALESCE(?, final_td),
                spud_date         = COALESCE(?, spud_date),
                completion_date   = COALESCE(?, completion_date),
                operator_ba_id    = COALESCE(NULLIF(?,''), operator_ba_id),
                field_id          = COALESCE(NULLIF(?,''), field_id),
                surface_latitude  = COALESCE(?, surface_latitude),
                surface_longitude = COALESCE(?, surface_longitude),
                row_changed_by    = ?,
                row_changed_date  = GETDATE()
            WHERE uwi = ?
        """
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.fast_executemany = True
            for i in range(0, len(update_rows), CHUNK_SIZE):
                batch  = update_rows[i:i+CHUNK_SIZE]
                params = [
                    (
                        r.get("well_status"),    r.get("final_td"),
                        r.get("spud_date"),      r.get("completion_date"),
                        r.get("operator_ba_id"), r.get("field_id"),
                        r.get("surface_latitude"), r.get("surface_longitude"),
                        "IMPORTER", r["uwi"],
                    )
                    for r in batch
                ]
                cursor.executemany(update_sql, params)
                raw_conn.commit()
                updated += len(batch)
                log(f"Updated {updated:,} / {len(update_rows):,}")
            cursor.close()
        finally:
            raw_conn.close()

    progress.progress(100, text="Done!")

    if errored:
        st.warning(f"⚠️ Inserted {inserted:,} · Updated {updated:,} · Errored {errored:,}")
    else:
        st.success(f"✅ Inserted **{inserted:,}** · Updated **{updated:,}**")

    st.session_state[SS_HISTORY].append({
        "time":     datetime.now().strftime("%H:%M"),
        "file":     fname,
        "inserted": inserted,
        "updated":  updated,
        "db":       target_db,
    })

    # Clear for next load
    for key in (SS_ROWS, SS_ERRORS, SS_FMT, SS_MAPPING):
        st.session_state[key] = None


# ── Tab 4: Register Format ────────────────────────────────────────────

def _tab_register(lib):
    st.subheader("Register a New Format")
    result = st.session_state.get(SS_MAPPING)

    if not result or not getattr(result, "confirmed", False):
        st.info("Complete and confirm an ML mapping in Tab 2 first, then return here.")
        return

    with st.form("register_fmt"):
        fmt_id   = st.text_input("Format ID",       placeholder="ok_occ_well_header")
        disp_nm  = st.text_input("Display Name",    placeholder="Oklahoma OCC Well Header")
        vendor   = st.text_input("Vendor / Agency", placeholder="Oklahoma Corporation Commission")
        src_val  = st.text_input("Source value",    placeholder="OCC")
        pattern  = st.text_input("File pattern",    placeholder="*.csv")
        conf_by  = st.text_input("Confirmed by",    value="perry")
        submit   = st.form_submit_button("📌 Register Format", type="primary")

    if submit:
        if not all([fmt_id, disp_nm, vendor, src_val]):
            st.error("Format ID, Display Name, Vendor and Source value are required.")
            return
        field_map = {m.source_col: m.target_field for m in result.mappings if m.target_field}
        detection = {"type": result.file_type, "fingerprint": result.fingerprint}
        try:
            lib.register_format(
                format_id=fmt_id, display_name=disp_nm, vendor=vendor,
                detection=detection, field_map=field_map,
                file_patterns=[pattern] if pattern else [],
                source_value=src_val, confirmed_by=conf_by,
            )
            st.success(f"✅ Registered **{disp_nm}** as `{fmt_id}`")
        except Exception as e:
            st.error(f"Registration failed: {e}")


# ── Helpers ───────────────────────────────────────────────────────────

@st.cache_resource
def _get_library():
    try:
        from format_library.format_library import FormatLibrary
        return FormatLibrary(
            registry_path=V3_ROOT / "format_library" / "format_registry.json"
        )
    except Exception as e:
        return None


def _sample(rows: list[dict], col: str) -> str:
    vals = []
    for r in rows[:10]:
        v = r.get(col)
        if v is not None and str(v).strip():
            vals.append(str(v)[:30])
        if len(vals) >= 3:
            break
    return ", ".join(vals)


def _show_format_table(lib):
    st.subheader("Registered Formats")
    data = [
        {
            "Format":  f["display_name"],
            "Tier":    f["tier"],
            "Vendor":  f["vendor"],
            "In":      "✓",
            "Out":     "✓" if f.get("outbound", {}).get("format") else "—",
        }
        for f in lib.formats
    ]
    st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)


# ── Standalone ────────────────────────────────────────────────────────

if __name__ == "__main__":
    st.set_page_config(page_title="Data Importer", layout="wide")
    render()

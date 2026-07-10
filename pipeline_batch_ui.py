r"""
pipeline_batch_ui.py — read-only status + reprocess panel for the loader.

Shows the pipeline funnel (Catalogued / Captured / Promoted / Remaining) and a
Reprocess-stuck button. It does NOT run the pipeline in-process — that deadlocks
against the run's own connections and freezes the Streamlit page. For processing,
use "Run Pipeline (headless)" above with its Batch mode toggle (inventory all,
then process N at a time) — a separate process that tails live and can't freeze
the app.

Usage (from your pipeline page):
    import pipeline_batch_ui
    pipeline_batch_ui.render(engine)
"""
import os as _os, sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
for _p in (_HERE, _os.path.dirname(_HERE)):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import streamlit as st
from sqlalchemy import text


def _counts(engine):
    with engine.connect() as c:
        f = lambda q: c.execute(text(q)).scalar() or 0
        catalogued = f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG "
                       "WHERE ISNULL(FLAG_DELETE,'N')<>'Y' AND DUPLICATE_GROUP IS NULL")
        # 'Captured' must count files that WENT THROUGH capture — but cat_well is a
        # STAGING table that DRAINS into dv_well on promote, so a live cat_well count
        # collapses to near-zero after a successful promote. Count the durable signal
        # instead: files stamped CAPTURED_HASH (capture ran) — this survives promote.
        captured = f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG "
                     "WHERE CAPTURED_HASH IS NOT NULL "
                     "AND ISNULL(FLAG_DELETE,'N')<>'Y' AND DUPLICATE_GROUP IS NULL")
        promoted = f("SELECT COUNT(*) FROM dataview.dv_well")
        # 'Stuck' = extracted but NEVER captured. Must EXCLUDE files whose cat_well
        # rows already PROMOTED to dv_well (that's success, not a stuck run). Key off
        # CAPTURED_HASH: a captured file has it set even after its cat_* rows drain.
        stuck = f("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG "
                  "WHERE HEADER_EXTRACTED='Y' AND CAPTURED_HASH IS NULL "
                  "AND ISNULL(FLAG_DELETE,'N')<>'Y' AND DUPLICATE_GROUP IS NULL "
                  "AND LOWER(FILE_EXT) IN ('.las','.pdf','.xlsx','.xls','.docx','.doc','.xml','.json')")
    return {"catalogued": catalogued, "captured": captured, "promoted": promoted,
            "stuck": stuck, "remaining": max(0, catalogued - captured)}


def render(engine):
    st.subheader("Pipeline — status")
    try:
        c = _counts(engine)
    except Exception as e:
        st.caption(f"(status unavailable: {e})")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Catalogued", f"{c['catalogued']:,}")
    m2.metric("Captured", f"{c['captured']:,}")
    m3.metric("Promoted", f"{c['promoted']:,}")
    m4.metric("Remaining", f"{c['remaining']:,}")
    st.progress(min(1.0, c["captured"] / max(1, c["catalogued"])),
                text=f"{c['captured']:,} / {c['catalogued']:,} captured")

    st.caption("To load/process files, use **Run Pipeline (headless)** above with "
               "**Batch mode** (inventory all, then process N at a time). It runs in a "
               "separate process — no UI freeze, live log. This panel is your live "
               "scoreboard; hit Refresh to update it.")

    col1, col2 = st.columns(2)
    if col1.button("↻ Refresh status", use_container_width=True):
        st.rerun()

    if c["stuck"]:
        st.warning(f"{c['stuck']:,} file(s) extracted but not captured "
                   f"(aborted/deadlocked run).")
        if col2.button(f"🔁 Reprocess {c['stuck']:,} stuck", use_container_width=True):
            try:
                with engine.begin() as con:
                    nr = con.execute(text(
                        "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                        "SET HEADER_EXTRACTED='N', CATALOG_READINESS=NULL, "
                        "ROW_CHANGED_DATE=GETUTCDATE() "
                        "WHERE HEADER_EXTRACTED='Y' AND INVENTORY_ID NOT IN "
                        "(SELECT INVENTORY_ID FROM file_catalog.cat_well "
                        " WHERE INVENTORY_ID IS NOT NULL)")).rowcount
                st.success(f"Reset {nr} stuck file(s) — re-run the headless pipeline.")
            except Exception as e:
                st.error(str(e)[:300])
            st.rerun()

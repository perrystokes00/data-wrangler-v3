"""
current_run_scorecard.py — a per-RUN scorecard (what THIS pipeline run just did),
complementing the cumulative 'Inventory vs processed' which sums all crawls ever.

Scopes to the current run by a run-start timestamp (UTC) captured in session state
when Run pipeline is clicked. Counts, per file type, files whose GLOBAL_FILE_CATALOG
SCAN_DATE >= run-start (seen this run) and how far each got THIS run — extracted,
captured, vaulted, promoted — using the per-run stamps (VAULTED_AT / PROMOTED_AT and
the cat_* CAPTURED_AT lineage).

Render after a run:
    from dataview.file_catalog.current_run_scorecard import render as render_run_scorecard
    render_run_scorecard(engine, st, since=st.session_state.get("fp_run_started"))
"""
from __future__ import annotations
from sqlalchemy import text


def _doc_promoted_cte(con):
    """INVENTORY_IDs whose document data reached dv_* (same idea as the cumulative
    scorecard's docs credit) — used to mark document files promoted this run."""
    tables = ("dv_well_formation_top", "dv_well_dir_srvy_hdr", "dv_well_dir_srvy_sta",
              "dv_well_completion", "dv_prod_volume", "dv_well_log", "dv_well_log_curve")
    parts = []
    for t in tables:
        try:
            ok = con.execute(text(
                "SELECT CASE WHEN OBJECT_ID(:o) IS NOT NULL AND EXISTS("
                "SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(:o) "
                "AND name='INVENTORY_ID') THEN 1 ELSE 0 END"), {"o": f"dataview.{t}"}).scalar()
            if ok:
                parts.append(f"SELECT INVENTORY_ID FROM dataview.{t} WITH (NOLOCK) "
                             f"WHERE INVENTORY_ID IS NOT NULL")
        except Exception:
            pass
    return parts


def render(engine, st, since=None):
    """Render the current-run scorecard. `since` is the UTC run-start string/datetime;
    if None, we can't scope to a run and show a hint instead."""
    import pandas as pd
    st.markdown("#### 🟢 This run — files processed")
    if not since:
        st.caption("Run a pipeline to see a per-run breakdown here. "
                   "(The table above is cumulative across all crawls.)")
        return

    # small grace buffer: shift the window back 2 minutes so a few seconds of clock
    # skew between the Python run-start stamp (UTC) and the SQL scan write doesn't
    # exclude files this run legitimately scanned.
    try:
        from datetime import datetime as _dt, timedelta as _td
        _s = _dt.strptime(str(since)[:19], "%Y-%m-%d %H:%M:%S") - _td(minutes=2)
        since = _s.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    with engine.connect() as con:
        # seismic-promoted this run (survey identity landed in dv_seis_set)
        try:
            seis_ok = con.execute(text(
                "SELECT CASE WHEN OBJECT_ID('dataview.dv_seis_set') IS NOT NULL "
                "AND OBJECT_ID('file_catalog.FILE_SEIS_HEADER') IS NOT NULL "
                "THEN 1 ELSE 0 END")).scalar() == 1
        except Exception:
            seis_ok = False
        seis_cte = ("seis_done AS (SELECT DISTINCT sh.INVENTORY_ID "
                    "FROM file_catalog.FILE_SEIS_HEADER sh WITH (NOLOCK) "
                    "JOIN dataview.dv_seis_set ss ON ss.seis_set_name = sh.SURVEY_NAME) "
                    ) if seis_ok else ""
        doc_parts = _doc_promoted_cte(con)
        doc_cte = ("docs_done AS (SELECT DISTINCT INVENTORY_ID FROM ("
                   + " UNION ALL ".join(doc_parts) + ") _u) ") if doc_parts else ""
        ctes = [c for c in (seis_cte, doc_cte) if c]
        with_clause = ("WITH " + ", ".join(ctes) + " ") if ctes else ""
        seis_join = "LEFT JOIN seis_done sd ON sd.INVENTORY_ID = g.INVENTORY_ID " if seis_cte else ""
        doc_join  = "LEFT JOIN docs_done dd ON dd.INVENTORY_ID = g.INVENTORY_ID " if doc_cte else ""
        seis_or = "OR sd.INVENTORY_ID IS NOT NULL " if seis_cte else ""
        doc_or  = "OR dd.INVENTORY_ID IS NOT NULL " if doc_cte else ""

        sql = text(f"""
            {with_clause}SELECT
                ISNULL(NULLIF(g.FILE_EXT,''),'(none)')                          AS [type],
                COUNT(*)                                                         AS seen_this_run,
                SUM(CASE WHEN g.HEADER_EXTRACTED='Y' THEN 1 ELSE 0 END)          AS extracted,
                SUM(CASE WHEN g.CATALOG_READINESS='CATALOGED' {seis_or}{doc_or}THEN 1 ELSE 0 END) AS cataloged,
                SUM(CASE WHEN g.VAULTED_AT  >= TRY_CAST(:since AS DATETIME2) THEN 1 ELSE 0 END)         AS vaulted,
                SUM(CASE WHEN g.PROMOTED_AT >= TRY_CAST(:since AS DATETIME2) {seis_or}{doc_or}THEN 1 ELSE 0 END) AS promoted,
                SUM(CASE WHEN g.HEADER_EXTRACTED IS NULL OR g.HEADER_EXTRACTED IN ('N','')
                         THEN 1 ELSE 0 END)                                      AS pending
            FROM file_catalog.GLOBAL_FILE_CATALOG g WITH (NOLOCK)
            {seis_join}{doc_join}
            WHERE COALESCE(TRY_CAST(g.ROW_CHANGED_DATE AS DATETIME2), TRY_CAST(g.SCAN_DATE AS DATETIME2)) >= TRY_CAST(:since AS DATETIME2)
            GROUP BY ISNULL(NULLIF(g.FILE_EXT,''),'(none)')
            ORDER BY seen_this_run DESC
        """)
        try:
            rows = con.execute(sql, {"since": since}).fetchall()
        except Exception as exc:
            st.caption(f"(per-run scorecard unavailable: {str(exc)[:100]})")
            return

    if not rows:
        st.caption("No files scanned in this run window.")
        return
    df = pd.DataFrame(rows, columns=["type", "seen this run", "extracted",
                                     "cataloged", "vaulted", "promoted", "pending"])
    st.dataframe(df, hide_index=True, use_container_width=True)
    tot = int(df["seen this run"].sum())
    prom = int(df["promoted"].sum())
    st.caption(f"This run touched {tot:,} file(s); {prom:,} reached dv_*. "
               f"Scoped to files changed/processed since the run started.")

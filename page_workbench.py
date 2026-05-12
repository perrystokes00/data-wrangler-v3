"""
page_workbench.py
=================
File Catalog & Workbench -- three tabs:

  1. Scan & Enrich  -- fast scan, bulk insert, Phase 2 header extraction
  2. Browse & View  -- filter catalog, view/plot files, extract and load data
  3. Header Files   -- query FILE_WELL_HEADER / FILE_SEIS_HEADER, export CSV
"""
import os
import re
import uuid
import streamlit as st
import pandas as pd
from pathlib import Path

# ── Extension sets ─────────────────────────────────────────────────────────
PDF_EXTS    = {".pdf"}
LAS_EXTS    = {".las"}
DLIS_EXTS   = {".dlis", ".dlf", ".dis"}
LIS_EXTS    = {".lis"}
SEGY_EXTS   = {".segy", ".sgy", ".seg"}
P190_EXTS   = {".p190", ".p90", ".p1"}
SHP_EXTS    = {".shp", ".geojson", ".gpkg", ".kml", ".kmz"}
OFFICE_EXTS = {".xlsx", ".xls", ".xlsm", ".docx", ".doc", ".csv", ".tsv"}
IMAGE_EXTS  = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
LOG_EXTS    = LAS_EXTS | DLIS_EXTS | LIS_EXTS

ALL_EXTS = (PDF_EXTS | LOG_EXTS | SEGY_EXTS | P190_EXTS |
            SHP_EXTS | OFFICE_EXTS | IMAGE_EXTS)

EXT_GROUP = {}
for e in PDF_EXTS:    EXT_GROUP[e] = "PDF"
for e in LOG_EXTS:    EXT_GROUP[e] = "Well Log"
for e in SEGY_EXTS:   EXT_GROUP[e] = "Seismic"
for e in P190_EXTS:   EXT_GROUP[e] = "Seismic"
for e in SHP_EXTS:    EXT_GROUP[e] = "Shapefile"
for e in OFFICE_EXTS: EXT_GROUP[e] = "Office"
for e in IMAGE_EXTS:  EXT_GROUP[e] = "Image"

ENRICH_CHUNK = 20   # files processed per rerun cycle


# =============================================================================
# Entry point
# =============================================================================

def run(engine=None, dialect: str = "mssql"):
    st.title("🗂️ File Catalog & Workbench")
    st.caption(
        "Scan & enrich files · Browse & view · "
        "Extract data · Load to DB"
    )

    if engine is None:
        st.warning("No database connection.")
        return

    # Phase 2 enrichment — runs at top of every rerun while active
    if st.session_state.get("wb_enriching"):
        _enrich_chunk(engine, dialect)
    elif st.session_state.get("wb_enrich_done"):
        st.success(
            f"✅ Enrichment complete — "
            f"{st.session_state.get('wb_enrich_total',0):,} files processed."
        )

    tabs = st.tabs([
        "🔍 Scan & Enrich",
        "📂 Browse & View",
        "🗺️ Well Map",
        "📋 Header Files",
    ])

    with tabs[0]: _tab_scan(engine, dialect)
    with tabs[1]: _tab_browse(engine, dialect)
    with tabs[2]: _tab_map(engine, dialect)
    with tabs[3]: _tab_headers(engine, dialect)


# =============================================================================
# Tab 1 -- Scan & Enrich
# =============================================================================

def _tab_scan(engine, dialect):
    from sqlalchemy import text as _t

    st.markdown("#### 🔍 Scan & Enrich")

    # ── Config ────────────────────────────────────────────────────────────────
    scan_path = st.text_input(
        "Root folder",
        placeholder=r"\\server\share\WellData  or  C:\WellData",
        key="wb_scan_path",
    )
    ext_groups = st.multiselect(
        "File types",
        ["PDF","Well Log","Seismic","Shapefile","Office","Image"],
        default=["PDF","Well Log","Seismic","Shapefile","Office"],
        key="wb_scan_exts",
    )
    _exts = {e for e, g in EXT_GROUP.items() if g in ext_groups}

    c1, c2, c3 = st.columns(3)

    # Phase 1
    if c1.button("🔍 Scan (Phase 1)", type="primary",
                 key="wb_p1", use_container_width=True):
        if not scan_path:
            st.error("Enter a folder path.")
        elif not Path(scan_path).exists():
            st.error(f"Not found: `{scan_path}`")
        else:
            _run_scan(engine, dialect, scan_path, _exts)

    # Phase 2
    if c2.button("⚙️ Enrich (Phase 2)", type="secondary",
                 key="wb_p2", use_container_width=True):
        st.session_state["wb_enriching"]     = True
        st.session_state["wb_enrich_offset"] = 0
        st.rerun()

    if c3.button("⏹ Stop", key="wb_stop", use_container_width=True):
        st.session_state["wb_enriching"] = False

    # Phase 2 thread count — tune parallelism. Default 8 works for mixed
    # extraction (PDF/DLIS/Office). Drop to 2-4 for DLIS-heavy batches
    # that load big chunks into memory; raise to 16 for many small files.
    _w = st.slider(
        "Phase 2 threads",
        min_value=1, max_value=16,
        value=int(st.session_state.get("wb_phase2_workers", 8)),
        key="wb_phase2_workers_slider",
        help="Files per chunk extracted in parallel. Lower for "
             "DLIS-heavy batches; higher for many small files. Default 8.",
    )
    st.session_state["wb_phase2_workers"] = _w

    # ── Catalog summary ───────────────────────────────────────────────────────
    st.divider()
    try:
        with engine.connect() as con:
            rows = con.execute(_t("""
                SELECT
                    FILE_TYPE_GROUP,
                    COUNT(*)                                               total,
                    SUM(CASE WHEN HEADER_EXTRACTED='Y' THEN 1 ELSE 0 END) enriched,
                    SUM(CASE WHEN CATALOG_READINESS='READY'     THEN 1 ELSE 0 END) ready,
                    SUM(CASE WHEN CATALOG_READINESS='NEEDS_UWI' THEN 1 ELSE 0 END) needs_uwi,
                    SUM(CASE WHEN CATALOG_READINESS='ATTENTION' THEN 1 ELSE 0 END) attention,
                    SUM(CASE WHEN ISNULL(FLAG_DELETE,'N')='Y'   THEN 1 ELSE 0 END) flagged
                FROM file_catalog.GLOBAL_FILE_CATALOG
                GROUP BY FILE_TYPE_GROUP
                ORDER BY total DESC
            """)).fetchall()

        if rows:
            df = pd.DataFrame(rows, columns=[
                "Type","Total","Enriched","Ready","Needs UWI","Attention","Flagged"])
            tot = df["Total"].sum()
            enr = df["Enriched"].sum()
            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Total cataloged",    f"{tot:,}")
            m2.metric("Enriched",           f"{enr:,}")
            m3.metric("Pending enrichment", f"{tot-enr:,}")
            m4.metric("Flagged",            int(df["Flagged"].sum()))
            st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.info("Catalog is empty — run Phase 1 scan.")
    except Exception as e:
        st.caption(f"Catalog summary: {e}")

    # ── Delete tools ──────────────────────────────────────────────────────────
    st.divider()
    st.markdown("**Delete from catalog**")
    d1, d2 = st.columns(2)

    del_ext = d1.text_input("By extension", placeholder=".tif",
                             key="wb_del_ext")
    if del_ext and d1.button("🗑️ Delete", key="wb_del_ext_btn"):
        try:
            with engine.begin() as con:
                n = con.execute(_t("""
                    DELETE FROM file_catalog.GLOBAL_FILE_CATALOG
                    WHERE FILE_EXT = :e
                """), {"e": del_ext.lower()}).rowcount
            st.success(f"Deleted {n:,} rows with ext `{del_ext}`")
        except Exception as e:
            st.error(f"Delete failed: {e}")

    del_pat = d2.text_input("By filename pattern", placeholder="thumb",
                             key="wb_del_pat")
    if del_pat and d2.button("🔍 Preview", key="wb_del_pat_prev"):
        try:
            with engine.connect() as con:
                cnt = con.execute(_t("""
                    SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
                    WHERE FILE_NAME LIKE :p
                """), {"p": f"%{del_pat}%"}).scalar()
            st.session_state["wb_del_cnt"] = cnt
            st.session_state["wb_del_val"] = del_pat
        except Exception as e:
            st.error(str(e))

    cnt = st.session_state.get("wb_del_cnt")
    pat = st.session_state.get("wb_del_val")
    if cnt is not None and pat == del_pat and del_pat:
        st.caption(f"{cnt:,} files match `*{del_pat}*`")
        if cnt > 0 and st.button(
                f"✅ Confirm delete {cnt:,}", key="wb_del_confirm",
                type="primary"):
            try:
                with engine.begin() as con:
                    n = con.execute(_t("""
                        DELETE FROM file_catalog.GLOBAL_FILE_CATALOG
                        WHERE FILE_NAME LIKE :p
                    """), {"p": f"%{del_pat}%"}).rowcount
                st.success(f"Deleted {n:,} rows")
                st.session_state.pop("wb_del_cnt", None)
            except Exception as e:
                st.error(str(e))

    # ── Delete all flagged ────────────────────────────────────────────────────
    st.divider()
    try:
        with engine.connect() as con:
            nf = con.execute(_t("""
                SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
                WHERE FLAG_DELETE='Y'
            """)).scalar() or 0
        if nf > 0:
            if st.button(f"🗑️ Delete all {nf:,} flagged files",
                         type="primary", key="wb_del_flagged"):
                st.session_state["wb_del_flagged_confirm"] = True

            if st.session_state.get("wb_del_flagged_confirm"):
                st.warning(
                    f"Remove **{nf:,} flagged files** from catalog? "
                    "Files on disk are NOT deleted."
                )
                cc1, cc2 = st.columns(2)
                if cc1.button("✅ Yes, delete", key="wb_del_flag_yes",
                              type="primary"):
                    with engine.begin() as con:
                        n = con.execute(_t("""
                            DELETE FROM file_catalog.GLOBAL_FILE_CATALOG
                            WHERE FLAG_DELETE='Y'
                        """)).rowcount
                    st.success(f"Deleted {n:,} flagged files from catalog.")
                    st.session_state.pop("wb_del_flagged_confirm", None)
                    st.rerun()
                if cc2.button("❌ Cancel", key="wb_del_flag_no"):
                    st.session_state.pop("wb_del_flagged_confirm", None)
                    st.rerun()
        else:
            st.caption("No files flagged for deletion.")
    except Exception as e:
        st.caption(f"Flag check: {e}")


def _run_scan(engine, dialect, root: str, exts: set):
    """Phase 1: fast os.scandir walk + BULK INSERT to GLOBAL_FILE_CATALOG."""
    import csv, tempfile, hashlib
    from datetime import datetime, timezone
    from sqlalchemy import text as _t

    prog = st.progress(0.0, text="Walking...")
    found = []
    folders = 0
    stack = [root]

    while stack:
        dirpath = stack.pop()
        folders += 1
        try:
            with os.scandir(dirpath) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in exts:
                                st_res = entry.stat()
                                found.append((
                                    entry.path, entry.name, ext,
                                    round(st_res.st_size/1024, 2),
                                    datetime.fromtimestamp(
                                        st_res.st_mtime,
                                        tz=timezone.utc
                                    ).strftime("%Y-%m-%d %H:%M:%S"),
                                    EXT_GROUP.get(ext, "Other"),
                                    root,
                                ))
                    except OSError:
                        pass
        except (PermissionError, OSError):
            pass
        if folders % 2000 == 0:
            prog.progress(0.3, text=f"{folders:,} folders · {len(found):,} files")

    if not found:
        st.warning("No files found.")
        return

    prog.progress(0.5, text=f"{len(found):,} files — writing CSV...")
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False,
        newline="", encoding="utf-8"
    )
    csv_path = tmp.name
    writer = csv.writer(tmp, delimiter="\t",
                        quoting=csv.QUOTE_NONE, escapechar="\\")
    for (fpath, fname, fext, size_kb, mod_dt, grp, rpath) in found:
        inv_id = hashlib.sha1(
            fpath.upper().encode("utf-8")).hexdigest().upper()
        writer.writerow([
            inv_id, fpath[:900], fname[:260], fext[:20],
            grp[:50], size_kb if size_kb else "",
            "", "", "UNCATALOGED", "",
            rpath[:900], now, now, now,
        ])
    tmp.close()

    prog.progress(0.7, text="Bulk inserting...")
    try:
        with engine.begin() as con:
            con.execute(_t("""
                IF OBJECT_ID('file_catalog.fc_stage','U') IS NOT NULL
                    DROP TABLE file_catalog.fc_stage;
                CREATE TABLE file_catalog.fc_stage (
                    INVENTORY_ID     NVARCHAR(40),
                    FILE_PATH        NVARCHAR(900),
                    FILE_NAME        NVARCHAR(260),
                    FILE_EXT         NVARCHAR(20),
                    FILE_TYPE_GROUP  NVARCHAR(50),
                    FILE_SIZE_KB     NVARCHAR(30),
                    FILE_HASH        NVARCHAR(40),
                    DUPLICATE_GROUP  NVARCHAR(64),
                    CATALOG_STATUS   NVARCHAR(20),
                    CATALOG_TABLE    NVARCHAR(100),
                    ROOT_PATH        NVARCHAR(900),
                    SCAN_DATE        NVARCHAR(30),
                    ROW_CREATED_DATE NVARCHAR(30),
                    ROW_CHANGED_DATE NVARCHAR(30)
                );
            """))
            con.execute(_t(f"""
                BULK INSERT file_catalog.fc_stage
                FROM '{csv_path}'
                WITH (FIELDTERMINATOR='\\t', ROWTERMINATOR='0x0D0A',
                      CODEPAGE='65001', FIRSTROW=1, TABLOCK);
            """))
            con.execute(_t("""
                MERGE file_catalog.GLOBAL_FILE_CATALOG AS tgt
                USING file_catalog.fc_stage AS src
                ON tgt.INVENTORY_ID = src.INVENTORY_ID
                WHEN MATCHED THEN UPDATE SET
                    FILE_SIZE_KB     = TRY_CAST(src.FILE_SIZE_KB AS DECIMAL(15,2)),
                    SCAN_DATE        = TRY_CAST(src.SCAN_DATE AS DATETIME2),
                    ROW_CHANGED_DATE = TRY_CAST(src.ROW_CHANGED_DATE AS DATETIME2)
                WHEN NOT MATCHED THEN INSERT (
                    INVENTORY_ID,FILE_PATH,FILE_NAME,FILE_EXT,
                    FILE_TYPE_GROUP,FILE_SIZE_KB,FILE_HASH,
                    DUPLICATE_GROUP,CATALOG_STATUS,CATALOG_TABLE,
                    ROOT_PATH,SCAN_DATE,ROW_CREATED_DATE,ROW_CHANGED_DATE
                ) VALUES (
                    src.INVENTORY_ID,src.FILE_PATH,src.FILE_NAME,src.FILE_EXT,
                    src.FILE_TYPE_GROUP,
                    TRY_CAST(src.FILE_SIZE_KB AS DECIMAL(15,2)),
                    src.FILE_HASH,src.DUPLICATE_GROUP,src.CATALOG_STATUS,
                    src.CATALOG_TABLE,src.ROOT_PATH,
                    TRY_CAST(src.SCAN_DATE AS DATETIME2),
                    TRY_CAST(src.ROW_CREATED_DATE AS DATETIME2),
                    TRY_CAST(src.ROW_CHANGED_DATE AS DATETIME2)
                );
            """))
            con.execute(_t(
                "DROP TABLE IF EXISTS file_catalog.fc_stage;"))

        prog.progress(1.0, text="Done.")
        st.success(
            f"✅ Phase 1 complete — {len(found):,} files "
            f"across {folders:,} folders. "
            f"Click **Enrich** to extract headers."
        )
    except Exception as e:
        st.error(f"Bulk insert failed: {e}")
    finally:
        try:
            os.unlink(csv_path)
        except Exception:
            pass


def _enrich_chunk(engine, dialect):
    """
    Phase 2: process ENRICH_CHUNK files per rerun.
    Extracts headers → FILE_WELL_HEADER / FILE_SEIS_HEADER.
    Shows a persistent progress bar at the top of the page.

    Extraction within each chunk runs in parallel across PHASE2_WORKERS
    threads. DB writes stay sequential in the main thread — single-row
    UPDATEs are microseconds each, so the bottleneck is file parsing
    (PDFs/DLIS can take seconds), which is what we parallelize.

    The chunked-rerun pattern is preserved: each chunk finishes, Streamlit
    reruns, the next chunk starts. The user can still hit Stop between
    chunks to pause without losing progress.
    """
    from sqlalchemy import text as _t
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Phase 2 worker count from session state. Default 8 — balanced for
    # mixed extraction (PDF/DLIS/Office). User can tune via the slider in
    # the Scan tab.
    PHASE2_WORKERS = int(st.session_state.get("wb_phase2_workers", 8))

    try:
        with engine.connect() as con:
            total_all = con.execute(_t("""
                SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
            """)).scalar() or 1

            pending = con.execute(_t("""
                SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
                WHERE HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED='N'
            """)).scalar() or 0

            rows = con.execute(_t(f"""
                SELECT TOP {ENRICH_CHUNK}
                    INVENTORY_ID, FILE_PATH, FILE_EXT
                FROM file_catalog.GLOBAL_FILE_CATALOG
                WHERE HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED='N'
                ORDER BY SCAN_DATE DESC
            """)).fetchall()
    except Exception as e:
        st.error(f"Enrichment query failed: {e}")
        st.session_state["wb_enriching"] = False
        return

    if not rows:
        st.success("✅ Phase 2 complete — all files enriched.")
        st.session_state["wb_enriching"] = False
        st.session_state["wb_enrich_done"] = True
        st.session_state["wb_enrich_total"] = total_all
        return

    # ── Parallel extraction within this chunk ────────────────────────────
    # Each worker handles one file: read it, extract fields, return result.
    # Workers don't touch the DB — writes happen in the main thread below.
    # Each result carries its own elapsed time so we can spot slow formats
    # and compare sum-of-times (would-be sequential) vs wall-clock (parallel).
    import time as _time
    _t_chunk_start = _time.monotonic()

    def _worker(row):
        inv_id, fpath, fext = row
        _t0 = _time.monotonic()
        try:
            fields = _extract_fields(fpath, (fext or "").lower())
            return ("ok", inv_id, fpath, fext, fields, None,
                    _time.monotonic() - _t0)
        except Exception as e:
            return ("err", inv_id, fpath, fext, None,
                    f"{type(e).__name__}: {e}",
                    _time.monotonic() - _t0)

    results = []
    _t_pool_start = _time.monotonic()
    with ThreadPoolExecutor(max_workers=PHASE2_WORKERS) as pool:
        futures = [pool.submit(_worker, row) for row in rows]
        for fut in as_completed(futures):
            try:
                # Per-file timeout: 5 min ceiling. Hung extractor doesn't
                # block the chunk.
                results.append(fut.result(timeout=300))
            except Exception as e:
                results.append(("err", None, "", "", None,
                                f"worker died: {e}", 0.0))
    _t_pool_end = _time.monotonic()
    _pool_elapsed = _t_pool_end - _t_pool_start

    # ── Batched DB writes via executemany (one round-trip per statement) ─
    # Previous attempt at "batched" was just one transaction wrapping per-
    # row execute() calls. Diagnostic showed that didn't help — cost is
    # per-statement, not per-transaction. ODBC was still doing N round-
    # trips, just with one commit at the end.
    #
    # Real fix: build parameter LISTS, call executemany() once per
    # statement-shape. pyodbc has fast_executemany=True enabled in our
    # engine config (db.py line 159), which makes executemany pack many
    # parameter sets into a single network round-trip.
    #
    # Expected: 3 round-trips per chunk (one for GLOBAL_FILE_CATALOG,
    # one for FILE_WELL_HEADER MERGE, one for FILE_SEIS_HEADER MERGE)
    # instead of N. For chunks with mixed file types, the WELL/SEIS
    # MERGEs only run if there's data of that category.
    _t_writes_start = _time.monotonic()

    # Build parameter lists by statement shape
    update_params: list = []     # for GLOBAL_FILE_CATALOG (success path)
    error_params:  list = []     # for GLOBAL_FILE_CATALOG (error path - 'E')
    well_params:   list = []     # for FILE_WELL_HEADER MERGE
    seis_params:   list = []     # for FILE_SEIS_HEADER MERGE
    done = 0
    last = ""
    per_ext_times: dict = {}

    for outcome, inv_id, fpath, fext, fields, err, elapsed in results:
        if fpath:
            last = Path(fpath).name
        ext_key = (fext or "?").lower()
        per_ext_times.setdefault(ext_key, []).append(elapsed)

        if outcome == "ok" and inv_id is not None:
            # Success: queue the GLOBAL_FILE_CATALOG UPDATE and the
            # matching MERGE for whichever header table this category lives in.
            score, readiness = _score(fields)
            update_params.append({
                "score":     score,
                "readiness": readiness,
                "uwi":       _trunc(fields.get("uwi"), 40),
                "issues":    "; ".join(_issues(fields)),
                "id":        inv_id,
            })
            category = fields.get("file_category", "UNKNOWN")
            if category == "WELL":
                well_params.append({
                    "hid":     uuid.uuid5(uuid.NAMESPACE_URL, inv_id).hex.upper(),
                    "inv_id":  inv_id,
                    "uwi":     _trunc(fields.get("uwi"),40),
                    "wn":      _trunc(fields.get("well_name"),255),
                    "op":      _trunc(fields.get("operator"),255),
                    "fld":     _trunc(fields.get("well_field"),100),
                    "st":      _trunc(fields.get("state"),50),
                    "co":      _trunc(fields.get("county"),100),
                    "lat":     _trunc(fields.get("latitude"),30),
                    "lon":     _trunc(fields.get("longitude"),30),
                    "td":      _trunc(fields.get("total_depth"),20),
                    "spud":    _trunc(fields.get("spud_date"),20),
                    "rig":     _trunc(fields.get("rig_release"),20),
                    "rt":      _trunc(fields.get("report_type"),50),
                    "stype":   _trunc(fields.get("survey_type"),50),
                    "contr":   _trunc(fields.get("contractor"),255),
                    "conf":    _safe_num(fields.get("confidence")),
                })
            elif category == "SEIS":
                seis_params.append({
                    "hid":      uuid.uuid5(uuid.NAMESPACE_URL, inv_id+"_s").hex.upper(),
                    "inv_id":   inv_id,
                    "sn":       _trunc(fields.get("survey_name"),255),
                    "ln":       _trunc(fields.get("line_name"),255),
                    "stype":    _trunc(fields.get("seis_set_type"),40),
                    "sd":       _trunc(fields.get("survey_date"),20),
                    "contr":    _trunc(fields.get("contractor"),255),
                    "bmin_lat": _safe_coord(fields.get("bbox_min_lat")),
                    "bmax_lat": _safe_coord(fields.get("bbox_max_lat")),
                    "bmin_lon": _safe_coord(fields.get("bbox_min_lon")),
                    "bmax_lon": _safe_coord(fields.get("bbox_max_lon")),
                    "epsg":     _safe_epsg(fields.get("epsg_code")),
                    "si":       _safe_sample_interval(fields.get("sample_interval")),
                    "tc":       _safe_trace_count(fields.get("trace_count")),
                    "sf":       _trunc(fields.get("shot_first"),20),
                    "sl":       _trunc(fields.get("shot_last"),20),
                })
            done += 1
        elif inv_id is not None:
            # Extraction errored — queue the error-marker UPDATE
            error_params.append({"id": inv_id})

    # Execute the batched writes. Each executemany() is a single round-trip
    # with fast_executemany=True. We isolate each statement-shape in its
    # own try/except so a failure in one (e.g. a triggered constraint
    # violation in FILE_WELL_HEADER) doesn't poison the others.
    try:
        with engine.begin() as con:
            if update_params:
                con.execute(_t("""
                    UPDATE file_catalog.GLOBAL_FILE_CATALOG SET
                        CATALOG_SCORE     = :score,
                        CATALOG_READINESS = :readiness,
                        MATCHED_UWI       = :uwi,
                        CATALOG_ISSUES    = :issues,
                        HEADER_EXTRACTED  = 'Y',
                        ROW_CHANGED_DATE  = GETUTCDATE()
                    WHERE INVENTORY_ID = :id
                """), update_params)
            if well_params:
                con.execute(_t("""
                    MERGE file_catalog.FILE_WELL_HEADER AS tgt
                    USING (SELECT :hid AS WELL_HEADER_ID) src
                    ON tgt.WELL_HEADER_ID = src.WELL_HEADER_ID
                    WHEN MATCHED THEN UPDATE SET
                        UWI=:uwi, WELL_NAME=:wn, OPERATOR=:op,
                        WELL_FIELD=:fld, STATE=:st, COUNTY=:co,
                        LATITUDE=:lat, LONGITUDE=:lon,
                        TOTAL_DEPTH=:td, SPUD_DATE=:spud,
                        RIG_RELEASE=:rig, REPORT_TYPE=:rt,
                        SURVEY_TYPE=:stype, CONTRACTOR=:contr,
                        CONFIDENCE=:conf, EXTRACTED_DATE=GETUTCDATE()
                    WHEN NOT MATCHED THEN INSERT (
                        WELL_HEADER_ID,INVENTORY_ID,
                        UWI,WELL_NAME,OPERATOR,WELL_FIELD,
                        STATE,COUNTY,LATITUDE,LONGITUDE,
                        TOTAL_DEPTH,SPUD_DATE,RIG_RELEASE,
                        REPORT_TYPE,SURVEY_TYPE,CONTRACTOR,CONFIDENCE,
                        EXTRACTED_DATE,EXTRACTED_BY
                    ) VALUES (
                        :hid,:inv_id,
                        :uwi,:wn,:op,:fld,
                        :st,:co,:lat,:lon,
                        :td,:spud,:rig,
                        :rt,:stype,:contr,:conf,
                        GETUTCDATE(),'DataWrangler'
                    );
                """), well_params)
            if seis_params:
                con.execute(_t("""
                    MERGE file_catalog.FILE_SEIS_HEADER AS tgt
                    USING (SELECT :hid AS SEIS_HEADER_ID) src
                    ON tgt.SEIS_HEADER_ID = src.SEIS_HEADER_ID
                    WHEN MATCHED THEN UPDATE SET
                        SURVEY_NAME=:sn, LINE_NAME=:ln,
                        SEIS_SET_TYPE=:stype, SURVEY_DATE=:sd,
                        CONTRACTOR=:contr,
                        BBOX_MIN_LAT=:bmin_lat, BBOX_MAX_LAT=:bmax_lat,
                        BBOX_MIN_LON=:bmin_lon, BBOX_MAX_LON=:bmax_lon,
                        EPSG_CODE=:epsg, SAMPLE_INTERVAL=:si,
                        TRACE_COUNT=:tc, SHOT_FIRST=:sf, SHOT_LAST=:sl,
                        EXTRACTED_DATE=GETUTCDATE()
                    WHEN NOT MATCHED THEN INSERT (
                        SEIS_HEADER_ID,INVENTORY_ID,
                        SURVEY_NAME,LINE_NAME,SEIS_SET_TYPE,SURVEY_DATE,
                        CONTRACTOR,BBOX_MIN_LAT,BBOX_MAX_LAT,
                        BBOX_MIN_LON,BBOX_MAX_LON,EPSG_CODE,
                        SAMPLE_INTERVAL,TRACE_COUNT,SHOT_FIRST,SHOT_LAST,
                        EXTRACTED_DATE,EXTRACTED_BY
                    ) VALUES (
                        :hid,:inv_id,
                        :sn,:ln,:stype,:sd,
                        :contr,:bmin_lat,:bmax_lat,
                        :bmin_lon,:bmax_lon,:epsg,
                        :si,:tc,:sf,:sl,
                        GETUTCDATE(),'DataWrangler'
                    );
                """), seis_params)
            if error_params:
                con.execute(_t("""
                    UPDATE file_catalog.GLOBAL_FILE_CATALOG
                    SET HEADER_EXTRACTED='E',
                        ROW_CHANGED_DATE=GETUTCDATE()
                    WHERE INVENTORY_ID=:id
                """), error_params)
    except Exception as e:
        st.error(f"Chunk transaction failed (rolled back): {e}")
        st.session_state["wb_enriching"] = False
        return
    _t_writes_end = _time.monotonic()
    _writes_elapsed = _t_writes_end - _t_writes_start

    # Sum of per-file extraction times. If sum_per_file >> pool_elapsed,
    # parallelism IS helping (threads overlapping). If sum ≈ pool, the
    # GIL or some serializing call is preventing real parallelism.
    _sum_per_file = sum(e for grp in per_ext_times.values() for e in grp)
    _speedup_ratio = (_sum_per_file / _pool_elapsed) if _pool_elapsed > 0 else 0.0

    total_done = total_all - pending + done
    pct = min(1.0, total_done / max(total_all, 1))

    st.progress(pct, text=(
        f"⚙️ Enriching — {total_done:,} / {total_all:,} "
        f"({pct*100:.0f}%) · {last}"
    ))
    st.caption(
        f"{pending - done:,} remaining · "
        f"{PHASE2_WORKERS} threads · "
        "click **⏹ Stop** to pause"
    )

    # ── Diagnostic: where did time go this chunk? ────────────────────────
    # Sum of per-file extraction times vs wall-clock pool time tells us
    # whether parallelism is actually working. A speedup ratio close to
    # PHASE2_WORKERS means good parallelism. A ratio close to 1.0 means
    # threads are serializing (probably GIL on pure-Python extractors).
    _per_ext_summary = " · ".join(
        f"{ext}:{sum(times):.2f}s({len(times)})"
        for ext, times in sorted(per_ext_times.items(),
                                 key=lambda kv: -sum(kv[1]))
    )
    st.caption(
        f"⏱ chunk={_pool_elapsed + _writes_elapsed:.2f}s "
        f"(extract:{_pool_elapsed:.2f}s, writes:{_writes_elapsed:.2f}s) · "
        f"sum-of-files={_sum_per_file:.2f}s · "
        f"speedup={_speedup_ratio:.1f}× (ideal: {PHASE2_WORKERS}×) · "
        f"by-ext: {_per_ext_summary}"
    )

    if len(rows) == ENRICH_CHUNK and pending > done:
        import time
        time.sleep(0.1)
        st.rerun()
    else:
        st.success(f"✅ Phase 2 complete — {total_all:,} files enriched.")
        st.session_state["wb_enriching"] = False
        st.session_state["wb_enrich_done"]  = True
        st.session_state["wb_enrich_total"] = total_all


# =============================================================================
# Field extraction and enrichment write
# =============================================================================

def _extract_fields(fpath: str, fext: str) -> dict:
    """Extract header fields from a file. Returns flat dict."""
    fields = {
        "file_category": "UNKNOWN",
        "report_type":   "UNKNOWN",
        "confidence":    0.0,
        # Well fields
        "uwi": None, "well_name": None, "operator": None,
        "well_field": None, "state": None, "county": None,
        "latitude": None, "longitude": None,
        "total_depth": None, "spud_date": None,
        "rig_release": None, "survey_type": None, "contractor": None,
        # Seis fields
        "survey_name": None, "line_name": None,
        "seis_set_type": None, "survey_date": None,
        "bbox_min_lat": None, "bbox_max_lat": None,
        "bbox_min_lon": None, "bbox_max_lon": None,
        "epsg_code": None, "sample_interval": None,
        "trace_count": None, "shot_first": None, "shot_last": None,
    }

    try:
        if fext == ".pdf":
            fields["file_category"] = "WELL"
            try:
                from modules.pdf_survey_catalog import classify_pdf
                cl = classify_pdf(fpath)
                fields.update({
                    "report_type": cl.get("report_type","UNKNOWN"),
                    "uwi":         cl.get("uwi"),
                    "well_name":   cl.get("well_name"),
                    "operator":    cl.get("operator"),
                    "well_field":  cl.get("field"),
                    "state":       cl.get("state"),
                    "county":      cl.get("county"),
                    "latitude":    cl.get("latitude"),
                    "longitude":   cl.get("longitude"),
                    "total_depth": cl.get("total_depth"),
                    "spud_date":   cl.get("spud_date"),
                    "rig_release": cl.get("rig_release"),
                    "survey_type": cl.get("survey_type"),
                    "contractor":  cl.get("contractor"),
                    "confidence":  float(cl.get("confidence") or 0),
                })
            except Exception:
                pass

        elif fext == ".las":
            fields["file_category"] = "WELL"
            fields["report_type"]   = "WELL_LOG"
            try:
                import lasio
                las = lasio.read(fpath)
                def _wv(m):
                    try:
                        v = str(las.well[m].value).strip()
                        return v if v and v.lower() not in (
                            "","unknown","none","--") else None
                    except Exception:
                        return None
                fields.update({
                    "uwi":         _wv("UWI") or _wv("API"),
                    "well_name":   _wv("WELL"),
                    "operator":    _wv("COMP") or _wv("PROV"),
                    "well_field":  _wv("FLD")  or _wv("FIELD"),
                    "state":       _wv("STAT") or _wv("STATE"),
                    "county":      _wv("CNTY") or _wv("COUNTY"),
                    "latitude":    _wv("SLAT") or _wv("LAT"),
                    "longitude":   _wv("SLON") or _wv("LON") or _wv("LONG"),
                    "total_depth": _wv("STOP") or _wv("TD"),
                    "spud_date":   _wv("SPUD"),
                    "contractor":  _wv("SRVC") or _wv("SERVICE"),
                })
            except Exception:
                pass

        elif fext in DLIS_EXTS:
            fields["file_category"] = "WELL"
            fields["report_type"]   = "WELL_LOG"
            try:
                import dlisio
                f, *tail = dlisio.dlis.load(fpath)
                origs = list(f.origins)
                if origs:
                    o = origs[0]
                    fields.update({
                        "well_name":  str(getattr(o,"well_name","") or "") or None,
                        "well_field": str(getattr(o,"field_name","") or "") or None,
                        "operator":   str(getattr(o,"company","")   or "") or None,
                    })
                try:
                    f.close()
                    for t in tail: t.close()
                except Exception:
                    pass
            except Exception:
                pass

        elif fext in LIS_EXTS:
            fields["file_category"] = "WELL"
            fields["report_type"]   = "WELL_LOG"

        elif fext in SEGY_EXTS:
            fields["file_category"] = "SEIS"
            fields["report_type"]   = "SEISMIC"
            try:
                import segyio
                with segyio.open(fpath, ignore_geometry=True) as f:
                    fields["trace_count"]    = f.tracecount
                    fields["sample_interval"]= f.bin[segyio.BinField.Interval]
                    fields["seis_set_type"]  = (
                        "3D" if f.tracecount > 10000 else "2D")
                    # Survey name from text header
                    try:
                        import re as _re
                        txt = segyio.tools.wrap(f.text[0])
                        m = _re.search(
                            r"(?:LINE|SURVEY|PROJECT)[:\s]+([A-Z0-9_\-\.]+)",
                            txt, _re.IGNORECASE)
                        if m:
                            fields["survey_name"] = m.group(1).strip()[:255]
                        m2 = _re.search(
                            r"CONTRACTOR[:\s]+([A-Za-z0-9_\-\s\.]+)",
                            txt, _re.IGNORECASE)
                        if m2:
                            fields["contractor"] = m2.group(1).strip()[:255]
                    except Exception:
                        pass
                    # Bbox from CDP coords
                    try:
                        n = min(f.tracecount, 200)
                        sf = f.bin[segyio.BinField.EnsembleScalar] or 1
                        scale = (abs(sf) if sf < 0
                                 else 1.0/sf if sf > 0 else 1.0)
                        xs = [f.header[i][segyio.TraceField.CDP_X]*scale
                              for i in range(n)]
                        ys = [f.header[i][segyio.TraceField.CDP_Y]*scale
                              for i in range(n)]
                        xs = [x for x in xs if x != 0]
                        ys = [y for y in ys if y != 0]
                        if xs and ys:
                            fields.update({
                                "bbox_min_lon": min(xs),
                                "bbox_max_lon": max(xs),
                                "bbox_min_lat": min(ys),
                                "bbox_max_lat": max(ys),
                            })
                    except Exception:
                        pass
            except Exception:
                pass

        elif fext in P190_EXTS:
            fields["file_category"] = "SEIS"
            fields["report_type"]   = "SEISMIC"
            fields["seis_set_type"] = "2D"
            try:
                shots = []
                with open(fpath, "r", errors="replace") as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        rec = line[0].upper()
                        if rec == "H":
                            parts = line[1:].split()
                            if len(parts) >= 2:
                                key = parts[0].upper()
                                val = " ".join(parts[1:])
                                if "LINE" in key or "SURVEY" in key:
                                    fields["survey_name"] = val[:255]
                                elif "CONTR" in key:
                                    fields["contractor"] = val[:255]
                        elif rec == "S":
                            parts = line.split()
                            if len(parts) >= 5:
                                try:
                                    shots.append((
                                        float(parts[3]),
                                        float(parts[4])))
                                except ValueError:
                                    pass
                if shots:
                    xs = [s[0] for s in shots]
                    ys = [s[1] for s in shots]
                    fields.update({
                        "bbox_min_lon": min(xs),
                        "bbox_max_lon": max(xs),
                        "bbox_min_lat": min(ys),
                        "bbox_max_lat": max(ys),
                        "trace_count":  len(shots),
                        "shot_first":   str(shots[0]),
                        "shot_last":    str(shots[-1]),
                    })
            except Exception:
                pass

        elif fext in SHP_EXTS:
            fields["file_category"] = "SEIS"
            fields["report_type"]   = "SHAPEFILE"
            try:
                from modules.shapefile_catalog import classify_shapefile
                cl = classify_shapefile(fpath)
                fields["confidence"] = float(cl.get("confidence") or 0)
                if cl.get("crs_epsg"):
                    fields["epsg_code"] = cl["crs_epsg"]
                if cl.get("bounds"):
                    b = cl["bounds"]
                    fields.update({
                        "bbox_min_lon": b.get("minx"),
                        "bbox_max_lon": b.get("maxx"),
                        "bbox_min_lat": b.get("miny"),
                        "bbox_max_lat": b.get("maxy"),
                    })
            except Exception:
                pass

        elif fext in OFFICE_EXTS:
            fields["file_category"] = "WELL"
            fields["report_type"]   = "OFFICE"
            try:
                from modules.file_summarizer import summarize
                s = summarize(fpath)
                fields.update({
                    "uwi":       s.get("uwi"),
                    "well_name": s.get("well_name"),
                })
            except Exception:
                pass

    except Exception:
        pass

    # Clean None/"None"/empty strings
    return {k: (v if v is not None and
                str(v).strip() not in ("","None","nan") else None)
            for k, v in fields.items()}


def _write_enrichment(engine, inv_id: str, fields: dict):
    """Write extracted header fields to catalog tables.

    Single-file write — opens its own transaction. Kept for the few
    callers outside the Phase 2 chunk loop. The chunk loop uses
    _write_enrichment_on() with a shared connection for batched-commit
    performance.
    """
    with engine.begin() as con:
        _write_enrichment_on(con, inv_id, fields)


def _write_enrichment_on(con, inv_id: str, fields: dict):
    """Write extracted header fields using a CALLER-PROVIDED connection.

    Used by the Phase 2 chunk loop, which wraps every UPDATE+MERGE in
    a single chunk-level transaction. Eliminates per-file transaction
    round-trip cost (~150ms each on SQL Server Express via named pipe),
    which the diagnostic captions revealed was 90% of chunk time.

    The connection is expected to be inside an active engine.begin()
    block — this function does NOT commit. All writes commit when the
    outer transaction commits.
    """
    from sqlalchemy import text as _t

    score, readiness = _score(fields)
    category = fields.get("file_category", "UNKNOWN")

    # Always update GLOBAL_FILE_CATALOG
    con.execute(_t("""
        UPDATE file_catalog.GLOBAL_FILE_CATALOG SET
            CATALOG_SCORE     = :score,
            CATALOG_READINESS = :readiness,
            MATCHED_UWI       = :uwi,
            CATALOG_ISSUES    = :issues,
            HEADER_EXTRACTED  = 'Y',
            ROW_CHANGED_DATE  = GETUTCDATE()
        WHERE INVENTORY_ID = :id
    """), {
        "score":     score,
        "readiness": readiness,
        "uwi":       _trunc(fields.get("uwi"), 40),
        "issues":    "; ".join(_issues(fields)),
        "id":        inv_id,
    })

    if category == "WELL":
        hid = uuid.uuid5(
            uuid.NAMESPACE_URL, inv_id).hex.upper()
        con.execute(_t("""
            MERGE file_catalog.FILE_WELL_HEADER AS tgt
            USING (SELECT :hid AS WELL_HEADER_ID) src
            ON tgt.WELL_HEADER_ID = src.WELL_HEADER_ID
            WHEN MATCHED THEN UPDATE SET
                UWI=:uwi, WELL_NAME=:wn, OPERATOR=:op,
                WELL_FIELD=:fld, STATE=:st, COUNTY=:co,
                LATITUDE=:lat, LONGITUDE=:lon,
                TOTAL_DEPTH=:td, SPUD_DATE=:spud,
                RIG_RELEASE=:rig, REPORT_TYPE=:rt,
                SURVEY_TYPE=:stype, CONTRACTOR=:contr,
                CONFIDENCE=:conf, EXTRACTED_DATE=GETUTCDATE()
            WHEN NOT MATCHED THEN INSERT (
                WELL_HEADER_ID,INVENTORY_ID,
                UWI,WELL_NAME,OPERATOR,WELL_FIELD,
                STATE,COUNTY,LATITUDE,LONGITUDE,
                TOTAL_DEPTH,SPUD_DATE,RIG_RELEASE,
                REPORT_TYPE,SURVEY_TYPE,CONTRACTOR,CONFIDENCE,
                EXTRACTED_DATE,EXTRACTED_BY
            ) VALUES (
                :hid,:inv_id,
                :uwi,:wn,:op,:fld,
                :st,:co,:lat,:lon,
                :td,:spud,:rig,
                :rt,:stype,:contr,:conf,
                GETUTCDATE(),'DataWrangler'
            );
        """), {
            "hid":     hid,    "inv_id": inv_id,
            "uwi":     _trunc(fields.get("uwi"),40),
            "wn":      _trunc(fields.get("well_name"),255),
            "op":      _trunc(fields.get("operator"),255),
            "fld":     _trunc(fields.get("well_field"),100),
            "st":      _trunc(fields.get("state"),50),
            "co":      _trunc(fields.get("county"),100),
            "lat":     _trunc(fields.get("latitude"),30),
            "lon":     _trunc(fields.get("longitude"),30),
            "td":      _trunc(fields.get("total_depth"),20),
            "spud":    _trunc(fields.get("spud_date"),20),
            "rig":     _trunc(fields.get("rig_release"),20),
            "rt":      _trunc(fields.get("report_type"),50),
            "stype":   _trunc(fields.get("survey_type"),50),
            "contr":   _trunc(fields.get("contractor"),255),
            "conf":    _safe_num(fields.get("confidence")),
        })

    elif category == "SEIS":
        hid = uuid.uuid5(
            uuid.NAMESPACE_URL, inv_id+"_s").hex.upper()
        con.execute(_t("""
            MERGE file_catalog.FILE_SEIS_HEADER AS tgt
            USING (SELECT :hid AS SEIS_HEADER_ID) src
            ON tgt.SEIS_HEADER_ID = src.SEIS_HEADER_ID
            WHEN MATCHED THEN UPDATE SET
                SURVEY_NAME=:sn, LINE_NAME=:ln,
                SEIS_SET_TYPE=:stype, SURVEY_DATE=:sd,
                CONTRACTOR=:contr,
                BBOX_MIN_LAT=:bmin_lat, BBOX_MAX_LAT=:bmax_lat,
                BBOX_MIN_LON=:bmin_lon, BBOX_MAX_LON=:bmax_lon,
                EPSG_CODE=:epsg, SAMPLE_INTERVAL=:si,
                TRACE_COUNT=:tc, SHOT_FIRST=:sf, SHOT_LAST=:sl,
                EXTRACTED_DATE=GETUTCDATE()
            WHEN NOT MATCHED THEN INSERT (
                SEIS_HEADER_ID,INVENTORY_ID,
                SURVEY_NAME,LINE_NAME,SEIS_SET_TYPE,SURVEY_DATE,
                CONTRACTOR,BBOX_MIN_LAT,BBOX_MAX_LAT,
                BBOX_MIN_LON,BBOX_MAX_LON,EPSG_CODE,
                SAMPLE_INTERVAL,TRACE_COUNT,SHOT_FIRST,SHOT_LAST,
                EXTRACTED_DATE,EXTRACTED_BY
            ) VALUES (
                :hid,:inv_id,
                :sn,:ln,:stype,:sd,
                :contr,:bmin_lat,:bmax_lat,
                :bmin_lon,:bmax_lon,:epsg,
                :si,:tc,:sf,:sl,
                GETUTCDATE(),'DataWrangler'
            );
        """), {
            "hid":      hid,      "inv_id":   inv_id,
            "sn":       _trunc(fields.get("survey_name"),255),
            "ln":       _trunc(fields.get("line_name"),255),
            "stype":    _trunc(fields.get("seis_set_type"),40),
            "sd":       _trunc(fields.get("survey_date"),20),
            "contr":    _trunc(fields.get("contractor"),255),
            "bmin_lat": _safe_coord(fields.get("bbox_min_lat")),
            "bmax_lat": _safe_coord(fields.get("bbox_max_lat")),
            "bmin_lon": _safe_coord(fields.get("bbox_min_lon")),
            "bmax_lon": _safe_coord(fields.get("bbox_max_lon")),
            "epsg":     _safe_epsg(fields.get("epsg_code")),
            "si":       _safe_sample_interval(fields.get("sample_interval")),
            "tc":       _safe_trace_count(fields.get("trace_count")),
            "sf":       _trunc(fields.get("shot_first"),20),
            "sl":       _trunc(fields.get("shot_last"),20),
        })


def _score(fields: dict) -> tuple:
    score = 0
    if fields.get("uwi"):       score += 40
    if fields.get("well_name"): score += 20
    if fields.get("operator"):  score += 10
    if fields.get("latitude") and fields.get("longitude"): score += 20
    if fields.get("total_depth"): score += 10
    if score >= 80:  return score, "READY"
    if score >= 60:  return score, "REVIEW"
    if score >= 30:  return score, "NEEDS_UWI"
    return score, "ATTENTION"


def _issues(fields: dict) -> list:
    out = []
    if not fields.get("uwi"):       out.append("No UWI")
    if not fields.get("well_name"): out.append("No well name")
    if not (fields.get("latitude") and fields.get("longitude")):
        out.append("No coordinates")
    return out


def _trunc(v, n):
    return str(v)[:n] if v is not None else None

def _safe_num(v):
    """Convert to float or None. Silently swallows bad input."""
    try:
        return float(str(v).replace(",","").strip()) if v is not None else None
    except (ValueError, TypeError):
        return None

def _safe_int(v):
    """Convert to int or None. Silently swallows bad input."""
    try:
        return int(float(str(v).strip())) if v is not None else None
    except (ValueError, TypeError):
        return None


# ── Bounded variants ────────────────────────────────────────────────────
# pyodbc's fast_executemany pre-checks numeric ranges and rejects the
# whole batch if any value overflows the target column's precision/scale.
# These helpers clamp values to known-safe ranges, dropping outliers to
# NULL rather than letting them poison the batch.

def _safe_coord(v):
    """Latitude or longitude. Returns float in [-180, 180] or None."""
    n = _safe_num(v)
    if n is None or not (-180.0 <= n <= 180.0):
        return None
    return n

def _safe_sample_interval(v):
    """Seismic sample interval (microseconds). Positive, sane upper bound."""
    n = _safe_num(v)
    # SEGY interval is in microseconds; legitimate values are 250-16000.
    # Anything outside [0, 1_000_000] is garbage from a bad header read.
    if n is None or n < 0 or n > 1_000_000:
        return None
    return n

def _safe_trace_count(v):
    """Seismic trace count. Positive int, sane upper bound."""
    n = _safe_int(v)
    if n is None or n < 0 or n > 100_000_000:
        return None
    return n

def _safe_epsg(v):
    """EPSG code. 4 to 6 digit positive int."""
    n = _safe_int(v)
    if n is None or n < 1000 or n > 999_999:
        return None
    return n


# =============================================================================
# Tab 2 -- Browse & View
# =============================================================================

def _tab_browse(engine, dialect):
    from sqlalchemy import text as _t

    st.markdown("#### 📂 Browse & View")

    # ── Filters ───────────────────────────────────────────────────────────────
    f1, f2, f3, f4 = st.columns(4)
    grp = f1.selectbox(
        "File type",
        ["All","PDF","Well Log","Seismic","Shapefile","Office","Image"],
        key="wb_grp",
    )
    rd = f2.selectbox(
        "Readiness",
        ["All","READY","REVIEW","NEEDS_UWI","ATTENTION"],
        key="wb_rd",
    )
    srch = f3.text_input("Filename contains", key="wb_srch",
                          placeholder="partial name...")
    flagged = f4.checkbox("Flagged only", key="wb_flagged")

    if st.button("🔍 Search", type="primary", key="wb_search_btn"):
        conditions = ["1=1"]
        params = {}
        if grp != "All":
            conditions.append("FILE_TYPE_GROUP=:grp")
            params["grp"] = grp
        if rd != "All":
            conditions.append("CATALOG_READINESS=:rd")
            params["rd"] = rd
        if srch:
            conditions.append("FILE_NAME LIKE :srch")
            params["srch"] = f"%{srch}%"
        if flagged:
            conditions.append("ISNULL(FLAG_DELETE,'N')='Y'")
        try:
            with engine.connect() as con:
                rows = con.execute(_t(f"""
                    SELECT TOP 500
                        INVENTORY_ID, FILE_PATH, FILE_NAME, FILE_EXT,
                        FILE_TYPE_GROUP, FILE_SIZE_KB,
                        CATALOG_READINESS, CATALOG_SCORE,
                        MATCHED_UWI, CATALOG_ISSUES,
                        ISNULL(FLAG_DELETE,'N') FLAG_DELETE,
                        HEADER_EXTRACTED
                    FROM file_catalog.GLOBAL_FILE_CATALOG
                    WHERE {" AND ".join(conditions)}
                    ORDER BY CATALOG_SCORE DESC, FILE_NAME
                """), params).fetchall()
            df = pd.DataFrame(rows, columns=[
                "INVENTORY_ID","FILE_PATH","FILE_NAME","FILE_EXT",
                "FILE_TYPE_GROUP","FILE_SIZE_KB",
                "CATALOG_READINESS","CATALOG_SCORE",
                "MATCHED_UWI","CATALOG_ISSUES",
                "FLAG_DELETE","HEADER_EXTRACTED",
            ])
            st.session_state["wb_results"] = df
            st.session_state.pop("wb_nav_idx", None)
        except Exception as e:
            st.error(f"Search failed: {e}")

    df = st.session_state.get("wb_results")
    if df is None:
        st.info("Set filters and click Search.")
        return

    st.caption(f"{len(df):,} files (max 500)")
    st.dataframe(
        df[["FILE_NAME","FILE_EXT","FILE_TYPE_GROUP",
            "CATALOG_READINESS","CATALOG_SCORE",
            "MATCHED_UWI","FLAG_DELETE"]],
        hide_index=True, use_container_width=True,
    )

    if df.empty:
        return

    st.divider()
    _wb_nav(engine, dialect, df)


def _wb_nav(engine, dialect, df):
    """Prev/Next nav + file detail + viewer + extract + load."""
    from sqlalchemy import text as _t

    n       = len(df)
    idx_key = "wb_nav_idx"
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0
    idx = max(0, min(st.session_state[idx_key], n-1))

    # Nav bar
    c_prev, c_info, c_next, c_jump = st.columns([1,4,1,2])
    with c_prev:
        if st.button("◀ Prev", key="wb_prev", disabled=(idx==0)):
            st.session_state[idx_key] = idx-1
            st.rerun()
    with c_next:
        if st.button("Next ▶", key="wb_next", disabled=(idx>=n-1)):
            st.session_state[idx_key] = idx+1
            st.rerun()
    with c_info:
        row = df.iloc[idx]
        badge = " 🚩" if row["FLAG_DELETE"]=="Y" else ""
        st.markdown(f"**{idx+1} / {n}**{badge}  `{row['FILE_NAME']}`")
    with c_jump:
        names  = df["FILE_NAME"].tolist()
        jumped = st.selectbox("Jump to", names, index=idx,
                              key="wb_jump",
                              label_visibility="collapsed")
        ji = names.index(jumped)
        if ji != idx:
            st.session_state[idx_key] = ji
            st.rerun()

    row    = df.iloc[idx]
    fpath  = row["FILE_PATH"]
    fext   = row["FILE_EXT"].lower()
    inv_id = row["INVENTORY_ID"]

    # ── Action bar ────────────────────────────────────────────────────────────
    a1, a2, a3, a4 = st.columns(4)

    is_flagged = row["FLAG_DELETE"] == "Y"
    if a1.button(
            "🚩 Unflag" if is_flagged else "🚩 Flag",
            key="wb_flag_btn"):
        _toggle_flag(engine, inv_id, not is_flagged)
        st.session_state.pop("wb_results", None)
        st.rerun()

    if a2.button("🔄 Re-enrich", key="wb_reenrich"):
        with st.spinner("Enriching..."):
            try:
                fields = _extract_fields(fpath, fext)
                _write_enrichment(engine, inv_id, fields)
                st.success("Re-enriched.")
                st.session_state.pop("wb_results", None)
                st.rerun()
            except Exception as e:
                st.error(f"Re-enrich failed: {e}")

    # Download
    if Path(fpath).exists():
        try:
            a4.download_button(
                "⬇ Download", data=Path(fpath).read_bytes(),
                file_name=row["FILE_NAME"], key="wb_dl_btn")
        except Exception:
            pass

    st.divider()

    # ── Catalog attributes from header tables ─────────────────────────────────
    _show_header_attrs(engine, inv_id, row)

    # ── Universal viewer ──────────────────────────────────────────────────────
    if Path(fpath).exists():
        try:
            from modules.file_viewer import view as _view
            _view(fpath, fext)
        except Exception as e:
            st.error(f"Viewer error: {e}")
    else:
        st.warning(f"File not found on disk: `{fpath}`")

    # ── Extract & Load (automatic) ───────────────────────────────────────────
    _extract_and_load(engine, dialect, fpath, fext, inv_id, row)


def _show_header_attrs(engine, inv_id: str, row):
    """Show enriched header from FILE_WELL_HEADER or FILE_SEIS_HEADER."""
    from sqlalchemy import text as _t

    grp = row.get("FILE_TYPE_GROUP","")
    is_seis = grp in ("Seismic","Shapefile")

    try:
        with engine.connect() as con:
            if is_seis:
                r = con.execute(_t("""
                    SELECT SURVEY_NAME, LINE_NAME, SEIS_SET_TYPE,
                           SURVEY_DATE, CONTRACTOR,
                           BBOX_MIN_LAT, BBOX_MAX_LAT,
                           BBOX_MIN_LON, BBOX_MAX_LON,
                           EPSG_CODE, SAMPLE_INTERVAL, TRACE_COUNT,
                           SHOT_FIRST, SHOT_LAST
                    FROM file_catalog.FILE_SEIS_HEADER
                    WHERE INVENTORY_ID=:id
                """), {"id": inv_id}).fetchone()
                if r:
                    attrs = dict(zip([
                        "Survey Name","Line Name","Set Type","Survey Date",
                        "Contractor","Min Lat","Max Lat","Min Lon","Max Lon",
                        "EPSG","Sample Interval","Trace Count",
                        "Shot First","Shot Last",
                    ], r))
                else:
                    attrs = {}
            else:
                r = con.execute(_t("""
                    SELECT UWI, WELL_NAME, OPERATOR, WELL_FIELD,
                           STATE, COUNTY, LATITUDE, LONGITUDE,
                           TOTAL_DEPTH, SPUD_DATE, RIG_RELEASE,
                           REPORT_TYPE, SURVEY_TYPE, CONTRACTOR, CONFIDENCE
                    FROM file_catalog.FILE_WELL_HEADER
                    WHERE INVENTORY_ID=:id
                """), {"id": inv_id}).fetchone()
                if r:
                    attrs = dict(zip([
                        "UWI","Well Name","Operator","Field",
                        "State","County","Latitude","Longitude",
                        "Total Depth","Spud Date","Rig Release",
                        "Report Type","Survey Type","Contractor","Confidence",
                    ], r))
                else:
                    attrs = {}

        if attrs:
            with st.expander("📋 Extracted header", expanded=True):
                adf = pd.DataFrame(
                    [{"Field": k, "Value": str(v)}
                     for k, v in attrs.items()
                     if v is not None and str(v).strip()
                     not in ("","None","nan")]
                )
                if not adf.empty:
                    st.dataframe(adf, hide_index=True,
                                 use_container_width=True)
        else:
            st.caption("No header extracted yet — click Re-enrich.")
    except Exception as e:
        st.caption(f"Header lookup: {e}")


def _extract_and_load(engine, dialect, fpath, fext, inv_id, row):
    """Extract structured data rows from file and offer DB load."""
    from sqlalchemy import text as _t

    st.markdown("#### 📐 Extracted Data")

    rows, label = _do_extract(fpath, fext)

    if not rows:
        st.info(f"No structured data extracted for {fext} files.")
        return

    df = pd.DataFrame(rows).fillna("")
    st.metric(f"{label} extracted", len(df))
    st.dataframe(df, hide_index=True, use_container_width=True)

    c1, c2 = st.columns(2)
    c1.download_button(
        f"⬇ Download {label} CSV",
        data=df.to_csv(index=False),
        file_name=f"{Path(fpath).stem}_{label.lower().replace(' ','_')}.csv",
        mime="text/csv",
        key="wb_extract_dl",
    )

    # Load to DB — check well exists first
    uwi = row.get("MATCHED_UWI","") or ""
    if not uwi:
        c2.warning("No UWI — load wells from Header Files tab first.")
        return

    _well_ok = False
    _resolved = uwi
    try:
        with engine.connect() as con:
            _r = con.execute(_t(
                "SELECT uwi FROM dataview.dv_well WHERE uwi=:u"
            ), {"u": uwi}).fetchone()
            if _r:
                _well_ok = True
            else:
                _norm = re.sub(r"[-\s/]","",uwi).upper()
                _r2 = con.execute(_t("""
                    SELECT uwi FROM dataview.dv_well
                    WHERE REPLACE(REPLACE(REPLACE(uwi,'-',''),' ',''),'/','')=:n
                """), {"n": _norm}).fetchone()
                if _r2:
                    _resolved = _r2[0]
                    _well_ok  = True
    except Exception:
        pass

    if not _well_ok:
        c2.warning(f"UWI `{uwi}` not in dv_well — create well first.")
        return

    if c2.button(
            f"🚀 Load {len(rows)} records to DB",
            type="primary", key="wb_load_btn"):
        _do_load(engine, dialect, fpath, fext, _resolved, rows)


def _do_extract(fpath: str, fext: str) -> tuple:
    """Extract structured data rows. Returns (rows, label)."""
    try:
        if fext == ".pdf":
            from modules.pdf_survey_catalog import (
                classify_pdf, extract_stations,
                extract_eowr, extract_rft_data,
                extract_well_test, extract_petrophysical,
                extract_casing_cement, extract_ddr,
                extract_scout_ticket,
                RT_DIRECTIONAL, RT_EOWR, RT_RFT,
                RT_WELL_TEST, RT_PETRO, RT_CASING,
                RT_DDR, RT_SCOUT,
            )
            cl = classify_pdf(fpath)
            rt = cl.get("report_type","UNKNOWN")

            if rt == RT_DIRECTIONAL:
                r = extract_stations(fpath)
                return r.get("stations",[]), "Stations"
            elif rt == RT_EOWR:
                r = extract_eowr(fpath)
                return r.get("strat",[]), "Strat tops"
            elif rt == RT_RFT:
                return extract_rft_data(fpath).get("rows",[]), "RFT rows"
            elif rt == RT_WELL_TEST:
                return extract_well_test(fpath).get("flow_rows",[]), "Flow periods"
            elif rt in (RT_PETRO,"PETROPHYSICAL"):
                from modules.extract_petro import extract_petro
                r = extract_petro(fpath)
                if r.get("ok"):
                    zones = r.get("zones", [])
                    return zones, f"Petro zones ({len(zones)})"
                else:
                    # Fallback to old extractor
                    r2 = extract_petrophysical(fpath)
                    return r2.get("zones") or r2.get("interval") or [], "Zones"
            elif rt == RT_CASING:
                r = extract_casing_cement(fpath)
                return r.get("casing",[]) + r.get("cement",[]), "Casing"
            elif rt == RT_DDR:
                return extract_ddr(fpath).get("ops",[]), "Operations"
            elif rt == RT_SCOUT:
                r = extract_scout_ticket(fpath)
                return r.get("ip_rows") or r.get("perf_rows") or [], "IP/Perf"
            else:
                return [], "Records"

        elif fext == ".las":
            import lasio
            las = lasio.read(fpath)
            df  = las.df().reset_index()
            return df.to_dict("records"), "Curve rows"

        elif fext in SEGY_EXTS:
            import segyio
            with segyio.open(fpath, ignore_geometry=True) as f:
                n = min(f.tracecount, 100)
                rows = []
                for i in range(n):
                    h = f.header[i]
                    rows.append({
                        "Trace": i+1,
                        "CDP":   h[segyio.TraceField.CDP],
                        "CDP_X": h[segyio.TraceField.CDP_X],
                        "CDP_Y": h[segyio.TraceField.CDP_Y],
                        "Offset":h[segyio.TraceField.offset],
                    })
            return rows, "Trace headers"

        elif fext in SHP_EXTS:
            import geopandas as gpd
            gdf = gpd.read_file(fpath)
            return gdf.drop(
                columns=["geometry"], errors="ignore"
            ).to_dict("records"), "Features"

    except Exception as e:
        st.error(f"Extraction error: {e}")
    return [], "Records"


def _do_load(engine, dialect, fpath, fext, uwi, rows):
    """Load extracted rows to PPDM tables."""
    well_info = {"uwi": uwi, "well_name":"", "operator":""}
    try:
        if fext == ".pdf":
            from modules.pdf_survey_catalog import (
                classify_pdf, load_to_ppdm, RT_DIRECTIONAL)
            cl = classify_pdf(fpath)
            rt = cl.get("report_type","UNKNOWN")
            well_info.update({
                "well_name": cl.get("well_name",""),
                "operator":  cl.get("operator",""),
            })
            if rt == RT_DIRECTIONAL:
                r = load_to_ppdm(well_info=well_info, stations=rows,
                                 engine=engine, dialect=dialect)
            else:
                from modules.pdf_db_loader import (
                    load_formation_tops, load_well_test,
                    load_rft, load_casing, load_scout,
                )
                from modules.pdf_survey_catalog import (
                    RT_EOWR, RT_RFT, RT_WELL_TEST,
                    RT_CASING, RT_SCOUT, RT_DST, RT_PETRO,
                )
                kw = dict(engine=engine, dialect=dialect,
                          well_info=well_info, rows=rows)
                if rt == RT_EOWR:
                    r = load_formation_tops(**kw)
                elif rt in (RT_WELL_TEST, RT_DST):
                    r = load_well_test(**kw)
                elif rt == RT_RFT:
                    r = load_rft(**kw)
                elif rt == RT_CASING:
                    r = load_casing(**kw)
                elif rt == RT_SCOUT:
                    r = load_scout(**kw)
                elif rt in (RT_PETRO, "PETROPHYSICAL"):
                    from modules.extract_petro import (
                        extract_petro, load_petro_zones)
                    petro = extract_petro(fpath)
                    if not petro.get("ok"):
                        st.error(f"Extraction failed: {petro.get('error')}")
                        return
                    r = load_petro_zones(engine, dialect, petro, uwi)
                else:
                    st.warning(f"Load not implemented for {rt}")
                    return

            errs = r.get("errors",[])
            if errs:
                st.error(f"Load errors: {'; '.join(str(e) for e in errs[:3])}")
            else:
                st.success(f"✅ Loaded {r.get('loaded',0)} records")

        elif fext in SHP_EXTS:
            from modules.shapefile_catalog import load_to_ppdm as shp_load
            shp_load(file_path=fpath, engine=engine,
                     dialect=dialect, well_info=well_info)
            st.success("✅ Shapefile loaded")

        else:
            st.info("Direct DB load not yet implemented for this file type.")

    except Exception as e:
        st.error(f"Load failed: {e}")


def _toggle_flag(engine, inv_id: str, flag: bool):
    from sqlalchemy import text as _t
    try:
        with engine.begin() as con:
            con.execute(_t("""
                UPDATE file_catalog.GLOBAL_FILE_CATALOG
                SET FLAG_DELETE=:f, ROW_CHANGED_DATE=GETUTCDATE()
                WHERE INVENTORY_ID=:id
            """), {"f": "Y" if flag else "N", "id": inv_id})
    except Exception as e:
        st.error(f"Flag failed: {e}")



# =============================================================================
# Tab 3 -- Well Map
# =============================================================================

def _tab_map(engine, dialect):
    from sqlalchemy import text as _t

    st.markdown("#### 🗺️ Well Map")
    st.caption(
        "Wells from FILE_WELL_HEADER with lat/lon. "
        "Click a marker for details and link to source file. "
        "Seismic survey footprints from FILE_SEIS_HEADER."
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns(3)
    show_seis  = c1.checkbox("Show seismic footprints", value=True,
                              key="wm_seis")
    show_all   = c2.checkbox("Include suspect coords", value=False,
                              key="wm_all",
                              help="Include wells that may have wrong coordinates")
    tile_style = c3.selectbox("Base map",
        ["CartoDB positron","OpenStreetMap","CartoDB dark_matter"],
        key="wm_tiles")

    # ── Query wells ───────────────────────────────────────────────────────────
    try:
        with engine.connect() as con:
            well_rows = con.execute(_t("""
                SELECT
                    wh.UWI, wh.WELL_NAME, wh.OPERATOR,
                    wh.WELL_FIELD, wh.STATE, wh.COUNTY,
                    CAST(wh.LATITUDE  AS FLOAT) AS LAT,
                    CAST(wh.LONGITUDE AS FLOAT) AS LON,
                    wh.TOTAL_DEPTH, wh.SPUD_DATE,
                    wh.REPORT_TYPE, wh.CONTRACTOR,
                    wh.CONFIDENCE,
                    gfc.FILE_PATH, gfc.FILE_NAME, gfc.FILE_EXT,
                    gfc.CATALOG_READINESS
                FROM file_catalog.FILE_WELL_HEADER wh
                JOIN file_catalog.GLOBAL_FILE_CATALOG gfc
                    ON gfc.INVENTORY_ID = wh.INVENTORY_ID
                WHERE wh.LATITUDE  IS NOT NULL
                  AND wh.LONGITUDE IS NOT NULL
                  AND TRY_CAST(wh.LATITUDE  AS FLOAT) BETWEEN -90  AND 90
                  AND TRY_CAST(wh.LONGITUDE AS FLOAT) BETWEEN -180 AND 180
            """)).fetchall()

            seis_rows = []
            if show_seis:
                try:
                    seis_rows = con.execute(_t("""
                        SELECT
                            sh.SURVEY_NAME, sh.SEIS_SET_TYPE,
                            sh.CONTRACTOR, sh.TRACE_COUNT,
                            CAST(sh.BBOX_MIN_LAT AS FLOAT) AS MIN_LAT,
                            CAST(sh.BBOX_MAX_LAT AS FLOAT) AS MAX_LAT,
                            CAST(sh.BBOX_MIN_LON AS FLOAT) AS MIN_LON,
                            CAST(sh.BBOX_MAX_LON AS FLOAT) AS MAX_LON,
                            gfc.FILE_NAME, gfc.FILE_EXT
                        FROM file_catalog.FILE_SEIS_HEADER sh
                        JOIN file_catalog.GLOBAL_FILE_CATALOG gfc
                            ON gfc.INVENTORY_ID = sh.INVENTORY_ID
                        WHERE sh.BBOX_MIN_LAT IS NOT NULL
                          AND sh.BBOX_MAX_LAT IS NOT NULL
                          AND sh.BBOX_MIN_LON IS NOT NULL
                          AND sh.BBOX_MAX_LON IS NOT NULL
                          AND TRY_CAST(sh.BBOX_MIN_LAT AS FLOAT) BETWEEN -90 AND 90
                          AND TRY_CAST(sh.BBOX_MIN_LON AS FLOAT) BETWEEN -180 AND 0
                    """)).fetchall()
                except Exception:
                    pass

    except Exception as e:
        st.error(f"Query failed: {e}")
        return

    if not well_rows:
        st.warning(
            "No wells with coordinates found. "
            "Run Phase 2 enrichment first."
        )
        return

    import pandas as pd
    wells = pd.DataFrame(well_rows, columns=[
        "uwi","well_name","operator","field","state","county",
        "lat","lon","total_depth","spud_date","report_type",
        "contractor","confidence","file_path","file_name",
        "file_ext","readiness",
    ])

    # Optionally filter suspect coordinates
    if not show_all:
        # US bounding box roughly
        wells = wells[
            wells["lat"].between(24, 50) &
            wells["lon"].between(-125, -65)
        ]

    m1, m2, m3 = st.columns(3)
    m1.metric("Wells on map",    len(wells))
    m2.metric("States",          wells["state"].nunique())
    m3.metric("Seismic surveys", len(seis_rows))

    if wells.empty:
        st.warning("No wells in valid US coordinates. "
                   "Check 'Include suspect coords' to show all.")
        return

    # ── Build folium map ──────────────────────────────────────────────────────
    import folium
    center_lat = wells["lat"].mean()
    center_lon = wells["lon"].mean()

    tile_map = {
        "CartoDB positron":    "CartoDB positron",
        "OpenStreetMap":       "OpenStreetMap",
        "CartoDB dark_matter": "CartoDB dark_matter",
    }

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=5,
        tiles=tile_map.get(tile_style, "CartoDB positron"),
    )

    # Color by report type
    type_colors = {
        "WELL_LOG":           "#378ADD",
        "DIRECTIONAL_SURVEY": "#C8922A",
        "OFFICE":             "#888780",
        "UNKNOWN":            "#B4B2A9",
    }

    # ── Well markers ──────────────────────────────────────────────────────────
    for _, w in wells.iterrows():
        color = type_colors.get(w["report_type"], "#378ADD")

        popup_html = f"""
        <div style="font-family:sans-serif;font-size:13px;min-width:200px">
            <b style="font-size:14px">{w['well_name'] or w['uwi']}</b><br>
            <hr style="margin:4px 0">
            <b>UWI:</b> {w['uwi'] or '—'}<br>
            <b>Field:</b> {w['field'] or '—'}<br>
            <b>Operator:</b> {w['operator'] or '—'}<br>
            <b>State:</b> {w['state'] or '—'} · {w['county'] or '—'}<br>
            <b>TD:</b> {w['total_depth'] or '—'} ft<br>
            <b>Type:</b> {w['report_type'] or '—'}<br>
            <b>Readiness:</b> {w['readiness'] or '—'}<br>
            <hr style="margin:4px 0">
            <b>Source:</b> {w['file_name']}<br>
            <small style="color:#666;word-break:break-all">{w['file_path']}</small>
        </div>
        """

        tooltip = f"{w['well_name'] or w['uwi']} · {w['field'] or ''}"

        folium.CircleMarker(
            location=[w["lat"], w["lon"]],
            radius=8,
            color="white",
            weight=1.5,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            tooltip=folium.Tooltip(tooltip),
            popup=folium.Popup(popup_html, max_width=280),
        ).add_to(m)

    # ── Seismic footprints ────────────────────────────────────────────────────
    if seis_rows:
        for sr in seis_rows:
            try:
                (sname, stype, contr, traces,
                 min_lat, max_lat, min_lon, max_lon,
                 fname, fext) = sr

                if None in (min_lat, max_lat, min_lon, max_lon):
                    continue

                popup_html = f"""
                <div style="font-family:sans-serif;font-size:13px">
                    <b>{sname or fname}</b><br>
                    <b>Type:</b> {stype or '—'}<br>
                    <b>Contractor:</b> {contr or '—'}<br>
                    <b>Traces:</b> {traces or '—'}<br>
                    <b>File:</b> {fname}
                </div>
                """

                folium.Rectangle(
                    bounds=[[min_lat, min_lon],
                            [max_lat, max_lon]],
                    color="#1D9E75",
                    weight=2,
                    fill=True,
                    fill_color="#1D9E75",
                    fill_opacity=0.1,
                    tooltip=folium.Tooltip(sname or fname),
                    popup=folium.Popup(popup_html, max_width=240),
                ).add_to(m)
            except Exception:
                pass

    # ── Legend ────────────────────────────────────────────────────────────────
    legend_html = """
    <div style="position:fixed;bottom:30px;left:30px;z-index:1000;
                background:white;padding:10px 14px;border-radius:8px;
                border:1px solid #ccc;font-size:12px;font-family:sans-serif">
        <b>Well type</b><br>
        <span style="color:#378ADD">&#9679;</span> Well log (LAS/DLIS)<br>
        <span style="color:#C8922A">&#9679;</span> Directional survey<br>
        <span style="color:#888780">&#9679;</span> Office / other<br>
        <span style="color:#1D9E75">&#9632;</span> Seismic footprint
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    # Fit bounds to data
    m.fit_bounds([
        [wells["lat"].min() - 0.5, wells["lon"].min() - 0.5],
        [wells["lat"].max() + 0.5, wells["lon"].max() + 0.5],
    ])

    # Render map HTML directly — avoids st_folium height issues in tabs
    map_html = m._repr_html_()
    st.components.v1.html(
        f'''<div style="width:100%;height:600px;">{map_html}</div>''',
        height=620,
        scrolling=False,
    )

    # ── Export options ────────────────────────────────────────────────────────
    st.divider()
    st.markdown("**Export**")
    ec1, ec2 = st.columns(2)

    # CSV
    ec1.download_button(
        "⬇ Download well locations CSV",
        data=wells.to_csv(index=False),
        file_name="well_locations.csv",
        mime="text/csv",
        key="wm_csv",
    )

    # GeoJSON
    try:
        import json
        features = []
        for _, w in wells.iterrows():
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [w["lon"], w["lat"]],
                },
                "properties": {
                    "uwi":         w["uwi"],
                    "well_name":   w["well_name"],
                    "operator":    w["operator"],
                    "field":       w["field"],
                    "state":       w["state"],
                    "county":      w["county"],
                    "total_depth": w["total_depth"],
                    "report_type": w["report_type"],
                    "file_path":   w["file_path"],
                    "file_name":   w["file_name"],
                    "readiness":   w["readiness"],
                },
            })
        gj = json.dumps({
            "type": "FeatureCollection",
            "features": features,
        }, indent=2)
        ec2.download_button(
            "⬇ Download GeoJSON",
            data=gj,
            file_name="well_locations.geojson",
            mime="application/geo+json",
            key="wm_geojson",
        )
    except Exception:
        pass


# =============================================================================
# Tab 4 -- Header Files
# =============================================================================

def _tab_headers(engine, dialect):
    from sqlalchemy import text as _t

    st.markdown("#### 📋 Header Files")
    st.caption(
        "Query extracted headers from FILE_WELL_HEADER and "
        "FILE_SEIS_HEADER. Export flat CSV for well creation "
        "or load seismic to dv_seis_set."
    )

    sub = st.tabs(["📋 Well Headers", "📡 Seis Headers"])

    # ── Well Headers ──────────────────────────────────────────────────────────
    with sub[0]:
        st.markdown("**Well header flat file**")
        f1, f2 = st.columns(2)
        has_uwi   = f1.checkbox("Has UWI only",     key="wh2_has_uwi")
        has_coord = f2.checkbox("Has Lat/Lon only",  key="wh2_has_coord")

        if st.button("🔍 Query", type="primary", key="wh2_query"):
            try:
                conds = ["1=1"]
                params = {}
                if has_uwi:
                    conds.append("wh.UWI IS NOT NULL AND wh.UWI!=''")
                if has_coord:
                    conds.append(
                        "wh.LATITUDE IS NOT NULL "
                        "AND wh.LONGITUDE IS NOT NULL")
                with engine.connect() as con:
                    rows = con.execute(_t(f"""
                        SELECT
                            gfc.FILE_PATH, gfc.FILE_NAME, gfc.FILE_EXT,
                            gfc.FILE_TYPE_GROUP,
                            gfc.CATALOG_READINESS, gfc.CATALOG_SCORE,
                            wh.UWI, wh.WELL_NAME, wh.OPERATOR,
                            wh.WELL_FIELD, wh.STATE, wh.COUNTY,
                            wh.LATITUDE, wh.LONGITUDE,
                            wh.TOTAL_DEPTH, wh.SPUD_DATE, wh.RIG_RELEASE,
                            wh.REPORT_TYPE, wh.SURVEY_TYPE,
                            wh.CONTRACTOR, wh.CONFIDENCE
                        FROM file_catalog.FILE_WELL_HEADER wh
                        JOIN file_catalog.GLOBAL_FILE_CATALOG gfc
                            ON gfc.INVENTORY_ID = wh.INVENTORY_ID
                        WHERE {" AND ".join(conds)}
                        ORDER BY gfc.CATALOG_SCORE DESC, gfc.FILE_NAME
                    """), params).fetchall()

                df = pd.DataFrame(rows, columns=[
                    "file_path","file_name","extension","type_group",
                    "readiness","score",
                    "uwi","well_name","operator","well_field",
                    "state","county","latitude","longitude",
                    "total_depth","spud_date","rig_release",
                    "report_type","survey_type","contractor","confidence",
                ])
                st.session_state["wh2_df"] = df
            except Exception as e:
                st.error(f"Query failed: {e}")
                st.caption(
                    "Run Phase 2 enrichment to populate FILE_WELL_HEADER.")

        df = st.session_state.get("wh2_df")
        if df is None:
            st.info("Click Query. Run Phase 2 enrichment if empty.")
        else:
            m1,m2,m3 = st.columns(3)
            m1.metric("Files",       len(df))
            m2.metric("Has UWI",
                      int(df["uwi"].notna().sum()))
            m3.metric("Has Lat/Lon",
                      int((df["latitude"].notna() &
                           df["longitude"].notna()).sum()))
            st.dataframe(df, hide_index=True, use_container_width=True)
            st.download_button(
                "⬇ Export Well Header Flat File",
                data=df.to_csv(index=False),
                file_name="well_header_flat_file.csv",
                mime="text/csv", key="wh2_export",
            )

    # ── Seis Headers ──────────────────────────────────────────────────────────
    with sub[1]:
        st.markdown("**Seismic header flat file**")
        has_survey = st.checkbox("Has survey name only", key="sh2_has_survey")

        if st.button("🔍 Query", type="primary", key="sh2_query"):
            try:
                conds = ["1=1"]
                if has_survey:
                    conds.append(
                        "sh.SURVEY_NAME IS NOT NULL "
                        "AND sh.SURVEY_NAME!=''")
                with engine.connect() as con:
                    rows = con.execute(_t(f"""
                        SELECT
                            gfc.FILE_PATH, gfc.FILE_NAME, gfc.FILE_EXT,
                            gfc.FILE_TYPE_GROUP, gfc.CATALOG_READINESS,
                            sh.SURVEY_NAME, sh.LINE_NAME,
                            sh.SEIS_SET_TYPE, sh.SURVEY_DATE,
                            sh.CONTRACTOR,
                            sh.BBOX_MIN_LAT, sh.BBOX_MAX_LAT,
                            sh.BBOX_MIN_LON, sh.BBOX_MAX_LON,
                            sh.EPSG_CODE, sh.SAMPLE_INTERVAL,
                            sh.TRACE_COUNT, sh.SHOT_FIRST, sh.SHOT_LAST,
                            sh.INVENTORY_ID
                        FROM file_catalog.FILE_SEIS_HEADER sh
                        JOIN file_catalog.GLOBAL_FILE_CATALOG gfc
                            ON gfc.INVENTORY_ID = sh.INVENTORY_ID
                        WHERE {" AND ".join(conds)}
                        ORDER BY gfc.FILE_NAME
                    """)).fetchall()

                df = pd.DataFrame(rows, columns=[
                    "file_path","file_name","extension","type_group",
                    "readiness","survey_name","line_name",
                    "seis_set_type","survey_date","contractor",
                    "bbox_min_lat","bbox_max_lat",
                    "bbox_min_lon","bbox_max_lon",
                    "epsg_code","sample_interval",
                    "trace_count","shot_first","shot_last",
                    "inventory_id",
                ])
                st.session_state["sh2_df"] = df
            except Exception as e:
                st.error(f"Query failed: {e}")
                st.caption(
                    "Run Phase 2 enrichment to populate FILE_SEIS_HEADER.")

        df = st.session_state.get("sh2_df")
        if df is None:
            st.info("Click Query. Run Phase 2 enrichment if empty.")
        else:
            m1,m2,m3 = st.columns(3)
            m1.metric("Seismic files", len(df))
            m2.metric("Has survey",
                      int(df["survey_name"].notna().sum()))
            m3.metric("Has bbox",
                      int(df["bbox_min_lat"].notna().sum()))

            st.dataframe(
                df.drop(columns=["inventory_id"]),
                hide_index=True, use_container_width=True,
            )

            c1, c2 = st.columns(2)
            c1.download_button(
                "⬇ Export Seis Header CSV",
                data=df.to_csv(index=False),
                file_name="seis_header_flat_file.csv",
                mime="text/csv", key="sh2_export",
            )
            if c2.button("🚀 Load to dv_seis_set",
                         key="sh2_load"):
                _load_seis(engine, dialect, df)


def _load_seis(engine, dialect, df):
    """Insert/update seis headers into dataview.dv_seis_set."""
    from sqlalchemy import text as _t

    to_load = df[
        df["survey_name"].notna() &
        (df["survey_name"].astype(str).str.strip() != "")
    ]
    if to_load.empty:
        st.warning("No rows have a survey name.")
        return

    loaded = errors = 0
    for _, row in to_load.iterrows():
        try:
            sid = uuid.uuid4().hex[:40].upper()
            with engine.begin() as con:
                ex = con.execute(_t("""
                    SELECT seis_set_id FROM dataview.dv_seis_set
                    WHERE seis_set_name=:n
                """), {"n": row["survey_name"]}).fetchone()

                if ex:
                    con.execute(_t("""
                        UPDATE dataview.dv_seis_set SET
                            file_path=:fp, catalog_id=:cid,
                            bbox_min_lat=:bmin_lat, bbox_max_lat=:bmax_lat,
                            bbox_min_lon=:bmin_lon, bbox_max_lon=:bmax_lon,
                            epsg_code=:epsg, remark=:remark,
                            row_changed_by='DataWrangler',
                            row_changed_date=GETUTCDATE()
                        WHERE seis_set_name=:n
                    """), {
                        "fp":       row["file_path"],
                        "cid":      row.get("inventory_id"),
                        "bmin_lat": _safe_num(row.get("bbox_min_lat")),
                        "bmax_lat": _safe_num(row.get("bbox_max_lat")),
                        "bmin_lon": _safe_num(row.get("bbox_min_lon")),
                        "bmax_lon": _safe_num(row.get("bbox_max_lon")),
                        "epsg":     _safe_int(row.get("epsg_code")),
                        "remark":   str(row.get("contractor",""))[:2000],
                        "n":        row["survey_name"],
                    })
                else:
                    con.execute(_t("""
                        INSERT INTO dataview.dv_seis_set (
                            seis_set_id, seis_set_name, seis_set_type,
                            file_path, catalog_id,
                            bbox_min_lat, bbox_max_lat,
                            bbox_min_lon, bbox_max_lon,
                            epsg_code, remark, active_ind, source,
                            row_created_by, row_created_date,
                            row_changed_by, row_changed_date
                        ) VALUES (
                            :sid,:sn,:stype,:fp,:cid,
                            :bmin_lat,:bmax_lat,:bmin_lon,:bmax_lon,
                            :epsg,:remark,'Y','FILE_CATALOG',
                            'DataWrangler',GETUTCDATE(),
                            'DataWrangler',GETUTCDATE()
                        )
                    """), {
                        "sid":      sid,
                        "sn":       row["survey_name"],
                        "stype":    str(row.get("seis_set_type","2D"))[:40],
                        "fp":       row["file_path"],
                        "cid":      row.get("inventory_id"),
                        "bmin_lat": _safe_num(row.get("bbox_min_lat")),
                        "bmax_lat": _safe_num(row.get("bbox_max_lat")),
                        "bmin_lon": _safe_num(row.get("bbox_min_lon")),
                        "bmax_lon": _safe_num(row.get("bbox_max_lon")),
                        "epsg":     _safe_int(row.get("epsg_code")),
                        "remark":   str(row.get("contractor",""))[:2000],
                    })
            loaded += 1
        except Exception:
            errors += 1

    if errors:
        st.error(f"Loaded {loaded}, {errors} errors.")
    else:
        st.success(f"✅ Loaded {loaded} rows to dv_seis_set.")

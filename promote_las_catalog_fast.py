"""
promote_las_catalog_fast.py
===========================
Drop-in replacement for promote_las_catalog() in promote_catalog.py.

Same inputs, same outputs (target, eligible, promoted, held, note), same
governance semantics — only the resolution mechanism changes:

  BEFORE: two CORRELATED subqueries evaluated PER curve row —
            * INVENTORY_ID: re-derives the basename and re-scans
              GLOBAL_FILE_CATALOG with a COUNT(*) for every row
            * has_well:     EXISTS against dv_well for every row
          …and the whole CTE is run TWICE (diagnostics COUNT, then INSERT).
          Over millions of curves on SQL Express that's the bottleneck.

  AFTER:  resolve once into indexed temp tables, JOIN, materialize #resolved
          a single time, then both the diagnostics and the INSERT read it.
          Per-row scans become single hash joins.

Semantics preserved exactly:
  * INVENTORY_ID accepted only on an UNAMBIGUOUS single basename match
    (GROUP BY FILE_NAME HAVING COUNT(*) = 1 — 0 or >1 matches -> held).
  * curves whose UWI is not in dv_well are HELD (has_well = 0), not failed.
  * additive insert with the same NOT EXISTS dedup key
    (INVENTORY_ID + CURVE_MNEMONIC + FRAME_NAME + LOGICAL_FILE).
"""
from __future__ import annotations

# These mirror the module-level constants in promote_catalog.py.
DV_SCHEMA = "dataview"


def object_exists(cur, schema: str, table: str) -> bool:
    cur.execute("SELECT 1 FROM sys.tables t JOIN sys.schemas s "
                "ON s.schema_id = t.schema_id "
                "WHERE s.name = ? AND t.name = ?", schema, table)
    return cur.fetchone() is not None


def promote_las_catalog(cur, apply, log):
    """Promote LAS/DLIS/LIS curves into dataview.dv_log_curve (set-based)."""
    if not object_exists(cur, DV_SCHEMA, "dv_log_curve"):
        return ("dv_log_curve", None, None, None, "no dv target")

    has_las  = object_exists(cur, "las_catalog", "LAS_FILE_CURVE")
    has_dlis = object_exists(cur, "las_catalog", "DLIS_CHANNEL")
    has_lis  = object_exists(cur, "las_catalog", "LIS_CHANNEL")
    if not (has_las or has_dlis or has_lis):
        return ("dv_log_curve", 0, 0, 0, "no las_catalog curves")

    branches = []
    if has_las:
        branches.append("""
        SELECT f.UWI AS uwi, 'LAS' AS fmt,
               CAST(NULL AS INT) AS logical_file,
               CAST(NULL AS NVARCHAR(128)) AS frame_name,
               c.CURVE_ID AS mnem, c.CURVE_DESCRIPTION AS long_name,
               c.CURVE_UNIT AS unit, c.API_CODE AS api_code,
               CAST(NULL AS NVARCHAR(32)) AS dim, CAST(NULL AS CHAR(1)) AS is_index,
               f.DEPTH_UOM AS uom, f.TOP_DEPTH AS dstart, f.BASE_DEPTH AS dstop,
               f.DEPTH_STEP AS dstep, f.SAMPLE_COUNT AS scount, f.FILE_NAME AS fname
        FROM las_catalog.LAS_FILE f
        JOIN las_catalog.LAS_FILE_CURVE c ON c.LAS_FILE_ID = f.LAS_FILE_ID""")
    if has_dlis:
        branches.append("""
        SELECT f.UWI, 'DLIS',
               ch.LOGICAL_FILE_IDX, ch.FRAME_NAME,
               ch.CHANNEL_NAME, ch.LONG_NAME, ch.UNITS, NULL,
               ch.DIMENSION, ch.IS_INDEX,
               fr.DEPTH_UOM, fr.TOP_DEPTH, fr.BASE_DEPTH, fr.SPACING,
               fr.SAMPLE_COUNT, f.FILE_NAME
        FROM las_catalog.DLIS_FILE f
        JOIN las_catalog.DLIS_CHANNEL ch ON ch.DLIS_FILE_ID = f.DLIS_FILE_ID
        LEFT JOIN las_catalog.DLIS_FRAME fr
               ON fr.DLIS_FILE_ID    = ch.DLIS_FILE_ID
              AND fr.LOGICAL_FILE_IDX = ch.LOGICAL_FILE_IDX
              AND fr.FRAME_NAME       = ch.FRAME_NAME""")
    if has_lis:
        branches.append("""
        SELECT f.UWI, 'LIS', NULL, NULL,
               ch.CHANNEL_NAME, NULL, ch.UNITS, NULL, NULL, ch.IS_INDEX,
               f.DEPTH_UOM, f.TOP_DEPTH, f.BASE_DEPTH, NULL,
               f.SAMPLE_COUNT, f.FILE_NAME
        FROM las_catalog.LIS_FILE f
        JOIN las_catalog.LIS_CHANNEL ch ON ch.LIS_FILE_ID = f.LIS_FILE_ID""")

    union_sql = "\n        UNION ALL\n".join(branches)

    # ── 1. materialize the union once, with the basename computed once ───────
    cur.execute("IF OBJECT_ID('tempdb..#curves')   IS NOT NULL DROP TABLE #curves")
    cur.execute("IF OBJECT_ID('tempdb..#fn2inv')   IS NOT NULL DROP TABLE #fn2inv")
    cur.execute("IF OBJECT_ID('tempdb..#welluwi')  IS NOT NULL DROP TABLE #welluwi")
    cur.execute("IF OBJECT_ID('tempdb..#resolved') IS NOT NULL DROP TABLE #resolved")

    cur.execute(f"""
        SELECT q.*,
               RIGHT(P.p, CHARINDEX('\\', REVERSE(P.p) + '\\') - 1) AS bname
        INTO #curves
        FROM (
        {union_sql}
        ) q
        CROSS APPLY (SELECT ISNULL(REPLACE(q.fname, '/', '\\'), '') AS p) P
    """)
    cur.execute("CREATE INDEX IX_curves_bname ON #curves(bname)")

    # ── 2. basename -> INVENTORY_ID, UNAMBIGUOUS matches only, built once ────
    #     (only basenames that actually appear in the curve set)
    cur.execute("""
        SELECT g.FILE_NAME AS bname, MIN(g.INVENTORY_ID) AS inv_id
        INTO #fn2inv
        FROM file_catalog.GLOBAL_FILE_CATALOG g
        WHERE g.FILE_NAME IN (SELECT bname FROM #curves)
        GROUP BY g.FILE_NAME
        HAVING COUNT(*) = 1
    """)
    cur.execute("CREATE INDEX IX_fn2inv_bname ON #fn2inv(bname)")

    # ── 3. which curve UWIs exist in dv_well, resolved once ──────────────────
    cur.execute(f"""
        SELECT DISTINCT w.uwi
        INTO #welluwi
        FROM {DV_SCHEMA}.dv_well w
        WHERE EXISTS (SELECT 1 FROM #curves c WHERE c.uwi = w.uwi)
    """)
    cur.execute("CREATE INDEX IX_welluwi_uwi ON #welluwi(uwi)")

    # ── 4. join once into #resolved; both diagnostics and insert read it ─────
    cur.execute("""
        SELECT c.*,
               fi.inv_id AS inv_id,
               CASE WHEN wu.uwi IS NOT NULL THEN 1 ELSE 0 END AS has_well
        INTO #resolved
        FROM #curves c
        LEFT JOIN #fn2inv  fi ON fi.bname = c.bname
        LEFT JOIN #welluwi wu ON wu.uwi  = c.uwi
    """)

    cur.execute("""
        SELECT COUNT(*) AS eligible,
               SUM(CASE WHEN inv_id IS NULL THEN 1 ELSE 0 END) AS no_inv,
               SUM(CASE WHEN inv_id IS NOT NULL AND has_well = 0
                        THEN 1 ELSE 0 END) AS no_well
        FROM #resolved
    """)
    eligible, no_inv, no_well = cur.fetchone()
    eligible = eligible or 0
    no_inv   = no_inv or 0
    no_well  = no_well or 0

    def _hold_log():
        if no_inv:
            log(f"    {'':30}   held {no_inv:>6}  no INVENTORY_ID match (audit)")
        if no_well:
            log(f"    {'':30}   held {no_well:>6}  UWI not yet in dv_well")

    if not apply or not eligible:
        _hold_log()
        for t in ("#curves", "#fn2inv", "#welluwi", "#resolved"):
            cur.execute(f"IF OBJECT_ID('tempdb..{t}') IS NOT NULL DROP TABLE {t}")
        return ("dv_log_curve", eligible, 0, no_inv + no_well, "LAS/DLIS/LIS curves")

    cur.execute("""
        INSERT INTO dataview.dv_log_curve
            (INVENTORY_ID, UWI, UWI14, SOURCE_FORMAT, LOGICAL_FILE, FRAME_NAME,
             CURVE_INDEX, CURVE_MNEMONIC, CURVE_LONG_NAME, CURVE_UNIT, API_CODE,
             CURVE_DIMENSION, IS_INDEX, DEPTH_UOM, DEPTH_START, DEPTH_STOP,
             DEPTH_STEP, SAMPLE_COUNT, NULL_VALUE)
        SELECT r.inv_id, r.uwi, NULL, r.fmt, r.logical_file, r.frame_name,
               NULL, r.mnem, r.long_name, r.unit, r.api_code,
               r.dim, r.is_index, r.uom, r.dstart, r.dstop,
               r.dstep, r.scount, NULL
        FROM #resolved r
        WHERE r.inv_id IS NOT NULL
          AND r.mnem   IS NOT NULL
          AND r.has_well = 1
          AND NOT EXISTS (
                SELECT 1 FROM dataview.dv_log_curve d
                 WHERE d.INVENTORY_ID = r.inv_id
                   AND d.CURVE_MNEMONIC = r.mnem
                   AND ISNULL(d.FRAME_NAME, '') = ISNULL(r.frame_name, '')
                   AND ISNULL(d.LOGICAL_FILE, -1) = ISNULL(r.logical_file, -1))
    """)
    promoted = cur.rowcount or 0
    _hold_log()

    for t in ("#curves", "#fn2inv", "#welluwi", "#resolved"):
        cur.execute(f"IF OBJECT_ID('tempdb..{t}') IS NOT NULL DROP TABLE {t}")

    return ("dv_log_curve", eligible, promoted, no_inv + no_well,
            "LAS/DLIS/LIS curves")

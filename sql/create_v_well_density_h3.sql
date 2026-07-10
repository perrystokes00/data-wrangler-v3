-- =============================================================================
-- create_v_well_density_h3.sql
--
-- Step 4 of the H3 pipeline. Recreate the federation view to expose H3
-- columns, and build the per-resolution density aggregation views that
-- the page will consume.
--
-- v_well's structure preserves Session 1's exact definition (the
-- dv_business_associate + dv_field joins, the ISNULL fallbacks, the
-- region-as-province-state quirk for GOM, etc.) with FOUR new columns
-- appended: h3_r4, h3_r5, h3_r6, h3_r7.
--
-- h3_coord_hash is NOT exposed in v_well — internal staleness marker,
-- no downstream consumer.
--
-- Two artifacts:
--
--   1. dataview_federation.v_well  (RECREATED)
--      - Canonical 20 columns from Session 1 (unchanged)
--      - PLUS h3_r4, h3_r5, h3_r6, h3_r7
--
--   2. dataview_federation.v_well_density_r{4,5,6,7}  (NEW)
--      - Pre-aggregated: (h3, well_count, dv_schema)
--      - One row per non-empty H3 cell per source schema
--
-- Density views are plain VIEWs (computed at query time), not materialized.
-- Performance is fine because h3_r5/h3_r6 are indexed and GROUP BY on an
-- indexed column = streaming aggregate plan. Output cardinality is in the
-- thousands max, comfortably within pyodbc's working envelope.
--
-- Author: Session 3, 2026-05-26
-- =============================================================================

USE [DataView];
GO

SET XACT_ABORT ON;
GO

PRINT '=== create_v_well_density_h3.sql ===';
GO

-- ---------------------------------------------------------------------------
-- Pre-flight: confirm H3 NOT NULL is in place before exposing H3 cols.
-- ---------------------------------------------------------------------------

DECLARE @nullable_count INT;
SELECT @nullable_count = COUNT(*)
FROM sys.columns
WHERE object_id IN (OBJECT_ID('dataview.dv_well'), OBJECT_ID('dataview_gom.well'))
  AND name IN ('h3_r4', 'h3_r5', 'h3_r6', 'h3_r7')
  AND is_nullable = 1;

IF @nullable_count > 0
BEGIN
    DECLARE @msg NVARCHAR(200) = CONCAT(
        'REFUSING TO RUN: ', @nullable_count,
        ' H3 columns are still nullable. ',
        'Run alter_wells_h3_not_null.sql first.'
    );
    RAISERROR(@msg, 16, 1);
END

PRINT 'Pre-flight passed: H3 columns are all NOT NULL.';
GO

-- ---------------------------------------------------------------------------
-- Drop dependent objects in correct order
-- ---------------------------------------------------------------------------

IF OBJECT_ID('dataview_federation.v_well_density_r4', 'V') IS NOT NULL
    DROP VIEW dataview_federation.v_well_density_r4;
IF OBJECT_ID('dataview_federation.v_well_density_r5', 'V') IS NOT NULL
    DROP VIEW dataview_federation.v_well_density_r5;
IF OBJECT_ID('dataview_federation.v_well_density_r6', 'V') IS NOT NULL
    DROP VIEW dataview_federation.v_well_density_r6;
IF OBJECT_ID('dataview_federation.v_well_density_r7', 'V') IS NOT NULL
    DROP VIEW dataview_federation.v_well_density_r7;

IF OBJECT_ID('dataview_federation.v_well', 'V') IS NOT NULL
    DROP VIEW dataview_federation.v_well;
GO

-- ---------------------------------------------------------------------------
-- v_well — Session 1's exact definition + 4 H3 columns appended.
-- ---------------------------------------------------------------------------

CREATE VIEW dataview_federation.v_well AS

-- ═══════════════════════════════════════════════════════════════════════
-- ARM 1: Onshore (dataview.dv_well, PPDM-shaped)
-- ═══════════════════════════════════════════════════════════════════════
-- Joins dv_business_associate for operator_name and dv_field for
-- field_name/basin_name. Existing dv_well.protraction_area column was
-- populated by populate_dv_well_protraction_area.py and stores friendly
-- names directly (e.g. "Mississippi Canyon"), so no translation needed.
SELECT
    -- IDENTITY
    CAST(w.uwi              AS NVARCHAR(36))   AS uwi,
    CAST(w.well_name        AS NVARCHAR(200))  AS well_name,
    CAST(w.api_num          AS NVARCHAR(50))   AS api_num,

    -- CLASSIFICATION (raw — no canonicalization in v1)
    CAST(w.well_type        AS NVARCHAR(50))   AS well_type,
    CAST(w.well_status      AS NVARCHAR(50))   AS well_status,

    -- LOCATION
    CAST(w.surface_latitude  AS FLOAT)         AS lat,
    CAST(w.surface_longitude AS FLOAT)         AS lon,
    CAST('USA'              AS NVARCHAR(10))   AS country,
    CAST(w.province_state   AS NVARCHAR(20))   AS province_state,
    CAST(w.county           AS NVARCHAR(50))   AS county,
    CAST(f.basin_name       AS NVARCHAR(100))  AS basin_name,
    CAST(f.field_name       AS NVARCHAR(100))  AS field_name,
    CAST(w.area             AS NVARCHAR(100))  AS area,
    CAST(w.protraction_area AS NVARCHAR(100))  AS protraction_area,

    -- DATES / DEPTHS
    CONVERT(VARCHAR(10), w.spud_date,       120) AS spud_date,
    CONVERT(VARCHAR(10), w.completion_date, 120) AS completion_date,
    CAST(w.final_td         AS FLOAT)          AS final_td,

    -- ATTRIBUTION
    CAST(ISNULL(ba.ba_name, 'Unknown') AS NVARCHAR(200)) AS operator_name,
    CAST(w.source           AS NVARCHAR(50))   AS source,
    CAST('dataview'         AS NVARCHAR(50))   AS dv_schema,

    -- H3 cells (NEW in Session 3)
    w.h3_r4                                    AS h3_r4,
    w.h3_r5                                    AS h3_r5,
    w.h3_r6                                    AS h3_r6,
    w.h3_r7                                    AS h3_r7

FROM dataview.dv_well w
    LEFT JOIN dataview.dv_business_associate ba
        ON ba.ba_id = w.operator_ba_id
    LEFT JOIN dataview.dv_field f
        ON f.field_id = w.field_id
WHERE w.surface_latitude  IS NOT NULL
  AND w.surface_longitude IS NOT NULL

UNION ALL

-- ═══════════════════════════════════════════════════════════════════════
-- ARM 2: Offshore (dataview_gom.well, BOEM-shaped)
-- ═══════════════════════════════════════════════════════════════════════
-- Joins boem_area_lookup to translate bottom_area_code → friendly name.
-- Columns the source schema doesn't have come through as NULL (county,
-- field_name, basin_name, area, country). well_id is cast to VARCHAR
-- to match onshore uwi's string type.
SELECT
    -- IDENTITY
    CAST(CONVERT(VARCHAR(36), w.well_id) AS NVARCHAR(36))     AS uwi,
    CAST(w.well_name           AS NVARCHAR(200))              AS well_name,
    CAST(w.api_well_number     AS NVARCHAR(50))               AS api_num,

    -- CLASSIFICATION (raw — BOEM codes, not PPDM-translated)
    CAST(ISNULL(w.type_code,   'Unknown') AS NVARCHAR(50))    AS well_type,
    CAST(ISNULL(w.status_code, 'Unknown') AS NVARCHAR(50))    AS well_status,

    -- LOCATION
    CAST(w.surface_latitude    AS FLOAT)                      AS lat,
    CAST(w.surface_longitude   AS FLOAT)                      AS lon,
    CAST(NULL                  AS NVARCHAR(10))               AS country,
    CAST(w.region              AS NVARCHAR(20))               AS province_state,
    CAST(NULL                  AS NVARCHAR(50))               AS county,
    CAST(NULL                  AS NVARCHAR(100))              AS basin_name,
    CAST(NULL                  AS NVARCHAR(100))              AS field_name,
    CAST(NULL                  AS NVARCHAR(100))              AS area,
    CAST(bal.area_name         AS NVARCHAR(100))              AS protraction_area,

    -- DATES / DEPTHS — completion_date uses total_depth_date as proxy
    -- since BOEM doesn't track a separate completion event
    CONVERT(VARCHAR(10), w.spud_date,        120)             AS spud_date,
    CONVERT(VARCHAR(10), w.total_depth_date, 120)             AS completion_date,
    CAST(w.bh_total_md_ft      AS FLOAT)                      AS final_td,

    -- ATTRIBUTION
    CAST(ISNULL(w.company_name, 'Unknown') AS NVARCHAR(200))  AS operator_name,
    CAST('BOEM'                AS NVARCHAR(50))               AS source,
    CAST('dataview_gom'        AS NVARCHAR(50))               AS dv_schema,

    -- H3 cells (NEW in Session 3)
    w.h3_r4                                                   AS h3_r4,
    w.h3_r5                                                   AS h3_r5,
    w.h3_r6                                                   AS h3_r6,
    w.h3_r7                                                   AS h3_r7

FROM dataview_gom.well w
    LEFT JOIN dataview_federation.boem_area_lookup bal
        ON bal.area_code = w.bottom_area_code
WHERE w.surface_latitude  IS NOT NULL
  AND w.surface_longitude IS NOT NULL;
GO

PRINT 'v_well recreated with H3 columns.';
GO

-- ---------------------------------------------------------------------------
-- Density views: one per resolution.
--
-- Each view returns (h3, well_count, dv_schema). Page can:
--   - aggregate cross-schema: SELECT h3, SUM(well_count) FROM v_well_density_r5 GROUP BY h3
--   - filter to one schema:   SELECT h3, well_count FROM v_well_density_r5 WHERE dv_schema = 'dataview'
--
-- UNION ALL with dv_schema discriminator lets each branch use its source
-- table's h3_r* index directly. Going through v_well would aggregate
-- across the UNION first, potentially over a non-indexed projection.
-- ---------------------------------------------------------------------------

CREATE VIEW dataview_federation.v_well_density_r4 AS
    SELECT h3_r4 AS h3, COUNT(*) AS well_count,
           CAST('dataview' AS NVARCHAR(50)) AS dv_schema
    FROM dataview.dv_well
    WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
    GROUP BY h3_r4
    UNION ALL
    SELECT h3_r4, COUNT(*), CAST('dataview_gom' AS NVARCHAR(50))
    FROM dataview_gom.well
    WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
    GROUP BY h3_r4;
GO

CREATE VIEW dataview_federation.v_well_density_r5 AS
    SELECT h3_r5 AS h3, COUNT(*) AS well_count,
           CAST('dataview' AS NVARCHAR(50)) AS dv_schema
    FROM dataview.dv_well
    WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
    GROUP BY h3_r5
    UNION ALL
    SELECT h3_r5, COUNT(*), CAST('dataview_gom' AS NVARCHAR(50))
    FROM dataview_gom.well
    WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
    GROUP BY h3_r5;
GO

CREATE VIEW dataview_federation.v_well_density_r6 AS
    SELECT h3_r6 AS h3, COUNT(*) AS well_count,
           CAST('dataview' AS NVARCHAR(50)) AS dv_schema
    FROM dataview.dv_well
    WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
    GROUP BY h3_r6
    UNION ALL
    SELECT h3_r6, COUNT(*), CAST('dataview_gom' AS NVARCHAR(50))
    FROM dataview_gom.well
    WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
    GROUP BY h3_r6;
GO

CREATE VIEW dataview_federation.v_well_density_r7 AS
    SELECT h3_r7 AS h3, COUNT(*) AS well_count,
           CAST('dataview' AS NVARCHAR(50)) AS dv_schema
    FROM dataview.dv_well
    WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
    GROUP BY h3_r7
    UNION ALL
    SELECT h3_r7, COUNT(*), CAST('dataview_gom' AS NVARCHAR(50))
    FROM dataview_gom.well
    WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
    GROUP BY h3_r7;
GO

PRINT 'Density views created (r4, r5, r6, r7).';
GO

-- ---------------------------------------------------------------------------
-- Smoke tests
--
-- Expected magnitudes (rough):
--   r4: ~50-200 cells across both sources (continent-wide)
--   r5: ~500-2,000 cells
--   r6: ~5,000-15,000 cells
--   r7: ~30,000-80,000 cells
--
-- Total wells per resolution should equal 531,783 (477,108 + 54,675).
-- ---------------------------------------------------------------------------

PRINT '';
PRINT 'Density view cell counts:';
SELECT 'r4' AS resolution, COUNT(*) AS distinct_cells,
       SUM(well_count) AS total_wells
FROM dataview_federation.v_well_density_r4
UNION ALL
SELECT 'r5', COUNT(*), SUM(well_count)
FROM dataview_federation.v_well_density_r5
UNION ALL
SELECT 'r6', COUNT(*), SUM(well_count)
FROM dataview_federation.v_well_density_r6
UNION ALL
SELECT 'r7', COUNT(*), SUM(well_count)
FROM dataview_federation.v_well_density_r7;

PRINT '';
PRINT 'v_well + density views ready. Next: validate_h3_views.py';
GO

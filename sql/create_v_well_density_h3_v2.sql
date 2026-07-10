-- =============================================================================
-- create_v_well_density_h3_v2.sql
--
-- Recreates dataview_federation.v_well and the four v_well_density_r* views.
--
-- Changes from v1 (Session 3 version):
--   * operator_name now falls back to the denormalized w.operator_name column
--     before defaulting to 'Unknown'. KGS rows have NULL operator_ba_id but
--     populated operator_name, so the old view returned 'Unknown' for all
--     KGS wells. The three-tier fallback is:
--           COALESCE(w.operator_name, ba.ba_name, 'Unknown')
--
--   * field_name uses the same pattern:
--           COALESCE(w.field_name, f.field_name, NULL)
--     KGS rows have NULL field_id but populated field_name.
--
-- Everything else preserved from the Session 3 view definition.
-- =============================================================================

USE [DataView];
GO

SET XACT_ABORT ON;
GO

PRINT '=== create_v_well_density_h3_v2.sql ===';
GO

-- ---------------------------------------------------------------------------
-- Pre-flight: confirm H3 NOT NULL is in place
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
        'Run delete_kgs_null_coords_and_restore_h3_v2.sql first.'
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

PRINT 'Dropped existing federation views.';
GO

-- ---------------------------------------------------------------------------
-- v_well — three-tier fallback for operator_name and field_name
-- ---------------------------------------------------------------------------
CREATE VIEW dataview_federation.v_well AS

-- ═══════════════════════════════════════════════════════════════════════
-- ARM 1: Onshore (dataview.dv_well, PPDM-shaped)
-- ═══════════════════════════════════════════════════════════════════════
-- operator_name: prefer the denormalized w.operator_name (populated for
-- sources that don't use ba_id), fall back to the ba lookup, then 'Unknown'.
-- field_name: same pattern with the denormalized w.field_name column.
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
    -- field_name three-tier fallback
    CAST(COALESCE(w.field_name, f.field_name) AS NVARCHAR(100)) AS field_name,
    CAST(w.area             AS NVARCHAR(100))  AS area,
    CAST(w.protraction_area AS NVARCHAR(100))  AS protraction_area,

    -- DATES / DEPTHS
    CONVERT(VARCHAR(10), w.spud_date,       120) AS spud_date,
    CONVERT(VARCHAR(10), w.completion_date, 120) AS completion_date,
    CAST(w.final_td         AS FLOAT)          AS final_td,

    -- ATTRIBUTION — operator_name three-tier fallback
    CAST(COALESCE(w.operator_name, ba.ba_name, 'Unknown')
         AS NVARCHAR(200))                       AS operator_name,
    CAST(w.source           AS NVARCHAR(50))   AS source,
    CAST('dataview'         AS NVARCHAR(50))   AS dv_schema,

    -- H3 cells
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
SELECT
    CAST(CONVERT(VARCHAR(36), w.well_id) AS NVARCHAR(36))     AS uwi,
    CAST(w.well_name           AS NVARCHAR(200))              AS well_name,
    CAST(w.api_well_number     AS NVARCHAR(50))               AS api_num,

    CAST(ISNULL(w.type_code,   'Unknown') AS NVARCHAR(50))    AS well_type,
    CAST(ISNULL(w.status_code, 'Unknown') AS NVARCHAR(50))    AS well_status,

    CAST(w.surface_latitude    AS FLOAT)                      AS lat,
    CAST(w.surface_longitude   AS FLOAT)                      AS lon,
    CAST(NULL                  AS NVARCHAR(10))               AS country,
    CAST(w.region              AS NVARCHAR(20))               AS province_state,
    CAST(NULL                  AS NVARCHAR(50))               AS county,
    CAST(NULL                  AS NVARCHAR(100))              AS basin_name,
    CAST(NULL                  AS NVARCHAR(100))              AS field_name,
    CAST(NULL                  AS NVARCHAR(100))              AS area,
    CAST(bal.area_name         AS NVARCHAR(100))              AS protraction_area,

    CONVERT(VARCHAR(10), w.spud_date,        120)             AS spud_date,
    CONVERT(VARCHAR(10), w.total_depth_date, 120)             AS completion_date,
    CAST(w.bh_total_md_ft      AS FLOAT)                      AS final_td,

    CAST(ISNULL(w.company_name, 'Unknown') AS NVARCHAR(200))  AS operator_name,
    CAST('BOEM'                AS NVARCHAR(50))               AS source,
    CAST('dataview_gom'        AS NVARCHAR(50))               AS dv_schema,

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

PRINT 'v_well recreated with H3 columns and denormalized fallbacks.';
GO

-- ---------------------------------------------------------------------------
-- Density views — one per resolution
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
-- ---------------------------------------------------------------------------
PRINT '';
PRINT 'Federation view smoke tests:';

SELECT 'v_well total wells'        AS metric, COUNT(*) AS value
FROM dataview_federation.v_well
UNION ALL
SELECT 'v_well KGS wells',          COUNT(*)
FROM dataview_federation.v_well WHERE source = 'KGS'
UNION ALL
SELECT 'v_well BOEM wells',         COUNT(*)
FROM dataview_federation.v_well WHERE source = 'BOEM'
UNION ALL
SELECT 'KGS wells with operator',   COUNT(*)
FROM dataview_federation.v_well WHERE source = 'KGS' AND operator_name != 'Unknown'
UNION ALL
SELECT 'KGS wells with field_name', COUNT(*)
FROM dataview_federation.v_well WHERE source = 'KGS' AND field_name IS NOT NULL;

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
PRINT 'v_well + density views recreated successfully.';
GO

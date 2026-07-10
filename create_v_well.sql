/*****************************************************************************
 * create_v_well.sql
 * ==================
 * Federation v1 — first deliverable.
 *
 * Builds dataview_federation.v_well, a view that unifies onshore wells
 * (dataview.dv_well, PPDM-shaped) and offshore wells (dataview_gom.well,
 * BOEM-shaped) under a single canonical 20-column shape.
 *
 * The view itself does no materialization — each query against v_well
 * re-runs the UNION ALL on the source tables. For V3's current scale
 * (~108K wells) this is fast enough. Materialization (a snapshot table)
 * is a future option if scale demands.
 *
 * Architectural decisions captured here:
 *   - View only (no snapshot in v1)
 *   - 20 canonical columns; raw status/type, NULL where data doesn't exist
 *   - Composite natural key (dv_schema, uwi) — no surrogate PK
 *   - Schema dropdown becomes a dv_schema filter
 *   - GOM field_name = NULL (no stand-in, was previously bottom_area_code)
 *   - GOM protraction_area = friendly name (joined from boem_area_lookup)
 *   - Both arms filter WHERE surface_lat/lon IS NOT NULL
 *
 * To install: run this script ONCE against the V3 database (DataView).
 * To uninstall: see DROP statements at bottom (commented out).
 *
 * Author: Data Wrangler Solutions LLC
 * Date:   2026-05-25
 *****************************************************************************/


-- ───────────────────────────────────────────────────────────────────────────
-- STEP 1: Create the federation schema
-- ───────────────────────────────────────────────────────────────────────────

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dataview_federation')
BEGIN
    EXEC('CREATE SCHEMA dataview_federation');
    PRINT 'Created schema: dataview_federation';
END
ELSE
BEGIN
    PRINT 'Schema dataview_federation already exists';
END
GO


-- ───────────────────────────────────────────────────────────────────────────
-- STEP 2: BOEM area-code lookup table
-- ───────────────────────────────────────────────────────────────────────────
-- Maps BOEM OCS area codes (2-3 letter) to canonical human-readable
-- names ("MC" → "Mississippi Canyon"). Sourced from boem_area_codes.py
-- which extracts unique values from BOEM's protclip.dbf shapefile.
--
-- Used by the GOM arm of v_well to translate bottom_area_code into
-- the canonical protraction_area name, matching how the onshore arm
-- already stores friendly names in dv_well.protraction_area.
--
-- This is a small static reference table (~63 rows). Refresh by
-- re-running the boem_area_codes.py extract and updating this script.

IF OBJECT_ID('dataview_federation.boem_area_lookup', 'U') IS NULL
BEGIN
    CREATE TABLE dataview_federation.boem_area_lookup (
        area_code  VARCHAR(5)    NOT NULL PRIMARY KEY,
        area_name  NVARCHAR(100) NOT NULL
    );
    PRINT 'Created table: dataview_federation.boem_area_lookup';
END
ELSE
BEGIN
    PRINT 'Table dataview_federation.boem_area_lookup already exists; truncating';
    TRUNCATE TABLE dataview_federation.boem_area_lookup;
END
GO

-- Populate from BOEM area code lookup
INSERT INTO dataview_federation.boem_area_lookup (area_code, area_name) VALUES
    ('AC', N'Alaminos Canyon'),
    ('AM', N'Amery Terrace'),
    ('AP', N'Apalachicola'),
    ('AT', N'Atwater Valley'),
    ('BA', N'Brazos'),
    ('BM', N'Bay Marchand'),
    ('BS', N'Breton Sound'),
    ('CA', N'Chandeleur'),
    ('CC', N'Corpus Christi'),
    ('CE', N'Campeche Escarpment'),
    ('CH', N'Charlotte Harbor'),
    ('DC', N'De Soto Canyon'),
    ('DD', N'Destin Dome'),
    ('DT', N'Dry Tortugas'),
    ('EB', N'East Breaks'),
    ('EC', N'East Cameron'),
    ('EI', N'Eugene Island'),
    ('EL', N'The Elbow'),
    ('EW', N'Ewing Bank'),
    ('FM', N'Florida Middle Ground'),
    ('FP', N'Florida Plain'),
    ('GA', N'Galveston'),
    ('GB', N'Garden Banks'),
    ('GC', N'Green Canyon'),
    ('GI', N'Grand Isle'),
    ('GV', N'Gainesville'),
    ('HE', N'Henderson'),
    ('HH', N'Howell Hook'),
    ('HI', N'High Island'),
    ('KC', N'Keathley Canyon'),
    ('KW', N'Key West'),
    ('LL', N'Lloyd Ridge'),
    ('LS', N'Lund South'),
    ('LU', N'Lund'),
    ('MA', N'Miami'),
    ('MC', N'Mississippi Canyon'),
    ('MI', N'Matagorda Island'),
    ('MO', N'Mobile'),
    ('MP', N'Main Pass'),
    ('MU', N'Mustang Island'),
    ('PB', N'St. Petersburg'),
    ('PE', N'Pensacola'),
    ('PI', N'Port Isabel'),
    ('PL', N'South Pelto'),
    ('PN', N'North Padre Island'),
    ('PR', N'Pulley Ridge'),
    ('PS', N'South Padre Island'),
    ('RK', N'Rankin'),
    ('SA', N'Sabine Pass'),
    ('SE', N'Sigsbee Escarpment'),
    ('SM', N'South Marsh Island'),
    ('SP', N'South Pass'),
    ('SS', N'Ship Shoal'),
    ('ST', N'South Timbalier'),
    ('SX', N'Sabine Pass'),
    ('TP', N'Tarpon Springs'),
    ('TV', N'Tortugas Valley'),
    ('VK', N'Viosca Knoll'),
    ('VN', N'Vernon Basin'),
    ('VR', N'Vermilion'),
    ('WC', N'West Cameron'),
    ('WD', N'West Delta'),
    ('WR', N'Walker Ridge');

PRINT 'Populated boem_area_lookup: 63 rows';
GO


-- ───────────────────────────────────────────────────────────────────────────
-- STEP 3: The federation view
-- ───────────────────────────────────────────────────────────────────────────
-- Drop and recreate (so re-running this script gives a clean state).

IF OBJECT_ID('dataview_federation.v_well', 'V') IS NOT NULL
    DROP VIEW dataview_federation.v_well;
GO

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
    CAST(w.depth_datum      AS FLOAT)          AS depth_datum,

    -- ATTRIBUTION
    CAST(ISNULL(ba.ba_name, 'Unknown') AS NVARCHAR(200)) AS operator_name,
    CAST(w.source           AS NVARCHAR(50))   AS source,
    CAST('dataview'         AS NVARCHAR(50))   AS dv_schema

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
    CAST(w.rkb_ft              AS FLOAT)                      AS depth_datum,

    -- ATTRIBUTION
    CAST(ISNULL(w.company_name, 'Unknown') AS NVARCHAR(200))  AS operator_name,
    CAST('BOEM'                AS NVARCHAR(50))               AS source,
    CAST('dataview_gom'        AS NVARCHAR(50))               AS dv_schema

FROM dataview_gom.well w
    LEFT JOIN dataview_federation.boem_area_lookup bal
        ON bal.area_code = w.bottom_area_code
WHERE w.surface_latitude  IS NOT NULL
  AND w.surface_longitude IS NOT NULL;
GO

PRINT 'Created view: dataview_federation.v_well';
GO


-- ───────────────────────────────────────────────────────────────────────────
-- VALIDATION (run after install to sanity-check)
-- ───────────────────────────────────────────────────────────────────────────

-- Total row count
SELECT 'TOTAL'              AS metric, COUNT(*) AS n FROM dataview_federation.v_well
UNION ALL
SELECT 'dataview rows'      AS metric, COUNT(*) AS n FROM dataview_federation.v_well WHERE dv_schema = 'dataview'
UNION ALL
SELECT 'dataview_gom rows'  AS metric, COUNT(*) AS n FROM dataview_federation.v_well WHERE dv_schema = 'dataview_gom'
UNION ALL
SELECT 'source dv_well'     AS metric, COUNT(*) AS n FROM dataview.dv_well WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
UNION ALL
SELECT 'source gom.well'    AS metric, COUNT(*) AS n FROM dataview_gom.well WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL;

-- Column NULL audit — what fraction of each column is NULL per schema?
-- Useful for sanity-checking the canonical shape decisions.
SELECT
    dv_schema,
    COUNT(*)                                    AS total_rows,
    SUM(CASE WHEN uwi              IS NULL THEN 1 ELSE 0 END) AS null_uwi,
    SUM(CASE WHEN well_name        IS NULL THEN 1 ELSE 0 END) AS null_well_name,
    SUM(CASE WHEN api_num          IS NULL THEN 1 ELSE 0 END) AS null_api_num,
    SUM(CASE WHEN well_type        IS NULL THEN 1 ELSE 0 END) AS null_well_type,
    SUM(CASE WHEN well_status      IS NULL THEN 1 ELSE 0 END) AS null_well_status,
    SUM(CASE WHEN country          IS NULL THEN 1 ELSE 0 END) AS null_country,
    SUM(CASE WHEN province_state   IS NULL THEN 1 ELSE 0 END) AS null_province_state,
    SUM(CASE WHEN county           IS NULL THEN 1 ELSE 0 END) AS null_county,
    SUM(CASE WHEN basin_name       IS NULL THEN 1 ELSE 0 END) AS null_basin_name,
    SUM(CASE WHEN field_name       IS NULL THEN 1 ELSE 0 END) AS null_field_name,
    SUM(CASE WHEN area             IS NULL THEN 1 ELSE 0 END) AS null_area,
    SUM(CASE WHEN protraction_area IS NULL THEN 1 ELSE 0 END) AS null_protraction_area,
    SUM(CASE WHEN spud_date        IS NULL THEN 1 ELSE 0 END) AS null_spud_date,
    SUM(CASE WHEN completion_date  IS NULL THEN 1 ELSE 0 END) AS null_completion_date,
    SUM(CASE WHEN final_td         IS NULL THEN 1 ELSE 0 END) AS null_final_td,
    SUM(CASE WHEN depth_datum      IS NULL THEN 1 ELSE 0 END) AS null_depth_datum,
    SUM(CASE WHEN operator_name    IS NULL THEN 1 ELSE 0 END) AS null_operator_name,
    SUM(CASE WHEN source           IS NULL THEN 1 ELSE 0 END) AS null_source
FROM dataview_federation.v_well
GROUP BY dv_schema;

-- Sample 3 rows from each schema
SELECT TOP 3 'dataview'      AS arm, * FROM dataview_federation.v_well WHERE dv_schema = 'dataview'      ORDER BY uwi;
SELECT TOP 3 'dataview_gom'  AS arm, * FROM dataview_federation.v_well WHERE dv_schema = 'dataview_gom'  ORDER BY uwi;

-- Distinct source values
SELECT dv_schema, source, COUNT(*) AS n
FROM dataview_federation.v_well
GROUP BY dv_schema, source
ORDER BY dv_schema, n DESC;

-- BOEM lookup coverage — how many GOM rows got a friendly protraction_area?
SELECT
    SUM(CASE WHEN protraction_area IS NOT NULL THEN 1 ELSE 0 END) AS got_name,
    SUM(CASE WHEN protraction_area IS NULL     THEN 1 ELSE 0 END) AS no_name,
    COUNT(*)                                                       AS total
FROM dataview_federation.v_well
WHERE dv_schema = 'dataview_gom';


-- ───────────────────────────────────────────────────────────────────────────
-- UNINSTALL (uncomment to remove federation v1 and start over)
-- ───────────────────────────────────────────────────────────────────────────
--
-- DROP VIEW  IF EXISTS dataview_federation.v_well;
-- DROP TABLE IF EXISTS dataview_federation.boem_area_lookup;
-- DROP SCHEMA IF EXISTS dataview_federation;

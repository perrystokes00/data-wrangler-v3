-- =============================================================================
-- redesign_dv_well_denormalized.sql
--
-- Greenfield schema redesign for the federation foundation. Drops the FK
-- reference tables (dv_business_associate, dv_field) and denormalizes
-- operator and field names directly onto dv_well. Switches from a natural
-- key (uwi NVARCHAR(80)) to a deterministic surrogate key (well_id) that
-- encodes source provenance: "KGS_1001187266", "RRC_42201234500000", etc.
--
-- Why this design:
--   1. Reload-idempotent: same source row → same well_id every time
--   2. Multi-source ready: source prefix prevents collisions across sources
--   3. No FK contamination: dirty operator names from one loader can't
--      pollute the reference for other sources
--   4. Simpler reload: TRUNCATE dv_well, reload — no FK dance needed
--   5. UNIQUE(source, source_native_id) guards against double-loads
--
-- Trade-off acknowledged: this departs from PPDM normalized reference
-- tables. Cross-source operator dedup becomes a search/match process
-- rather than an FK structure. We're betting that's the right level of
-- normalization for federation-first design.
--
-- IMPORTANT: this is DESTRUCTIVE. It DROPs dv_well, dv_business_associate,
-- and dv_field. All data in those tables is lost. The KGS reload via the
-- new loader replaces the well data. Operator/field reference data is
-- rebuilt as part of that load (denormalized onto each well row).
--
-- BEFORE RUNNING:
--   1. Confirm git working tree is committed
--   2. Confirm no production users will be affected
--   3. Confirm you have the KGS CSV file available for reload
--   4. Consider backing up dv_well first:
--        SELECT * INTO dataview_backup.dv_well_20260527 FROM dataview.dv_well;
--   5. Review which views/procs depend on dv_well structure (see audit section)
--
-- After running, the next step is the new generic CSV loader, which
-- populates dv_well from raw source CSVs.
--
-- Author: Session 5, 2026-05-27
-- =============================================================================

USE [DataView];
GO

SET XACT_ABORT ON;
GO

PRINT '═══════════════════════════════════════════════════════════════════════';
PRINT 'Schema redesign: denormalized dv_well with surrogate keys';
PRINT '═══════════════════════════════════════════════════════════════════════';
GO

-- ---------------------------------------------------------------------------
-- Pre-flight audit: report what we're about to lose
-- ---------------------------------------------------------------------------
PRINT '';
PRINT '── Pre-flight: current row counts ──';
SELECT 'dataview.dv_well' AS table_name, COUNT(*) AS row_count FROM dataview.dv_well
UNION ALL
SELECT 'dataview.dv_business_associate', COUNT(*) FROM dataview.dv_business_associate
UNION ALL
SELECT 'dataview.dv_field', COUNT(*) FROM dataview.dv_field;

PRINT '';
PRINT '── Pre-flight: objects that depend on dv_well ──';
PRINT '   (if any of these are non-empty, decide whether to preserve them)';
SELECT
    OBJECT_SCHEMA_NAME(referencing_id) + '.' + OBJECT_NAME(referencing_id) AS dependent_object,
    OBJECT_SCHEMA_NAME(referenced_id) + '.' + OBJECT_NAME(referenced_id) AS depends_on
FROM sys.sql_expression_dependencies
WHERE referenced_id IN (
    OBJECT_ID('dataview.dv_well'),
    OBJECT_ID('dataview.dv_business_associate'),
    OBJECT_ID('dataview.dv_field')
)
ORDER BY dependent_object;
GO

-- ---------------------------------------------------------------------------
-- Drop dependent views first (they reference columns we're about to drop)
-- ---------------------------------------------------------------------------
PRINT '';
PRINT '── Dropping dependent views ──';

IF OBJECT_ID('dataview_federation.v_well_density_r4', 'V') IS NOT NULL
BEGIN
    DROP VIEW dataview_federation.v_well_density_r4;
    PRINT '   dropped: dataview_federation.v_well_density_r4';
END
IF OBJECT_ID('dataview_federation.v_well_density_r5', 'V') IS NOT NULL
BEGIN
    DROP VIEW dataview_federation.v_well_density_r5;
    PRINT '   dropped: dataview_federation.v_well_density_r5';
END
IF OBJECT_ID('dataview_federation.v_well_density_r6', 'V') IS NOT NULL
BEGIN
    DROP VIEW dataview_federation.v_well_density_r6;
    PRINT '   dropped: dataview_federation.v_well_density_r6';
END
IF OBJECT_ID('dataview_federation.v_well_density_r7', 'V') IS NOT NULL
BEGIN
    DROP VIEW dataview_federation.v_well_density_r7;
    PRINT '   dropped: dataview_federation.v_well_density_r7';
END

IF OBJECT_ID('dataview_federation.v_well', 'V') IS NOT NULL
BEGIN
    DROP VIEW dataview_federation.v_well;
    PRINT '   dropped: dataview_federation.v_well';
END
GO

-- ---------------------------------------------------------------------------
-- Drop the old tables. Order matters only if there are real FKs — and
-- since the existing schema didn't enforce them (yesterday's audit showed
-- dirty FK targets), we can drop in any order.
--
-- NOTE: dropping dv_well also drops the following 20 indexes that have
-- accumulated over the v3 development cycle. Recorded here for posterity
-- so anyone reverting this change knows what existed before:
--
--   ix_dv_well_api                     api_num
--   ix_dv_well_coords                  surface_latitude, surface_longitude
--   IX_dv_well_county                  county
--   IX_dv_well_fed_search_covering     17-column covering index
--   ix_dv_well_field                   field_id  (duplicate of below)
--   IX_dv_well_field_id                field_id  (duplicate of above)
--   IX_dv_well_h3_r5                   h3_r5
--   IX_dv_well_h3_r6                   h3_r6
--   ix_dv_well_latlon                  14-column covering index
--   IX_dv_well_loader                  17-column covering index (~identical to fed_search_covering)
--   ix_dv_well_location                country, province_state, county
--   ix_dv_well_name                    well_name
--   ix_dv_well_operator                operator_ba_id  (duplicate of below)
--   IX_dv_well_operator_ba_id          operator_ba_id  (duplicate of above)
--   IX_dv_well_province_state          province_state  (duplicate of below)
--   IX_dv_well_state                   province_state  (duplicate of above)
--   IX_dv_well_state_county_op_field   6-column covering index
--   IX_dv_well_source                  source
--   IX_dv_well_well_status             well_status
--   pk_dv_well                         CLUSTERED PK on uwi
--
-- The new schema starts with just 3 indexes (source, h3_r5, h3_r6) plus
-- the clustered PK. Re-add others only after profiling real query patterns
-- on the redesigned schema.
-- ---------------------------------------------------------------------------
PRINT '';
PRINT '── Dropping old tables ──';

IF OBJECT_ID('dataview.dv_well', 'U') IS NOT NULL
BEGIN
    DROP TABLE dataview.dv_well;
    PRINT '   dropped: dataview.dv_well';
END

IF OBJECT_ID('dataview.dv_business_associate', 'U') IS NOT NULL
BEGIN
    DROP TABLE dataview.dv_business_associate;
    PRINT '   dropped: dataview.dv_business_associate';
END

IF OBJECT_ID('dataview.dv_field', 'U') IS NOT NULL
BEGIN
    DROP TABLE dataview.dv_field;
    PRINT '   dropped: dataview.dv_field';
END
GO

-- ---------------------------------------------------------------------------
-- CREATE the new dv_well with the denormalized, surrogate-key design
--
-- Column groupings:
--   IDENTITY            : well_id (PK), source, source_native_id
--   IDENTIFIERS         : api_num, api_num_nodash, well_name, well_num, lease_name, permit_number
--   OPERATOR            : operator_name, original_operator_name  (denormalized)
--   FIELD               : field_name, producing_formation, formation_at_td  (denormalized)
--   CLASSIFICATION      : well_type, well_status
--   LOCATION            : country, state, county, area, protraction_area, coords, etc.
--   DEPTH/ELEVATION     : ground/kb/datum/final_td/uom
--   DATES               : spud, completion, abandonment
--   H3 SPATIAL INDEX    : r4-r7 cells + coord_hash (populated by backfill)
--   AUDIT               : active_ind, remark, row_created/changed_by/date
-- ---------------------------------------------------------------------------
PRINT '';
PRINT '── Creating new dv_well (denormalized, surrogate-key) ──';

CREATE TABLE dataview.dv_well (
    -- ── IDENTITY (deterministic, reload-stable) ─────────────────────
    well_id                  NVARCHAR(80)   NOT NULL,
    source                   NVARCHAR(50)   NOT NULL,
    source_native_id         NVARCHAR(80)   NOT NULL,

    -- ── IDENTIFIERS (searchable attributes) ─────────────────────────
    api_num                  NVARCHAR(40)   NULL,
    api_num_nodash           NVARCHAR(20)   NULL,
    well_name                NVARCHAR(510)  NULL,
    well_num                 NVARCHAR(80)   NULL,
    lease_name               NVARCHAR(510)  NULL,
    permit_number            NVARCHAR(80)   NULL,
    license_num              NVARCHAR(80)   NULL,

    -- ── OPERATOR (denormalized, normalized at load) ─────────────────
    operator_name            NVARCHAR(510)  NULL,
    original_operator_name   NVARCHAR(510)  NULL,

    -- ── FIELD (denormalized, normalized at load) ────────────────────
    field_name               NVARCHAR(510)  NULL,
    producing_formation      NVARCHAR(510)  NULL,
    formation_at_td          NVARCHAR(510)  NULL,

    -- ── CLASSIFICATION ──────────────────────────────────────────────
    well_type                NVARCHAR(80)   NULL,
    well_status              NVARCHAR(80)   NULL,

    -- ── LOCATION ────────────────────────────────────────────────────
    country                  NVARCHAR(80)   NULL,
    province_state           NVARCHAR(200)  NULL,
    county                   NVARCHAR(200)  NULL,
    area                     NVARCHAR(200)  NULL,
    protraction_area         NVARCHAR(200)  NULL,
    surface_latitude         NUMERIC(9,6)   NULL,
    surface_longitude        NUMERIC(9,6)   NULL,
    bottom_hole_latitude     NUMERIC(9,6)   NULL,
    bottom_hole_longitude    NUMERIC(9,6)   NULL,
    long_lat_source          NVARCHAR(80)   NULL,
    legal_survey_type        NVARCHAR(80)   NULL,
    epsg_code                INT            NULL,
    onshore_offshore_ind     NVARCHAR(20)   NULL,

    -- ── DEPTH / ELEVATION ───────────────────────────────────────────
    ground_elevation         NUMERIC(9,2)   NULL,
    kb_elevation             NUMERIC(9,2)   NULL,
    elevation_ouom           NVARCHAR(80)   NULL,
    depth_datum              NVARCHAR(80)   NULL,
    final_td                 NUMERIC(9,2)   NULL,

    -- ── DATES ───────────────────────────────────────────────────────
    spud_date                DATETIME2      NULL,
    completion_date          DATETIME2      NULL,
    abandonment_date         DATETIME2      NULL,

    -- ── H3 SPATIAL INDEX (populated by backfill_h3_bcp.py) ──────────
    -- Nullable for now; the backfill enforces NOT NULL after population.
    h3_r4                    NVARCHAR(15)   NULL,
    h3_r5                    NVARCHAR(15)   NULL,
    h3_r6                    NVARCHAR(15)   NULL,
    h3_r7                    NVARCHAR(15)   NULL,
    h3_coord_hash            BINARY(32)     NULL,

    -- ── AUDIT ───────────────────────────────────────────────────────
    active_ind               NVARCHAR(2)    NOT NULL  DEFAULT 'Y',
    remark                   NVARCHAR(4000) NULL,
    row_created_by           NVARCHAR(80)   NOT NULL  DEFAULT SYSTEM_USER,
    row_created_date         DATETIME2      NOT NULL  DEFAULT SYSUTCDATETIME(),
    row_changed_by           NVARCHAR(80)   NULL,
    row_changed_date         DATETIME2      NULL,

    -- ── CONSTRAINTS ─────────────────────────────────────────────────
    -- Primary key on the synthetic ID.
    CONSTRAINT pk_dv_well
        PRIMARY KEY CLUSTERED (well_id),

    -- Integrity guard: same source's native ID can't appear twice.
    -- (e.g., loading KGS twice without TRUNCATE-first would fail here
    -- rather than silently double-load.)
    CONSTRAINT uq_dv_well_source_native
        UNIQUE (source, source_native_id),

    -- Replaces the old ck_dv_well_ai. Restricts active_ind to Y/N.
    CONSTRAINT ck_dv_well_ai
        CHECK (active_ind IN ('Y', 'N'))
);

PRINT '   created: dataview.dv_well';
PRINT '            41 attribute columns + 2 audit columns + 2 constraints';
GO

-- ---------------------------------------------------------------------------
-- Indexes — start lean. Add more after profiling real query patterns
-- against the new schema.
--
-- Why these three:
--   IX_dv_well_source        : the "all KGS wells" filter, frequent
--   IX_dv_well_h3_r5         : H3 density at zoom level 5 (page workhorse)
--   IX_dv_well_h3_r6         : H3 density at zoom level 6 (page workhorse)
--
-- NOT included (deferred):
--   IX on api_num            : add if string-search performance becomes an issue
--   IX on operator_name      : LIKE '%X%' won't use a B-tree anyway
--   IX on field_name         : same
--   IX on surface_lat/lon    : H3 cells supersede most spatial queries
-- ---------------------------------------------------------------------------
PRINT '';
PRINT '── Creating indexes ──';

CREATE NONCLUSTERED INDEX IX_dv_well_source
    ON dataview.dv_well (source);
PRINT '   created: IX_dv_well_source';

CREATE NONCLUSTERED INDEX IX_dv_well_h3_r5
    ON dataview.dv_well (h3_r5);
PRINT '   created: IX_dv_well_h3_r5';

CREATE NONCLUSTERED INDEX IX_dv_well_h3_r6
    ON dataview.dv_well (h3_r6);
PRINT '   created: IX_dv_well_h3_r6';
GO

-- ---------------------------------------------------------------------------
-- Post-flight: verify the new structure
-- ---------------------------------------------------------------------------
PRINT '';
PRINT '── Post-flight verification ──';

SELECT
    c.column_id AS ord,
    c.name AS column_name,
    t.name + CASE
        WHEN t.name IN ('nvarchar','varchar') THEN '(' + CAST(c.max_length / 2 AS VARCHAR) + ')'
        WHEN t.name = 'numeric' THEN '(' + CAST(c.precision AS VARCHAR) + ',' + CAST(c.scale AS VARCHAR) + ')'
        WHEN t.name = 'binary' THEN '(' + CAST(c.max_length AS VARCHAR) + ')'
        ELSE ''
    END AS data_type,
    CASE WHEN c.is_nullable = 1 THEN 'NULL' ELSE 'NOT NULL' END AS nullable
FROM sys.columns c
JOIN sys.types t ON t.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID('dataview.dv_well')
ORDER BY c.column_id;

PRINT '';
PRINT '── Constraints ──';
SELECT
    name AS constraint_name,
    type_desc AS constraint_type
FROM sys.objects
WHERE parent_object_id = OBJECT_ID('dataview.dv_well')
  AND type IN ('PK', 'UQ')
ORDER BY type_desc, name;

PRINT '';
PRINT '── Indexes ──';
SELECT
    i.name AS index_name,
    i.type_desc AS index_type
FROM sys.indexes i
WHERE i.object_id = OBJECT_ID('dataview.dv_well')
  AND i.type > 0
ORDER BY i.name;

PRINT '';
PRINT '═══════════════════════════════════════════════════════════════════════';
PRINT 'Schema redesign complete.';
PRINT '';
PRINT 'Next steps:';
PRINT '  1. Run the new generic CSV loader to populate dv_well from KGS data';
PRINT '  2. Re-run backfill_h3_bcp.py to populate H3 cells for new rows';
PRINT '  3. Recreate dataview_federation.v_well (uses new column names)';
PRINT '  4. Recreate dataview_federation.v_well_density_r4..r7';
PRINT '═══════════════════════════════════════════════════════════════════════';
GO

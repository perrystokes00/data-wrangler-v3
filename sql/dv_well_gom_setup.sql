-- ============================================================================
-- dv_well_gom_setup.sql
-- ----------------------------------------------------------------------------
-- Creates the universal well identifier registry and the GOM-specific well
-- attribute table.
--
-- Idempotent: safe to re-run. Existing objects are not modified.
--
-- Run in SSMS against the DataView database.
-- ============================================================================

USE DataView;
GO

-- ── Schema: dataview_gom ────────────────────────────────────────────────────
-- Per-region schema for GOM-specific data. Pattern: dataview_<region>.<entity>
-- where <region> is the OCS planning area or basin name.
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dataview_gom')
BEGIN
    EXEC('CREATE SCHEMA dataview_gom AUTHORIZATION dbo;');
    PRINT '  ✓ Created schema [dataview_gom]';
END
ELSE
    PRINT '  • Schema [dataview_gom] already exists';
GO


-- ── Table: dataview.dv_well_identifier ──────────────────────────────────────
-- Universal cross-region identifier registry. One row per (well_id,
-- identifier_type). A single well can have multiple identifiers:
--   ('GOM:42-317-...', 'API_BOEM', '012032016500', 'BOEM', ...)
--   ('GOM:42-317-...', 'API_14',   '04203020165000', 'DERIVED', ...)
-- This is what loaders look up to resolve a source UWI to an internal well_id.
IF NOT EXISTS (SELECT 1 FROM sys.tables t
               JOIN sys.schemas s ON s.schema_id = t.schema_id
               WHERE s.name = 'dataview' AND t.name = 'dv_well_identifier')
BEGIN
    CREATE TABLE dataview.dv_well_identifier (
        well_id          UNIQUEIDENTIFIER NOT NULL,
        identifier_type  NVARCHAR(20)     NOT NULL,
            -- 'API_BOEM' (12-digit), 'API_14' (14-digit US standard),
            -- 'KGS', 'RRC', 'AER', 'SOURCE' (raw source value), etc.
        identifier_value NVARCHAR(40)     NOT NULL,
        source_system    NVARCHAR(40)     NULL,
            -- Where this identifier came from. 'BOEM', 'KGS', 'RRC',
            -- 'OPERATOR', 'DERIVED' (when we transformed one form into another).
        loaded_date      DATETIME2(0)     NOT NULL DEFAULT SYSUTCDATETIME(),
        is_primary       BIT              NOT NULL DEFAULT 0,
            -- One row per well_id should have is_primary=1. Indicates the
            -- "canonical" external ID for that well — used for display and
            -- export defaults.

        CONSTRAINT pk_dv_well_identifier
            PRIMARY KEY CLUSTERED (well_id, identifier_type)
    );

    -- Lookup index: "given an external API number, find the well_id".
    -- This is the hot path for every loader that resolves source UWIs.
    CREATE NONCLUSTERED INDEX ix_dv_well_identifier_lookup
        ON dataview.dv_well_identifier (identifier_type, identifier_value)
        INCLUDE (well_id);

    PRINT '  ✓ Created table [dataview].[dv_well_identifier]';
END
ELSE
    PRINT '  • Table [dataview].[dv_well_identifier] already exists';
GO


-- ── Table: dataview_gom.well ────────────────────────────────────────────────
-- BOEM Gulf of America well headers, source-shaped (one column per BOEM field).
-- Columns are sized to the BOEM data observed in the export. The well_id is
-- the universal internal key (a deterministic UUID derived from
-- 'BOEM:' + api_well_number — see gom_well_loader.py).
IF NOT EXISTS (SELECT 1 FROM sys.tables t
               JOIN sys.schemas s ON s.schema_id = t.schema_id
               WHERE s.name = 'dataview_gom' AND t.name = 'well')
BEGIN
    CREATE TABLE dataview_gom.well (
        -- ── Universal key ──────────────────────────────────────────────
        well_id              UNIQUEIDENTIFIER NOT NULL,

        -- ── BOEM identifiers ───────────────────────────────────────────
        api_well_number      NVARCHAR(20)  NOT NULL,
            -- BOEM's 12-digit API. Natural row identifier from the source.
            -- Kept as the "natural" lookup; well_id is the synthetic.
        well_name            NVARCHAR(40)  NULL,
            -- BOEM well name (trimmed; source has leading spaces).
        well_name_suffix     NVARCHAR(20)  NULL,
            -- ST00BP00 format — sidetrack/bypass designation.

        -- ── Lease & location framework ─────────────────────────────────
        surface_lease_number NVARCHAR(20)  NULL,
        bottom_lease_number  NVARCHAR(20)  NULL,
        bottom_area_code     NVARCHAR(10)  NULL,
            -- OCS protraction area: MO=Mobile, WD=West Delta, WC=West Cameron, etc.
        bottom_block_number  NVARCHAR(20)  NULL,
            -- Lease block within the area. Stored as string (source has
            -- leading spaces and varying width).
        region               NVARCHAR(40)  NULL,
            -- Always "Gulf of America" in current BOEM data, but kept as a
            -- column in case BOEM partitions further.

        -- ── Operator (text only for now; FK linkage deferred) ──────────
        company_name         NVARCHAR(255) NULL,
            -- Operator name as BOEM provides it. Not FK'd to a BA table
            -- tonight — defer that to the operator-normalization pass.

        -- ── Dates ──────────────────────────────────────────────────────
        spud_date            DATE          NULL,
        total_depth_date     DATE          NULL,
        status_date          DATE          NULL,

        -- ── Depths (in feet, per BOEM export) ──────────────────────────
        bh_total_md_ft       DECIMAL(10,2) NULL,
            -- "BH Total MD (feet)" — bottomhole measured depth.
        true_vertical_depth_ft DECIMAL(10,2) NULL,
        tvd_subsea_ft        DECIMAL(10,2) NULL,
            -- TVD referenced to subsea datum.
        rkb_ft               DECIMAL(10,2) NULL,
            -- Rotary kelly bushing elevation.
        kop_ft               DECIMAL(10,2) NULL,
            -- Kick-off point (often NULL for vertical wells).
        water_depth_ft       DECIMAL(10,2) NULL,

        -- ── Status / type / completion codes ───────────────────────────
        type_code            NVARCHAR(10)  NULL,
            -- E=Exploration, D=Development, etc.
        status_code          NVARCHAR(10)  NULL,
            -- COM, PA, ST, etc.
        casing_cut_code      NVARCHAR(10)  NULL,
            -- Y=cut, N=not cut, M=multiple. BOEM regulatory marker.
        underwater_comp_stub NVARCHAR(10)  NULL,
            -- Y/N — underwater completion stub indicator.

        -- ── Coordinates ────────────────────────────────────────────────
        -- BOEM provides both low- and high-precision coordinate pairs. We
        -- store the high-precision (starred) values; the low-precision
        -- versions are redundant.
        surface_latitude     DECIMAL(11,7) NULL,
        surface_longitude    DECIMAL(11,7) NULL,
        bottom_latitude      DECIMAL(11,7) NULL,
        bottom_longitude     DECIMAL(11,7) NULL,

        -- ── Provenance ─────────────────────────────────────────────────
        source_file          NVARCHAR(255) NULL,
            -- Path or filename of the load source.
        loaded_date          DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),
        row_changed_date     DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT pk_dv_well_gom PRIMARY KEY CLUSTERED (well_id),
        CONSTRAINT uq_dv_well_gom_api UNIQUE (api_well_number)
    );

    -- Lookups by lease / area / block for filtering in the UI
    CREATE NONCLUSTERED INDEX ix_dv_well_gom_lease
        ON dataview_gom.well (bottom_lease_number);
    CREATE NONCLUSTERED INDEX ix_dv_well_gom_area_block
        ON dataview_gom.well (bottom_area_code, bottom_block_number);

    -- Spatial filter on surface coords (used by the map's bbox queries)
    CREATE NONCLUSTERED INDEX ix_dv_well_gom_surface_coords
        ON dataview_gom.well (surface_latitude, surface_longitude)
        WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL;

    PRINT '  ✓ Created table [dataview_gom].[well]';
END
ELSE
    PRINT '  • Table [dataview_gom].[well] already exists';
GO


-- ── Sanity report ───────────────────────────────────────────────────────────
PRINT '';
PRINT '─── Setup complete ──────────────────────────────────────────';
SELECT
    SCHEMA_NAME(t.schema_id) + '.' + t.name        AS table_name,
    (SELECT COUNT(*) FROM sys.columns WHERE object_id = t.object_id) AS columns,
    (SELECT COUNT(*) FROM sys.indexes WHERE object_id = t.object_id) AS indexes
FROM sys.tables t
WHERE (SCHEMA_NAME(t.schema_id) = 'dataview' AND t.name = 'dv_well_identifier')
   OR (SCHEMA_NAME(t.schema_id) = 'dataview_gom' AND t.name = 'well')
ORDER BY 1;
GO

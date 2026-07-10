-- =============================================================================
-- create_dv_well_ext_kgs.sql
--
-- Creates the source-native extension table for KGS wells. Follows the
-- existing pattern of dv_well_ext_michigan_wells and dv_well_ext_wy_wogcc:
--   - PK is `uwi` (NVARCHAR(40)) — linked back to dv_well
--   - All source columns NVARCHAR(500) for maximum flexibility on raw load
--   - Native KGS column names preserved exactly as published
--
-- This is the "raw" KGS data preservation layer. The federated master
-- dv_well gets a mapped/cleaned PPDM-shaped row alongside this.
--
-- After this DDL, the KGS loader populates this table (one row per KGS
-- well, native columns), then also writes mapped rows to dv_well and
-- dv_well_identifier.
-- =============================================================================

USE [DataView];
GO

SET XACT_ABORT ON;
SET NOCOUNT ON;
GO

BEGIN TRY
    BEGIN TRANSACTION;

    PRINT '═══════════════════════════════════════════════════════════════════════';
    PRINT 'Creating dataview.dv_well_ext_kgs (KGS source-native extension table)';
    PRINT '═══════════════════════════════════════════════════════════════════════';

    -- Defensive: if it already exists, abort rather than recreate silently.
    IF OBJECT_ID('dataview.dv_well_ext_kgs', 'U') IS NOT NULL
    BEGIN
        RAISERROR('Table dataview.dv_well_ext_kgs already exists. Drop it first if you want to recreate.', 16, 1);
    END

    CREATE TABLE [dataview].[dv_well_ext_kgs](
        [uwi]                      NVARCHAR(40)  NOT NULL,

        -- KGS native columns (all 43, in source order, all NVARCHAR(500))
        [KID]                      NVARCHAR(500) NULL,
        [API_NUMBER]               NVARCHAR(500) NULL,
        [API_NUM_NODASH]           NVARCHAR(500) NULL,
        [LEASE]                    NVARCHAR(500) NULL,
        [WELL]                     NVARCHAR(500) NULL,
        [FIELD]                    NVARCHAR(500) NULL,
        [LATITUDE]                 NVARCHAR(500) NULL,
        [LONGITUDE]                NVARCHAR(500) NULL,
        [LONG_LAT_SOURCE]          NVARCHAR(500) NULL,
        [TOWNSHIP]                 NVARCHAR(500) NULL,
        [TWN_DIR]                  NVARCHAR(500) NULL,
        [RANGE_]                   NVARCHAR(500) NULL,  -- 'RANGE' is reserved, suffix with _
        [RANGE_DIR]                NVARCHAR(500) NULL,
        [SECTION_]                 NVARCHAR(500) NULL,  -- 'SECTION' is reserved, suffix with _
        [SPOT]                     NVARCHAR(500) NULL,
        [FEET_NORTH]               NVARCHAR(500) NULL,
        [FEET_EAST]                NVARCHAR(500) NULL,
        [FOOT_REF]                 NVARCHAR(500) NULL,
        [ORIG_OPERATOR]            NVARCHAR(500) NULL,
        [CURR_OPERATOR]            NVARCHAR(500) NULL,
        [ELEVATION]                NVARCHAR(500) NULL,
        [ELEV_REF]                 NVARCHAR(500) NULL,
        [SURFACE_ELEVATION_LIDAR]  NVARCHAR(500) NULL,
        [DEPTH]                    NVARCHAR(500) NULL,
        [FORMATION_AT_TOTAL_DEPTH] NVARCHAR(500) NULL,
        [PRODUCE_FORM]             NVARCHAR(500) NULL,
        [IP_OIL]                   NVARCHAR(500) NULL,
        [IP_GAS]                   NVARCHAR(500) NULL,
        [IP_WATER]                 NVARCHAR(500) NULL,
        [PERMIT]                   NVARCHAR(500) NULL,
        [SPUD]                     NVARCHAR(500) NULL,
        [COMPLETION]               NVARCHAR(500) NULL,
        [PLUGGING]                 NVARCHAR(500) NULL,
        [MODIFIED]                 NVARCHAR(500) NULL,
        [OIL_KID]                  NVARCHAR(500) NULL,
        [OIL_DOR_ID]               NVARCHAR(500) NULL,
        [GAS_KID]                  NVARCHAR(500) NULL,
        [GAS_DOR_ID]               NVARCHAR(500) NULL,
        [KCC_PERMIT]               NVARCHAR(500) NULL,
        [STATUS]                   NVARCHAR(500) NULL,
        [STATUS2]                  NVARCHAR(500) NULL,
        [COMMENTS]                 NVARCHAR(500) NULL,
        [LEASE_WELL_NAME]          NVARCHAR(500) NULL,

        -- Audit
        [loaded_date]              DATETIME2(0)  NOT NULL DEFAULT SYSUTCDATETIME(),

        CONSTRAINT [pk_dv_well_ext_kgs] PRIMARY KEY CLUSTERED ([uwi])
    );

    PRINT '   created: dataview.dv_well_ext_kgs';

    -- Index to support cross-source lookups by KGS native KID
    CREATE NONCLUSTERED INDEX [IX_dv_well_ext_kgs_KID]
        ON [dataview].[dv_well_ext_kgs] ([KID]);

    PRINT '   created: IX_dv_well_ext_kgs_KID';

    -- Index to support API-based queries (a common cross-source join)
    CREATE NONCLUSTERED INDEX [IX_dv_well_ext_kgs_API]
        ON [dataview].[dv_well_ext_kgs] ([API_NUMBER]);

    PRINT '   created: IX_dv_well_ext_kgs_API';

    COMMIT TRANSACTION;

    PRINT '';
    PRINT 'dv_well_ext_kgs created successfully.';
    PRINT 'Ready for the KGS loader to populate it.';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    PRINT 'FAILED: ' + ERROR_MESSAGE();
    THROW;
END CATCH
GO

-- ---------------------------------------------------------------------------
-- Note on reserved-word column renames:
--
-- Two KGS source columns clash with SQL Server reserved words: RANGE and
-- SECTION. Storing as bracketed identifiers ([RANGE], [SECTION]) is legal
-- but every downstream query has to remember the brackets — a maintenance
-- footgun. The convention used elsewhere in dataview (and matching what
-- the dv_well_ext_wy_wogcc table does, which has SEC/TWP not RANGE/SECTION)
-- is to suffix with _ : RANGE → RANGE_, SECTION → SECTION_.
--
-- The loader maps:
--    CSV column 'RANGE'   → table column 'RANGE_'
--    CSV column 'SECTION' → table column 'SECTION_'
-- so the source-native rebuild stays lossless.
-- ---------------------------------------------------------------------------

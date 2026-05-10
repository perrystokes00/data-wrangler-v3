-- =============================================================================
-- Well Log Catalog — DLIS / LIS Extension DDL for SQL Server
-- =============================================================================
-- Step 1: Rename LAS_REPOSITORY → WL_REPOSITORY (shared across all formats)
-- Step 2: Add DLIS tables (DLIS_FILE, DLIS_LOGICAL_FILE, DLIS_FRAME,
--                          DLIS_CHANNEL, DLIS_PARAMETER)
-- Step 3: Add LIS tables  (LIS_FILE, LIS_CHANNEL)
--
-- Run this script AFTER the original las_catalog_ddl.sql has been applied.
-- Safe to re-run — all statements use IF NOT EXISTS guards.
--
-- DLIS depth values are stored in NATIVE units as found in the file,
-- plus a DEPTH_UOM column so the application can convert on the fly.
-- Common native units: '0.1 in', 'ft', 'm', 's' (time logs)
-- =============================================================================


-- =============================================================================
-- STEP 1 — Rename LAS_REPOSITORY to WL_REPOSITORY
-- =============================================================================

-- Drop the FK from LAS_FILE first, rename table, re-add FK
IF OBJECT_ID('[las_catalog].[WL_REPOSITORY]', 'U') IS NULL
BEGIN
    -- Drop existing FK constraint on LAS_FILE
    IF EXISTS (
        SELECT 1 FROM sys.foreign_keys
        WHERE name = 'LASFILE_REP_FK'
          AND parent_object_id = OBJECT_ID('[las_catalog].[LAS_FILE]')
    )
    BEGIN
        ALTER TABLE [las_catalog].[LAS_FILE]
            DROP CONSTRAINT [LASFILE_REP_FK]
    END

    -- Rename the table
    EXEC sp_rename '[las_catalog].[LAS_REPOSITORY]', 'WL_REPOSITORY'

    -- Re-add FK pointing to new name
    ALTER TABLE [las_catalog].[LAS_FILE]
        ADD CONSTRAINT [LASFILE_REP_FK]
        FOREIGN KEY ([REPOSITORY_ID])
        REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID])

    PRINT 'LAS_REPOSITORY renamed to WL_REPOSITORY'
END
ELSE
    PRINT 'WL_REPOSITORY already exists — skipping rename'
GO


-- =============================================================================
-- STEP 2 — DLIS Tables
-- =============================================================================

-- ── DLIS_FILE ─────────────────────────────────────────────────────────────────
-- One row per physical DLIS file on disk.
IF OBJECT_ID('[las_catalog].[DLIS_FILE]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_FILE] (
    [DLIS_FILE_ID]     NVARCHAR(40)   NOT NULL,  -- PK — SHA1 of full path
    [REPOSITORY_ID]    NVARCHAR(40)   NOT NULL,  -- FK → WL_REPOSITORY
    [UWI]              NVARCHAR(40)   NOT NULL,  -- FK → dbo.WELL
    [FILE_NAME]        NVARCHAR(500)  NOT NULL,  -- relative path in repository
    [FILE_SIZE_KB]     NUMERIC(15,2)  NULL,
    [FILE_HASH]        NVARCHAR(64)   NULL,       -- SHA256 for dedup
    [LOGICAL_FILE_COUNT] NUMERIC(5,0) NULL,       -- number of logical files
    [CATALOG_DATE]     DATETIME2      NULL,
    [LAST_SEEN_DATE]   DATETIME2      NULL,
    [ACTIVE_IND]       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    [REMARK]           NVARCHAR(2000) NULL,
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [DLISFILE_PK]      PRIMARY KEY ([DLIS_FILE_ID]),
    CONSTRAINT [DLISFILE_REP_FK]  FOREIGN KEY ([REPOSITORY_ID])
        REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID]),
    CONSTRAINT [DLISFILE_WELL_FK] FOREIGN KEY ([UWI])
        REFERENCES [dbo].[WELL] ([UWI])
)
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'DLISFILE_UWI_IDX')
    CREATE INDEX [DLISFILE_UWI_IDX]
        ON [las_catalog].[DLIS_FILE] ([UWI])
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'DLISFILE_HASH_IDX')
    CREATE INDEX [DLISFILE_HASH_IDX]
        ON [las_catalog].[DLIS_FILE] ([FILE_HASH])
        WHERE [FILE_HASH] IS NOT NULL
GO


-- ── DLIS_LOGICAL_FILE ─────────────────────────────────────────────────────────
-- One row per logical file within a physical DLIS file.
-- Most DLIS files have one logical file but the standard allows many.
IF OBJECT_ID('[las_catalog].[DLIS_LOGICAL_FILE]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_LOGICAL_FILE] (
    [DLIS_FILE_ID]     NVARCHAR(40)   NOT NULL,  -- PK + FK → DLIS_FILE
    [LOGICAL_FILE_IDX] NUMERIC(5,0)   NOT NULL,  -- PK — 0-based index
    [DESCRIPTION]      NVARCHAR(255)  NULL,       -- LogicalFile description string
    [WELL_NAME]        NVARCHAR(255)  NULL,       -- origin.well_name
    [WELL_ID]          NVARCHAR(100)  NULL,       -- origin.well_id (API/UWI in file)
    [COMPANY]          NVARCHAR(255)  NULL,       -- origin.company
    [FIELD_NAME]       NVARCHAR(255)  NULL,       -- origin.field_name
    [PRODUCER_NAME]    NVARCHAR(255)  NULL,       -- origin.producer_name (e.g. Schlumberger)
    [PRODUCT]          NVARCHAR(255)  NULL,       -- origin.product (software)
    [VERSION]          NVARCHAR(100)  NULL,       -- origin.version
    [FILE_SET_NAME]    NVARCHAR(255)  NULL,       -- origin.file_set_name
    [RUN_NUMBER]       NVARCHAR(40)   NULL,       -- origin.run_number
    [CREATION_TIME]    DATETIME2      NULL,       -- origin.creation_time
    [ORDER_NUMBER]     NVARCHAR(40)   NULL,       -- origin.order_number
    [FRAME_COUNT]      NUMERIC(5,0)   NULL,       -- number of frames
    [CHANNEL_COUNT]    NUMERIC(5,0)   NULL,       -- total channels across all frames
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [DLISLF_PK]      PRIMARY KEY ([DLIS_FILE_ID], [LOGICAL_FILE_IDX]),
    CONSTRAINT [DLISLF_FILE_FK] FOREIGN KEY ([DLIS_FILE_ID])
        REFERENCES [las_catalog].[DLIS_FILE] ([DLIS_FILE_ID])
)
GO


-- ── DLIS_FRAME ───────────────────────────────────────────────────────────────
-- One row per frame (log pass) within a logical file.
-- Frames are the key structural unit in DLIS — each represents a log run
-- or processing pass, all channels sharing the same depth/time index.
IF OBJECT_ID('[las_catalog].[DLIS_FRAME]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_FRAME] (
    [DLIS_FILE_ID]     NVARCHAR(40)   NOT NULL,  -- PK + FK → DLIS_LOGICAL_FILE
    [LOGICAL_FILE_IDX] NUMERIC(5,0)   NOT NULL,  -- PK + FK
    [FRAME_NAME]       NVARCHAR(100)  NOT NULL,  -- PK — frame.name (e.g. '60B')
    [INDEX_CHANNEL]    NVARCHAR(40)   NULL,       -- frame.index (depth/time channel)
    [INDEX_TYPE]       NVARCHAR(40)   NULL,       -- BOREHOLE-DEPTH, TIME, etc.
    [TOP_DEPTH]        NUMERIC(15,5)  NULL,       -- min of index channel
    [BASE_DEPTH]       NUMERIC(15,5)  NULL,       -- max of index channel
    [DEPTH_UOM]        NVARCHAR(20)   NULL,       -- native unit e.g. '0.1 in', 'ft', 'm'
    [DEPTH_UOM_STD]    NVARCHAR(5)    NULL,       -- standardised: M or FT (for search)
    [TOP_DEPTH_M]      NUMERIC(15,3)  NULL,       -- top depth converted to metres
    [BASE_DEPTH_M]     NUMERIC(15,3)  NULL,       -- base depth converted to metres
    [SPACING]          NUMERIC(15,5)  NULL,       -- sample spacing in native units
    [CHANNEL_COUNT]    NUMERIC(5,0)   NULL,       -- channels in this frame
    [SAMPLE_COUNT]     NUMERIC(15,0)  NULL,       -- depth samples
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [DLISFR_PK]     PRIMARY KEY ([DLIS_FILE_ID], [LOGICAL_FILE_IDX], [FRAME_NAME]),
    CONSTRAINT [DLISFR_LF_FK]  FOREIGN KEY ([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
        REFERENCES [las_catalog].[DLIS_LOGICAL_FILE] ([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
)
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'DLISFR_DEPTH_IDX')
    CREATE INDEX [DLISFR_DEPTH_IDX]
        ON [las_catalog].[DLIS_FRAME] ([TOP_DEPTH_M], [BASE_DEPTH_M])
        WHERE [TOP_DEPTH_M] IS NOT NULL AND [BASE_DEPTH_M] IS NOT NULL
GO


-- ── DLIS_CHANNEL ─────────────────────────────────────────────────────────────
-- One row per channel (curve) within a frame.
IF OBJECT_ID('[las_catalog].[DLIS_CHANNEL]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_CHANNEL] (
    [DLIS_FILE_ID]     NVARCHAR(40)   NOT NULL,  -- PK + FK
    [LOGICAL_FILE_IDX] NUMERIC(5,0)   NOT NULL,  -- PK + FK
    [FRAME_NAME]       NVARCHAR(100)  NOT NULL,  -- PK + FK
    [CHANNEL_NAME]     NVARCHAR(40)   NOT NULL,  -- PK — mnemonic e.g. GR_ARC
    [LONG_NAME]        NVARCHAR(255)  NULL,       -- channel.long_name
    [UNITS]            NVARCHAR(40)   NULL,       -- channel.units
    [DIMENSION]        NVARCHAR(40)   NULL,       -- scalar / array dimensions
    [IS_INDEX]         NVARCHAR(1)    NOT NULL DEFAULT 'N',  -- Y if depth/time index
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [DLISCH_PK]    PRIMARY KEY ([DLIS_FILE_ID], [LOGICAL_FILE_IDX],
                                           [FRAME_NAME], [CHANNEL_NAME]),
    CONSTRAINT [DLISCH_FR_FK] FOREIGN KEY ([DLIS_FILE_ID], [LOGICAL_FILE_IDX], [FRAME_NAME])
        REFERENCES [las_catalog].[DLIS_FRAME] ([DLIS_FILE_ID], [LOGICAL_FILE_IDX], [FRAME_NAME])
)
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'DLISCH_NAME_IDX')
    CREATE INDEX [DLISCH_NAME_IDX]
        ON [las_catalog].[DLIS_CHANNEL] ([CHANNEL_NAME])
GO


-- ── DLIS_PARAMETER ───────────────────────────────────────────────────────────
-- Tool and acquisition parameters stored in a logical file.
-- One DLIS file can have hundreds of these (213 in the Chevron example).
IF OBJECT_ID('[las_catalog].[DLIS_PARAMETER]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_PARAMETER] (
    [DLIS_FILE_ID]     NVARCHAR(40)   NOT NULL,  -- PK + FK
    [LOGICAL_FILE_IDX] NUMERIC(5,0)   NOT NULL,  -- PK + FK
    [PARAMETER_NAME]   NVARCHAR(40)   NOT NULL,  -- PK — parameter.name
    [LONG_NAME]        NVARCHAR(255)  NULL,       -- parameter.long_name
    [VALUE]            NVARCHAR(500)  NULL,       -- first value (stringified)
    [UNITS]            NVARCHAR(40)   NULL,
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [DLISPM_PK]    PRIMARY KEY ([DLIS_FILE_ID], [LOGICAL_FILE_IDX], [PARAMETER_NAME]),
    CONSTRAINT [DLISPM_LF_FK] FOREIGN KEY ([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
        REFERENCES [las_catalog].[DLIS_LOGICAL_FILE] ([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
)
GO


-- =============================================================================
-- STEP 3 — LIS Tables
-- =============================================================================

-- ── LIS_FILE ─────────────────────────────────────────────────────────────────
-- LIS is structurally simpler than DLIS — typically one file, one spec,
-- flat channels. No logical file or frame hierarchy needed.
IF OBJECT_ID('[las_catalog].[LIS_FILE]', 'U') IS NULL
CREATE TABLE [las_catalog].[LIS_FILE] (
    [LIS_FILE_ID]      NVARCHAR(40)   NOT NULL,  -- PK — SHA1 of full path
    [REPOSITORY_ID]    NVARCHAR(40)   NOT NULL,  -- FK → WL_REPOSITORY
    [UWI]              NVARCHAR(40)   NOT NULL,  -- FK → dbo.WELL
    [FILE_NAME]        NVARCHAR(500)  NOT NULL,  -- relative path
    [FILE_SIZE_KB]     NUMERIC(15,2)  NULL,
    [FILE_HASH]        NVARCHAR(64)   NULL,
    [WELL_NAME]        NVARCHAR(255)  NULL,       -- WN mnemonic
    [COMPANY]          NVARCHAR(255)  NULL,       -- CN mnemonic
    [FIELD_NAME]       NVARCHAR(255)  NULL,       -- FN mnemonic
    [LOG_DATE]         NVARCHAR(50)   NULL,       -- DATE mnemonic
    [SERVICE_COMPANY]  NVARCHAR(255)  NULL,
    [TOP_DEPTH]        NUMERIC(15,5)  NULL,       -- min of depth channel
    [BASE_DEPTH]       NUMERIC(15,5)  NULL,       -- max of depth channel
    [DEPTH_UOM]        NVARCHAR(10)   NULL,       -- F or M
    [CHANNEL_COUNT]    NUMERIC(5,0)   NULL,
    [SAMPLE_COUNT]     NUMERIC(15,0)  NULL,
    [CATALOG_DATE]     DATETIME2      NULL,
    [LAST_SEEN_DATE]   DATETIME2      NULL,
    [ACTIVE_IND]       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    [REMARK]           NVARCHAR(2000) NULL,
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [LISFILE_PK]      PRIMARY KEY ([LIS_FILE_ID]),
    CONSTRAINT [LISFILE_REP_FK]  FOREIGN KEY ([REPOSITORY_ID])
        REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID]),
    CONSTRAINT [LISFILE_WELL_FK] FOREIGN KEY ([UWI])
        REFERENCES [dbo].[WELL] ([UWI])
)
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LISFILE_UWI_IDX')
    CREATE INDEX [LISFILE_UWI_IDX]
        ON [las_catalog].[LIS_FILE] ([UWI])
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LISFILE_DEPTH_IDX')
    CREATE INDEX [LISFILE_DEPTH_IDX]
        ON [las_catalog].[LIS_FILE] ([TOP_DEPTH], [BASE_DEPTH])
        WHERE [TOP_DEPTH] IS NOT NULL AND [BASE_DEPTH] IS NOT NULL
GO


-- ── LIS_CHANNEL ──────────────────────────────────────────────────────────────
IF OBJECT_ID('[las_catalog].[LIS_CHANNEL]', 'U') IS NULL
CREATE TABLE [las_catalog].[LIS_CHANNEL] (
    [LIS_FILE_ID]      NVARCHAR(40)  NOT NULL,  -- PK + FK → LIS_FILE
    [CHANNEL_NAME]     NVARCHAR(40)  NOT NULL,  -- PK — mnemonic e.g. GRC
    [UNITS]            NVARCHAR(40)  NULL,       -- PUNI from wellsite record
    [DESCRIPTION]      NVARCHAR(255) NULL,
    [IS_INDEX]         NVARCHAR(1)   NOT NULL DEFAULT 'N',
    [SOURCE]           NVARCHAR(40)  NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)  NULL,
    [ROW_CREATED_DATE] DATETIME2     NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)  NULL,
    [ROW_CHANGED_DATE] DATETIME2     NULL,
    CONSTRAINT [LISCH_PK]      PRIMARY KEY ([LIS_FILE_ID], [CHANNEL_NAME]),
    CONSTRAINT [LISCH_FILE_FK] FOREIGN KEY ([LIS_FILE_ID])
        REFERENCES [las_catalog].[LIS_FILE] ([LIS_FILE_ID])
)
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LISCH_NAME_IDX')
    CREATE INDEX [LISCH_NAME_IDX]
        ON [las_catalog].[LIS_CHANNEL] ([CHANNEL_NAME])
GO


-- =============================================================================
-- Summary of las_catalog schema after this script
-- =============================================================================
--
--  WL_REPOSITORY          shared repository — LAS, DLIS, LIS
--
--  LAS_FILE               FK → WL_REPOSITORY, FK → dbo.WELL
--  LAS_FILE_CURVE         FK → LAS_FILE
--  LAS_FILE_PARAMETER     FK → LAS_FILE
--
--  DLIS_FILE              FK → WL_REPOSITORY, FK → dbo.WELL
--  DLIS_LOGICAL_FILE      FK → DLIS_FILE
--  DLIS_FRAME             FK → DLIS_LOGICAL_FILE
--  DLIS_CHANNEL           FK → DLIS_FRAME
--  DLIS_PARAMETER         FK → DLIS_LOGICAL_FILE
--
--  LIS_FILE               FK → WL_REPOSITORY, FK → dbo.WELL
--  LIS_CHANNEL            FK → LIS_FILE
--
-- =============================================================================

-- Useful cross-format query — all well log files for a UWI
-- SELECT 'LAS' AS FORMAT, f.FILE_NAME, f.TOP_DEPTH, f.BASE_DEPTH,
--        f.DEPTH_UOM, f.CURVE_COUNT AS CHANNELS,
--        r.BASE_PATH + '\' + f.FILE_NAME AS FULL_PATH
-- FROM las_catalog.LAS_FILE f
-- JOIN las_catalog.WL_REPOSITORY r ON r.REPOSITORY_ID = f.REPOSITORY_ID
-- WHERE f.UWI = :uwi
-- UNION ALL
-- SELECT 'DLIS', df.FILE_NAME,
--        fr.TOP_DEPTH_M, fr.BASE_DEPTH_M, 'M', fr.CHANNEL_COUNT,
--        r.BASE_PATH + '\' + df.FILE_NAME
-- FROM las_catalog.DLIS_FILE df
-- JOIN las_catalog.DLIS_LOGICAL_FILE lf ON lf.DLIS_FILE_ID = df.DLIS_FILE_ID
-- JOIN las_catalog.DLIS_FRAME fr ON fr.DLIS_FILE_ID = lf.DLIS_FILE_ID
--                                AND fr.LOGICAL_FILE_IDX = lf.LOGICAL_FILE_IDX
-- JOIN las_catalog.WL_REPOSITORY r ON r.REPOSITORY_ID = df.REPOSITORY_ID
-- WHERE df.UWI = :uwi
-- UNION ALL
-- SELECT 'LIS', f.FILE_NAME, f.TOP_DEPTH, f.BASE_DEPTH,
--        f.DEPTH_UOM, f.CHANNEL_COUNT,
--        r.BASE_PATH + '\' + f.FILE_NAME
-- FROM las_catalog.LIS_FILE f
-- JOIN las_catalog.WL_REPOSITORY r ON r.REPOSITORY_ID = f.REPOSITORY_ID
-- WHERE f.UWI = :uwi
-- ORDER BY TOP_DEPTH

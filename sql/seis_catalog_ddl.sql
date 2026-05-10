-- =============================================================================
-- Seismic File Catalog -- DDL for SQL Server
-- =============================================================================
-- Tables:
--   SEIS_FILE_CATALOG     One row per physical SEG-Y or P190 file
--   SEIS_FILE_HEADER      SEG-Y EBCDIC text header lines / P190 record counts
--
-- Optional PPDM seeds (if PPDM 3.9 is installed):
--   dbo.SEIS_SET          Survey / line set record
--   dbo.SEIS_LINE         Individual 2D line or 3D reference
--
-- Notes:
--   FK to dbo.SEIS_LINE and dbo.SEIS_SET are nullable -- files can be
--   catalogued without any PPDM seismic data loaded.
--   Safe to re-run -- all statements use IF NOT EXISTS guards.
-- =============================================================================


-- ============================================================================
-- SEIS_FILE_CATALOG
-- ============================================================================
IF OBJECT_ID('[las_catalog].[SEIS_FILE_CATALOG]', 'U') IS NULL
CREATE TABLE [las_catalog].[SEIS_FILE_CATALOG] (
    -- Identity
    [SEIS_FILE_ID]       NVARCHAR(40)   NOT NULL,   -- SHA1 of normalised path
    [REPOSITORY_ID]      NVARCHAR(40)   NULL,        -- FK → WL_REPOSITORY (nullable)
    [FILE_FORMAT]        NVARCHAR(10)   NOT NULL,    -- SEGY or P190
    [FILE_NAME]          NVARCHAR(500)  NOT NULL,    -- relative path within repository
    [FILE_SIZE_KB]       NUMERIC(15,2)  NULL,
    [FILE_HASH]          NVARCHAR(64)   NULL,        -- SHA256 for dedup

    -- Survey / line linkage (optional)
    [SEIS_SET_ID]        NVARCHAR(40)   NULL,        -- FK → dbo.SEIS_SET (nullable)
    [SEIS_LINE_ID]       NVARCHAR(40)   NULL,        -- FK → dbo.SEIS_LINE (nullable)
    [SEIS_SET_SUBID]     NVARCHAR(40)   NULL,

    -- Survey identification from file header
    [SURVEY_NAME]        NVARCHAR(255)  NULL,
    [LINE_NAME]          NVARCHAR(255)  NULL,
    [VESSEL_NAME]        NVARCHAR(255)  NULL,
    [CLIENT_NAME]        NVARCHAR(255)  NULL,
    [DIMENSIONALITY]     NVARCHAR(10)   NULL,        -- 2D or 3D

    -- SEG-Y specific
    [SAMPLE_INTERVAL_US] NUMERIC(10,2)  NULL,        -- microseconds
    [SAMPLE_COUNT]       NUMERIC(10,0)  NULL,
    [TRACE_COUNT]        NUMERIC(15,0)  NULL,
    [DATA_FORMAT]        NVARCHAR(40)   NULL,        -- IBM float, IEEE float, etc.
    [SEGY_REVISION]      NVARCHAR(10)   NULL,        -- 0, 1, 2

    -- P190 specific
    [RECORD_COUNT]       NUMERIC(10,0)  NULL,        -- total records
    [SHOT_COUNT]         NUMERIC(10,0)  NULL,
    [FIRST_SHOT_POINT]   NUMERIC(10,2)  NULL,
    [LAST_SHOT_POINT]    NUMERIC(10,2)  NULL,
    [NAV_SYSTEM]         NVARCHAR(40)   NULL,

    -- Temporal coverage
    [ACQ_DATE_START]     NVARCHAR(30)   NULL,
    [ACQ_DATE_END]       NVARCHAR(30)   NULL,

    -- Bounding box — geographic (decimal degrees)
    [MIN_LAT]            NUMERIC(12,7)  NULL,
    [MAX_LAT]            NUMERIC(12,7)  NULL,
    [MIN_LON]            NUMERIC(12,7)  NULL,
    [MAX_LON]            NUMERIC(12,7)  NULL,

    -- Bounding box — projected (metres or feet, CRS dependent)
    [MIN_X]              NUMERIC(18,3)  NULL,
    [MAX_X]              NUMERIC(18,3)  NULL,
    [MIN_Y]              NUMERIC(18,3)  NULL,
    [MAX_Y]              NUMERIC(18,3)  NULL,
    [COORD_SYSTEM]       NVARCHAR(255)  NULL,        -- CRS description from header

    -- Depth / time range
    [MIN_DEPTH_MS]       NUMERIC(12,3)  NULL,        -- milliseconds (SEG-Y time axis)
    [MAX_DEPTH_MS]       NUMERIC(12,3)  NULL,

    -- Inline / crossline (3D only)
    [MIN_INLINE]         NUMERIC(10,0)  NULL,
    [MAX_INLINE]         NUMERIC(10,0)  NULL,
    [MIN_CROSSLINE]      NUMERIC(10,0)  NULL,
    [MAX_CROSSLINE]      NUMERIC(10,0)  NULL,

    -- Catalog admin
    [CATALOG_DATE]       DATETIME2      NULL,
    [LAST_SEEN_DATE]     DATETIME2      NULL,
    [ACTIVE_IND]         NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    [REMARK]             NVARCHAR(2000) NULL,
    [SOURCE]             NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]     NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE]   DATETIME2      NULL,
    [ROW_CHANGED_BY]     NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE]   DATETIME2      NULL,

    CONSTRAINT [SEISCAT_PK]     PRIMARY KEY ([SEIS_FILE_ID]),
    CONSTRAINT [SEISCAT_REP_FK] FOREIGN KEY ([REPOSITORY_ID])
        REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID])
)
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'SEISCAT_FORMAT_IDX')
    CREATE INDEX [SEISCAT_FORMAT_IDX]
        ON [las_catalog].[SEIS_FILE_CATALOG] ([FILE_FORMAT])
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'SEISCAT_SURVEY_IDX')
    CREATE INDEX [SEISCAT_SURVEY_IDX]
        ON [las_catalog].[SEIS_FILE_CATALOG] ([SURVEY_NAME])
        WHERE [SURVEY_NAME] IS NOT NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'SEISCAT_HASH_IDX')
    CREATE INDEX [SEISCAT_HASH_IDX]
        ON [las_catalog].[SEIS_FILE_CATALOG] ([FILE_HASH])
        WHERE [FILE_HASH] IS NOT NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'SEISCAT_BBOX_IDX')
    CREATE INDEX [SEISCAT_BBOX_IDX]
        ON [las_catalog].[SEIS_FILE_CATALOG] ([MIN_LAT],[MAX_LAT],[MIN_LON],[MAX_LON])
        WHERE [MIN_LAT] IS NOT NULL
GO


-- ============================================================================
-- SEIS_FILE_HEADER
-- ============================================================================
IF OBJECT_ID('[las_catalog].[SEIS_FILE_HEADER]', 'U') IS NULL
CREATE TABLE [las_catalog].[SEIS_FILE_HEADER] (
    [SEIS_FILE_ID]   NVARCHAR(40)   NOT NULL,
    [LINE_NO]        NUMERIC(5,0)   NOT NULL,   -- 1-40 for SEG-Y; record type for P190
    [HEADER_TEXT]    NVARCHAR(80)   NULL,        -- raw header line content
    [SOURCE]         NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY] NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2    NULL,
    CONSTRAINT [SEISHDR_PK]      PRIMARY KEY ([SEIS_FILE_ID], [LINE_NO]),
    CONSTRAINT [SEISHDR_FILE_FK] FOREIGN KEY ([SEIS_FILE_ID])
        REFERENCES [las_catalog].[SEIS_FILE_CATALOG] ([SEIS_FILE_ID])
)
GO


-- ============================================================================
-- PPDM seed helpers
-- ============================================================================
-- These queries check whether PPDM seismic tables exist.
-- Run before attempting to seed.

-- SELECT CASE WHEN OBJECT_ID('dbo.SEIS_SET',  'U') IS NOT NULL THEN 'EXISTS' ELSE 'MISSING' END AS SEIS_SET_STATUS
-- SELECT CASE WHEN OBJECT_ID('dbo.SEIS_LINE', 'U') IS NOT NULL THEN 'EXISTS' ELSE 'MISSING' END AS SEIS_LINE_STATUS


-- ============================================================================
-- CLEAR ALL (for testing) -- run each line individually in SSMS
-- ============================================================================
-- DELETE FROM las_catalog.SEIS_FILE_HEADER;
-- DELETE FROM las_catalog.SEIS_FILE_CATALOG;

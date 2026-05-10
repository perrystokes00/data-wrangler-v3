-- =============================================================================
-- Well Log File Catalog -- Full DDL for SQL Server (Fresh Install)
-- =============================================================================
-- Tables (in creation order):
--   WL_REPOSITORY          Shared physical storage locations
--   LAS_FILE               One row per LAS file
--   LAS_FILE_CURVE         One row per curve mnemonic per LAS file
--   LAS_FILE_PARAMETER     LAS ~W and ~P header items
--   DLIS_FILE              One row per physical DLIS file
--   DLIS_LOGICAL_FILE      One row per logical file within a DLIS file
--   DLIS_FRAME             One row per frame within a logical file
--   DLIS_CHANNEL           One row per channel within a frame
--   DLIS_PARAMETER         Tool/acquisition parameters within a logical file
--   LIS_FILE               One row per LIS file
--   LIS_CHANNEL            One row per channel within a LIS file
--   WL_FILE_UWI_MAP        Staging area for bulk UWI assignment
--
-- Prerequisites:
--   PPDM 3.9 must be installed (dbo.WELL required)
--   Run as a user with CREATE TABLE / CREATE SCHEMA privileges
--   Safe to re-run -- all statements use IF NOT EXISTS guards
-- =============================================================================


-- ============================================================================
-- SCHEMA
-- ============================================================================
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'las_catalog')
    EXEC('CREATE SCHEMA [las_catalog]')
GO


-- ============================================================================
-- WL_REPOSITORY
-- ============================================================================
IF OBJECT_ID('[las_catalog].[WL_REPOSITORY]', 'U') IS NULL
CREATE TABLE [las_catalog].[WL_REPOSITORY] (
    [REPOSITORY_ID]    NVARCHAR(40)   NOT NULL,
    [REPOSITORY_NAME]  NVARCHAR(200)  NOT NULL,
    [REPOSITORY_TYPE]  NVARCHAR(40)   NOT NULL,
    [BASE_PATH]        NVARCHAR(500)  NOT NULL,
    [ACTIVE_IND]       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    [REMARK]           NVARCHAR(2000) NULL,
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [WLREP_PK] PRIMARY KEY ([REPOSITORY_ID])
)
GO


-- ============================================================================
-- LAS_FILE
-- ============================================================================
IF OBJECT_ID('[las_catalog].[LAS_FILE]', 'U') IS NULL
CREATE TABLE [las_catalog].[LAS_FILE] (
    [LAS_FILE_ID]      NVARCHAR(40)   NOT NULL,
    [REPOSITORY_ID]    NVARCHAR(40)   NOT NULL,
    [UWI]              NVARCHAR(40)   NOT NULL,
    [WELL_NAME]        NVARCHAR(255)  NULL,
    [FILE_NAME]        NVARCHAR(500)  NOT NULL,
    [FILE_SIZE_KB]     NUMERIC(15,2)  NULL,
    [LAS_VERSION]      NVARCHAR(10)   NULL,
    [OPERATOR]         NVARCHAR(255)  NULL,
    [FIELD]            NVARCHAR(255)  NULL,
    [COUNTRY]          NVARCHAR(255)  NULL,
    [STATE_PROVINCE]   NVARCHAR(255)  NULL,
    [COUNTY]           NVARCHAR(255)  NULL,
    [TOP_DEPTH]        NUMERIC(15,5)  NULL,
    [BASE_DEPTH]       NUMERIC(15,5)  NULL,
    [DEPTH_STEP]       NUMERIC(15,5)  NULL,
    [DEPTH_UOM]        NVARCHAR(10)   NULL,
    [LOG_DATE]         NVARCHAR(50)   NULL,
    [SERVICE_COMPANY]  NVARCHAR(255)  NULL,
    [CURVE_COUNT]      NUMERIC(10,0)  NULL,
    [SAMPLE_COUNT]     NUMERIC(15,0)  NULL,
    [FILE_HASH]        NVARCHAR(64)   NULL,
    [CATALOG_DATE]     DATETIME2      NULL,
    [LAST_SEEN_DATE]   DATETIME2      NULL,
    [ACTIVE_IND]       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    [REMARK]           NVARCHAR(2000) NULL,
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [LASFILE_PK]      PRIMARY KEY ([LAS_FILE_ID]),
    CONSTRAINT [LASFILE_REP_FK]  FOREIGN KEY ([REPOSITORY_ID])
        REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID]),
    CONSTRAINT [LASFILE_WELL_FK] FOREIGN KEY ([UWI])
        REFERENCES [dbo].[WELL] ([UWI])
)
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LASFILE_UWI_IDX')
    CREATE INDEX [LASFILE_UWI_IDX]   ON [las_catalog].[LAS_FILE] ([UWI])
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LASFILE_HASH_IDX')
    CREATE INDEX [LASFILE_HASH_IDX]  ON [las_catalog].[LAS_FILE] ([FILE_HASH])
    WHERE [FILE_HASH] IS NOT NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LASFILE_DEPTH_IDX')
    CREATE INDEX [LASFILE_DEPTH_IDX] ON [las_catalog].[LAS_FILE] ([TOP_DEPTH],[BASE_DEPTH])
    WHERE [TOP_DEPTH] IS NOT NULL AND [BASE_DEPTH] IS NOT NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LASFILE_FIELD_IDX')
    CREATE INDEX [LASFILE_FIELD_IDX] ON [las_catalog].[LAS_FILE] ([FIELD])
    WHERE [FIELD] IS NOT NULL
GO


-- ============================================================================
-- LAS_FILE_CURVE
-- ============================================================================
IF OBJECT_ID('[las_catalog].[LAS_FILE_CURVE]', 'U') IS NULL
CREATE TABLE [las_catalog].[LAS_FILE_CURVE] (
    [LAS_FILE_ID]       NVARCHAR(40)  NOT NULL,
    [CURVE_ID]          NVARCHAR(40)  NOT NULL,
    [CURVE_UNIT]        NVARCHAR(40)  NULL,
    [CURVE_DESCRIPTION] NVARCHAR(255) NULL,
    [CURVE_TYPE]        NVARCHAR(40)  NULL,
    [API_CODE]          NVARCHAR(40)  NULL,
    [SOURCE]            NVARCHAR(40)  NOT NULL,
    [ROW_CREATED_BY]    NVARCHAR(30)  NULL,
    [ROW_CREATED_DATE]  DATETIME2     NULL,
    [ROW_CHANGED_BY]    NVARCHAR(30)  NULL,
    [ROW_CHANGED_DATE]  DATETIME2     NULL,
    CONSTRAINT [LASCURVE_PK]      PRIMARY KEY ([LAS_FILE_ID], [CURVE_ID]),
    CONSTRAINT [LASCURVE_FILE_FK] FOREIGN KEY ([LAS_FILE_ID])
        REFERENCES [las_catalog].[LAS_FILE] ([LAS_FILE_ID])
)
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LASCURVE_ID_IDX')
    CREATE INDEX [LASCURVE_ID_IDX] ON [las_catalog].[LAS_FILE_CURVE] ([CURVE_ID])
GO


-- ============================================================================
-- LAS_FILE_PARAMETER
-- ============================================================================
IF OBJECT_ID('[las_catalog].[LAS_FILE_PARAMETER]', 'U') IS NULL
CREATE TABLE [las_catalog].[LAS_FILE_PARAMETER] (
    [LAS_FILE_ID]       NVARCHAR(40)  NOT NULL,
    [PARAMETER_NAME]    NVARCHAR(40)  NOT NULL,
    [PARAMETER_VALUE]   NVARCHAR(500) NULL,
    [PARAMETER_UNIT]    NVARCHAR(40)  NULL,
    [SECTION]           NVARCHAR(10)  NULL,
    [SOURCE]            NVARCHAR(40)  NOT NULL,
    [ROW_CREATED_BY]    NVARCHAR(30)  NULL,
    [ROW_CREATED_DATE]  DATETIME2     NULL,
    [ROW_CHANGED_BY]    NVARCHAR(30)  NULL,
    [ROW_CHANGED_DATE]  DATETIME2     NULL,
    CONSTRAINT [LASPARM_PK]      PRIMARY KEY ([LAS_FILE_ID], [PARAMETER_NAME]),
    CONSTRAINT [LASPARM_FILE_FK] FOREIGN KEY ([LAS_FILE_ID])
        REFERENCES [las_catalog].[LAS_FILE] ([LAS_FILE_ID])
)
GO


-- ============================================================================
-- DLIS_FILE
-- ============================================================================
IF OBJECT_ID('[las_catalog].[DLIS_FILE]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_FILE] (
    [DLIS_FILE_ID]       NVARCHAR(40)   NOT NULL,
    [REPOSITORY_ID]      NVARCHAR(40)   NOT NULL,
    [UWI]                NVARCHAR(40)   NOT NULL,
    [FILE_NAME]          NVARCHAR(500)  NOT NULL,
    [FILE_SIZE_KB]       NUMERIC(15,2)  NULL,
    [FILE_HASH]          NVARCHAR(64)   NULL,
    [LOGICAL_FILE_COUNT] NUMERIC(5,0)   NULL,
    [CATALOG_DATE]       DATETIME2      NULL,
    [LAST_SEEN_DATE]     DATETIME2      NULL,
    [ACTIVE_IND]         NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    [SOURCE]             NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]     NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE]   DATETIME2      NULL,
    [ROW_CHANGED_BY]     NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE]   DATETIME2      NULL,
    CONSTRAINT [DLISFILE_PK]      PRIMARY KEY ([DLIS_FILE_ID]),
    CONSTRAINT [DLISFILE_REP_FK]  FOREIGN KEY ([REPOSITORY_ID])
        REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID]),
    CONSTRAINT [DLISFILE_WELL_FK] FOREIGN KEY ([UWI])
        REFERENCES [dbo].[WELL] ([UWI])
)
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'DLISFILE_UWI_IDX')
    CREATE INDEX [DLISFILE_UWI_IDX]  ON [las_catalog].[DLIS_FILE] ([UWI])
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'DLISFILE_HASH_IDX')
    CREATE INDEX [DLISFILE_HASH_IDX] ON [las_catalog].[DLIS_FILE] ([FILE_HASH])
    WHERE [FILE_HASH] IS NOT NULL
GO


-- ============================================================================
-- DLIS_LOGICAL_FILE
-- ============================================================================
IF OBJECT_ID('[las_catalog].[DLIS_LOGICAL_FILE]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_LOGICAL_FILE] (
    [DLIS_FILE_ID]     NVARCHAR(40)   NOT NULL,
    [LOGICAL_FILE_IDX] NUMERIC(5,0)   NOT NULL,
    [DESCRIPTION]      NVARCHAR(255)  NULL,
    [WELL_NAME]        NVARCHAR(255)  NULL,
    [WELL_ID]          NVARCHAR(255)  NULL,
    [COMPANY]          NVARCHAR(255)  NULL,
    [FIELD_NAME]       NVARCHAR(255)  NULL,
    [PRODUCER_NAME]    NVARCHAR(255)  NULL,
    [PRODUCT]          NVARCHAR(255)  NULL,
    [VERSION]          NVARCHAR(40)   NULL,
    [FILE_SET_NAME]    NVARCHAR(255)  NULL,
    [RUN_NUMBER]       NVARCHAR(40)   NULL,
    [CREATION_TIME]    NVARCHAR(30)   NULL,
    [ORDER_NUMBER]     NVARCHAR(40)   NULL,
    [FRAME_COUNT]      NUMERIC(5,0)   NULL,
    [CHANNEL_COUNT]    NUMERIC(10,0)  NULL,
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


-- ============================================================================
-- DLIS_FRAME
-- ============================================================================
IF OBJECT_ID('[las_catalog].[DLIS_FRAME]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_FRAME] (
    [DLIS_FILE_ID]     NVARCHAR(40)   NOT NULL,
    [LOGICAL_FILE_IDX] NUMERIC(5,0)   NOT NULL,
    [FRAME_NAME]       NVARCHAR(255)  NOT NULL,
    [INDEX_CHANNEL]    NVARCHAR(40)   NULL,
    [TOP_DEPTH]        NUMERIC(15,5)  NULL,
    [BASE_DEPTH]       NUMERIC(15,5)  NULL,
    [DEPTH_UOM]        NVARCHAR(20)   NULL,
    [DEPTH_UOM_STD]    NVARCHAR(10)   NULL,
    [TOP_DEPTH_M]      NUMERIC(15,5)  NULL,
    [BASE_DEPTH_M]     NUMERIC(15,5)  NULL,
    [SPACING]          NUMERIC(15,5)  NULL,
    [CHANNEL_COUNT]    NUMERIC(10,0)  NULL,
    [SAMPLE_COUNT]     NUMERIC(15,0)  NULL,
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [DLISFR_PK]    PRIMARY KEY ([DLIS_FILE_ID], [LOGICAL_FILE_IDX], [FRAME_NAME]),
    CONSTRAINT [DLISFR_LF_FK] FOREIGN KEY ([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
        REFERENCES [las_catalog].[DLIS_LOGICAL_FILE] ([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
)
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'DLISFR_DEPTH_IDX')
    CREATE INDEX [DLISFR_DEPTH_IDX] ON [las_catalog].[DLIS_FRAME] ([TOP_DEPTH_M],[BASE_DEPTH_M])
    WHERE [TOP_DEPTH_M] IS NOT NULL AND [BASE_DEPTH_M] IS NOT NULL
GO


-- ============================================================================
-- DLIS_CHANNEL
-- ============================================================================
IF OBJECT_ID('[las_catalog].[DLIS_CHANNEL]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_CHANNEL] (
    [DLIS_FILE_ID]     NVARCHAR(40)   NOT NULL,
    [LOGICAL_FILE_IDX] NUMERIC(5,0)   NOT NULL,
    [FRAME_NAME]       NVARCHAR(255)  NOT NULL,
    [CHANNEL_NAME]     NVARCHAR(40)   NOT NULL,
    [LONG_NAME]        NVARCHAR(255)  NULL,
    [UNITS]            NVARCHAR(40)   NULL,
    [DIMENSION]        NVARCHAR(40)   NULL,
    [IS_INDEX]         NVARCHAR(1)    NOT NULL DEFAULT 'N',
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
    CREATE INDEX [DLISCH_NAME_IDX] ON [las_catalog].[DLIS_CHANNEL] ([CHANNEL_NAME])
GO


-- ============================================================================
-- DLIS_PARAMETER
-- ============================================================================
IF OBJECT_ID('[las_catalog].[DLIS_PARAMETER]', 'U') IS NULL
CREATE TABLE [las_catalog].[DLIS_PARAMETER] (
    [DLIS_FILE_ID]     NVARCHAR(40)   NOT NULL,
    [LOGICAL_FILE_IDX] NUMERIC(5,0)   NOT NULL,
    [PARAMETER_NAME]   NVARCHAR(40)   NOT NULL,
    [LONG_NAME]        NVARCHAR(255)  NULL,
    [VALUE]            NVARCHAR(500)  NULL,
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


-- ============================================================================
-- LIS_FILE
-- ============================================================================
IF OBJECT_ID('[las_catalog].[LIS_FILE]', 'U') IS NULL
CREATE TABLE [las_catalog].[LIS_FILE] (
    [LIS_FILE_ID]      NVARCHAR(40)   NOT NULL,
    [REPOSITORY_ID]    NVARCHAR(40)   NOT NULL,
    [UWI]              NVARCHAR(40)   NOT NULL,
    [FILE_NAME]        NVARCHAR(500)  NOT NULL,
    [FILE_SIZE_KB]     NUMERIC(15,2)  NULL,
    [FILE_HASH]        NVARCHAR(64)   NULL,
    [WELL_NAME]        NVARCHAR(255)  NULL,
    [COMPANY]          NVARCHAR(255)  NULL,
    [FIELD_NAME]       NVARCHAR(255)  NULL,
    [LOG_DATE]         NVARCHAR(50)   NULL,
    [TOP_DEPTH]        NUMERIC(15,5)  NULL,
    [BASE_DEPTH]       NUMERIC(15,5)  NULL,
    [DEPTH_UOM]        NVARCHAR(20)   NULL,
    [CHANNEL_COUNT]    NUMERIC(10,0)  NULL,
    [SAMPLE_COUNT]     NUMERIC(15,0)  NULL,
    [SERVICE_COMPANY]  NVARCHAR(255)  NULL,
    [CATALOG_DATE]     DATETIME2      NULL,
    [LAST_SEEN_DATE]   DATETIME2      NULL,
    [ACTIVE_IND]       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
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
    CREATE INDEX [LISFILE_UWI_IDX]   ON [las_catalog].[LIS_FILE] ([UWI])
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LISFILE_HASH_IDX')
    CREATE INDEX [LISFILE_HASH_IDX]  ON [las_catalog].[LIS_FILE] ([FILE_HASH])
    WHERE [FILE_HASH] IS NOT NULL
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'LISFILE_DEPTH_IDX')
    CREATE INDEX [LISFILE_DEPTH_IDX] ON [las_catalog].[LIS_FILE] ([TOP_DEPTH],[BASE_DEPTH])
    WHERE [TOP_DEPTH] IS NOT NULL AND [BASE_DEPTH] IS NOT NULL
GO


-- ============================================================================
-- LIS_CHANNEL
-- ============================================================================
IF OBJECT_ID('[las_catalog].[LIS_CHANNEL]', 'U') IS NULL
CREATE TABLE [las_catalog].[LIS_CHANNEL] (
    [LIS_FILE_ID]      NVARCHAR(40)  NOT NULL,
    [CHANNEL_NAME]     NVARCHAR(40)  NOT NULL,
    [UNITS]            NVARCHAR(40)  NULL,
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
    CREATE INDEX [LISCH_NAME_IDX] ON [las_catalog].[LIS_CHANNEL] ([CHANNEL_NAME])
GO


-- ============================================================================
-- WL_FILE_UWI_MAP  (staging)
-- ============================================================================
IF OBJECT_ID('[las_catalog].[WL_FILE_UWI_MAP]', 'U') IS NULL
CREATE TABLE [las_catalog].[WL_FILE_UWI_MAP] (
    [MAP_ID]           NVARCHAR(40)   NOT NULL,
    [FILE_PATH]        NVARCHAR(500)  NOT NULL,
    [FILE_NAME]        NVARCHAR(255)  NOT NULL,
    [FILE_FORMAT]      NVARCHAR(10)   NOT NULL,
    [REPOSITORY_ID]    NVARCHAR(40)   NULL,
    [UWI]              NVARCHAR(40)   NULL,
    [HEADER_WELL_ID]   NVARCHAR(255)  NULL,
    [MATCH_METHOD]     NVARCHAR(20)   NULL,
    [MATCH_SCORE]      NUMERIC(5,1)   NULL,
    [MATCH_WELL_NAME]  NVARCHAR(255)  NULL,
    [STATUS]           NVARCHAR(20)   NOT NULL DEFAULT 'PENDING',
    [FILE_SIZE_KB]     NUMERIC(15,2)  NULL,
    [REMARK]           NVARCHAR(2000) NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [WLMAP_PK]     PRIMARY KEY ([MAP_ID]),
    CONSTRAINT [WLMAP_REP_FK] FOREIGN KEY ([REPOSITORY_ID])
        REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID])
)
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'WLMAP_STATUS_IDX')
    CREATE INDEX [WLMAP_STATUS_IDX]   ON [las_catalog].[WL_FILE_UWI_MAP] ([STATUS],[FILE_FORMAT])
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'WLMAP_CREATED_IDX')
    CREATE INDEX [WLMAP_CREATED_IDX]  ON [las_catalog].[WL_FILE_UWI_MAP] ([ROW_CREATED_DATE])
GO


-- ============================================================================
-- CLEAR ALL DATA (for testing) -- run each DELETE individually in SSMS
-- ============================================================================
-- DELETE FROM las_catalog.DLIS_CHANNEL;
-- DELETE FROM las_catalog.DLIS_PARAMETER;
-- DELETE FROM las_catalog.DLIS_FRAME;
-- DELETE FROM las_catalog.DLIS_LOGICAL_FILE;
-- DELETE FROM las_catalog.DLIS_FILE;
-- DELETE FROM las_catalog.LIS_CHANNEL;
-- DELETE FROM las_catalog.LIS_FILE;
-- DELETE FROM las_catalog.LAS_FILE_CURVE;
-- DELETE FROM las_catalog.LAS_FILE_PARAMETER;
-- DELETE FROM las_catalog.LAS_FILE;
-- DELETE FROM las_catalog.WL_FILE_UWI_MAP;
-- DELETE FROM las_catalog.WL_REPOSITORY;


-- ============================================================================
-- DROP ALL TABLES (clean slate) -- run each DROP individually in SSMS
-- ============================================================================
-- DROP TABLE IF EXISTS las_catalog.DLIS_CHANNEL;
-- DROP TABLE IF EXISTS las_catalog.DLIS_PARAMETER;
-- DROP TABLE IF EXISTS las_catalog.DLIS_FRAME;
-- DROP TABLE IF EXISTS las_catalog.DLIS_LOGICAL_FILE;
-- DROP TABLE IF EXISTS las_catalog.DLIS_FILE;
-- DROP TABLE IF EXISTS las_catalog.LIS_CHANNEL;
-- DROP TABLE IF EXISTS las_catalog.LIS_FILE;
-- DROP TABLE IF EXISTS las_catalog.LAS_FILE_CURVE;
-- DROP TABLE IF EXISTS las_catalog.LAS_FILE_PARAMETER;
-- DROP TABLE IF EXISTS las_catalog.LAS_FILE;
-- DROP TABLE IF EXISTS las_catalog.WL_FILE_UWI_MAP;
-- DROP TABLE IF EXISTS las_catalog.WL_REPOSITORY;

-- =============================================================================
-- LAS File Catalog — DDL for SQL Server
-- =============================================================================
-- Creates schema [las_catalog] with four tables:
--   LAS_REPOSITORY      physical storage locations
--   LAS_FILE            one row per LAS file (header metadata)
--   LAS_FILE_CURVE      one row per curve in the file header
--   LAS_FILE_PARAMETER  other header sections (params, other)
--
-- The catalog sits alongside PPDM 3.9 in the same database.
-- UWI in LAS_FILE is a soft reference to WELL.UWI (no FK constraint)
-- so files can be catalogued before being matched to a well.
--
-- Run this script once against your target database.
-- Safe to re-run — uses IF NOT EXISTS guards throughout.
-- =============================================================================

-- ── Schema ───────────────────────────────────────────────────────────────────
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'las_catalog')
    EXEC('CREATE SCHEMA [las_catalog]')
GO

-- ── LAS_REPOSITORY ───────────────────────────────────────────────────────────
IF OBJECT_ID('[las_catalog].[LAS_REPOSITORY]', 'U') IS NULL
CREATE TABLE [las_catalog].[LAS_REPOSITORY] (
    [REPOSITORY_ID]    NVARCHAR(40)   NOT NULL,
    [REPOSITORY_NAME]  NVARCHAR(200)  NOT NULL,
    [REPOSITORY_TYPE]  NVARCHAR(40)   NOT NULL,  -- LOCAL, UNC, S3, AZURE_BLOB, SHAREPOINT
    [BASE_PATH]        NVARCHAR(500)  NOT NULL,  -- root path / bucket / URL
    [ACTIVE_IND]       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    [REMARK]           NVARCHAR(2000) NULL,
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [LASREP_PK] PRIMARY KEY ([REPOSITORY_ID])
)
GO

-- ── LAS_FILE ─────────────────────────────────────────────────────────────────
IF OBJECT_ID('[las_catalog].[LAS_FILE]', 'U') IS NULL
CREATE TABLE [las_catalog].[LAS_FILE] (
    [LAS_FILE_ID]      NVARCHAR(40)   NOT NULL,  -- SHA1 of full path
    [REPOSITORY_ID]    NVARCHAR(40)   NOT NULL,  -- FK → LAS_REPOSITORY
    [UWI]              NVARCHAR(40)   NOT NULL,  -- FK → dbo.WELL.UWI
    [WELL_NAME]        NVARCHAR(255)  NULL,       -- from LAS WELL header
    [FILE_NAME]        NVARCHAR(500)  NOT NULL,  -- relative path within repository
    [FILE_SIZE_KB]     NUMERIC(15,2)  NULL,
    [LAS_VERSION]      NVARCHAR(10)   NULL,       -- 1.2, 2.0, 3.0
    [OPERATOR]         NVARCHAR(255)  NULL,       -- COMP mnemonic
    [FIELD]            NVARCHAR(255)  NULL,       -- FLD mnemonic
    [COUNTRY]          NVARCHAR(255)  NULL,       -- CTRY mnemonic
    [STATE_PROVINCE]   NVARCHAR(255)  NULL,       -- PROV / STAT mnemonic
    [COUNTY]           NVARCHAR(255)  NULL,       -- CNTY mnemonic
    [TOP_DEPTH]        NUMERIC(15,5)  NULL,       -- STRT value
    [BASE_DEPTH]       NUMERIC(15,5)  NULL,       -- STOP value
    [DEPTH_STEP]       NUMERIC(15,5)  NULL,       -- STEP value
    [DEPTH_UOM]        NVARCHAR(10)   NULL,       -- M or FT
    [LOG_DATE]         NVARCHAR(50)   NULL,       -- DATE mnemonic (string — formats vary)
    [SERVICE_COMPANY]  NVARCHAR(255)  NULL,       -- SRVC mnemonic
    [CURVE_COUNT]      NUMERIC(10,0)  NULL,       -- curves excluding depth index
    [SAMPLE_COUNT]     NUMERIC(15,0)  NULL,       -- depth samples per curve
    [FILE_HASH]        NVARCHAR(64)   NULL,       -- SHA256 for dedup detection
    [CATALOG_DATE]     DATETIME2      NULL,       -- when this row was catalogued
    [LAST_SEEN_DATE]   DATETIME2      NULL,       -- last time file was confirmed present
    [ACTIVE_IND]       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
    [REMARK]           NVARCHAR(2000) NULL,
    [SOURCE]           NVARCHAR(40)   NOT NULL,
    [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
    [ROW_CREATED_DATE] DATETIME2      NULL,
    [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
    [ROW_CHANGED_DATE] DATETIME2      NULL,
    CONSTRAINT [LASFILE_PK] PRIMARY KEY ([LAS_FILE_ID]),
    CONSTRAINT [LASFILE_REP_FK] FOREIGN KEY ([REPOSITORY_ID])
        REFERENCES [las_catalog].[LAS_REPOSITORY] ([REPOSITORY_ID])
)
GO

-- Indexes for common search patterns
CREATE INDEX [LASFILE_UWI_IDX]   ON [las_catalog].[LAS_FILE] ([UWI])
    WHERE [UWI] IS NOT NULL
GO
CREATE INDEX [LASFILE_DEPTH_IDX] ON [las_catalog].[LAS_FILE] ([TOP_DEPTH], [BASE_DEPTH])
    WHERE [TOP_DEPTH] IS NOT NULL AND [BASE_DEPTH] IS NOT NULL
GO
CREATE INDEX [LASFILE_FIELD_IDX] ON [las_catalog].[LAS_FILE] ([FIELD])
    WHERE [FIELD] IS NOT NULL
GO
CREATE INDEX [LASFILE_HASH_IDX]  ON [las_catalog].[LAS_FILE] ([FILE_HASH])
    WHERE [FILE_HASH] IS NOT NULL
GO

-- ── LAS_FILE_CURVE ───────────────────────────────────────────────────────────
IF OBJECT_ID('[las_catalog].[LAS_FILE_CURVE]', 'U') IS NULL
CREATE TABLE [las_catalog].[LAS_FILE_CURVE] (
    [LAS_FILE_ID]       NVARCHAR(40)  NOT NULL,  -- PK+FK → LAS_FILE
    [CURVE_ID]          NVARCHAR(40)  NOT NULL,  -- PK, mnemonic e.g. GR
    [CURVE_UNIT]        NVARCHAR(40)  NULL,
    [CURVE_DESCRIPTION] NVARCHAR(255) NULL,
    [CURVE_TYPE]        NVARCHAR(40)  NULL,       -- DEPT, REGULAR
    [API_CODE]          NVARCHAR(40)  NULL,       -- LAS API curve code if present
    [SOURCE]            NVARCHAR(40)  NOT NULL,
    [ROW_CREATED_BY]    NVARCHAR(30)  NULL,
    [ROW_CREATED_DATE]  DATETIME2     NULL,
    [ROW_CHANGED_BY]    NVARCHAR(30)  NULL,
    [ROW_CHANGED_DATE]  DATETIME2     NULL,
    CONSTRAINT [LASCURVE_PK] PRIMARY KEY ([LAS_FILE_ID], [CURVE_ID]),
    CONSTRAINT [LASCURVE_FILE_FK] FOREIGN KEY ([LAS_FILE_ID])
        REFERENCES [las_catalog].[LAS_FILE] ([LAS_FILE_ID])
)
GO

-- Index for searching by curve mnemonic across all files
CREATE INDEX [LASCURVE_ID_IDX] ON [las_catalog].[LAS_FILE_CURVE] ([CURVE_ID])
GO

-- ── LAS_FILE_PARAMETER ───────────────────────────────────────────────────────
IF OBJECT_ID('[las_catalog].[LAS_FILE_PARAMETER]', 'U') IS NULL
CREATE TABLE [las_catalog].[LAS_FILE_PARAMETER] (
    [LAS_FILE_ID]       NVARCHAR(40)  NOT NULL,  -- PK+FK → LAS_FILE
    [PARAMETER_NAME]    NVARCHAR(40)  NOT NULL,  -- PK, any ~P section mnemonic
    [PARAMETER_VALUE]   NVARCHAR(500) NULL,
    [PARAMETER_UNIT]    NVARCHAR(40)  NULL,
    [SECTION]           NVARCHAR(10)  NULL,       -- W, C, P, O
    [SOURCE]            NVARCHAR(40)  NOT NULL,
    [ROW_CREATED_BY]    NVARCHAR(30)  NULL,
    [ROW_CREATED_DATE]  DATETIME2     NULL,
    [ROW_CHANGED_BY]    NVARCHAR(30)  NULL,
    [ROW_CHANGED_DATE]  DATETIME2     NULL,
    CONSTRAINT [LASPARM_PK] PRIMARY KEY ([LAS_FILE_ID], [PARAMETER_NAME]),
    CONSTRAINT [LASPARM_FILE_FK] FOREIGN KEY ([LAS_FILE_ID])
        REFERENCES [las_catalog].[LAS_FILE] ([LAS_FILE_ID])
)
GO

-- =============================================================================
-- Useful catalog queries
-- =============================================================================

-- All files containing a GR curve between 1500-3000m
-- SELECT f.UWI, f.WELL_NAME, f.FILE_NAME, f.TOP_DEPTH, f.BASE_DEPTH,
--        r.BASE_PATH + '\' + f.FILE_NAME AS FULL_PATH
-- FROM las_catalog.LAS_FILE f
-- JOIN las_catalog.LAS_REPOSITORY r ON r.REPOSITORY_ID = f.REPOSITORY_ID
-- JOIN las_catalog.LAS_FILE_CURVE c ON c.LAS_FILE_ID = f.LAS_FILE_ID
-- WHERE c.CURVE_ID = 'GR'
--   AND f.TOP_DEPTH <= 3000 AND f.BASE_DEPTH >= 1500

-- Duplicate file detection across repositories
-- SELECT f.FILE_HASH, COUNT(*) AS COPIES
-- FROM las_catalog.LAS_FILE f
-- WHERE f.FILE_HASH IS NOT NULL
-- GROUP BY f.FILE_HASH
-- HAVING COUNT(*) > 1

-- Files not yet matched to a PPDM well
-- SELECT f.LAS_FILE_ID, f.WELL_NAME, f.FILE_NAME, r.BASE_PATH
-- FROM las_catalog.LAS_FILE f
-- JOIN las_catalog.LAS_REPOSITORY r ON r.REPOSITORY_ID = f.REPOSITORY_ID
-- WHERE f.UWI IS NULL AND f.ACTIVE_IND = 'Y'

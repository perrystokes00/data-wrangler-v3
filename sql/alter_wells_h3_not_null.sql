-- =============================================================================
-- alter_wells_h3_not_null.sql
--
-- Step 3 of the H3 backfill pipeline. Run AFTER backfill_h3_bcp.py and
-- validate_h3_backfill.py confirm 100% coverage.
--
-- Actions:
--   1. Promote h3_r4..h3_r7 and h3_coord_hash from NULL to NOT NULL on
--      both source tables. Future inserts cannot slip through with
--      surface coordinates but without H3 cells — the ETL loaders MUST
--      compute H3 before INSERT.
--   2. Add nonclustered indexes on h3_r5 and h3_r6 — the zoom-adaptive
--      workhorses for the page's density grid. R4 is wide enough (~hundreds
--      of cells continent-wide) that a table scan with GROUP BY is fine.
--      R7 use is bounded by bbox prefiltering — also doesn't need a
--      standalone index. Add them later if profiling shows pain.
--
-- This script is point-of-no-return for the NOT NULL decision. The DROP
-- INDEX ... IF EXISTS pattern at the top makes it re-runnable; but once
-- the NOT NULL alter completes, removing it requires either ALTER COLUMN
-- back to NULL or a column drop+re-add. So make sure the validator
-- already gave 16/16 before running this.
--
-- Author: Session 3, 2026-05-26
-- =============================================================================

USE [DataView];
GO

SET XACT_ABORT ON;
GO

PRINT '=== alter_wells_h3_not_null.sql ===';
GO

-- ---------------------------------------------------------------------------
-- Pre-flight: refuse to run if any H3 column has NULL where coords exist.
-- This catches the "ran the alter without validating first" mistake.
-- ---------------------------------------------------------------------------

DECLARE @bad_dv  INT;
DECLARE @bad_gom INT;

SELECT @bad_dv = COUNT(*) FROM dataview.dv_well
WHERE surface_latitude IS NOT NULL
  AND surface_longitude IS NOT NULL
  AND (h3_r4 IS NULL OR h3_r5 IS NULL OR h3_r6 IS NULL
       OR h3_r7 IS NULL OR h3_coord_hash IS NULL);

SELECT @bad_gom = COUNT(*) FROM dataview_gom.well
WHERE surface_latitude IS NOT NULL
  AND surface_longitude IS NOT NULL
  AND (h3_r4 IS NULL OR h3_r5 IS NULL OR h3_r6 IS NULL
       OR h3_r7 IS NULL OR h3_coord_hash IS NULL);

IF @bad_dv > 0 OR @bad_gom > 0
BEGIN
    DECLARE @msg NVARCHAR(300) = CONCAT(
        'REFUSING TO RUN: ', @bad_dv,
        ' dataview wells + ', @bad_gom,
        ' GOM wells have surface coords but missing H3 cells. ',
        'Run validate_h3_backfill.py first; fix the gaps, then re-run this.'
    );
    RAISERROR(@msg, 16, 1);
    -- XACT_ABORT triggers rollback
END

PRINT 'Pre-flight passed: 100% H3 coverage on both source tables.';
GO

-- ---------------------------------------------------------------------------
-- Step 1: ALTER COLUMN to NOT NULL on both tables
-- The existing column type stays the same; only the nullability changes.
-- ---------------------------------------------------------------------------

PRINT 'Promoting H3 columns to NOT NULL on dataview.dv_well ...';

ALTER TABLE dataview.dv_well ALTER COLUMN h3_r4         NVARCHAR(15) NOT NULL;
ALTER TABLE dataview.dv_well ALTER COLUMN h3_r5         NVARCHAR(15) NOT NULL;
ALTER TABLE dataview.dv_well ALTER COLUMN h3_r6         NVARCHAR(15) NOT NULL;
ALTER TABLE dataview.dv_well ALTER COLUMN h3_r7         NVARCHAR(15) NOT NULL;
ALTER TABLE dataview.dv_well ALTER COLUMN h3_coord_hash BINARY(32)   NOT NULL;

PRINT '  dataview.dv_well: NOT NULL applied.';

PRINT 'Promoting H3 columns to NOT NULL on dataview_gom.well ...';

ALTER TABLE dataview_gom.well ALTER COLUMN h3_r4         NVARCHAR(15) NOT NULL;
ALTER TABLE dataview_gom.well ALTER COLUMN h3_r5         NVARCHAR(15) NOT NULL;
ALTER TABLE dataview_gom.well ALTER COLUMN h3_r6         NVARCHAR(15) NOT NULL;
ALTER TABLE dataview_gom.well ALTER COLUMN h3_r7         NVARCHAR(15) NOT NULL;
ALTER TABLE dataview_gom.well ALTER COLUMN h3_coord_hash BINARY(32)   NOT NULL;

PRINT '  dataview_gom.well: NOT NULL applied.';
GO

-- ---------------------------------------------------------------------------
-- Step 2: Indexes on h3_r5 and h3_r6 (zoom-adaptive workhorses).
--
-- Each is a single-column nonclustered index. The GROUP BY pattern the page
-- will use:
--    SELECT h3_r5, COUNT(*) FROM dv_well GROUP BY h3_r5
-- benefits hugely from a sorted index — SQL Server can use a streaming
-- aggregate instead of building a hash table.
--
-- DROP IF EXISTS makes the script re-runnable.
-- ---------------------------------------------------------------------------

PRINT 'Creating indexes on h3_r5 and h3_r6 (dataview.dv_well) ...';

IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_dv_well_h3_r5'
           AND object_id = OBJECT_ID('dataview.dv_well'))
    DROP INDEX IX_dv_well_h3_r5 ON dataview.dv_well;
CREATE NONCLUSTERED INDEX IX_dv_well_h3_r5 ON dataview.dv_well(h3_r5);

IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_dv_well_h3_r6'
           AND object_id = OBJECT_ID('dataview.dv_well'))
    DROP INDEX IX_dv_well_h3_r6 ON dataview.dv_well;
CREATE NONCLUSTERED INDEX IX_dv_well_h3_r6 ON dataview.dv_well(h3_r6);

PRINT '  dataview.dv_well: indexes ready.';

PRINT 'Creating indexes on h3_r5 and h3_r6 (dataview_gom.well) ...';

IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_dv_well_gom_h3_r5'
           AND object_id = OBJECT_ID('dataview_gom.well'))
    DROP INDEX IX_dv_well_gom_h3_r5 ON dataview_gom.well;
CREATE NONCLUSTERED INDEX IX_dv_well_gom_h3_r5 ON dataview_gom.well(h3_r5);

IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_dv_well_gom_h3_r6'
           AND object_id = OBJECT_ID('dataview_gom.well'))
    DROP INDEX IX_dv_well_gom_h3_r6 ON dataview_gom.well;
CREATE NONCLUSTERED INDEX IX_dv_well_gom_h3_r6 ON dataview_gom.well(h3_r6);

PRINT '  dataview_gom.well: indexes ready.';
GO

-- ---------------------------------------------------------------------------
-- Verification: list final state of H3 columns + indexes
-- ---------------------------------------------------------------------------

PRINT '';
PRINT 'Final column state:';
SELECT
    OBJECT_SCHEMA_NAME(c.object_id) + '.' + OBJECT_NAME(c.object_id) AS table_name,
    c.name AS column_name,
    CASE WHEN c.is_nullable = 1 THEN 'NULL' ELSE 'NOT NULL' END AS nullable
FROM sys.columns c
WHERE c.object_id IN (OBJECT_ID('dataview.dv_well'), OBJECT_ID('dataview_gom.well'))
  AND c.name IN ('h3_r4', 'h3_r5', 'h3_r6', 'h3_r7', 'h3_coord_hash')
ORDER BY table_name, column_name;

PRINT '';
PRINT 'Final index state:';
SELECT
    OBJECT_SCHEMA_NAME(i.object_id) + '.' + OBJECT_NAME(i.object_id) AS table_name,
    i.name AS index_name
FROM sys.indexes i
WHERE i.object_id IN (OBJECT_ID('dataview.dv_well'), OBJECT_ID('dataview_gom.well'))
  AND i.name LIKE 'IX_%h3%'
ORDER BY table_name, i.name;

PRINT '';
PRINT 'NOT NULL + indexes complete. Next: create_v_well_density_h3.sql';
GO

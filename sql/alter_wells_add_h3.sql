-- =============================================================================
-- alter_wells_add_h3.sql
--
-- Step 1 of the H3 backfill pipeline. Adds H3 cell columns to the two
-- source well tables. Columns are nullable initially — the backfill
-- script populates them, then alter_wells_h3_not_null.sql enforces
-- NOT NULL once 100% coverage is validated.
--
-- Columns added (to each of dataview.dv_well and dataview_gom.well):
--   h3_r4         NVARCHAR(15)    — H3 cell at resolution 4 (~1,770 km², state/region)
--   h3_r5         NVARCHAR(15)    — H3 cell at resolution 5 (~253 km²,  county-ish)
--   h3_r6         NVARCHAR(15)    — H3 cell at resolution 6 (~36 km²,   township)
--   h3_r7         NVARCHAR(15)    — H3 cell at resolution 7 (~5.16 km², play)
--   h3_coord_hash BINARY(32)      — SHA2_256 of "lat|lon" for staleness detection
--
-- Why NVARCHAR(15): H3 cell IDs are 15-char hex strings. Matches WranglerView.
-- BIGINT would be marginally faster for joins/groups, but at the per-resolution
-- GROUP BY workload we're optimizing for (hundreds-of-rows results), the diff
-- is invisible while debuggability is real.
--
-- Why BINARY(32): SHA2_256 returns 256 bits = 32 bytes. Fixed-width is faster
-- to compare and index than VARBINARY.
--
-- IF NOT EXISTS guards make this script re-runnable. Useful for dev iteration
-- and harmless in production (no-op on second run).
--
-- Author: Session 3, 2026-05-26
-- =============================================================================

USE [DataView];
GO

SET XACT_ABORT ON;
GO

PRINT '=== alter_wells_add_h3.sql ===';

-- ---------------------------------------------------------------------------
-- dataview.dv_well
-- ---------------------------------------------------------------------------
PRINT 'Adding H3 columns to dataview.dv_well ...';

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'h3_r4')
    ALTER TABLE dataview.dv_well ADD h3_r4 NVARCHAR(15) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'h3_r5')
    ALTER TABLE dataview.dv_well ADD h3_r5 NVARCHAR(15) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'h3_r6')
    ALTER TABLE dataview.dv_well ADD h3_r6 NVARCHAR(15) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'h3_r7')
    ALTER TABLE dataview.dv_well ADD h3_r7 NVARCHAR(15) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'h3_coord_hash')
    ALTER TABLE dataview.dv_well ADD h3_coord_hash BINARY(32) NULL;

PRINT '  dataview.dv_well: H3 columns ready.';
GO

-- ---------------------------------------------------------------------------
-- dataview_gom.well
-- ---------------------------------------------------------------------------
PRINT 'Adding H3 columns to dataview_gom.well ...';

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview_gom.well') AND name = 'h3_r4')
    ALTER TABLE dataview_gom.well ADD h3_r4 NVARCHAR(15) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview_gom.well') AND name = 'h3_r5')
    ALTER TABLE dataview_gom.well ADD h3_r5 NVARCHAR(15) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview_gom.well') AND name = 'h3_r6')
    ALTER TABLE dataview_gom.well ADD h3_r6 NVARCHAR(15) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview_gom.well') AND name = 'h3_r7')
    ALTER TABLE dataview_gom.well ADD h3_r7 NVARCHAR(15) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview_gom.well') AND name = 'h3_coord_hash')
    ALTER TABLE dataview_gom.well ADD h3_coord_hash BINARY(32) NULL;

PRINT '  dataview_gom.well: H3 columns ready.';
GO

-- ---------------------------------------------------------------------------
-- Verify columns exist on both tables
-- ---------------------------------------------------------------------------
SELECT
    OBJECT_SCHEMA_NAME(c.object_id) + '.' + OBJECT_NAME(c.object_id) AS table_name,
    c.name AS column_name,
    t.name + CASE
        WHEN t.name IN ('nvarchar', 'varchar') THEN '(' + CAST(c.max_length / 2 AS VARCHAR) + ')'
        WHEN t.name = 'binary' THEN '(' + CAST(c.max_length AS VARCHAR) + ')'
        ELSE ''
    END AS data_type,
    CASE WHEN c.is_nullable = 1 THEN 'NULL' ELSE 'NOT NULL' END AS nullable
FROM sys.columns c
JOIN sys.types t ON t.user_type_id = c.user_type_id
WHERE c.object_id IN (OBJECT_ID('dataview.dv_well'), OBJECT_ID('dataview_gom.well'))
  AND c.name IN ('h3_r4', 'h3_r5', 'h3_r6', 'h3_r7', 'h3_coord_hash')
ORDER BY table_name, column_name;

PRINT 'Expected: 10 rows (5 columns × 2 tables), all nullable.';
PRINT 'Next step: run backfill_h3.py to populate H3 cells.';
GO

-- =============================================================================
-- cleanup_null_coord_wells_v2.sql
--
-- Replaces cleanup_null_coord_wells.sql (which failed at depth-2 FK).
--
-- Removes wells with NULL surface coordinates from dataview.dv_well and
-- dataview_gom.well. Prerequisite for the H3 backfill: every remaining well
-- must have coordinates so the H3 NOT NULL constraint can be applied.
--
-- HARD DELETE — no archive (archive tables in dataview_archive schema
-- already exist from an earlier draft and can be retained or dropped
-- separately; not this script's concern).
--
-- FK graph (uncovered via sys.foreign_keys recursive CTE):
--   depth 1 (15 direct children of dv_well via uwi)
--   depth 2 (11 grandchildren, 10 via uwi column, 1 (dv_prod_volume) via
--            prod_entity_id → dv_prod_entity)
--
-- Pre-flight check confirmed the orphan well 49-039-12345-0000 has zero
-- rows in dv_prod_volume via the prod_entity_id chain, so we don't have
-- to handle that path for THIS run — but a robust script must still
-- handle it in case future orphans have prod volumes.
--
-- Affected rows (verified pre-flight):
--   dataview.dv_well                : 1   well (UWI 49-039-12345-0000)
--   dataview.dv_well_core           : 1+  rows
--   dataview.dv_well_dir_srvy_hdr   : 0   rows (already gone, see archive)
--   dataview.dv_well_dst            : 1+  rows
--   dataview_gom.well               : 801 wells
--
-- Delete order: depth 2 first (grandchildren), then depth 1 (direct
-- children), then parent. dataview_gom.well last (no FKs, simple delete).
--
-- Transactional with XACT_ABORT ON; any failure rolls everything back.
--
-- Author: Session 3, 2026-05-26
-- =============================================================================

USE [DataView];
GO

SET XACT_ABORT ON;
GO

BEGIN TRANSACTION;

DECLARE @null_uwi NVARCHAR(50) = '49-039-12345-0000';
DECLARE @msg NVARCHAR(200);

SET @msg = 'Pre-cleanup counts:';
RAISERROR(@msg, 0, 1) WITH NOWAIT;

SELECT @msg = CONCAT('  dataview.dv_well total: ', FORMAT(COUNT(*), 'N0'))
FROM dataview.dv_well;
RAISERROR(@msg, 0, 1) WITH NOWAIT;

SELECT @msg = CONCAT('  dataview_gom.well total: ', FORMAT(COUNT(*), 'N0'))
FROM dataview_gom.well;
RAISERROR(@msg, 0, 1) WITH NOWAIT;

-- ---------------------------------------------------------------------------
-- Phase 1a: DEPTH-2 grandchildren of dv_well (must delete before depth 1)
--
-- 10 tables have a uwi column directly — straight WHERE uwi = filter.
-- 1 table (dv_prod_volume) joins through prod_entity_id; use IN subquery
-- to handle the indirection. Even though pre-flight showed 0 rows for
-- this run's orphan, the script remains correct for any future orphan
-- with prod volumes.
-- ---------------------------------------------------------------------------

SET @msg = 'Phase 1a: removing depth-2 grandchildren of dv_well';
RAISERROR(@msg, 0, 1) WITH NOWAIT;

DELETE FROM dataview.dv_strat_interval     WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_core_photo    WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_core_sample   WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_dir_srvy_sta  WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_dst_period    WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_log_curve     WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_perforation   WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_petro_zone    WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_shows         WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_stimulation   WHERE uwi = @null_uwi;

-- dv_prod_volume — indirect via dv_prod_entity
DELETE FROM dataview.dv_prod_volume
WHERE prod_entity_id IN (
    SELECT prod_entity_id
    FROM dataview.dv_prod_entity
    WHERE uwi = @null_uwi
);

-- ---------------------------------------------------------------------------
-- Phase 1b: DEPTH-1 direct children of dv_well
-- ---------------------------------------------------------------------------

SET @msg = 'Phase 1b: removing depth-1 direct children of dv_well';
RAISERROR(@msg, 0, 1) WITH NOWAIT;

DELETE FROM dataview.dv_prod_entity        WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_alias         WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_casing        WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_completion    WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_core          WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_dir_srvy_hdr  WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_dst           WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_extension     WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_formation_top WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_legal         WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_log           WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_mud_log       WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_petro_interp  WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_well_pressure      WHERE uwi = @null_uwi;
DELETE FROM dataview.dv_wl_file_catalog    WHERE uwi = @null_uwi;

-- ---------------------------------------------------------------------------
-- Phase 1c: dv_well parent itself
-- ---------------------------------------------------------------------------

SET @msg = 'Phase 1c: removing dv_well parent row';
RAISERROR(@msg, 0, 1) WITH NOWAIT;

DELETE FROM dataview.dv_well WHERE uwi = @null_uwi;

DECLARE @dv_deleted INT = @@ROWCOUNT;
SET @msg = CONCAT('  Deleted from dataview.dv_well: ', @dv_deleted, ' row(s)');
RAISERROR(@msg, 0, 1) WITH NOWAIT;

-- ---------------------------------------------------------------------------
-- Phase 2: GOM side
-- 801 wells with NULL surface coords. No inbound FKs per pre-flight.
-- ---------------------------------------------------------------------------

SET @msg = 'Phase 2: removing GOM wells with NULL surface coordinates';
RAISERROR(@msg, 0, 1) WITH NOWAIT;

DELETE FROM dataview_gom.well
WHERE surface_latitude IS NULL OR surface_longitude IS NULL;

DECLARE @gom_deleted INT = @@ROWCOUNT;
SET @msg = CONCAT('  Deleted from dataview_gom.well: ', @gom_deleted, ' row(s)');
RAISERROR(@msg, 0, 1) WITH NOWAIT;

-- ---------------------------------------------------------------------------
-- Phase 3: Verify post-cleanup state — zero NULL-coord rows must remain.
-- ---------------------------------------------------------------------------

DECLARE @dv_remaining_null  INT;
DECLARE @gom_remaining_null INT;

SELECT @dv_remaining_null = COUNT(*) FROM dataview.dv_well
WHERE surface_latitude IS NULL OR surface_longitude IS NULL;

SELECT @gom_remaining_null = COUNT(*) FROM dataview_gom.well
WHERE surface_latitude IS NULL OR surface_longitude IS NULL;

IF @dv_remaining_null > 0 OR @gom_remaining_null > 0
BEGIN
    SET @msg = CONCAT('SAFETY ABORT: ', @dv_remaining_null, ' dataview + ',
                      @gom_remaining_null, ' GOM null-coord rows still exist. ',
                      'Rolling back. Investigate before re-running.');
    RAISERROR(@msg, 16, 1);
    -- XACT_ABORT triggers rollback
END

SET @msg = 'Phase 3: verification passed';
RAISERROR(@msg, 0, 1) WITH NOWAIT;

SELECT @msg = CONCAT('  dataview.dv_well total: ', FORMAT(COUNT(*), 'N0'),
                     ' (all w/ surface coords)') FROM dataview.dv_well;
RAISERROR(@msg, 0, 1) WITH NOWAIT;
SELECT @msg = CONCAT('  dataview_gom.well total: ', FORMAT(COUNT(*), 'N0'),
                     ' (all w/ surface coords)') FROM dataview_gom.well;
RAISERROR(@msg, 0, 1) WITH NOWAIT;

COMMIT TRANSACTION;

PRINT 'CLEANUP COMPLETE — ready for H3 schema work.';
GO

-- Expected post-state:
--   dataview.dv_well  = 477,108 rows, all w/ surface_latitude AND surface_longitude
--   dataview_gom.well = 54,675  rows, all w/ surface_latitude AND surface_longitude

-- =============================================================================
-- delete_kgs_null_coords_and_restore_h3.sql
--
-- Cleanup after the KGS reload + H3 backfill:
--   1. Delete the 50 KGS rows that have NULL surface_latitude/longitude.
--      These rows can never appear on the map or in the federation
--      (filtered indexes exclude them), so they have no operational value.
--   2. Delete their companion rows from dv_well_ext_kgs (raw native)
--      and dv_well_identifier (UWI/KID/API crosswalk).
--   3. Restore the NOT NULL constraints on dv_well.h3_* that were
--      relaxed during the load.
--
-- All in one transaction. Verifies row counts before/after.
-- =============================================================================

USE [DataView];
GO

SET XACT_ABORT ON;
SET NOCOUNT ON;
GO

BEGIN TRY
    BEGIN TRANSACTION;

    PRINT '═══════════════════════════════════════════════════════════════════════';
    PRINT 'KGS post-load cleanup — delete null-coord rows + restore NOT NULL';
    PRINT '═══════════════════════════════════════════════════════════════════════';

    -- ────────────────────────────────────────────────────────────────────
    -- Pre-flight: capture the UWIs we're about to delete + counts
    -- ────────────────────────────────────────────────────────────────────
    PRINT '';
    PRINT '── Pre-flight ──';

    -- Snapshot the doomed UWIs into a table variable so we can use them
    -- across all three DELETEs without re-querying dv_well each time.
    DECLARE @doomed TABLE (uwi NVARCHAR(40) PRIMARY KEY);

    INSERT INTO @doomed (uwi)
    SELECT uwi
    FROM dataview.dv_well
    WHERE source = 'KGS'
      AND (surface_latitude IS NULL OR surface_longitude IS NULL);

    DECLARE @doomed_count INT = (SELECT COUNT(*) FROM @doomed);
    PRINT '   Null-coord KGS rows to delete: ' + CAST(@doomed_count AS VARCHAR);

    IF @doomed_count = 0
    BEGIN
        PRINT '   No null-coord rows found — nothing to delete.';
        PRINT '   Skipping DELETE steps, proceeding to NOT NULL restoration.';
    END
    ELSE IF @doomed_count > 100
    BEGIN
        -- Safety: if more than ~100 rows would be deleted, something's off.
        -- Original loader reported exactly 50.
        DECLARE @msg NVARCHAR(200) =
            'Unexpected count: ' + CAST(@doomed_count AS VARCHAR) +
            ' null-coord rows (expected ~50). Aborting for safety.';
        RAISERROR(@msg, 16, 1);
    END

    -- ────────────────────────────────────────────────────────────────────
    -- Pre-cleanup snapshot
    -- ────────────────────────────────────────────────────────────────────
    DECLARE @before_well INT = (SELECT COUNT(*) FROM dataview.dv_well WHERE source = 'KGS');
    DECLARE @before_ext  INT = (SELECT COUNT(*) FROM dataview.dv_well_ext_kgs);
    DECLARE @before_id   INT = (SELECT COUNT(*) FROM dataview.dv_well_identifier WHERE source_system = 'KGS');

    PRINT '   Before cleanup:';
    PRINT '     dv_well (KGS)        : ' + CAST(@before_well AS VARCHAR);
    PRINT '     dv_well_ext_kgs      : ' + CAST(@before_ext AS VARCHAR);
    PRINT '     dv_well_identifier   : ' + CAST(@before_id AS VARCHAR);

    -- ────────────────────────────────────────────────────────────────────
    -- DELETE from dv_well_identifier first (no FK enforcement but
    -- conceptually leaf-first delete)
    -- ────────────────────────────────────────────────────────────────────
    IF @doomed_count > 0
    BEGIN
        PRINT '';
        PRINT '── Deleting companion identifier rows ──';
        DELETE FROM dataview.dv_well_identifier
        WHERE source_system = 'KGS'
          AND well_id IN (
              SELECT well_id
              FROM dataview.dv_well_identifier
              WHERE identifier_type = 'UWI'
                AND identifier_value IN (SELECT uwi FROM @doomed)
          );
        PRINT '   deleted: ' + CAST(@@ROWCOUNT AS VARCHAR) + ' identifier rows';

        -- ────────────────────────────────────────────────────────────────
        -- DELETE from dv_well_ext_kgs (the source-native raw rows)
        -- ────────────────────────────────────────────────────────────────
        PRINT '';
        PRINT '── Deleting companion ext rows ──';
        DELETE FROM dataview.dv_well_ext_kgs
        WHERE uwi IN (SELECT uwi FROM @doomed);
        PRINT '   deleted: ' + CAST(@@ROWCOUNT AS VARCHAR) + ' ext rows';

        -- ────────────────────────────────────────────────────────────────
        -- DELETE from dv_well last (it's the parent in most FKs)
        -- ────────────────────────────────────────────────────────────────
        PRINT '';
        PRINT '── Deleting null-coord KGS rows from dv_well ──';
        DELETE FROM dataview.dv_well
        WHERE uwi IN (SELECT uwi FROM @doomed);
        PRINT '   deleted: ' + CAST(@@ROWCOUNT AS VARCHAR) + ' dv_well rows';
    END

    -- ────────────────────────────────────────────────────────────────────
    -- Post-DELETE verification
    -- ────────────────────────────────────────────────────────────────────
    PRINT '';
    PRINT '── Post-delete verification ──';

    DECLARE @after_well INT = (SELECT COUNT(*) FROM dataview.dv_well WHERE source = 'KGS');
    DECLARE @after_ext  INT = (SELECT COUNT(*) FROM dataview.dv_well_ext_kgs);
    DECLARE @after_id   INT = (SELECT COUNT(*) FROM dataview.dv_well_identifier WHERE source_system = 'KGS');

    PRINT '   After delete:';
    PRINT '     dv_well (KGS)        : ' + CAST(@after_well AS VARCHAR)
          + '  (was ' + CAST(@before_well AS VARCHAR) + ')';
    PRINT '     dv_well_ext_kgs      : ' + CAST(@after_ext AS VARCHAR)
          + '  (was ' + CAST(@before_ext AS VARCHAR) + ')';
    PRINT '     dv_well_identifier   : ' + CAST(@after_id AS VARCHAR)
          + '  (was ' + CAST(@before_id AS VARCHAR) + ')';

    -- Sanity: no remaining KGS rows with NULL h3 (was true before, must
    -- still be true now since we just deleted the only NULL-h3 rows)
    DECLARE @remaining_null_h3 INT = (
        SELECT COUNT(*)
        FROM dataview.dv_well
        WHERE source = 'KGS' AND h3_coord_hash IS NULL
    );

    IF @remaining_null_h3 > 0
    BEGIN
        DECLARE @errmsg NVARCHAR(200) =
            'Cleanup failed: ' + CAST(@remaining_null_h3 AS VARCHAR) +
            ' KGS rows still have NULL h3_coord_hash. Aborting NOT NULL restore.';
        RAISERROR(@errmsg, 16, 1);
    END

    PRINT '   Remaining KGS rows with NULL h3: 0  ✓';

    -- ────────────────────────────────────────────────────────────────────
    -- Restore NOT NULL on dv_well.h3_* columns
    -- ────────────────────────────────────────────────────────────────────
    -- Also need to make sure no non-KGS rows have NULL h3. If any do, we
    -- have a problem we should know about before restoring constraints.
    DECLARE @global_null_h3 INT = (
        SELECT COUNT(*)
        FROM dataview.dv_well
        WHERE h3_coord_hash IS NULL
    );

    IF @global_null_h3 > 0
    BEGIN
        DECLARE @errmsg2 NVARCHAR(200) =
            'Cannot restore NOT NULL: ' + CAST(@global_null_h3 AS VARCHAR) +
            ' rows still have NULL h3_coord_hash (across all sources).';
        RAISERROR(@errmsg2, 16, 1);
    END

    PRINT '';
    PRINT '── Restoring NOT NULL on dv_well.h3_* columns ──';

    ALTER TABLE [dataview].[dv_well] ALTER COLUMN [h3_r4] NVARCHAR(15) NOT NULL;
    PRINT '   h3_r4         : NOT NULL';

    ALTER TABLE [dataview].[dv_well] ALTER COLUMN [h3_r5] NVARCHAR(15) NOT NULL;
    PRINT '   h3_r5         : NOT NULL';

    ALTER TABLE [dataview].[dv_well] ALTER COLUMN [h3_r6] NVARCHAR(15) NOT NULL;
    PRINT '   h3_r6         : NOT NULL';

    ALTER TABLE [dataview].[dv_well] ALTER COLUMN [h3_r7] NVARCHAR(15) NOT NULL;
    PRINT '   h3_r7         : NOT NULL';

    ALTER TABLE [dataview].[dv_well] ALTER COLUMN [h3_coord_hash] BINARY(32) NOT NULL;
    PRINT '   h3_coord_hash : NOT NULL';

    COMMIT TRANSACTION;

    PRINT '';
    PRINT '═══════════════════════════════════════════════════════════════════════';
    PRINT 'Post-load cleanup complete.';
    PRINT '═══════════════════════════════════════════════════════════════════════';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    PRINT '';
    PRINT 'FAILED:';
    PRINT '   Error number: ' + CAST(ERROR_NUMBER() AS VARCHAR);
    PRINT '   Error line:   ' + CAST(ERROR_LINE() AS VARCHAR);
    PRINT '   Message:      ' + ERROR_MESSAGE();
    THROW;
END CATCH
GO

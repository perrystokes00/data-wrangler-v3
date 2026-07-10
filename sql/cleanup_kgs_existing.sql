-- =============================================================================
-- cleanup_kgs_existing.sql
--
-- Deletes the existing dirty KGS rows from dv_well so the new loader has a
-- clean slate. The original loader inserted 476,957 rows with source =
-- 'KGS_GEOJSON' that have contamination in operator_name and field_name
-- (newlines, quotes, column shifts).
--
-- New loader will insert with source = 'KGS' (simpler) and clean data.
--
-- This script also clears any related H3 / dv_well_identifier rows so the
-- next reload doesn't leave orphans.
-- =============================================================================

USE [DataView];
GO

SET XACT_ABORT ON;
SET NOCOUNT ON;
GO

BEGIN TRY
    BEGIN TRANSACTION;

    PRINT '═══════════════════════════════════════════════════════════════════════';
    PRINT 'KGS cleanup — delete existing dirty rows before reload';
    PRINT '═══════════════════════════════════════════════════════════════════════';

    -- Pre-flight: report what we're about to delete
    DECLARE @kgs_well_count INT;
    SELECT @kgs_well_count = COUNT(*)
    FROM dataview.dv_well
    WHERE source IN ('KGS', 'KGS_GEOJSON');

    PRINT '';
    PRINT '── Pre-flight ──';
    PRINT '   Existing KGS rows in dv_well: ' + CAST(@kgs_well_count AS VARCHAR);

    -- Check identifier table too
    DECLARE @kgs_id_count INT = 0;
    IF OBJECT_ID('dataview.dv_well_identifier', 'U') IS NOT NULL
    BEGIN
        SELECT @kgs_id_count = COUNT(*)
        FROM dataview.dv_well_identifier
        WHERE source_system IN ('KGS', 'KGS_GEOJSON');
        PRINT '   Existing KGS rows in dv_well_identifier: ' + CAST(@kgs_id_count AS VARCHAR);
    END

    -- Check existing dv_well_ext_kgs
    DECLARE @kgs_ext_count INT = 0;
    IF OBJECT_ID('dataview.dv_well_ext_kgs', 'U') IS NOT NULL
    BEGIN
        SELECT @kgs_ext_count = COUNT(*) FROM dataview.dv_well_ext_kgs;
        PRINT '   Existing rows in dv_well_ext_kgs: ' + CAST(@kgs_ext_count AS VARCHAR);
    END

    -- -----------------------------------------------------------------------
    -- DELETE from dv_well_identifier first (if it has KGS rows)
    -- -----------------------------------------------------------------------
    IF @kgs_id_count > 0
    BEGIN
        PRINT '';
        PRINT '── Deleting from dv_well_identifier ──';
        DELETE FROM dataview.dv_well_identifier
        WHERE source_system IN ('KGS', 'KGS_GEOJSON');
        PRINT '   deleted: ' + CAST(@@ROWCOUNT AS VARCHAR) + ' identifier rows';
    END

    -- -----------------------------------------------------------------------
    -- TRUNCATE dv_well_ext_kgs (faster than DELETE, table was just created)
    -- -----------------------------------------------------------------------
    IF @kgs_ext_count > 0
    BEGIN
        PRINT '';
        PRINT '── Truncating dv_well_ext_kgs ──';
        TRUNCATE TABLE dataview.dv_well_ext_kgs;
        PRINT '   truncated: ' + CAST(@kgs_ext_count AS VARCHAR) + ' rows';
    END

    -- -----------------------------------------------------------------------
    -- DELETE from dv_well WHERE source IN ('KGS','KGS_GEOJSON')
    -- This is the big one — 476,957 rows
    -- -----------------------------------------------------------------------
    PRINT '';
    PRINT '── Deleting KGS rows from dv_well ──';
    PRINT '   This is the big one (~477K rows). Will take ~20-30 seconds.';

    DELETE FROM dataview.dv_well
    WHERE source IN ('KGS', 'KGS_GEOJSON');

    DECLARE @deleted INT = @@ROWCOUNT;
    PRINT '   deleted: ' + CAST(@deleted AS VARCHAR) + ' well rows';

    -- -----------------------------------------------------------------------
    -- Verify: post-cleanup row counts
    -- -----------------------------------------------------------------------
    PRINT '';
    PRINT '── Post-cleanup verification ──';

    SELECT @kgs_well_count = COUNT(*)
    FROM dataview.dv_well
    WHERE source IN ('KGS', 'KGS_GEOJSON');

    IF @kgs_well_count > 0
    BEGIN
        DECLARE @err NVARCHAR(200) =
            'Expected 0 KGS rows after delete, found ' + CAST(@kgs_well_count AS VARCHAR);
        RAISERROR(@err, 16, 1);
    END

    PRINT '   KGS rows remaining in dv_well: 0  ✓';

    -- Total remaining wells (sanity check — should be ~54K non-KGS rows
    -- from DATAVIEW and OSDU sources)
    DECLARE @non_kgs_count INT;
    SELECT @non_kgs_count = COUNT(*) FROM dataview.dv_well;
    PRINT '   Non-KGS rows in dv_well: ' + CAST(@non_kgs_count AS VARCHAR);

    COMMIT TRANSACTION;

    PRINT '';
    PRINT '═══════════════════════════════════════════════════════════════════════';
    PRINT 'Cleanup complete. Ready to run load_kgs.py';
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

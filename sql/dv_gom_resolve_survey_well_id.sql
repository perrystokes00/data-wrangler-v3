/* ===================================================================
   dv_gom_resolve_survey_well_id.sql
   -------------------------------------------------------------------
   well_id resolution pass for dataview_gom.directional_survey_point.

   The directional survey loader stores api_well_number raw and leaves
   well_id NULL — surveys load cleanly even for APIs not yet in
   dataview_gom.well. This script is the follow-up pass that fills in
   well_id by joining to dataview_gom.well on api_well_number.

   Run this AFTER the directional survey loader, as part of the rebuild
   sequence (or any time new surveys have been loaded).

   Design
   ------
   - BATCHED update. The table is ~4.9M rows; a single UPDATE that wide
     would bloat the transaction log on SQL Express (10 GB ceiling).
     The loop updates @batch_size rows at a time, each statement its
     own implicit transaction, so the log stays small and reusable.
   - IDEMPOTENT. The WHERE well_id IS NULL filter means:
       * a fresh run resolves every unresolved row
       * a re-run is cheap — it only touches rows still NULL
       * surveys whose api_well_number has no matching well stay NULL
         (no match = nothing to set) and simply wait for a future
         dataview_gom.well load
   - No GO statements — pyodbc executes one batch. Matches the
     dv_indexes.sql / dv_gom_directional_survey.sql convention.
   - Prints a before/after summary so the rebuild log shows what
     happened.
   =================================================================== */

SET NOCOUNT ON;

DECLARE @batch_size   INT = 50000;
DECLARE @rows_updated INT = 1;          -- prime the loop
DECLARE @total_done   BIGINT = 0;

/* ---- Pre-pass snapshot ---------------------------------------------- */
DECLARE @unresolved_before BIGINT = (
    SELECT COUNT_BIG(*)
    FROM dataview_gom.directional_survey_point
    WHERE well_id IS NULL
);
DECLARE @total_points BIGINT = (
    SELECT COUNT_BIG(*) FROM dataview_gom.directional_survey_point
);

PRINT 'GOM survey well_id resolution — starting';
PRINT '  total survey points : ' + CAST(@total_points       AS VARCHAR(20));
PRINT '  unresolved (NULL)   : ' + CAST(@unresolved_before  AS VARCHAR(20));

/* ---- Batched resolution loop ---------------------------------------- */
/* Each pass updates up to @batch_size still-NULL rows whose
   api_well_number matches a borehole record. TOP keeps each statement
   bounded; the loop exits when a pass updates 0 rows (everything that
   CAN be resolved has been). */
WHILE @rows_updated > 0
BEGIN
    UPDATE TOP (@batch_size) s
       SET s.well_id          = w.well_id,
           s.row_changed_date = SYSUTCDATETIME()
    FROM dataview_gom.directional_survey_point AS s
    INNER JOIN dataview_gom.well AS w
        ON w.api_well_number = s.api_well_number
    WHERE s.well_id IS NULL;

    SET @rows_updated = @@ROWCOUNT;
    SET @total_done   = @total_done + @rows_updated;
END;

/* ---- Post-pass snapshot --------------------------------------------- */
DECLARE @unresolved_after BIGINT = (
    SELECT COUNT_BIG(*)
    FROM dataview_gom.directional_survey_point
    WHERE well_id IS NULL
);

PRINT 'GOM survey well_id resolution — complete';
PRINT '  rows resolved this run : ' + CAST(@total_done        AS VARCHAR(20));
PRINT '  still unresolved       : ' + CAST(@unresolved_after  AS VARCHAR(20));
PRINT '    (unresolved rows have an api_well_number with no matching';
PRINT '     dataview_gom.well record — they resolve on a future run';
PRINT '     once that borehole header is loaded)';

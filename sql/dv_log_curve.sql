/* ============================================================================
   dv_log_curve.sql — curated target for the file-side log curve registry.
   ----------------------------------------------------------------------------
   Columns mirror file_catalog.cat_log_curve so promote_catalog's shared-column
   copy carries every field. cat_name('dv_log_curve') = 'cat_log_curve', so once
   'dv_log_curve' is in MIRROR_TABLES (build_catalog_mirror.py), the existing
   promote lifts cat_log_curve → dv_log_curve as a normal detail table:
   UWI-gated against dv_well, INVENTORY-keyed per-file replace. No las_catalog
   bridge needed for logs.

   Idempotent. Run:  sqlcmd -S PERRY\SQLEXPRESS -d DataView -E -i dv_log_curve.sql
   ============================================================================ */
USE DataView;
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
SET NOCOUNT ON;

IF OBJECT_ID('dataview.dv_log_curve','U') IS NULL
BEGIN
    CREATE TABLE dataview.dv_log_curve (
        LOG_CURVE_ID     BIGINT IDENTITY(1,1) NOT NULL
                         CONSTRAINT PK_dv_log_curve PRIMARY KEY,
        UWI              VARCHAR(64)  NOT NULL,   -- gate / FK to dv_well
        UWI14            VARCHAR(14)  NULL,
        SOURCE_FORMAT    VARCHAR(8)   NULL,       -- LAS / DLIS / LIS
        LOGICAL_FILE     INT          NULL,
        FRAME_NAME       VARCHAR(128) NULL,
        CURVE_INDEX      INT          NULL,
        CURVE_MNEMONIC   VARCHAR(64)  NULL,
        CURVE_LONG_NAME  VARCHAR(256) NULL,
        CURVE_UNIT       VARCHAR(32)  NULL,
        API_CODE         VARCHAR(32)  NULL,
        CURVE_DIMENSION  VARCHAR(32)  NULL,
        IS_INDEX         CHAR(1)      NULL,
        DEPTH_UOM        VARCHAR(16)  NULL,
        DEPTH_START      FLOAT        NULL,
        DEPTH_STOP       FLOAT        NULL,
        DEPTH_STEP       FLOAT        NULL,
        SAMPLE_COUNT     INT          NULL,
        NULL_VALUE       FLOAT        NULL,
        INVENTORY_ID     NVARCHAR(64) NULL,       -- lineage for per-file replace
        ROW_CREATED_BY   VARCHAR(30)  NULL,       -- promote fills ('PROMOTE')
        ROW_CREATED_DATE DATETIME2    NULL,
        ACTIVE_IND       CHAR(1)      NULL
    );
    CREATE INDEX IX_dv_log_curve_uwi  ON dataview.dv_log_curve(UWI);
    CREATE INDEX IX_dv_log_curve_inv  ON dataview.dv_log_curve(INVENTORY_ID);
    CREATE INDEX IX_dv_log_curve_mnem ON dataview.dv_log_curve(CURVE_MNEMONIC);
    PRINT 'created dataview.dv_log_curve';
END
ELSE
    PRINT 'dataview.dv_log_curve already exists';

/* FK to dv_well — gives the promote toposort the edge to lift dv_well before
   dv_log_curve, so a single pass resolves new wells too. Guarded: if dv_well.UWI
   differs in type/length the FK is skipped (the promote EXISTS-gate already
   quarantines unmatched UWIs, and a second promote pass catches any new wells). */
IF OBJECT_ID('dataview.dv_log_curve','U') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_dv_log_curve_well')
BEGIN
    BEGIN TRY
        ALTER TABLE dataview.dv_log_curve WITH NOCHECK
            ADD CONSTRAINT FK_dv_log_curve_well
            FOREIGN KEY (UWI) REFERENCES dataview.dv_well(UWI);
        PRINT 'added FK_dv_log_curve_well';
    END TRY
    BEGIN CATCH
        PRINT 'FK skipped (' + ERROR_MESSAGE()
            + ') — promote EXISTS-gate still applies; re-run promote to catch new wells';
    END CATCH
END

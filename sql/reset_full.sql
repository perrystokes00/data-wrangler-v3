/* ============================================================================
   reset_full.sql  —  total clean slate for an extraction / load re-test
   ----------------------------------------------------------------------------
   Wipes, in one transaction (rolls back completely on any error):
     A) EVERY table in schema  file_catalog       (FK-safe: NOCHECK → DELETE → re-CHECK)
     B) EVERY table in schema  las_catalog         (FK-safe, same)  — skipped if absent
     C) promoted rows in dataview.dv_* detail tables
        (rows carrying an INVENTORY_ID — i.e. lifted from the catalog)
     D) dv_well header rows created by capture / promote
        (row_created_by IN ('DataWrangler','PROMOTE'))

   Reference / curated dv_well rows loaded by the importer keep their own
   row_created_by and are NOT removed.  The BEFORE report prints the full
   dv_well row_created_by breakdown so you can confirm what D will delete.

   Table sets are DISCOVERED from the catalog (new mirrors picked up
   automatically).  C & D run with FK enforcement temporarily disabled on the
   touched dataview tables, so delete order never matters.

   Run:  sqlcmd -S PERRY\SQLEXPRESS -d DataView -E -i reset_full.sql
   ============================================================================ */
USE DataView;
-- sqlcmd defaults QUOTED_IDENTIFIER OFF, which blocks DML on tables that have
-- a spatial / computed-column / filtered index (dv_well's geography index).
-- Force the ANSI options ON so the dataview deletes are allowed.
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
SET NOCOUNT ON;
PRINT 'reset_full v2 (QUOTED_IDENTIFIER ON)';

DECLARE @sql  NVARCHAR(MAX),
        @crlf NCHAR(2) = NCHAR(13) + NCHAR(10);

/* reusable per-schema rowcount report ------------------------------------- */
DECLARE @rep_fc NVARCHAR(MAX) = N'', @rep_lc NVARCHAR(MAX) = N'',
        @rep_dv NVARCHAR(MAX) = N'';

SELECT @rep_fc = ISNULL(@rep_fc + ' UNION ALL ', '') +
       'SELECT ''file_catalog'' sch, ''' + name + ''' tbl, COUNT(*) rows FROM '
       + 'file_catalog.' + QUOTENAME(name)
FROM sys.tables WHERE schema_id = SCHEMA_ID('file_catalog');

IF SCHEMA_ID('las_catalog') IS NOT NULL
    SELECT @rep_lc = ISNULL(@rep_lc + ' UNION ALL ', '') +
           'SELECT ''las_catalog'' sch, ''' + name + ''' tbl, COUNT(*) rows FROM '
           + 'las_catalog.' + QUOTENAME(name)
    FROM sys.tables WHERE schema_id = SCHEMA_ID('las_catalog');

SELECT @rep_dv = ISNULL(@rep_dv + ' UNION ALL ', '') +
       'SELECT ''dataview'' sch, ''' + t.name + ''' tbl, '
       + 'COUNT(*) rows FROM dataview.' + QUOTENAME(t.name)
       + ' WHERE INVENTORY_ID IS NOT NULL'
FROM sys.tables t
JOIN sys.columns c ON c.object_id = t.object_id AND c.name = 'INVENTORY_ID'
WHERE t.schema_id = SCHEMA_ID('dataview') AND t.name <> 'dv_well';

/* -------------------------------------------------------------------------- */
PRINT '================  BEFORE  ================';
PRINT '-- file_catalog --';            IF @rep_fc <> '' EXEC(@rep_fc);
PRINT '-- las_catalog --';             IF @rep_lc <> '' EXEC(@rep_lc); ELSE PRINT '(no las_catalog schema)';
PRINT '-- dataview promoted detail --'; IF @rep_dv <> '' EXEC(@rep_dv);
PRINT '-- dv_well by row_created_by --';
SELECT row_created_by, COUNT(*) AS rows
FROM dataview.dv_well GROUP BY row_created_by ORDER BY rows DESC;

/* ========================================================================== */
BEGIN TRY
BEGIN TRAN;

    /* ---- A. wipe all of file_catalog ------------------------------------ */
    PRINT '--- A: file_catalog ---';
    SET @sql = N'';
    SELECT @sql = @sql
        + 'ALTER TABLE file_catalog.' + QUOTENAME(name) + ' NOCHECK CONSTRAINT ALL;' + @crlf
    FROM sys.tables WHERE schema_id = SCHEMA_ID('file_catalog');
    SELECT @sql = @sql
        + 'DELETE FROM file_catalog.' + QUOTENAME(name) + ';' + @crlf
    FROM sys.tables WHERE schema_id = SCHEMA_ID('file_catalog');
    SELECT @sql = @sql
        + 'ALTER TABLE file_catalog.' + QUOTENAME(name) + ' WITH CHECK CHECK CONSTRAINT ALL;' + @crlf
    FROM sys.tables WHERE schema_id = SCHEMA_ID('file_catalog');
    IF @sql <> N'' EXEC sys.sp_executesql @sql;

    /* ---- B. wipe all of las_catalog (if present) ------------------------ */
    IF SCHEMA_ID('las_catalog') IS NOT NULL
    BEGIN
        PRINT '--- B: las_catalog ---';
        SET @sql = N'';
        SELECT @sql = @sql
            + 'ALTER TABLE las_catalog.' + QUOTENAME(name) + ' NOCHECK CONSTRAINT ALL;' + @crlf
        FROM sys.tables WHERE schema_id = SCHEMA_ID('las_catalog');
        SELECT @sql = @sql
            + 'DELETE FROM las_catalog.' + QUOTENAME(name) + ';' + @crlf
        FROM sys.tables WHERE schema_id = SCHEMA_ID('las_catalog');
        SELECT @sql = @sql
            + 'ALTER TABLE las_catalog.' + QUOTENAME(name) + ' WITH CHECK CHECK CONSTRAINT ALL;' + @crlf
        FROM sys.tables WHERE schema_id = SCHEMA_ID('las_catalog');
        IF @sql <> N'' EXEC sys.sp_executesql @sql;
    END

    /* ---- C & D. dataview: disable FK on touched tables, delete, re-check - */
    PRINT '--- C/D: dataview promoted rows + created headers ---';

    -- touched set = dv_well + every dataview table with an INVENTORY_ID column
    DECLARE @dvtabs TABLE (name sysname);
    INSERT @dvtabs(name)
    SELECT t.name FROM sys.tables t
    JOIN sys.columns c ON c.object_id = t.object_id AND c.name = 'INVENTORY_ID'
    WHERE t.schema_id = SCHEMA_ID('dataview') AND t.name <> 'dv_well'
    UNION SELECT 'dv_well';

    SET @sql = N'';
    SELECT @sql = @sql
        + 'ALTER TABLE dataview.' + QUOTENAME(name) + ' NOCHECK CONSTRAINT ALL;' + @crlf
    FROM @dvtabs;
    IF @sql <> N'' EXEC sys.sp_executesql @sql;

    -- C: promoted detail rows
    SET @sql = N'';
    SELECT @sql = @sql
        + 'DELETE FROM dataview.' + QUOTENAME(name) + ' WHERE INVENTORY_ID IS NOT NULL;' + @crlf
    FROM @dvtabs WHERE name <> 'dv_well';
    IF @sql <> N'' EXEC sys.sp_executesql @sql;

    -- D: dv_well headers created by capture / promote
    IF EXISTS (SELECT 1 FROM sys.columns
               WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'row_created_by')
        DELETE FROM dataview.dv_well
        WHERE row_created_by IN ('DataWrangler', 'PROMOTE');

    -- restore FK enforcement
    SET @sql = N'';
    SELECT @sql = @sql
        + 'ALTER TABLE dataview.' + QUOTENAME(name) + ' WITH CHECK CHECK CONSTRAINT ALL;' + @crlf
    FROM @dvtabs;
    IF @sql <> N'' EXEC sys.sp_executesql @sql;

COMMIT TRAN;
PRINT '================  COMMITTED  ================';
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRAN;
    PRINT '================  ROLLED BACK — nothing changed  ================';
    PRINT ERROR_MESSAGE();
    THROW;
END CATCH;

/* -------------------------------------------------------------------------- */
PRINT '================  AFTER  ================';
PRINT '-- file_catalog --';            IF @rep_fc <> '' EXEC(@rep_fc);
PRINT '-- las_catalog --';             IF @rep_lc <> '' EXEC(@rep_lc); ELSE PRINT '(no las_catalog schema)';
PRINT '-- dataview promoted detail --'; IF @rep_dv <> '' EXEC(@rep_dv);
PRINT '-- dv_well by row_created_by --';
SELECT row_created_by, COUNT(*) AS rows
FROM dataview.dv_well GROUP BY row_created_by ORDER BY rows DESC;

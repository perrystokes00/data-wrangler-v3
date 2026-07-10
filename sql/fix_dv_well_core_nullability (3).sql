/* ============================================================================
   fix_dv_well_core_nullability.sql

   dataview.dv_well_core ships with a set of audit / metadata columns marked
   NOT NULL with no default. That forces every core load to supply values the
   source files don't carry (core_num, core_show, the *_ouom unit codes, the
   *_ba_id company ids, photo flags, row_created_by, ...). This script:

     1. Makes those columns NULLable (reading each column's REAL data type from
        the catalog so the ALTER preserves length / precision / scale).
     2. Gives row_created_by a default ('DV_TABLE_LOADER') so the loader no
        longer has to supply it — which also drops it from the "required" list
        the Mapping Studio shows.

   HOW TO RUN
     - Run this script ALONE in a fresh query window. Do not paste other
       statements above it -- a stray batch above is what produced the earlier
       Msg 4145 / 102 error (it was never this script).
     - It APPLIES by default (@Apply = 1). Set @Apply = 0 to preview the exact
       ALTER statements without changing anything.
     - After it runs, click "Refresh schema" in the Mapping Studio so the cache
       picks up the new nullability and default.

   Safe to re-run: already-nullable columns are skipped, and the default is
   only added if row_created_by has none.
   ============================================================================ */

SET NOCOUNT ON;

DECLARE @Apply  BIT     = 1;                 -- 1 = execute, 0 = preview only
DECLARE @schema SYSNAME = N'dataview';
DECLARE @table  SYSNAME = N'dv_well_core';

DECLARE @cols TABLE (name SYSNAME PRIMARY KEY);
INSERT INTO @cols (name) VALUES
    (N'core_num'), (N'core_show'), (N'depth_ouom'), (N'depth_datum'),
    (N'core_length'), (N'recovery_length'), (N'length_ouom'), (N'core_date'),
    (N'cutting_company_ba_id'), (N'analysis_company_ba_id'), (N'photo_count'),
    (N'has_uv_photos'), (N'has_thin_section_photos'), (N'row_created_by');

DECLARE @sql NVARCHAR(MAX);
DECLARE @col SYSNAME, @typedef NVARCHAR(200), @is_nullable BIT;

DECLARE cur CURSOR LOCAL FAST_FORWARD FOR
    SELECT c.name,
           t.name +
             CASE
               WHEN t.name IN ('varchar','char','varbinary','binary')
                    THEN '(' + CASE WHEN c.max_length = -1 THEN 'max'
                                    ELSE CONVERT(VARCHAR(10), c.max_length) END + ')'
               WHEN t.name IN ('nvarchar','nchar')
                    THEN '(' + CASE WHEN c.max_length = -1 THEN 'max'
                                    ELSE CONVERT(VARCHAR(10), c.max_length / 2) END + ')'
               WHEN t.name IN ('decimal','numeric')
                    THEN '(' + CONVERT(VARCHAR(10), c.precision) + ',' +
                               CONVERT(VARCHAR(10), c.scale) + ')'
               WHEN t.name IN ('datetime2','time','datetimeoffset')
                    THEN '(' + CONVERT(VARCHAR(10), c.scale) + ')'
               ELSE ''
             END AS typedef,
           c.is_nullable
    FROM   sys.columns c
    JOIN   sys.tables  tb ON tb.object_id    = c.object_id
    JOIN   sys.schemas s  ON s.schema_id      = tb.schema_id
    JOIN   sys.types   t  ON t.user_type_id   = c.user_type_id
    WHERE  s.name = @schema AND tb.name = @table
      AND  c.name IN (SELECT name FROM @cols);

OPEN cur;
FETCH NEXT FROM cur INTO @col, @typedef, @is_nullable;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF @is_nullable = 0
    BEGIN
        SET @sql = N'ALTER TABLE ' + QUOTENAME(@schema) + N'.' + QUOTENAME(@table)
                 + N' ALTER COLUMN ' + QUOTENAME(@col) + N' ' + @typedef + N' NULL;';
        PRINT @sql;
        IF @Apply = 1 EXEC sys.sp_executesql @sql;
    END
    ELSE
        PRINT '-- ' + @col + ' already nullable, skipped';

    FETCH NEXT FROM cur INTO @col, @typedef, @is_nullable;
END
CLOSE cur;
DEALLOCATE cur;

/* row_created_by default -- only if the column exists and has no default yet. */
IF EXISTS (SELECT 1
           FROM sys.columns c
           JOIN sys.tables  tb ON tb.object_id = c.object_id
           JOIN sys.schemas s  ON s.schema_id   = tb.schema_id
           WHERE s.name = @schema AND tb.name = @table AND c.name = 'row_created_by')
   AND NOT EXISTS (SELECT 1
                   FROM sys.default_constraints dc
                   JOIN sys.columns c ON c.object_id = dc.parent_object_id
                                     AND c.column_id = dc.parent_column_id
                   JOIN sys.tables  tb ON tb.object_id = c.object_id
                   JOIN sys.schemas s  ON s.schema_id   = tb.schema_id
                   WHERE s.name = @schema AND tb.name = @table
                     AND c.name = 'row_created_by')
BEGIN
    SET @sql = N'ALTER TABLE ' + QUOTENAME(@schema) + N'.' + QUOTENAME(@table)
             + N' ADD CONSTRAINT DF_dv_well_core_rcb '
             + N'DEFAULT (''DV_TABLE_LOADER'') FOR row_created_by;';
    PRINT @sql;
    IF @Apply = 1 EXEC sys.sp_executesql @sql;
END
ELSE
    PRINT '-- row_created_by default already present (or column missing), skipped';

PRINT '';
PRINT CASE WHEN @Apply = 1
           THEN '== Applied. Click "Refresh schema" in the Mapping Studio. =='
           ELSE '== Preview only (@Apply = 0). Set @Apply = 1 and re-run to apply. ==' END;

/* ============================================================================
   catalog_provenance.sql
   ----------------------------------------------------------------------------
   Show what was populated in dv_* FROM the file catalog. Promote stamps every
   row it lifts with source = 'CATALOG' (header + detail), so that is the single
   discriminator — bulk / hand-loaded rows keep their own source code.

   Three result sets:
     1) per-table summary  — catalog rows + distinct wells, by dv_* table
     2) per-well breakdown — for each catalog well, rows per child table
     3) well -> source file — traced via child tables that carry INVENTORY_ID
                              (dv_well itself has no INVENTORY_ID column)

   Run in SSMS, or:
     sqlcmd -S PERRY\SQLEXPRESS -d DataView -E -i catalog_provenance.sql
   ============================================================================ */
SET NOCOUNT ON;

/* dataview tables that carry a `source` column = the promote targets, noting
   which also have UWI and INVENTORY_ID columns */
IF OBJECT_ID('tempdb..#cat') IS NOT NULL DROP TABLE #cat;
SELECT t.name AS tbl,
       MAX(CASE WHEN c.name = 'UWI'          THEN 1 ELSE 0 END) AS has_uwi,
       MAX(CASE WHEN c.name = 'INVENTORY_ID' THEN 1 ELSE 0 END) AS has_inv
INTO #cat
FROM sys.tables t
JOIN sys.schemas s ON s.schema_id = t.schema_id AND s.name = 'dataview'
JOIN sys.columns c ON c.object_id = t.object_id
WHERE EXISTS (SELECT 1 FROM sys.columns sc
              WHERE sc.object_id = t.object_id AND sc.name = 'source')
GROUP BY t.name;

DECLARE @sql NVARCHAR(MAX);

/* ---- 1) catalog rows per table ---------------------------------------- */
SET @sql = N'';
SELECT @sql = @sql
     + CASE WHEN @sql = N'' THEN N'' ELSE N' UNION ALL ' END
     + N'SELECT ''' + tbl + N''' AS dv_table, COUNT(*) AS catalog_rows, '
     + CASE WHEN has_uwi = 1 THEN N'COUNT(DISTINCT UWI)'
            ELSE N'CAST(NULL AS INT)' END + N' AS wells '
     + N'FROM dataview.' + QUOTENAME(tbl) + N' WHERE source = ''CATALOG'''
FROM #cat;
SET @sql = N'SELECT * FROM (' + @sql
         + N') x WHERE catalog_rows > 0 ORDER BY catalog_rows DESC';
PRINT '--- 1) catalog rows per dv_* table ---';
EXEC sys.sp_executesql @sql;

/* ---- 2) per-well breakdown (tables that carry UWI) -------------------- */
SET @sql = N'';
SELECT @sql = @sql
     + CASE WHEN @sql = N'' THEN N'' ELSE N' UNION ALL ' END
     + N'SELECT UWI, ''' + tbl + N''' AS dv_table, COUNT(*) AS row_count '
     + N'FROM dataview.' + QUOTENAME(tbl)
     + N' WHERE source = ''CATALOG'' GROUP BY UWI'
FROM #cat WHERE has_uwi = 1;
IF @sql = N''
    PRINT '--- 2) skipped: no catalog table carries UWI ---';
ELSE
BEGIN
    SET @sql = N'SELECT w.UWI, w.well_name, b.dv_table, b.row_count '
             + N'FROM (' + @sql + N') b '
             + N'LEFT JOIN dataview.dv_well w ON w.UWI = b.UWI '
             + N'ORDER BY w.well_name, b.dv_table';
    PRINT '--- 2) per-well child rows from the catalog ---';
    EXEC sys.sp_executesql @sql;
END

/* ---- 3) well -> source file via children carrying INVENTORY_ID -------- */
SET @sql = N'';
SELECT @sql = @sql
     + CASE WHEN @sql = N'' THEN N'' ELSE N' UNION ALL ' END
     + N'SELECT DISTINCT UWI, INVENTORY_ID FROM dataview.' + QUOTENAME(tbl)
     + N' WHERE source = ''CATALOG'' AND INVENTORY_ID IS NOT NULL'
FROM #cat WHERE has_uwi = 1 AND has_inv = 1;
IF @sql = N''
    PRINT '--- 3) skipped: no catalog table carries both UWI and INVENTORY_ID ---';
ELSE
BEGIN
    SET @sql = N'SELECT DISTINCT w.UWI, w.well_name, g.FILE_NAME, g.FILE_PATH '
             + N'FROM (' + @sql + N') b '
             + N'LEFT JOIN dataview.dv_well w ON w.UWI = b.UWI '
             + N'LEFT JOIN file_catalog.GLOBAL_FILE_CATALOG g '
             + N'       ON g.INVENTORY_ID = b.INVENTORY_ID '
             + N'ORDER BY w.well_name';
    PRINT '--- 3) catalog wells traced to their source document ---';
    EXEC sys.sp_executesql @sql;
END

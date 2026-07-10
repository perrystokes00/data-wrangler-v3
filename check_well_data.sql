/* =====================================================================
   check_well_data.sql — what data does a given well have?
   Self-checking: builds the UNION dynamically from tables that ACTUALLY
   exist in the dataview schema and have a 'uwi' column, so it can't fail
   on a table-name mismatch. One row per domain: count + YES/no.
   Run in SSMS against DataView_Demo. Change @uwi to check another well.
   ===================================================================== */
USE DataView_Demo;
GO
SET NOCOUNT ON;

DECLARE @uwi char(14) = '42317123450000';

/* domains we care about: table -> friendly label */
DECLARE @dom TABLE (tbl sysname, label nvarchar(60), ord int);
INSERT INTO @dom (tbl, label, ord) VALUES
 ('dv_well',                 'the well record',        0),
 ('dv_well_formation_top',   'formation tops',         1),
 ('dv_well_dir_srvy_hdr',    'directional survey hdr', 2),
 ('dv_well_dir_srvy_sta',    'directional survey sta', 3),
 ('dv_well_completion',      'completions',            4),
 ('dv_well_dst',             'DST',                    5),
 ('dv_well_core',            'core',                   6),
 ('dv_well_core_sample',     'core samples',           7),
 ('dv_well_petro_interp',    'petro interpretation',   8),
 ('dv_well_petro_zone',      'petro zones',            9),
 ('dv_well_stimulation',     'stimulation',           10),
 ('dv_well_log',             'logs',                  11),
 ('dv_well_log_curve',       'log curves',            12),
 ('dv_prod_entity',          'production entity',     13),
 ('dv_prod_volume',          'production volumes',    14);

DECLARE @sql nvarchar(max) = N'';

SELECT @sql = @sql +
  CASE WHEN @sql = N'' THEN N'' ELSE N' UNION ALL ' END +
  N'SELECT ' + QUOTENAME(d.label, '''') + N' AS data_domain, ' +
  CAST(d.ord AS nvarchar(10)) + N' AS ord, COUNT(*) AS row_count, ' +
  N'CASE WHEN COUNT(*)>0 THEN ''YES'' ELSE ''no'' END AS has_data ' +
  N'FROM dataview.' + QUOTENAME(d.tbl) +
  N' WHERE uwi = @uwi'
FROM @dom d
JOIN INFORMATION_SCHEMA.COLUMNS c
  ON c.TABLE_SCHEMA = 'dataview' AND c.TABLE_NAME = d.tbl
 AND c.COLUMN_NAME = 'uwi';

/* documents live in file_catalog.GLOBAL_FILE_CATALOG, keyed by UWI14 */
IF EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
           WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='GLOBAL_FILE_CATALOG'
             AND COLUMN_NAME='UWI14')
    SET @sql = @sql + N' UNION ALL SELECT ''catalogued documents'', 15, COUNT(*), ' +
        N'CASE WHEN COUNT(*)>0 THEN ''YES'' ELSE ''no'' END ' +
        N'FROM file_catalog.GLOBAL_FILE_CATALOG ' +
        N'WHERE UWI14 = @uwi AND ISNULL(FLAG_DELETE,''N'') <> ''Y''';

SET @sql = N'SELECT data_domain, row_count, has_data FROM ( ' + @sql +
           N' ) q ORDER BY CASE has_data WHEN ''YES'' THEN 0 ELSE 1 END, ord;';

EXEC sp_executesql @sql, N'@uwi char(14)', @uwi = @uwi;
GO

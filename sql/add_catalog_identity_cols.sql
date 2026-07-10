/*  add_catalog_identity_cols.sql — run in SSMS against DataView_Demo.
    Gives GLOBAL_FILE_CATALOG the identity columns so it is directly queryable:
        SELECT * FROM file_catalog.GLOBAL_FILE_CATALOG WHERE UWI14 = '...';
        SELECT * FROM file_catalog.GLOBAL_FILE_CATALOG WHERE SURVEY_NAME = '...';
    Idempotent — safe to re-run. GO separators are required so each column
    exists before the index batch that references it compiles.                */

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = 'file_catalog'
                 AND TABLE_NAME   = 'GLOBAL_FILE_CATALOG'
                 AND COLUMN_NAME  = 'UWI14')
    ALTER TABLE file_catalog.GLOBAL_FILE_CATALOG ADD UWI14 char(14) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = 'file_catalog'
                 AND TABLE_NAME   = 'GLOBAL_FILE_CATALOG'
                 AND COLUMN_NAME  = 'SURVEY_NAME')
    ALTER TABLE file_catalog.GLOBAL_FILE_CATALOG ADD SURVEY_NAME nvarchar(255) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes i
               JOIN sys.objects o ON o.object_id = i.object_id
               WHERE i.name = 'IX_GFC_UWI14' AND o.name = 'GLOBAL_FILE_CATALOG')
    CREATE INDEX IX_GFC_UWI14
        ON file_catalog.GLOBAL_FILE_CATALOG(UWI14);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes i
               JOIN sys.objects o ON o.object_id = i.object_id
               WHERE i.name = 'IX_GFC_SURVEY' AND o.name = 'GLOBAL_FILE_CATALOG')
    CREATE INDEX IX_GFC_SURVEY
        ON file_catalog.GLOBAL_FILE_CATALOG(SURVEY_NAME);
GO

/* verify */
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'file_catalog'
  AND TABLE_NAME   = 'GLOBAL_FILE_CATALOG'
  AND COLUMN_NAME IN ('UWI14', 'SURVEY_NAME');

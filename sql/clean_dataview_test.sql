USE DataView_Test;
GO

-- Disable all FK constraints in dataview schema
EXEC sp_MSforeachtable
    @command1 = 'ALTER TABLE ? NOCHECK CONSTRAINT ALL',
    @whereand = 'AND SCHEMA_NAME(schema_id) = ''dataview''';

-- Clear data tables
DELETE FROM dataview.dv_well;
DELETE FROM dataview.dv_business_associate;
DELETE FROM dataview.dv_field;

-- Clear staging
IF OBJECT_ID('dataview.dv_stg_well', 'U') IS NOT NULL
    TRUNCATE TABLE dataview.dv_stg_well;

-- Re-enable FK constraints
EXEC sp_MSforeachtable
    @command1 = 'ALTER TABLE ? WITH CHECK CHECK CONSTRAINT ALL',
    @whereand = 'AND SCHEMA_NAME(schema_id) = ''dataview''';

-- Verify
SELECT 'dv_well'               AS tbl, COUNT(*) AS n FROM dataview.dv_well
UNION ALL
SELECT 'dv_business_associate',         COUNT(*) FROM dataview.dv_business_associate
UNION ALL
SELECT 'dv_field',                      COUNT(*) FROM dataview.dv_field;

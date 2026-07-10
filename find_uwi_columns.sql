/* find_uwi_columns.sql — what is the UWI column ACTUALLY called in each dv_* table?
   Some tables may use uwi, UWI, uwi14, well_id, etc. Run this first, then we build
   the check against the real names. */
USE DataView_Demo;
GO
SELECT c.TABLE_NAME,
       c.COLUMN_NAME,
       c.DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE c.TABLE_SCHEMA = 'dataview'
  AND (c.COLUMN_NAME LIKE '%uwi%' OR c.COLUMN_NAME LIKE '%well_id%'
       OR c.COLUMN_NAME = 'well')
  AND c.TABLE_NAME LIKE 'dv_%'
ORDER BY c.TABLE_NAME, c.COLUMN_NAME;
GO

/* ============================================================================
   diag_las_inv.sql  --  why does INVENTORY_ID resolution miss for deep logs?
   Run:  sqlcmd -S PERRY\SQLEXPRESS -d DataView -E -i diag_las_inv.sql -W -s "|"
   Paste the whole output back.
   ========================================================================== */
SET NOCOUNT ON;

PRINT '=== 1. las_catalog file names (FILE_NAME as stored) ===';
SELECT TOP 5 'LAS'  AS fmt, FILE_NAME FROM las_catalog.LAS_FILE
UNION ALL SELECT TOP 5 'DLIS', FILE_NAME FROM las_catalog.DLIS_FILE
UNION ALL SELECT TOP 5 'LIS',  FILE_NAME FROM las_catalog.LIS_FILE;

PRINT '';
PRINT '=== 2. GLOBAL_FILE_CATALOG paths for deep formats ===';
SELECT TOP 8 INVENTORY_ID, FILE_NAME, FILE_PATH
FROM file_catalog.GLOBAL_FILE_CATALOG
WHERE FILE_EXT IN ('.las','.dlis','.dlf','.dis','.lis')
   OR LOWER(RIGHT(FILE_NAME,4)) IN ('.las','.lis')
   OR LOWER(RIGHT(FILE_NAME,5)) = '.dlis';

PRINT '';
PRINT '=== 3. match-count by strategy (LAS_FILE as probe) ===';
SELECT
  (SELECT COUNT(*) FROM las_catalog.LAS_FILE) AS las_files,
  -- a) current: full path ENDS WITH stored rel name
  (SELECT COUNT(*) FROM las_catalog.LAS_FILE f
     WHERE EXISTS (SELECT 1 FROM file_catalog.GLOBAL_FILE_CATALOG g
                    WHERE g.FILE_PATH LIKE '%' + f.FILE_NAME)) AS suffix_match,
  -- b) basename equality (strip any dir, both slash styles)
  (SELECT COUNT(*) FROM las_catalog.LAS_FILE f
     WHERE EXISTS (SELECT 1 FROM file_catalog.GLOBAL_FILE_CATALOG g
                    WHERE g.FILE_NAME =
                      RIGHT(REPLACE(f.FILE_NAME,'/','\'),
                            CHARINDEX('\', REVERSE(REPLACE(f.FILE_NAME,'/','\')) + '\') - 1))) AS basename_match,
  -- c) via WL_FILE_UWI_MAP full path -> GLOBAL
  (SELECT COUNT(*) FROM las_catalog.LAS_FILE f
     WHERE EXISTS (SELECT 1 FROM las_catalog.WL_FILE_UWI_MAP m
                    JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.FILE_PATH = m.FILE_PATH
                    WHERE m.FILE_NAME = f.FILE_NAME)) AS via_uwimap;

PRINT '';
PRINT '=== 4. WL_FILE_UWI_MAP sample (does it carry full paths?) ===';
SELECT TOP 5 FILE_FORMAT, FILE_NAME, FILE_PATH, UWI
FROM las_catalog.WL_FILE_UWI_MAP;

PRINT '';
PRINT '=== 5. do the deep UWIs exist in dv_well? ===';
SELECT
  (SELECT COUNT(DISTINCT UWI) FROM las_catalog.LAS_FILE)  AS las_uwis,
  (SELECT COUNT(DISTINCT f.UWI) FROM las_catalog.LAS_FILE f
     WHERE EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi = f.UWI)) AS las_uwis_in_dvwell;

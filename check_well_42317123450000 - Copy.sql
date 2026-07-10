/* =====================================================================
   check_well_42317123450000.sql
   What data does well 42317123450000 have? One row per data domain with
   a count and a YES/no flag. Run in SSMS against DataView_Demo (or set
   the DB in the USE line). Change @uwi to check a different well.
   ===================================================================== */
USE DataView_Demo;
GO
SET NOCOUNT ON;

DECLARE @uwi char(14) = '42317123450000';

/* ---- 1) does the well itself exist in dv_well? ---- */
SELECT
    'dv_well (the well record)' AS data_domain,
    COUNT(*)                    AS row_count,
    CASE WHEN COUNT(*) > 0 THEN 'YES' ELSE 'no' END AS has_data
FROM dataview.dv_well
WHERE uwi = @uwi

UNION ALL SELECT 'formation tops',        COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_formation_top   WHERE uwi = @uwi
UNION ALL SELECT 'directional survey hdr', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_dir_srvy_hdr    WHERE uwi = @uwi
UNION ALL SELECT 'directional survey sta', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_dir_srvy_sta    WHERE uwi = @uwi
UNION ALL SELECT 'completions',           COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_completion      WHERE uwi = @uwi
UNION ALL SELECT 'DST',                   COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_dst             WHERE uwi = @uwi
UNION ALL SELECT 'core',                  COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_core            WHERE uwi = @uwi
UNION ALL SELECT 'core samples',          COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_core_sample     WHERE uwi = @uwi
UNION ALL SELECT 'petro interpretation',  COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_petro_interp    WHERE uwi = @uwi
UNION ALL SELECT 'petro zones',           COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_petro_zone      WHERE uwi = @uwi
UNION ALL SELECT 'stimulation',           COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_stimulation     WHERE uwi = @uwi
UNION ALL SELECT 'logs',                  COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_log             WHERE uwi = @uwi
UNION ALL SELECT 'log curves',            COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_well_log_curve       WHERE uwi = @uwi
UNION ALL SELECT 'production entity',     COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_prod_entity          WHERE uwi = @uwi
UNION ALL SELECT 'production volumes',    COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM dataview.dv_prod_volume          WHERE uwi = @uwi
UNION ALL SELECT 'catalogued documents', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
    FROM file_catalog.GLOBAL_FILE_CATALOG WHERE UWI14 = @uwi
                                            AND ISNULL(FLAG_DELETE,'N') <> 'Y'
ORDER BY has_data DESC, data_domain;
GO

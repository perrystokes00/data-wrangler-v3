USE DataView_Demo;
GO
SET NOCOUNT ON;
DECLARE @uwi char(14) = '42317123450000';

SELECT 'the well record' AS data_domain, COUNT(*) AS n,
       CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END AS has_data
  FROM dataview.dv_well WHERE uwi = @uwi
UNION ALL SELECT 'formation tops', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_formation_top WHERE uwi = @uwi
UNION ALL SELECT 'strat intervals', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_strat_interval WHERE uwi = @uwi
UNION ALL SELECT 'directional survey hdr', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_dir_srvy_hdr WHERE uwi = @uwi
UNION ALL SELECT 'directional survey sta', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_dir_srvy_sta WHERE uwi = @uwi
UNION ALL SELECT 'completions', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_completion WHERE uwi = @uwi
UNION ALL SELECT 'casing', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_casing WHERE uwi = @uwi
UNION ALL SELECT 'perforations', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_perforation WHERE uwi = @uwi
UNION ALL SELECT 'DST', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_dst WHERE uwi = @uwi
UNION ALL SELECT 'DST periods', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_dst_period WHERE uwi = @uwi
UNION ALL SELECT 'core', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_core WHERE uwi = @uwi
UNION ALL SELECT 'core samples', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_core_sample WHERE uwi = @uwi
UNION ALL SELECT 'core photos', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_core_photo WHERE uwi = @uwi
UNION ALL SELECT 'petro interpretation', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_petro_interp WHERE uwi = @uwi
UNION ALL SELECT 'petro zones', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_petro_zone WHERE uwi = @uwi
UNION ALL SELECT 'stimulation', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_stimulation WHERE uwi = @uwi
UNION ALL SELECT 'shows', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_shows WHERE uwi = @uwi
UNION ALL SELECT 'pressure', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_pressure WHERE uwi = @uwi
UNION ALL SELECT 'mud log', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_mud_log WHERE uwi = @uwi
UNION ALL SELECT 'logs', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_log WHERE uwi = @uwi
UNION ALL SELECT 'log curves', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_log_curve WHERE uwi = @uwi
UNION ALL SELECT 'production entity', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_prod_entity WHERE uwi = @uwi
UNION ALL SELECT 'well aliases', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_alias WHERE uwi = @uwi
UNION ALL SELECT 'well legal', COUNT(*), CASE WHEN COUNT(*)>0 THEN 'YES' ELSE 'no' END
  FROM dataview.dv_well_legal WHERE uwi = @uwi
ORDER BY has_data DESC, data_domain;
GO

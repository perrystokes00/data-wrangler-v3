@echo off
setlocal
set OUTDIR=C:\Bulk\snowflake_export
set SERVER=127.0.0.1\SQLEXPRESS

if not exist "%OUTDIR%" mkdir "%OUTDIR%"

echo ── North Dakota NDIC ──────────────────────────────
echo uwi,api_num,well_name,operator_name,field_name,surface_latitude,surface_longitude,county,province_state,well_status,well_type,spud_date,completion_date,final_td,source,area> "%OUTDIR%\raw_nd_well.csv"
bcp "SELECT CAST(uwi AS VARCHAR(14)), ISNULL(api_num,''), ISNULL(REPLACE(well_name,',',''),''), ISNULL(REPLACE(operator_name,',',''),''), ISNULL(REPLACE(field_name,',',''),''), CAST(surface_latitude AS VARCHAR(20)), CAST(surface_longitude AS VARCHAR(20)), ISNULL(county,''), ISNULL(province_state,''), ISNULL(well_status,''), ISNULL(well_type,''), ISNULL(CONVERT(VARCHAR(10), spud_date, 120),''), ISNULL(CONVERT(VARCHAR(10), completion_date, 120),''), ISNULL(CAST(final_td AS VARCHAR(20)),''), source, ISNULL(area,'') FROM DataView.dataview.dv_well WHERE source = 'NDIC'" queryout "%OUTDIR%\raw_nd_data.tmp" -c -t"," -T -S "%SERVER%"
type "%OUTDIR%\raw_nd_data.tmp" >> "%OUTDIR%\raw_nd_well.csv"
del "%OUTDIR%\raw_nd_data.tmp"

echo ── OSDU ──────────────────────────────
echo uwi,api_num,well_name,operator_name,field_name,surface_latitude,surface_longitude,county,province_state,well_status,well_type,spud_date,completion_date,final_td,source,area> "%OUTDIR%\raw_osdu_well.csv"
bcp "SELECT CAST(uwi AS VARCHAR(14)), ISNULL(api_num,''), ISNULL(REPLACE(well_name,',',''),''), ISNULL(REPLACE(operator_name,',',''),''), ISNULL(REPLACE(field_name,',',''),''), CAST(surface_latitude AS VARCHAR(20)), CAST(surface_longitude AS VARCHAR(20)), ISNULL(county,''), ISNULL(province_state,''), ISNULL(well_status,''), ISNULL(well_type,''), ISNULL(CONVERT(VARCHAR(10), spud_date, 120),''), ISNULL(CONVERT(VARCHAR(10), completion_date, 120),''), ISNULL(CAST(final_td AS VARCHAR(20)),''), source, ISNULL(area,'') FROM DataView.dataview.dv_well WHERE source = 'OSDU'" queryout "%OUTDIR%\raw_osdu_data.tmp" -c -t"," -T -S "%SERVER%"
type "%OUTDIR%\raw_osdu_data.tmp" >> "%OUTDIR%\raw_osdu_well.csv"
del "%OUTDIR%\raw_osdu_data.tmp"

echo ── Kansas KGS ──────────────────────────────
echo uwi,api_num,well_name,operator_name,field_name,surface_latitude,surface_longitude,county,province_state,well_status,well_type,spud_date,completion_date,final_td,source,area> "%OUTDIR%\raw_ks_well.csv"
bcp "SELECT CAST(uwi AS VARCHAR(14)), ISNULL(api_num,''), ISNULL(REPLACE(well_name,',',''),''), ISNULL(REPLACE(operator_name,',',''),''), ISNULL(REPLACE(field_name,',',''),''), CAST(surface_latitude AS VARCHAR(20)), CAST(surface_longitude AS VARCHAR(20)), ISNULL(county,''), ISNULL(province_state,''), ISNULL(well_status,''), ISNULL(well_type,''), ISNULL(CONVERT(VARCHAR(10), spud_date, 120),''), ISNULL(CONVERT(VARCHAR(10), completion_date, 120),''), ISNULL(CAST(final_td AS VARCHAR(20)),''), source, ISNULL(area,'') FROM DataView.dataview.dv_well WHERE source = 'KGS_GEOJSON'" queryout "%OUTDIR%\raw_ks_data.tmp" -c -t"," -T -S "%SERVER%"
type "%OUTDIR%\raw_ks_data.tmp" >> "%OUTDIR%\raw_ks_well.csv"
del "%OUTDIR%\raw_ks_data.tmp"

echo ── Texas RRC ──────────────────────────────
echo uwi,api_num,well_name,operator_name,field_name,surface_latitude,surface_longitude,county,province_state,well_status,well_type,spud_date,completion_date,final_td,source,area> "%OUTDIR%\raw_tx_well.csv"
bcp "SELECT CAST(uwi AS VARCHAR(14)), ISNULL(api_num,''), ISNULL(REPLACE(well_name,',',''),''), ISNULL(REPLACE(operator_name,',',''),''), ISNULL(REPLACE(field_name,',',''),''), CAST(surface_latitude AS VARCHAR(20)), CAST(surface_longitude AS VARCHAR(20)), ISNULL(county,''), ISNULL(province_state,''), ISNULL(well_status,''), ISNULL(well_type,''), ISNULL(CONVERT(VARCHAR(10), spud_date, 120),''), ISNULL(CONVERT(VARCHAR(10), completion_date, 120),''), ISNULL(CAST(final_td AS VARCHAR(20)),''), source, ISNULL(area,'') FROM DataView.dataview.dv_well WHERE source = 'RRC_TX_SHP' AND surface_latitude IS NOT NULL" queryout "%OUTDIR%\raw_tx_data.tmp" -c -t"," -T -S "%SERVER%"
type "%OUTDIR%\raw_tx_data.tmp" >> "%OUTDIR%\raw_tx_well.csv"
del "%OUTDIR%\raw_tx_data.tmp"

echo ── BOEM GOM ──────────────────────────────
echo well_id,api_well_number,well_name,company_name,region,bottom_area_code,bottom_block_number,surface_latitude,surface_longitude,bottom_latitude,bottom_longitude,bh_total_md_ft,true_vertical_depth_ft,spud_date,status_code,type_code,water_depth_ft> "%OUTDIR%\raw_boem_well.csv"
bcp "SELECT CONVERT(VARCHAR(36), well_id), ISNULL(api_well_number,''), ISNULL(REPLACE(well_name,',',''),''), ISNULL(REPLACE(company_name,',',''),''), ISNULL(region,''), ISNULL(bottom_area_code,''), ISNULL(bottom_block_number,''), CAST(surface_latitude AS VARCHAR(20)), CAST(surface_longitude AS VARCHAR(20)), ISNULL(CAST(bottom_latitude AS VARCHAR(20)),''), ISNULL(CAST(bottom_longitude AS VARCHAR(20)),''), ISNULL(CAST(bh_total_md_ft AS VARCHAR(20)),''), ISNULL(CAST(true_vertical_depth_ft AS VARCHAR(20)),''), ISNULL(CONVERT(VARCHAR(10), spud_date, 120),''), ISNULL(status_code,''), ISNULL(type_code,''), ISNULL(CAST(water_depth_ft AS VARCHAR(20)),'') FROM DataView.dataview_gom.well WHERE surface_latitude IS NOT NULL" queryout "%OUTDIR%\raw_boem_data.tmp" -c -t"," -T -S "%SERVER%"
type "%OUTDIR%\raw_boem_data.tmp" >> "%OUTDIR%\raw_boem_well.csv"
del "%OUTDIR%\raw_boem_data.tmp"

echo.
echo ── Done ──────────────────────────────
dir "%OUTDIR%\*.csv"

/* =====================================================================
   profile_well_master.sql   —  READ-ONLY assessment of WELL_MASTER
   Run in SSMS connected anywhere (table is fully qualified). Nothing is
   written. Each grid answers one question about the mess so we can decide
   clean-in-place vs reload, and find what's already good.
   ===================================================================== */
DECLARE @T NVARCHAR(200) = 'WELL_REF.well_ref.WELL_MASTER';   -- (for reference)

/* 1) Scale & freshness */
SELECT total_rows = COUNT(*),
       distinct_ref_id = COUNT(DISTINCT REF_ID),
       loaded_min = MIN(LOADED_AT),
       loaded_max = MAX(LOADED_AT)
FROM WELL_REF.well_ref.WELL_MASTER;

/* 2) Source mix (top 30 distinct SOURCE_LIST values) */
SELECT TOP 30 SOURCE_LIST, rows = COUNT(*)
FROM WELL_REF.well_ref.WELL_MASTER
GROUP BY SOURCE_LIST
ORDER BY COUNT(*) DESC;

/* 3) Identity quality */
SELECT
  rows            = COUNT(*),
  api10_blank     = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(API_10)),'') IS NULL THEN 1 ELSE 0 END),
  api10_is_10dig  = SUM(CASE WHEN API_10 LIKE '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]' THEN 1 ELSE 0 END),
  uwi_suspect     = SUM(CASE WHEN UWI_SUSPECT = 1 THEN 1 ELSE 0 END),
  uwi14_blank     = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(UWI14)),'') IS NULL THEN 1 ELSE 0 END)
FROM WELL_REF.well_ref.WELL_MASTER;

/* 4) Duplication on API_10 (only clean 10-digit values) */
SELECT
  rows_with_valid_api10 = COUNT(*),
  distinct_api10        = COUNT(DISTINCT API_10),
  duplicate_excess_rows = COUNT(*) - COUNT(DISTINCT API_10)
FROM WELL_REF.well_ref.WELL_MASTER
WHERE API_10 LIKE '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]';

/* 4b) Worst dup clusters (same API_10 appearing many times) */
SELECT TOP 20 API_10, copies = COUNT(*)
FROM WELL_REF.well_ref.WELL_MASTER
WHERE API_10 LIKE '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'
GROUP BY API_10
HAVING COUNT(*) > 1
ORDER BY COUNT(*) DESC;

/* 5) Standardization — PROVINCE_STATE variants (should be 2-letter) */
SELECT TOP 40 PROVINCE_STATE, rows = COUNT(*)
FROM WELL_REF.well_ref.WELL_MASTER
GROUP BY PROVINCE_STATE
ORDER BY COUNT(*) DESC;

/* 5b) COUNTRY variants */
SELECT COUNTRY, rows = COUNT(*)
FROM WELL_REF.well_ref.WELL_MASTER
GROUP BY COUNTRY
ORDER BY COUNT(*) DESC;

/* 5c) WELL_TYPE raw values + how many already have STD_WELL_TYPE */
SELECT TOP 40 WELL_TYPE, rows = COUNT(*),
       std_filled = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(STD_WELL_TYPE)),'') IS NOT NULL THEN 1 ELSE 0 END)
FROM WELL_REF.well_ref.WELL_MASTER
GROUP BY WELL_TYPE
ORDER BY COUNT(*) DESC;

/* 5d) WELL_STATUS raw values + how many already have STD_WELL_STATUS */
SELECT TOP 40 WELL_STATUS, rows = COUNT(*),
       std_filled = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(STD_WELL_STATUS)),'') IS NOT NULL THEN 1 ELSE 0 END)
FROM WELL_REF.well_ref.WELL_MASTER
GROUP BY WELL_STATUS
ORDER BY COUNT(*) DESC;

/* 6) Coordinate quality */
SELECT
  null_coord      = SUM(CASE WHEN SURFACE_LATITUDE IS NULL OR SURFACE_LONGITUDE IS NULL THEN 1 ELSE 0 END),
  zero_coord      = SUM(CASE WHEN SURFACE_LATITUDE = 0 AND SURFACE_LONGITUDE = 0 THEN 1 ELSE 0 END),
  out_of_range    = SUM(CASE WHEN SURFACE_LATITUDE NOT BETWEEN -90 AND 90
                              OR SURFACE_LONGITUDE NOT BETWEEN -180 AND 180 THEN 1 ELSE 0 END),
  us_implausible  = SUM(CASE WHEN SURFACE_LATITUDE NOT BETWEEN 18 AND 72
                              OR SURFACE_LONGITUDE NOT BETWEEN -180 AND -64 THEN 1 ELSE 0 END)
FROM WELL_REF.well_ref.WELL_MASTER;

/* 7) Completeness — blank rate per key attribute */
SELECT
  rows         = COUNT(*),
  no_well_name = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(WELL_NAME)),'')     IS NULL THEN 1 ELSE 0 END),
  no_operator  = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(OPERATOR_NAME)),'') IS NULL THEN 1 ELSE 0 END),
  no_field     = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(FIELD_NAME)),'')    IS NULL THEN 1 ELSE 0 END),
  no_county    = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(COUNTY)),'')        IS NULL THEN 1 ELSE 0 END),
  no_type      = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(WELL_TYPE)),'')     IS NULL THEN 1 ELSE 0 END),
  no_status    = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(WELL_STATUS)),'')   IS NULL THEN 1 ELSE 0 END),
  no_td        = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(TOTAL_DEPTH)),'')   IS NULL THEN 1 ELSE 0 END),
  no_spud      = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(SPUD_DATE)),'')     IS NULL THEN 1 ELSE 0 END),
  no_latlon    = SUM(CASE WHEN SURFACE_LATITUDE IS NULL OR SURFACE_LONGITUDE IS NULL THEN 1 ELSE 0 END)
FROM WELL_REF.well_ref.WELL_MASTER;

/* 8) Text-typed numerics that don't parse */
SELECT
  td_present       = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(TOTAL_DEPTH)),'') IS NOT NULL THEN 1 ELSE 0 END),
  td_nonnumeric    = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(TOTAL_DEPTH)),'') IS NOT NULL
                              AND TRY_CONVERT(decimal(18,3), TOTAL_DEPTH) IS NULL THEN 1 ELSE 0 END),
  spud_present     = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(SPUD_DATE)),'') IS NOT NULL THEN 1 ELSE 0 END),
  spud_unparseable = SUM(CASE WHEN NULLIF(LTRIM(RTRIM(SPUD_DATE)),'') IS NOT NULL
                              AND TRY_CONVERT(date, SPUD_DATE) IS NULL THEN 1 ELSE 0 END)
FROM WELL_REF.well_ref.WELL_MASTER;

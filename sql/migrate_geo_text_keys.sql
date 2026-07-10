/* ================================================================
   migrate_geo_text_keys.sql   ·   DataView v3
   Rekey geo reference tables on TEXT, not codes (Option 2).

     dv_province_state.province_state_id  ->  province_state_abbrev   ('TX')
     dv_county  ->  composite unique (province_state_id, county_name) ('TX','Harris')

   dv_well references become:
     province_state            -> dv_province_state.province_state_id   (single, abbrev)
     (county, province_state)  -> dv_county(county_name, province_state_id)  (COMPOSITE)

   FIPS / API codes are kept as attribute columns (no longer the key).
   Self-discovering: captures, drops, recreates every FK on the two
   tables; the dv_well->dv_county FK is rebuilt as a composite.
   Transactional + pre-flight. Ends PAUSED — review the result sets,
   then run COMMIT TRAN geo_rekey;  (or ROLLBACK TRAN geo_rekey;)
   ================================================================ */
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRAN geo_rekey;

/* ---- 0 · PRE-FLIGHT (THROW rolls back via XACT_ABORT) ------------- */

IF EXISTS (SELECT 1 FROM dataview.dv_province_state
           WHERE NULLIF(LTRIM(RTRIM(province_state_abbrev)),'') IS NULL)
BEGIN
    SELECT 'missing abbrev' AS problem, province_state_id, province_state_name
    FROM dataview.dv_province_state
    WHERE NULLIF(LTRIM(RTRIM(province_state_abbrev)),'') IS NULL;
    ;THROW 50001, 'dv_province_state rows missing province_state_abbrev — fill first.', 1;
END

IF EXISTS (SELECT 1 FROM dataview.dv_province_state
           GROUP BY country_code, UPPER(LTRIM(RTRIM(province_state_abbrev)))
           HAVING COUNT(*) > 1)
    ;THROW 50002, 'province_state_abbrev not unique within country_code.', 1;

IF EXISTS (SELECT 1 FROM dataview.dv_county c
           JOIN dataview.dv_province_state p ON p.province_state_id = c.province_state_id
           WHERE NULLIF(LTRIM(RTRIM(p.province_state_abbrev)),'') IS NULL)
    ;THROW 50003, 'Some counties reference a province_state with no abbrev.', 1;

IF EXISTS (
    SELECT 1 FROM dataview.dv_county c
    JOIN dataview.dv_province_state p ON p.province_state_id = c.province_state_id
    GROUP BY UPPER(LTRIM(RTRIM(p.province_state_abbrev))), LTRIM(RTRIM(c.county_name))
    HAVING COUNT(*) > 1)
BEGIN
    SELECT 'dup (state,county)' AS problem,
           UPPER(LTRIM(RTRIM(p.province_state_abbrev))) AS st,
           LTRIM(RTRIM(c.county_name)) AS county, COUNT(*) AS n
    FROM dataview.dv_county c
    JOIN dataview.dv_province_state p ON p.province_state_id = c.province_state_id
    GROUP BY UPPER(LTRIM(RTRIM(p.province_state_abbrev))), LTRIM(RTRIM(c.county_name))
    HAVING COUNT(*) > 1;
    ;THROW 50004, '(state, county_name) not unique — dedup dv_county first.', 1;
END

/* ---- 1 · CAPTURE every FK referencing the two tables -------------- */
IF OBJECT_ID('tempdb..#fk') IS NOT NULL DROP TABLE #fk;
SELECT
  fk.object_id,
  fk.name                       AS fk_name,
  ctab.name                     AS child_table,
  rtab.name                     AS ref_table,
  'ALTER TABLE ' + QUOTENAME(csch.name) + '.' + QUOTENAME(ctab.name)
     + ' DROP CONSTRAINT ' + QUOTENAME(fk.name) + ';'                 AS drop_sql,
  'ALTER TABLE ' + QUOTENAME(csch.name) + '.' + QUOTENAME(ctab.name)
     + ' ADD CONSTRAINT ' + QUOTENAME(fk.name) + ' FOREIGN KEY ('
     + STUFF((SELECT ',' + QUOTENAME(pc.name)
              FROM sys.foreign_key_columns k
              JOIN sys.columns pc ON pc.object_id=k.parent_object_id AND pc.column_id=k.parent_column_id
              WHERE k.constraint_object_id=fk.object_id ORDER BY k.constraint_column_id
              FOR XML PATH('')),1,1,'')
     + ') REFERENCES ' + QUOTENAME(rsch.name) + '.' + QUOTENAME(rtab.name) + '('
     + STUFF((SELECT ',' + QUOTENAME(rc.name)
              FROM sys.foreign_key_columns k
              JOIN sys.columns rc ON rc.object_id=k.referenced_object_id AND rc.column_id=k.referenced_column_id
              WHERE k.constraint_object_id=fk.object_id ORDER BY k.constraint_column_id
              FOR XML PATH('')),1,1,'')
     + ');'                                                           AS create_sql
INTO #fk
FROM sys.foreign_keys fk
JOIN sys.tables   ctab ON ctab.object_id = fk.parent_object_id
JOIN sys.schemas  csch ON csch.schema_id = ctab.schema_id
JOIN sys.tables   rtab ON rtab.object_id = fk.referenced_object_id
JOIN sys.schemas  rsch ON rsch.schema_id = rtab.schema_id
WHERE rsch.name='dataview' AND rtab.name IN ('dv_province_state','dv_county');

SELECT 'captured FK' AS info, fk_name, child_table, ref_table FROM #fk;

/* ---- 2 · DROP captured FKs (version-safe accumulation) ------------ */
DECLARE @sql NVARCHAR(MAX) = N'';
SELECT @sql = @sql + drop_sql + CHAR(10) FROM #fk;
IF LEN(@sql) > 0 EXEC sys.sp_executesql @sql;

/* ---- 3 · REKEY province_state -> abbrev --------------------------- */
-- child (county.province_state_id) first, while the old join still resolves
UPDATE c
   SET c.province_state_id = UPPER(LTRIM(RTRIM(p.province_state_abbrev)))
FROM dataview.dv_county c
JOIN dataview.dv_province_state p ON p.province_state_id = c.province_state_id;
-- then the parent PK
UPDATE dataview.dv_province_state
   SET province_state_id = UPPER(LTRIM(RTRIM(province_state_abbrev)));

/* ---- 4 · COUNTY composite key + widen dv_well.county to match ----- */
UPDATE dataview.dv_county SET county_name = LTRIM(RTRIM(county_name));

-- FK columns must match length: dv_well.county(40) -> match county_name(255)
ALTER TABLE dataview.dv_well ALTER COLUMN county nvarchar(255) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name='UQ_dv_county_state_name'
                 AND object_id=OBJECT_ID('dataview.dv_county'))
    ALTER TABLE dataview.dv_county
      ADD CONSTRAINT UQ_dv_county_state_name UNIQUE (province_state_id, county_name);

/* ---- 5 · RECREATE FKs --------------------------------------------- */
-- all captured FKs EXCEPT dv_well->dv_county (that one becomes composite)
SET @sql = N'';
SELECT @sql = @sql + create_sql + CHAR(10)
FROM #fk WHERE NOT (child_table='dv_well' AND ref_table='dv_county');
IF LEN(@sql) > 0 EXEC sys.sp_executesql @sql;

-- new composite well->county FK
IF EXISTS (SELECT 1 FROM #fk WHERE child_table='dv_well' AND ref_table='dv_county')
   AND NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name='FK_dv_well_county_state')
    ALTER TABLE dataview.dv_well
      ADD CONSTRAINT FK_dv_well_county_state
      FOREIGN KEY (county, province_state)
      REFERENCES dataview.dv_county (county_name, province_state_id);

/* ---- 6 · VERIFY (review, then COMMIT or ROLLBACK) ----------------- */
SELECT TOP 15 province_state_id, province_state_name, province_state_abbrev,
       api_state_code, fips_code
FROM dataview.dv_province_state ORDER BY province_state_id;

SELECT TOP 15 province_state_id, county_name, county_id, fips_full, api_county_code
FROM dataview.dv_county ORDER BY province_state_id, county_name;

SELECT COUNT(*) AS province_states FROM dataview.dv_province_state;
SELECT COUNT(*) AS counties        FROM dataview.dv_county;
SELECT name AS dv_well_fks FROM sys.foreign_keys
WHERE parent_object_id=OBJECT_ID('dataview.dv_well');

PRINT '================================================================';
PRINT ' Review the result sets above.';
PRINT '   If correct:  COMMIT TRAN geo_rekey;';
PRINT '   To undo:     ROLLBACK TRAN geo_rekey;';
PRINT '================================================================';
-- COMMIT TRAN geo_rekey;
-- ROLLBACK TRAN geo_rekey;

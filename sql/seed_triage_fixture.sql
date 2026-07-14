/* =====================================================================
   seed_triage_fixture.sql
   Fabricate catalog + header rows to test triage / backfill against the
   curated mini master (WELL_REF.well_ref.WELL_MASTER_MINI, is_anchor=1).

   Run while connected to DataView_Demo (targets are fully qualified anyway).
   All fixture rows are tagged ROOT_PATH = 'C:\FIXTURE' so they wipe cleanly:
       DELETE h FROM DataView_Demo.file_catalog.FILE_WELL_HEADER h
         JOIN DataView_Demo.file_catalog.GLOBAL_FILE_CATALOG g
              ON g.INVENTORY_ID = h.INVENTORY_ID
        WHERE g.ROOT_PATH = 'C:\FIXTURE';
       DELETE FROM DataView_Demo.file_catalog.GLOBAL_FILE_CATALOG
        WHERE ROOT_PATH = 'C:\FIXTURE';

   Six defect groups (NTILE over the 177 anchors), with the EXPECTED triage
   result for each:

   G1 BACKFILL   matched UWI present, attributes blank
                 -> triage backfills name/county/state/latlon/TD/spud/field
   G2 NORMALIZE  UWI written dashed '42-XXX-XXXXX', no matched UWI
                 -> triage normalizes -> resolves -> backfills
   G3 RESOLVE    no UWI at all; name + lat/lon present
                 -> triage resolves UWI by name/location, then backfills
   G4 QUARANTINE UWI = fake (county + 99999); name not in master
                 -> triage finds NO match, parks it, invents nothing
   G5 CONFLICT   matched UWI present, COUNTY deliberately wrong
                 -> triage applies precedence/scoring (corrects or flags)
   G6 CONTROL    fully populated from master
                 -> match, high tier, nothing to backfill (no-op)

   Operator is NOT a backfill target: the 177 anchors have no OPERATOR_NAME
   in the master, so nothing could be filled there.
   ===================================================================== */

SET NOCOUNT ON;

/* ---- 1) Anchors + per-row computed identity/grouping ---- */
IF OBJECT_ID('tempdb..#fx') IS NOT NULL DROP TABLE #fx;

SELECT
    seq        = ROW_NUMBER() OVER (ORDER BY m.API_10),
    grp        = NTILE(6)     OVER (ORDER BY m.API_10),
    api10      = m.API_10,
    uwi14      = m.API_10 + '0000',
    uwi_dashed = SUBSTRING(m.API_10,1,2) + '-' + SUBSTRING(m.API_10,3,3)
                 + '-' + SUBSTRING(m.API_10,6,5),
    uwi_fake   = LEFT(m.API_10,5) + '999990000',
    well_name  = m.WELL_NAME,
    well_field = m.FIELD_NAME,
    county     = m.COUNTY,
    lat        = m.SURFACE_LATITUDE,
    lon        = m.SURFACE_LONGITUDE,
    td         = TRY_CONVERT(decimal(18,5), m.TOTAL_DEPTH),
    spud       = m.SPUD_DATE,
    name_norm  = m.NAME_NORM
INTO #fx
FROM WELL_REF.well_ref.WELL_MASTER_MINI m
WHERE m.is_anchor = 1;

/* deterministic ids + file presentation (cycles ext to represent file types) */
ALTER TABLE #fx ADD
    inventory_id   AS UPPER(CONVERT(VARCHAR(40),
                       HASHBYTES('SHA1', CONCAT('FX|', uwi14, '|', grp, '|', seq)), 2)) PERSISTED,
    file_ext       AS (CHOOSE((seq % 5) + 1, '.las', '.json', '.pdf', '.segy', '.shp')) PERSISTED,
    file_grp       AS (CHOOSE((seq % 5) + 1, 'Well Log', 'OSDU / JSON Well Log',
                       'Scout / PDF', 'Seismic', 'Shapefile')) PERSISTED;
ALTER TABLE #fx ADD
    well_header_id AS UPPER(CONVERT(VARCHAR(32), HASHBYTES('MD5', inventory_id), 2)) PERSISTED,
    file_name      AS ('fx_' + uwi14 + file_ext) PERSISTED;

/* ---- 2) GLOBAL_FILE_CATALOG (inventory row per fixture file) ---- */
INSERT INTO DataView_Demo.file_catalog.GLOBAL_FILE_CATALOG
    (INVENTORY_ID, FILE_PATH, FILE_NAME, FILE_EXT, FILE_SIZE_KB, FILE_HASH,
     SCAN_DATE, ROOT_PATH, FILE_TYPE_GROUP, HEADER_EXTRACTED, FLAG_DELETE,
     ROW_CREATED_DATE, ROW_CHANGED_DATE, CATALOG_SCORE, CATALOG_READINESS,
     MATCHED_UWI, CATALOG_STATUS, VAULTED)
SELECT
    f.inventory_id,
    'C:\FIXTURE\' + f.file_name,
    f.file_name,
    f.file_ext,
    12.00,
    UPPER(CONVERT(VARCHAR(64), HASHBYTES('SHA2_256', f.inventory_id), 2)),
    SYSUTCDATETIME(),
    'C:\FIXTURE',
    f.file_grp,
    'Y',
    'N',
    SYSUTCDATETIME(),
    SYSUTCDATETIME(),
    80,
    'CATALOGED',
    CASE WHEN f.grp IN (1,5,6) THEN f.uwi14 ELSE NULL END,  -- pre-matched groups
    'UNCATALOGED',
    0
FROM #fx f;

/* ---- 3) FILE_WELL_HEADER (the extracted attributes triage reads/fills) ---- */
INSERT INTO DataView_Demo.file_catalog.FILE_WELL_HEADER
    (WELL_HEADER_ID, INVENTORY_ID, UWI, WELL_NAME, OPERATOR, WELL_FIELD,
     STATE, COUNTY, LATITUDE, LONGITUDE, TOTAL_DEPTH, SPUD_DATE,
     CONFIDENCE, EXTRACTED_DATE, EXTRACTED_BY, UWI14, IDENTITY_SOURCE, NAME_NORM)
SELECT
    f.well_header_id,
    f.inventory_id,
    /* UWI */            CASE f.grp WHEN 1 THEN f.uwi14
                                    WHEN 2 THEN f.uwi_dashed
                                    WHEN 3 THEN NULL
                                    WHEN 4 THEN f.uwi_fake
                                    WHEN 5 THEN f.uwi14
                                    WHEN 6 THEN f.uwi14 END,
    /* WELL_NAME */      CASE f.grp WHEN 1 THEN NULL
                                    WHEN 2 THEN NULL
                                    WHEN 3 THEN f.well_name
                                    WHEN 4 THEN 'FIXTURE NOMATCH ' + CAST(f.seq AS VARCHAR(10))
                                    WHEN 5 THEN f.well_name
                                    WHEN 6 THEN f.well_name END,
    /* OPERATOR */       NULL,
    /* WELL_FIELD */     CASE WHEN f.grp = 6 THEN f.well_field ELSE NULL END,
    /* STATE */          CASE WHEN f.grp IN (5,6) THEN 'TX' ELSE NULL END,
    /* COUNTY */         CASE f.grp WHEN 5 THEN 'WRONGCOUNTY'
                                    WHEN 6 THEN f.county ELSE NULL END,
    /* LATITUDE */       CASE WHEN f.grp IN (3,5,6) THEN f.lat ELSE NULL END,
    /* LONGITUDE */      CASE WHEN f.grp IN (3,5,6) THEN f.lon ELSE NULL END,
    /* TOTAL_DEPTH */    CASE WHEN f.grp = 6 THEN f.td ELSE NULL END,
    /* SPUD_DATE */      CASE WHEN f.grp = 6 THEN f.spud ELSE NULL END,
    /* CONFIDENCE */     1.00,
    SYSUTCDATETIME(),
    'FIXTURE',
    /* UWI14 */          CASE f.grp WHEN 1 THEN f.uwi14
                                    WHEN 4 THEN f.uwi_fake
                                    WHEN 5 THEN f.uwi14
                                    WHEN 6 THEN f.uwi14 ELSE NULL END,
    /* IDENTITY_SOURCE */ 'FIXTURE',
    /* NAME_NORM */      CASE f.grp WHEN 3 THEN f.name_norm
                                    WHEN 6 THEN f.name_norm ELSE NULL END
FROM #fx f;

/* ---- 4) What we seeded, by group ---- */
SELECT f.grp,
       grp_name = CHOOSE(f.grp,'G1 BACKFILL','G2 NORMALIZE','G3 RESOLVE',
                               'G4 QUARANTINE','G5 CONFLICT','G6 CONTROL'),
       files = COUNT(*)
FROM #fx f GROUP BY f.grp ORDER BY f.grp;

SELECT total_fixture_files = COUNT(*) FROM #fx;

DROP TABLE #fx;

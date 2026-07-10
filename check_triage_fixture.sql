/* =====================================================================
   check_triage_fixture.sql
   Run AFTER triage to see what it did to the fixture, grouped by defect
   class. Compare against the expected outcomes in seed_triage_fixture.sql.
   Connect to DataView_Demo.
   ===================================================================== */

;WITH fx AS (
    SELECT g.INVENTORY_ID, g.FILE_NAME, g.MATCHED_UWI, g.MATCH_METHOD,
           g.VALUE_TIER, g.TRIAGE_SCORE, g.TRIAGE_REASON, g.CATALOG_READINESS,
           h.UWI, h.UWI14, h.WELL_NAME, h.COUNTY, h.STATE,
           h.LATITUDE, h.LONGITUDE, h.TOTAL_DEPTH, h.WELL_FIELD,
           grp = CASE
               WHEN g.FILE_NAME LIKE 'fx_%' THEN
                 /* recover group from how the row was seeded */
                 CASE
                   WHEN h.WELL_NAME LIKE 'FIXTURE NOMATCH%'        THEN 4
                   WHEN h.COUNTY = 'WRONGCOUNTY'                    THEN 5
                   WHEN h.UWI LIKE '%-%-%'                          THEN 2
                   WHEN h.UWI IS NULL AND g.MATCHED_UWI IS NULL
                        AND h.WELL_NAME IS NOT NULL                 THEN 3
                   WHEN h.WELL_FIELD IS NOT NULL AND h.COUNTY IS NOT NULL THEN 6
                   ELSE 1
                 END
           END
    FROM DataView_Demo.file_catalog.GLOBAL_FILE_CATALOG g
    JOIN DataView_Demo.file_catalog.FILE_WELL_HEADER  h
         ON h.INVENTORY_ID = g.INVENTORY_ID
    WHERE g.ROOT_PATH = 'C:\FIXTURE'
)
SELECT
    grp,
    grp_name = CHOOSE(grp,'G1 BACKFILL','G2 NORMALIZE','G3 RESOLVE',
                          'G4 QUARANTINE','G5 CONFLICT','G6 CONTROL'),
    files          = COUNT(*),
    got_matched    = SUM(CASE WHEN MATCHED_UWI   IS NOT NULL THEN 1 ELSE 0 END),
    got_tier       = SUM(CASE WHEN VALUE_TIER    IS NOT NULL THEN 1 ELSE 0 END),
    filled_name    = SUM(CASE WHEN WELL_NAME     IS NOT NULL THEN 1 ELSE 0 END),
    filled_county  = SUM(CASE WHEN COUNTY        IS NOT NULL THEN 1 ELSE 0 END),
    filled_state   = SUM(CASE WHEN STATE         IS NOT NULL THEN 1 ELSE 0 END),
    filled_latlon  = SUM(CASE WHEN LATITUDE      IS NOT NULL THEN 1 ELSE 0 END),
    filled_td      = SUM(CASE WHEN TOTAL_DEPTH   IS NOT NULL THEN 1 ELSE 0 END)
FROM fx
GROUP BY grp
ORDER BY grp;

/* Spot-check rows (first few of each group) */
;WITH fx AS (
    SELECT g.FILE_NAME, g.MATCHED_UWI, g.VALUE_TIER, g.TRIAGE_REASON,
           h.UWI, h.WELL_NAME, h.COUNTY, h.STATE, h.LATITUDE, h.LONGITUDE,
           rn = ROW_NUMBER() OVER (PARTITION BY LEFT(g.FILE_NAME,3) ORDER BY g.FILE_NAME)
    FROM DataView_Demo.file_catalog.GLOBAL_FILE_CATALOG g
    JOIN DataView_Demo.file_catalog.FILE_WELL_HEADER  h
         ON h.INVENTORY_ID = g.INVENTORY_ID
    WHERE g.ROOT_PATH = 'C:\FIXTURE'
)
SELECT TOP (30) * FROM fx ORDER BY FILE_NAME;

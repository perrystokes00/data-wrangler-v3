/* ============================================================================
   seed_test_reference.sql

   Builds a SMALL test reference table (WELL_REF.well_ref.WELL_MASTER_TEST)
   derived from the synthetic catalog, so triage_inventory.py can be validated
   end-to-end WITHOUT touching the real 4.7M WELL_MASTER.

   It manufactures rows that match the synthetic files in two directions:
     A) name <- UWI : for catalog files that have a UWI but no name, a ref row
        with the same UWI14 and a made-up name  -> exercises 'ref-name-by-uwi'
     B) UWI  <- name: for catalog files that have a name (NAME_NORM) but no UWI,
        a ref row with the same NAME_NORM (deduped so it is exact+unique) and a
        fabricated UWI14 + corroborating TD/spud -> exercises 'ref-name-unique'

   PREREQUISITE: run triage once first so FILE_WELL_HEADER.UWI14 / NAME_NORM are
   populated (the seed reads those):
       python triage_inventory.py            -- apply; reference fills will be 0

   THEN run this script, THEN:
       python triage_inventory.py --ref WELL_REF.well_ref.WELL_MASTER_TEST
   ...and the ref-name-by-uwi / ref-name-unique counts should be > 0.

   Adjust the DataView database name below if yours differs.
   ============================================================================ */

USE WELL_REF;
GO

IF OBJECT_ID('well_ref.WELL_MASTER_TEST') IS NOT NULL
    DROP TABLE well_ref.WELL_MASTER_TEST;
GO

CREATE TABLE well_ref.WELL_MASTER_TEST (
    UWI14       varchar(14)  NULL,
    UWI         varchar(30)  NULL,
    WELL_NAME   varchar(200) NULL,
    NAME_NORM   varchar(200) NULL,
    TOTAL_DEPTH float        NULL,
    SPUD_DATE   date         NULL
);
GO

/* A) name <- UWI : match UWI-only catalog files, give them a name ---------- */
INSERT INTO well_ref.WELL_MASTER_TEST
        (UWI14, UWI, WELL_NAME, NAME_NORM, TOTAL_DEPTH, SPUD_DATE)
SELECT DISTINCT TOP (50)
       h.UWI14,
       h.UWI,
       'TEST WELL ' + h.UWI14,        -- a name the file is missing
       'TEST WELL ' + h.UWI14,        -- already in NAME_NORM form (no cleanup needed)
       TRY_CONVERT(float, h.TOTAL_DEPTH),
       TRY_CONVERT(date,  h.SPUD_DATE)
FROM DataView.file_catalog.FILE_WELL_HEADER h
WHERE NULLIF(h.UWI14,'') IS NOT NULL
  AND NULLIF(LTRIM(RTRIM(h.WELL_NAME)),'') IS NULL;
GO

/* B) UWI <- name (exact + unique): match name-only files, give them a UWI --- */
;WITH names AS (
    SELECT h.NAME_NORM,
           MAX(TRY_CONVERT(float, h.TOTAL_DEPTH)) AS TOTAL_DEPTH,
           MAX(TRY_CONVERT(date,  h.SPUD_DATE))   AS SPUD_DATE,
           ROW_NUMBER() OVER (ORDER BY h.NAME_NORM) AS rn
    FROM DataView.file_catalog.FILE_WELL_HEADER h
    WHERE NULLIF(h.UWI14,'') IS NULL
      AND NULLIF(LTRIM(RTRIM(h.NAME_NORM)),'') IS NOT NULL
    GROUP BY h.NAME_NORM           -- one row per name => exact + unique
)
INSERT INTO well_ref.WELL_MASTER_TEST
        (UWI14, UWI, WELL_NAME, NAME_NORM, TOTAL_DEPTH, SPUD_DATE)
SELECT TOP (50)
       '99' + RIGHT('000000000000' + CAST(rn AS varchar(12)), 12),  -- 14-digit fabricated UWI
       NULL,
       NAME_NORM,
       NAME_NORM,
       TOTAL_DEPTH,
       SPUD_DATE
FROM names;
GO

/* what we built */
SELECT 'test ref rows' AS label, COUNT(*) AS n FROM well_ref.WELL_MASTER_TEST;
SELECT TOP 10 UWI14, WELL_NAME, NAME_NORM FROM well_ref.WELL_MASTER_TEST ORDER BY UWI14;
GO

/* C) AMBIGUITY GUARD: give ONE name-only NAME_NORM a SECOND, conflicting ref
   row with a different UWI. That NAME_NORM now has two candidate UWIs, so the
   exact-unique step MUST refuse it and the file MUST stay in REVIEW (rather
   than guessing). After re-running triage you should therefore see exact+unique
   fill ONE FEWER than before, and REVIEW = 1 (this file). ------------------- */
;WITH first_name AS (
    SELECT TOP (1) h.NAME_NORM
    FROM DataView.file_catalog.FILE_WELL_HEADER h
    WHERE NULLIF(h.UWI14,'') IS NULL
      AND NULLIF(LTRIM(RTRIM(h.NAME_NORM)),'') IS NOT NULL
    ORDER BY h.NAME_NORM
)
INSERT INTO well_ref.WELL_MASTER_TEST
        (UWI14, UWI, WELL_NAME, NAME_NORM, TOTAL_DEPTH, SPUD_DATE)
SELECT '88000000000001', NULL, NAME_NORM, NAME_NORM, NULL, NULL
FROM first_name;
GO

PRINT 'Ambiguous NAME_NORM (expect this one to stay in REVIEW):';
SELECT NAME_NORM, COUNT(*) AS candidate_uwis
FROM well_ref.WELL_MASTER_TEST
GROUP BY NAME_NORM HAVING COUNT(*) > 1;
GO

/* ---- cleanup when finished testing ----------------------------------------
   DROP TABLE well_ref.WELL_MASTER_TEST;
   -- and clear the test-applied identities if you want a clean slate:
   -- UPDATE file_catalog.FILE_WELL_HEADER
   --   SET WELL_NAME=NULL, UWI14=NULL, NAME_NORM=NULL, IDENTITY_SOURCE=NULL
   -- WHERE IDENTITY_SOURCE LIKE 'ref-%';      -- (run in DataView)
   --------------------------------------------------------------------------- */

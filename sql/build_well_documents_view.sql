/* ============================================================================
   build_well_documents_view.sql
   DataView v3 — "documented wells" view for the mapping app.

   Run this in SSMS against the DataView database. It creates
   dataview.v_well_documents (one row per UWI that has at least one catalogued
   document, with its best-known coordinate and a document rollup) and then
   materializes it to dataview.well_documents for the map to read quickly.

   Coordinate priority (best available source wins, per UWI):
     1. WELL_REF.well_ref.WELL_MASTER  (reference master, keyed on UWI14)
     2. dataview.dv_well               (promoted / curated headers)
     3. file_catalog.cat_well          (captured from document headers)

   Requires SQL Server 2017+ (STRING_AGG) and that WELL_REF is on this instance.
   ============================================================================ */

USE DataView;
GO

-- ── 1. The view ─────────────────────────────────────────────────────────────
CREATE OR ALTER VIEW dataview.v_well_documents AS
WITH docs AS (
    SELECT
        MATCHED_UWI AS uwi,
        COUNT(*)                                                       AS doc_count,
        SUM(CASE WHEN FILE_TYPE_GROUP = 'PDF'       THEN 1 ELSE 0 END) AS pdf_count,
        SUM(CASE WHEN FILE_TYPE_GROUP = 'Well Log'  THEN 1 ELSE 0 END) AS log_count,
        SUM(CASE WHEN FILE_TYPE_GROUP IN ('Seismic','Seismic 2D','Seismic 3D')
                                                    THEN 1 ELSE 0 END) AS seismic_count,
        SUM(CASE WHEN FILE_TYPE_GROUP = 'Office'    THEN 1 ELSE 0 END) AS office_count,
        SUM(CASE WHEN FILE_TYPE_GROUP = 'Shapefile' THEN 1 ELSE 0 END) AS gis_count,
        SUM(CASE WHEN FILE_TYPE_GROUP = 'WITSML'    THEN 1 ELSE 0 END) AS witsml_count
    FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE NULLIF(LTRIM(RTRIM(MATCHED_UWI)), '') IS NOT NULL
      AND ISNULL(FLAG_DELETE, 'N') <> 'Y'
    GROUP BY MATCHED_UWI
),
types AS (
    SELECT uwi, STRING_AGG(ft, ', ') WITHIN GROUP (ORDER BY ft) AS doc_types
    FROM (
        SELECT DISTINCT MATCHED_UWI AS uwi, FILE_TYPE_GROUP AS ft
        FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE NULLIF(LTRIM(RTRIM(MATCHED_UWI)), '') IS NOT NULL
          AND ISNULL(FLAG_DELETE, 'N') <> 'Y'
          AND NULLIF(LTRIM(RTRIM(FILE_TYPE_GROUP)), '') IS NOT NULL
    ) x
    GROUP BY uwi
),
coords AS (
    SELECT uwi, lat, lon, well_name, coord_source
    FROM (
        SELECT uwi, lat, lon, well_name, coord_source,
               ROW_NUMBER() OVER (PARTITION BY uwi ORDER BY pr) AS rn
        FROM (
            -- 1) reference well master — broad, clean coordinates (keyed UWI14)
            SELECT UWI14 AS uwi, SURFACE_LATITUDE AS lat,
                   SURFACE_LONGITUDE AS lon, WELL_NAME AS well_name,
                   'reference' AS coord_source, 1 AS pr
            FROM WELL_REF.well_ref.WELL_MASTER
            WHERE SURFACE_LATITUDE IS NOT NULL AND SURFACE_LONGITUDE IS NOT NULL
              AND NULLIF(LTRIM(RTRIM(UWI14)), '') IS NOT NULL
              AND UWI14 IN (SELECT uwi FROM docs)
            UNION ALL
            -- 2) our promoted / curated headers
            SELECT uwi, surface_latitude, surface_longitude,
                   well_name, 'dv_well', 2
            FROM dataview.dv_well
            WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
              AND uwi IN (SELECT uwi FROM docs)
            UNION ALL
            -- 3) coordinates captured from document headers
            SELECT uwi, surface_latitude, surface_longitude,
                   well_name, 'cat_well', 3
            FROM file_catalog.cat_well
            WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL
              AND uwi IN (SELECT uwi FROM docs)
        ) s
    ) r
    WHERE rn = 1
)
SELECT
    d.uwi,
    c.lat,
    c.lon,
    COALESCE(NULLIF(LTRIM(RTRIM(c.well_name)), ''), d.uwi) AS well_name,
    c.coord_source,
    d.doc_count, d.pdf_count, d.log_count, d.seismic_count,
    d.office_count, d.gis_count, d.witsml_count,
    t.doc_types
FROM docs d
JOIN coords c ON c.uwi = d.uwi
LEFT JOIN types t ON t.uwi = d.uwi;
GO

PRINT '-- view dataview.v_well_documents created/updated';
SELECT COUNT(*) AS documented_wells_with_coordinate FROM dataview.v_well_documents;
GO

-- ── 2. Materialize to a fast indexed table the map reads ─────────────────────
IF OBJECT_ID('dataview.well_documents', 'U') IS NOT NULL
    DROP TABLE dataview.well_documents;
GO

SELECT * INTO dataview.well_documents FROM dataview.v_well_documents;
GO

CREATE CLUSTERED INDEX IX_well_documents_latlon
    ON dataview.well_documents (lat, lon);
CREATE NONCLUSTERED INDEX IX_well_documents_uwi
    ON dataview.well_documents (uwi);
GO

PRINT '-- materialized dataview.well_documents';
SELECT COUNT(*) AS materialized_rows,
       SUM(CASE WHEN coord_source = 'reference' THEN 1 ELSE 0 END) AS from_reference,
       SUM(CASE WHEN coord_source = 'dv_well'   THEN 1 ELSE 0 END) AS from_dv_well,
       SUM(CASE WHEN coord_source = 'cat_well'  THEN 1 ELSE 0 END) AS from_cat_well
FROM dataview.well_documents;
GO

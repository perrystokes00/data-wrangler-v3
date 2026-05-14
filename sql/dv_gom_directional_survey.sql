/* ===================================================================
   dv_gom_directional_survey.sql
   -------------------------------------------------------------------
   Table for BOEM Gulf of America directional survey points (the
   "Azimuth" survey file — directfixed.txt).

   One row per survey station. A well's full trajectory is the set of
   rows sharing an api_well_number, ordered by survey_point_md.

   Design notes
   ------------
   - api_well_number is stored RAW. well_id (the UUID that links to
     dataview_gom.well) is resolved in a SEPARATE follow-up pass via
     UPDATE ... JOIN, not at load time. This mirrors the importer FK
     pre-flight pattern and means surveys for APIs not yet in
     dataview_gom.well still load cleanly — they just stay unresolved
     until a matching borehole record exists.
   - well_id is therefore NULLable and unindexed-as-FK for now. The
     resolution pass and any FK constraint come later.
   - latitude / longitude are stored AS-IS from the BOEM file (NAD27).
     Datum reconciliation against dataview_gom.well is a later concern.
   - survey_point_id is a surrogate identity PK — survey files have no
     natural single-column key, and (api_well_number, survey_point_md)
     is the natural composite but we keep it as a unique index rather
     than the PK so the identity column can drive fast inserts.
   - No GO statements — this file is run through pyodbc, which executes
     one batch. Matches the dv_indexes.sql convention.
   =================================================================== */

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dataview_gom')
    EXEC('CREATE SCHEMA dataview_gom');

IF OBJECT_ID('dataview_gom.directional_survey_point', 'U') IS NULL
BEGIN
    CREATE TABLE dataview_gom.directional_survey_point (
        survey_point_id   BIGINT IDENTITY(1,1) NOT NULL,

        -- Linkage. api_well_number is the raw BOEM API from the survey
        -- file; well_id is resolved later by joining to dataview_gom.well.
        api_well_number   NVARCHAR(20)   NOT NULL,
        well_id           UNIQUEIDENTIFIER NULL,

        -- Survey station measurements (BOEM Azimuth format).
        survey_point_md   DECIMAL(10,2)  NULL,   -- measured depth, ft
        incl_ang          DECIMAL(8,3)   NULL,   -- inclination angle, degrees
        azimuth           DECIMAL(8,3)   NULL,   -- azimuth, degrees (0-360)
        survey_point_tvd  DECIMAL(10,2)  NULL,   -- true vertical depth, ft

        -- Station coordinates — NAD27, stored as the BOEM file gives them.
        latitude          DECIMAL(11,7)  NULL,
        longitude         DECIMAL(11,7)  NULL,

        -- BOEM's per-row last-update date (MM/DD/YYYY in the source).
        last_update       DATE           NULL,

        -- Provenance.
        source_file       NVARCHAR(255)  NULL,
        loaded_date       DATETIME2(0)   NOT NULL CONSTRAINT DF_dvgom_dsp_loaded
                                                  DEFAULT SYSUTCDATETIME(),
        row_changed_date  DATETIME2(0)   NOT NULL CONSTRAINT DF_dvgom_dsp_changed
                                                  DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_dvgom_directional_survey_point
            PRIMARY KEY CLUSTERED (survey_point_id)
    );

    -- Natural composite key: one station per (well, measured depth).
    -- Unique so the loader's MERGE can target it for idempotent re-runs.
    CREATE UNIQUE INDEX UX_dvgom_dsp_api_md
        ON dataview_gom.directional_survey_point (api_well_number, survey_point_md);

    -- Supports both the later well_id-resolution UPDATE...JOIN and
    -- per-well trajectory lookups (WHERE api_well_number = ...).
    CREATE INDEX IX_dvgom_dsp_api
        ON dataview_gom.directional_survey_point (api_well_number);

    -- Once well_id is resolved, trajectory lookups by well_id are common.
    CREATE INDEX IX_dvgom_dsp_well_id
        ON dataview_gom.directional_survey_point (well_id)
        WHERE well_id IS NOT NULL;
END;

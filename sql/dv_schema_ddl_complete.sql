-- =============================================================================
-- DataView Schema — CONSOLIDATED DDL
-- All 46 tables in a single file (base + patch1 + patch2 with all fixes applied)
-- 
-- Run order:
--   1. Create DataView database manually in SSMS
--   2. Execute this file against DataView
--
-- Tables: 46
--   Reference  : dv_r_source, dv_r_well_type, dv_r_well_status, dv_r_uom
--   Core well  : dv_well, dv_well_alias, dv_source, dv_business_associate, dv_field
--   Geology    : dv_well_formation_top, dv_strat_interval
--   Logs       : dv_well_log, dv_well_log_curve, dv_wl_file_catalog
--   Surveys    : dv_well_dir_srvy_hdr, dv_well_dir_srvy_sta
--   Seismic    : dv_seis_set, dv_seis_line, dv_seis_file_catalog
--   Production : dv_prod_entity, dv_prod_volume
--   Files/QC   : dv_global_file_catalog, dv_spatial_layer, dv_load_batch,
--                dv_column_map, dv_data_quality
--   Political  : dv_country, dv_province_state, dv_county, dv_basin,
--                dv_plss_township, dv_ocs_block
--   Well sub   : dv_well_core, dv_well_core_sample, dv_well_core_photo,
--                dv_well_dst, dv_well_dst_period, dv_well_pressure,
--                dv_well_completion, dv_well_perforation, dv_well_stimulation,
--                dv_well_casing, dv_well_mud_log, dv_well_shows
--   Petro      : dv_well_petro_interp, dv_well_petro_zone
--
-- Fixes incorporated (vs original patch files):
--   dv_well_perforation  : shot_density_ouom FLOAT → NVARCHAR(40)
--   dv_well_stimulation  : fluid_volume_ouom/proppant_mass_ouom FLOAT → NVARCHAR(40)
--                          service_co_ba_id column added
--   dv_well_casing       : string_num NOT NULL → NULL
--   dv_well_mud_log      : mud_logger_ba_id column added
--   dv_well_shows        : ic5_pct, nc5_pct, fluorescence_color,
--                          fluorescence_intensity, cut_color NOT NULL → NULL
-- =============================================================================
USE DataView;
GO

-- =============================================================================
-- DataView Schema DDL
-- Database   : Any SQL Server instance (existing)
-- Schema     : dataview
-- Prefix     : dv_
-- PPDM       : Aligned with PPDM 3.9 column naming conventions
-- Dialects   : SQL Server primary → Oracle / Snowflake upgrade path
-- Created    : 2026-04-30
-- =============================================================================
-- SECTIONS:
--   1.  Schema creation
--   2.  Reference tables        (dv_r_*)              4 tables
--   3.  Entity tables                                  3 tables
--   4.  Well                                           2 tables
--   5.  Directional survey                             2 tables
--   6.  Stratigraphy (flattened + intervals)           2 tables
--   7.  Well logs                                      2 tables
--   8.  Seismic                                        2 tables
--   9.  Production                                     2 tables
--  10.  File catalog                                   3 tables
--  11.  Spatial                                        1 table
--  12.  Audit / pipeline                               3 tables
--  13.  Political                                      6 tables
--                                               TOTAL 32 tables
-- =============================================================================

-- =============================================================================
-- 1. SCHEMA
-- =============================================================================

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dataview')
    EXEC('CREATE SCHEMA dataview');
GO

-- =============================================================================
-- DROP ORDER  (children before parents)
-- =============================================================================
-- Patch 2 tables (must drop before base tables they reference)
IF OBJECT_ID('dataview.dv_well_petro_zone',   'U') IS NOT NULL DROP TABLE dataview.dv_well_petro_zone;
IF OBJECT_ID('dataview.dv_well_petro_interp', 'U') IS NOT NULL DROP TABLE dataview.dv_well_petro_interp;
-- Patch 1 tables
IF OBJECT_ID('dataview.dv_well_shows',        'U') IS NOT NULL DROP TABLE dataview.dv_well_shows;
IF OBJECT_ID('dataview.dv_well_mud_log',      'U') IS NOT NULL DROP TABLE dataview.dv_well_mud_log;
IF OBJECT_ID('dataview.dv_well_casing',       'U') IS NOT NULL DROP TABLE dataview.dv_well_casing;
IF OBJECT_ID('dataview.dv_well_stimulation',  'U') IS NOT NULL DROP TABLE dataview.dv_well_stimulation;
IF OBJECT_ID('dataview.dv_well_perforation',  'U') IS NOT NULL DROP TABLE dataview.dv_well_perforation;
IF OBJECT_ID('dataview.dv_well_completion',   'U') IS NOT NULL DROP TABLE dataview.dv_well_completion;
IF OBJECT_ID('dataview.dv_well_pressure',     'U') IS NOT NULL DROP TABLE dataview.dv_well_pressure;
IF OBJECT_ID('dataview.dv_well_dst_period',   'U') IS NOT NULL DROP TABLE dataview.dv_well_dst_period;
IF OBJECT_ID('dataview.dv_well_dst',          'U') IS NOT NULL DROP TABLE dataview.dv_well_dst;
IF OBJECT_ID('dataview.dv_well_core_photo',   'U') IS NOT NULL DROP TABLE dataview.dv_well_core_photo;
IF OBJECT_ID('dataview.dv_well_core_sample',  'U') IS NOT NULL DROP TABLE dataview.dv_well_core_sample;
IF OBJECT_ID('dataview.dv_well_core',         'U') IS NOT NULL DROP TABLE dataview.dv_well_core;
-- Base tables
IF OBJECT_ID('dataview.dv_data_quality',        'U') IS NOT NULL DROP TABLE dataview.dv_data_quality;
IF OBJECT_ID('dataview.dv_column_map',          'U') IS NOT NULL DROP TABLE dataview.dv_column_map;
IF OBJECT_ID('dataview.dv_load_batch',          'U') IS NOT NULL DROP TABLE dataview.dv_load_batch;
IF OBJECT_ID('dataview.dv_spatial_layer',       'U') IS NOT NULL DROP TABLE dataview.dv_spatial_layer;
IF OBJECT_ID('dataview.dv_global_file_catalog', 'U') IS NOT NULL DROP TABLE dataview.dv_global_file_catalog;
IF OBJECT_ID('dataview.dv_seis_file_catalog',   'U') IS NOT NULL DROP TABLE dataview.dv_seis_file_catalog;
IF OBJECT_ID('dataview.dv_wl_file_catalog',     'U') IS NOT NULL DROP TABLE dataview.dv_wl_file_catalog;
IF OBJECT_ID('dataview.dv_prod_volume',         'U') IS NOT NULL DROP TABLE dataview.dv_prod_volume;
IF OBJECT_ID('dataview.dv_prod_entity',         'U') IS NOT NULL DROP TABLE dataview.dv_prod_entity;
IF OBJECT_ID('dataview.dv_seis_line',           'U') IS NOT NULL DROP TABLE dataview.dv_seis_line;
IF OBJECT_ID('dataview.dv_seis_set',            'U') IS NOT NULL DROP TABLE dataview.dv_seis_set;
IF OBJECT_ID('dataview.dv_well_log_curve',      'U') IS NOT NULL DROP TABLE dataview.dv_well_log_curve;
IF OBJECT_ID('dataview.dv_well_log',            'U') IS NOT NULL DROP TABLE dataview.dv_well_log;
IF OBJECT_ID('dataview.dv_strat_interval',      'U') IS NOT NULL DROP TABLE dataview.dv_strat_interval;
IF OBJECT_ID('dataview.dv_well_formation_top',  'U') IS NOT NULL DROP TABLE dataview.dv_well_formation_top;
IF OBJECT_ID('dataview.dv_well_dir_srvy_sta',   'U') IS NOT NULL DROP TABLE dataview.dv_well_dir_srvy_sta;
IF OBJECT_ID('dataview.dv_well_dir_srvy_hdr',   'U') IS NOT NULL DROP TABLE dataview.dv_well_dir_srvy_hdr;
IF OBJECT_ID('dataview.dv_well_alias',          'U') IS NOT NULL DROP TABLE dataview.dv_well_alias;
IF OBJECT_ID('dataview.dv_well',                'U') IS NOT NULL DROP TABLE dataview.dv_well;
IF OBJECT_ID('dataview.dv_field',               'U') IS NOT NULL DROP TABLE dataview.dv_field;
IF OBJECT_ID('dataview.dv_business_associate',  'U') IS NOT NULL DROP TABLE dataview.dv_business_associate;
IF OBJECT_ID('dataview.dv_source',              'U') IS NOT NULL DROP TABLE dataview.dv_source;
IF OBJECT_ID('dataview.dv_ocs_block',           'U') IS NOT NULL DROP TABLE dataview.dv_ocs_block;
IF OBJECT_ID('dataview.dv_plss_township',       'U') IS NOT NULL DROP TABLE dataview.dv_plss_township;
IF OBJECT_ID('dataview.dv_county',              'U') IS NOT NULL DROP TABLE dataview.dv_county;
IF OBJECT_ID('dataview.dv_basin',               'U') IS NOT NULL DROP TABLE dataview.dv_basin;
IF OBJECT_ID('dataview.dv_province_state',      'U') IS NOT NULL DROP TABLE dataview.dv_province_state;
IF OBJECT_ID('dataview.dv_country',             'U') IS NOT NULL DROP TABLE dataview.dv_country;
IF OBJECT_ID('dataview.dv_r_uom',              'U') IS NOT NULL DROP TABLE dataview.dv_r_uom;
IF OBJECT_ID('dataview.dv_r_well_status',      'U') IS NOT NULL DROP TABLE dataview.dv_r_well_status;
IF OBJECT_ID('dataview.dv_r_well_type',        'U') IS NOT NULL DROP TABLE dataview.dv_r_well_type;
IF OBJECT_ID('dataview.dv_r_source',           'U') IS NOT NULL DROP TABLE dataview.dv_r_source;
GO

-- =============================================================================
-- 2. REFERENCE TABLES
-- =============================================================================

CREATE TABLE dataview.dv_r_source (
    source                  NVARCHAR(40)    NOT NULL,
    short_name              NVARCHAR(40)    NULL,
    long_name               NVARCHAR(255)   NULL,
    remark                  NVARCHAR(2000)  NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    CONSTRAINT pk_dv_r_source       PRIMARY KEY (source),
    CONSTRAINT ck_dv_r_source_ai    CHECK (active_ind IN ('Y','N'))
);
GO

CREATE TABLE dataview.dv_r_well_type (
    well_type               NVARCHAR(40)    NOT NULL,
    short_name              NVARCHAR(40)    NULL,
    long_name               NVARCHAR(255)   NULL,
    remark                  NVARCHAR(2000)  NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    CONSTRAINT pk_dv_r_well_type    PRIMARY KEY (well_type),
    CONSTRAINT ck_dv_r_wtype_ai     CHECK (active_ind IN ('Y','N'))
);
GO

CREATE TABLE dataview.dv_r_well_status (
    well_status             NVARCHAR(40)    NOT NULL,
    short_name              NVARCHAR(40)    NULL,
    long_name               NVARCHAR(255)   NULL,
    remark                  NVARCHAR(2000)  NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    CONSTRAINT pk_dv_r_well_status  PRIMARY KEY (well_status),
    CONSTRAINT ck_dv_r_wstatus_ai   CHECK (active_ind IN ('Y','N'))
);
GO

CREATE TABLE dataview.dv_r_uom (
    uom_code                NVARCHAR(40)    NOT NULL,
    unit_of_measure         NVARCHAR(255)   NULL,
    uom_description         NVARCHAR(2000)  NULL,
    uom_type                NVARCHAR(40)    NULL,   -- LENGTH, PRESSURE, VOLUME, TEMP, RATE …
    si_equivalent           NUMERIC(20,10)  NULL,
    si_uom_code             NVARCHAR(40)    NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    CONSTRAINT pk_dv_r_uom          PRIMARY KEY (uom_code),
    CONSTRAINT ck_dv_r_uom_ai       CHECK (active_ind IN ('Y','N'))
);
GO

-- =============================================================================
-- 3. ENTITY TABLES
-- =============================================================================

CREATE TABLE dataview.dv_source (
    source                  NVARCHAR(40)    NOT NULL,
    source_type             NVARCHAR(40)    NULL,
    short_name              NVARCHAR(40)    NULL,
    long_name               NVARCHAR(255)   NULL,
    description             NVARCHAR(2000)  NULL,
    url                     NVARCHAR(1000)  NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source_ref              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_source         PRIMARY KEY (source),
    CONSTRAINT ck_dv_source_ai      CHECK (active_ind IN ('Y','N'))
);
GO

CREATE TABLE dataview.dv_business_associate (
    ba_id                   NVARCHAR(40)    NOT NULL,   -- SHA1 of normalised ba_name
    ba_type                 NVARCHAR(40)    NULL,       -- OPERATOR, CONTRACTOR, PARTNER …
    ba_name                 NVARCHAR(255)   NOT NULL,
    ba_name_alias           NVARCHAR(255)   NULL,
    short_name              NVARCHAR(40)    NULL,
    address_1               NVARCHAR(255)   NULL,
    address_2               NVARCHAR(255)   NULL,
    city                    NVARCHAR(100)   NULL,
    state_province          NVARCHAR(100)   NULL,
    postal_code             NVARCHAR(20)    NULL,
    country                 NVARCHAR(40)    NULL,
    phone_num               NVARCHAR(40)    NULL,
    email_addr              NVARCHAR(255)   NULL,
    duns_num                NVARCHAR(20)    NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_business_associate PRIMARY KEY (ba_id),
    CONSTRAINT ck_dv_ba_ai          CHECK (active_ind IN ('Y','N'))
);
GO

CREATE TABLE dataview.dv_field (
    field_id                NVARCHAR(40)    NOT NULL,   -- SHA1 of field_name + country
    field_name              NVARCHAR(255)   NOT NULL,
    field_type              NVARCHAR(40)    NULL,
    country                 NVARCHAR(40)    NULL,
    province_state          NVARCHAR(100)   NULL,
    county                  NVARCHAR(100)   NULL,
    basin_name              NVARCHAR(255)   NULL,
    operator_ba_id          NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    discovery_date          DATETIME2       NULL,
    field_status            NVARCHAR(40)    NULL,
    onshore_offshore_ind    NVARCHAR(10)    NULL,       -- ONSHORE / OFFSHORE / BOTH
    surface_latitude        NUMERIC(15,10)  NULL,
    surface_longitude       NUMERIC(15,10)  NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_field          PRIMARY KEY (field_id),
    CONSTRAINT ck_dv_field_ai       CHECK (active_ind IN ('Y','N'))
);
GO

-- =============================================================================
-- 4. WELL
-- =============================================================================

CREATE TABLE dataview.dv_well (
    uwi                     NVARCHAR(40)    NOT NULL,   -- Unique Well Identifier
    well_name               NVARCHAR(255)   NULL,
    well_num                NVARCHAR(40)    NULL,
    operator_ba_id          NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    field_id                NVARCHAR(40)    NULL REFERENCES dataview.dv_field(field_id),
    well_type               NVARCHAR(40)    NULL REFERENCES dataview.dv_r_well_type(well_type),
    well_status             NVARCHAR(40)    NULL REFERENCES dataview.dv_r_well_status(well_status),
    country                 NVARCHAR(40)    NULL,
    province_state          NVARCHAR(100)   NULL,
    county                  NVARCHAR(100)   NULL,
    legal_survey_type       NVARCHAR(40)    NULL,       -- PLSS, NTS, DLS, RA …
    surface_latitude        NUMERIC(15,10)  NULL,
    surface_longitude       NUMERIC(15,10)  NULL,
    ground_elevation        NUMERIC(15,4)   NULL,
    ground_elevation_ouom   NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    kb_elevation            NUMERIC(15,4)   NULL,
    kb_elevation_ouom       NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    spud_date               DATETIME2       NULL,
    completion_date         DATETIME2       NULL,
    final_td                NUMERIC(15,4)   NULL,
    final_td_ouom           NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    depth_datum             NVARCHAR(40)    NULL,       -- KB, GL, DF, MSL …
    depth_datum_elevation   NUMERIC(15,4)   NULL,
    epsg_code               INT             NULL,
    api_num                 NVARCHAR(20)    NULL,
    license_num             NVARCHAR(40)    NULL,
    lease_name              NVARCHAR(255)   NULL,
    onshore_offshore_ind    NVARCHAR(10)    NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well           PRIMARY KEY (uwi),
    CONSTRAINT ck_dv_well_ai        CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_well_name     ON dataview.dv_well(well_name);
CREATE INDEX ix_dv_well_api      ON dataview.dv_well(api_num);
CREATE INDEX ix_dv_well_field    ON dataview.dv_well(field_id);
CREATE INDEX ix_dv_well_operator ON dataview.dv_well(operator_ba_id);
CREATE INDEX ix_dv_well_location ON dataview.dv_well(country, province_state, county);
GO

CREATE TABLE dataview.dv_well_alias (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    alias_id                NVARCHAR(40)    NOT NULL,
    alias_name              NVARCHAR(255)   NOT NULL,
    alias_type              NVARCHAR(40)    NULL,       -- API, LICENSE, COMMON, REGULATORY …
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_alias     PRIMARY KEY (uwi, alias_id),
    CONSTRAINT ck_dv_walias_ai      CHECK (active_ind IN ('Y','N'))
);
GO

-- =============================================================================
-- 5. DIRECTIONAL SURVEY
-- =============================================================================

CREATE TABLE dataview.dv_well_dir_srvy_hdr (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    survey_id               NVARCHAR(40)    NOT NULL,
    survey_type             NVARCHAR(40)    NULL,       -- MWD, GYRO, MAGNETIC …
    survey_date             DATETIME2       NULL,
    contractor_ba_id        NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    depth_datum             NVARCHAR(40)    NULL,
    depth_datum_elevation   NUMERIC(15,4)   NULL,
    survey_top_depth        NUMERIC(15,4)   NULL,
    survey_base_depth       NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_dir_srvy_hdr  PRIMARY KEY (uwi, survey_id),
    CONSTRAINT ck_dv_srvy_hdr_ai        CHECK (active_ind IN ('Y','N'))
);
GO

CREATE TABLE dataview.dv_well_dir_srvy_sta (
    uwi                     NVARCHAR(40)    NOT NULL,
    survey_id               NVARCHAR(40)    NOT NULL,
    station_id              NVARCHAR(40)    NOT NULL,
    md                      NUMERIC(15,4)   NULL,   -- measured depth
    incl                    NUMERIC(10,4)   NULL,   -- inclination degrees
    azim                    NUMERIC(10,4)   NULL,   -- azimuth degrees
    tvd                     NUMERIC(15,4)   NULL,   -- true vertical depth
    ns_offset               NUMERIC(15,4)   NULL,   -- north/south offset
    ew_offset               NUMERIC(15,4)   NULL,   -- east/west offset
    surface_latitude        NUMERIC(15,10)  NULL,
    surface_longitude       NUMERIC(15,10)  NULL,
    dls                     NUMERIC(10,4)   NULL,   -- dogleg severity deg/100ft
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_dir_srvy_sta  PRIMARY KEY (uwi, survey_id, station_id),
    CONSTRAINT fk_srvy_sta_hdr          FOREIGN KEY (uwi, survey_id)
        REFERENCES dataview.dv_well_dir_srvy_hdr(uwi, survey_id)
);
CREATE INDEX ix_dv_srvy_sta_uwi ON dataview.dv_well_dir_srvy_sta(uwi);
GO

-- =============================================================================
-- 6. STRATIGRAPHY  (flattened single-table pick + child interval table)
-- =============================================================================

CREATE TABLE dataview.dv_well_formation_top (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    strat_unit_id           NVARCHAR(40)    NOT NULL,   -- surrogate or regional code
    interp_id               NVARCHAR(40)    NOT NULL DEFAULT '1',
    -- Flattened strat name set + unit attributes
    strat_name_set          NVARCHAR(255)   NULL,   -- e.g. GULF COAST, PERMIAN BASIN
    strat_unit_name         NVARCHAR(255)   NULL,   -- e.g. Woodford Shale
    strat_unit_type         NVARCHAR(40)    NULL,   -- FORMATION, GROUP, MEMBER, ZONE
    strat_unit_subtype      NVARCHAR(40)    NULL,   -- RESERVOIR, SEAL, SOURCE ROCK …
    age_top_ma              NUMERIC(10,3)   NULL,   -- age top (million years)
    age_base_ma             NUMERIC(10,3)   NULL,
    lithology               NVARCHAR(100)   NULL,
    -- Pick geometry
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    gross_thickness         AS (CASE WHEN base_depth IS NOT NULL AND top_depth IS NOT NULL
                                THEN base_depth - top_depth ELSE NULL END),
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    depth_datum             NVARCHAR(40)    NULL,   -- KB, GL, MSL …
    tvd_top                 NUMERIC(15,4)   NULL,
    tvd_base                NUMERIC(15,4)   NULL,
    -- Fluid contacts (top-level)
    owc_depth               NUMERIC(15,4)   NULL,   -- oil-water contact
    goc_depth               NUMERIC(15,4)   NULL,   -- gas-oil contact
    gwc_depth               NUMERIC(15,4)   NULL,   -- gas-water contact
    -- Interpretation metadata
    interp_date             DATETIME2       NULL,
    interpreter_ba_id       NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    confidence_level        NVARCHAR(40)    NULL,   -- HIGH, MEDIUM, LOW
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_formation_top PRIMARY KEY (uwi, strat_unit_id, interp_id),
    CONSTRAINT ck_dv_fmt_ai             CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_fmt_uwi     ON dataview.dv_well_formation_top(uwi);
CREATE INDEX ix_dv_fmt_name    ON dataview.dv_well_formation_top(strat_unit_name);
CREATE INDEX ix_dv_fmt_nameset ON dataview.dv_well_formation_top(strat_name_set);
GO

-- Sub-intervals within a formation pick (pay zones, fluid contacts, lithofacies)
CREATE TABLE dataview.dv_strat_interval (
    uwi                     NVARCHAR(40)    NOT NULL,
    strat_unit_id           NVARCHAR(40)    NOT NULL,
    interp_id               NVARCHAR(40)    NOT NULL DEFAULT '1',
    interval_id             NVARCHAR(40)    NOT NULL,
    interval_type           NVARCHAR(40)    NULL,   -- PAY, NON-PAY, TIGHT, TRANSITION …
    interval_name           NVARCHAR(255)   NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    net_thickness           NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    porosity                NUMERIC(10,4)   NULL,
    water_saturation        NUMERIC(10,4)   NULL,
    permeability            NUMERIC(15,4)   NULL,
    perm_ouom               NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    fluid_type              NVARCHAR(40)    NULL,   -- OIL, GAS, WATER, CONDENSATE …
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_strat_interval     PRIMARY KEY (uwi, strat_unit_id, interp_id, interval_id),
    CONSTRAINT fk_strat_interval_top    FOREIGN KEY (uwi, strat_unit_id, interp_id)
        REFERENCES dataview.dv_well_formation_top(uwi, strat_unit_id, interp_id)
);
CREATE INDEX ix_dv_strat_int_uwi ON dataview.dv_strat_interval(uwi);
GO

-- =============================================================================
-- 7. WELL LOGS
-- =============================================================================

CREATE TABLE dataview.dv_well_log (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    log_id                  NVARCHAR(40)    NOT NULL,
    log_type                NVARCHAR(40)    NULL,   -- WIRELINE, MWD, LWD, CSU …
    run_num                 NVARCHAR(10)    NULL,
    log_date                DATETIME2       NULL,
    service_company_ba_id   NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    depth_datum             NVARCHAR(40)    NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    null_value              NUMERIC(15,4)   NULL,
    file_path               NVARCHAR(1000)  NULL,   -- vault-relative path to LAS/DLIS
    file_format             NVARCHAR(20)    NULL,   -- LAS, DLIS, LIS, ASCII …
    catalog_id              NVARCHAR(40)    NULL,   -- soft FK to dv_wl_file_catalog
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_log       PRIMARY KEY (uwi, log_id),
    CONSTRAINT ck_dv_well_log_ai    CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_well_log_uwi  ON dataview.dv_well_log(uwi);
CREATE INDEX ix_dv_well_log_type ON dataview.dv_well_log(log_type);
GO

CREATE TABLE dataview.dv_well_log_curve (
    uwi                     NVARCHAR(40)    NOT NULL,
    log_id                  NVARCHAR(40)    NOT NULL,
    curve_id                NVARCHAR(40)    NOT NULL,
    mnemonic                NVARCHAR(40)    NOT NULL,   -- GR, RHOB, NPHI, DT, RT …
    mnemonic_alias          NVARCHAR(40)    NULL,
    curve_description       NVARCHAR(255)   NULL,
    curve_unit              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    null_value              NUMERIC(15,4)   NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    min_value               NUMERIC(20,6)   NULL,
    max_value               NUMERIC(20,6)   NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_log_curve     PRIMARY KEY (uwi, log_id, curve_id),
    CONSTRAINT fk_log_curve_log         FOREIGN KEY (uwi, log_id)
        REFERENCES dataview.dv_well_log(uwi, log_id),
    CONSTRAINT ck_dv_log_curve_ai       CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_log_curve_uwi      ON dataview.dv_well_log_curve(uwi);
CREATE INDEX ix_dv_log_curve_mnemonic ON dataview.dv_well_log_curve(mnemonic);
GO

-- =============================================================================
-- 8. SEISMIC
-- =============================================================================

CREATE TABLE dataview.dv_seis_set (
    seis_set_id             NVARCHAR(40)    NOT NULL,
    seis_set_name           NVARCHAR(255)   NOT NULL,
    seis_set_type           NVARCHAR(40)    NULL,   -- 2D, 3D, 4D, VSP …
    survey_date             DATETIME2       NULL,
    contractor_ba_id        NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    operator_ba_id          NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    country                 NVARCHAR(40)    NULL,
    province_state          NVARCHAR(100)   NULL,
    basin_name              NVARCHAR(255)   NULL,
    survey_area_km2         NUMERIC(15,4)   NULL,
    bbox_min_lat            NUMERIC(15,10)  NULL,
    bbox_max_lat            NUMERIC(15,10)  NULL,
    bbox_min_lon            NUMERIC(15,10)  NULL,
    bbox_max_lon            NUMERIC(15,10)  NULL,
    epsg_code               INT             NULL,
    file_path               NVARCHAR(1000)  NULL,   -- vault-relative path
    catalog_id              NVARCHAR(40)    NULL,   -- soft FK to dv_seis_file_catalog
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_seis_set       PRIMARY KEY (seis_set_id),
    CONSTRAINT ck_dv_seis_set_ai    CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_seis_set_name ON dataview.dv_seis_set(seis_set_name);
GO

CREATE TABLE dataview.dv_seis_line (
    seis_set_id             NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_seis_set(seis_set_id),
    line_id                 NVARCHAR(40)    NOT NULL,
    line_name               NVARCHAR(255)   NULL,
    line_type               NVARCHAR(40)    NULL,   -- INLINE, CROSSLINE, ARBITRARY …
    shot_point_start        NUMERIC(15,4)   NULL,
    shot_point_end          NUMERIC(15,4)   NULL,
    cdp_start               INT             NULL,
    cdp_end                 INT             NULL,
    record_length_ms        NUMERIC(10,3)   NULL,
    sample_rate_ms          NUMERIC(10,4)   NULL,
    trace_count             INT             NULL,
    file_path               NVARCHAR(1000)  NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_seis_line      PRIMARY KEY (seis_set_id, line_id),
    CONSTRAINT ck_dv_seis_line_ai   CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_seis_line_set  ON dataview.dv_seis_line(seis_set_id);
CREATE INDEX ix_dv_seis_line_name ON dataview.dv_seis_line(line_name);
GO

-- =============================================================================
-- 9. PRODUCTION
-- =============================================================================

CREATE TABLE dataview.dv_prod_entity (
    prod_entity_id          NVARCHAR(40)    NOT NULL,
    uwi                     NVARCHAR(40)    NULL REFERENCES dataview.dv_well(uwi),
    field_id                NVARCHAR(40)    NULL REFERENCES dataview.dv_field(field_id),
    operator_ba_id          NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    prod_entity_type        NVARCHAR(40)    NULL,   -- WELL, LEASE, FIELD, COMPLETION …
    prod_entity_name        NVARCHAR(255)   NULL,
    first_prod_date         DATETIME2       NULL,
    last_prod_date          DATETIME2       NULL,
    primary_fluid           NVARCHAR(40)    NULL,   -- OIL, GAS, WATER, CONDENSATE …
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_prod_entity    PRIMARY KEY (prod_entity_id),
    CONSTRAINT ck_dv_prod_ent_ai    CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_prod_entity_uwi   ON dataview.dv_prod_entity(uwi);
CREATE INDEX ix_dv_prod_entity_field ON dataview.dv_prod_entity(field_id);
GO

CREATE TABLE dataview.dv_prod_volume (
    prod_entity_id          NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_prod_entity(prod_entity_id),
    period_date             NVARCHAR(7)     NOT NULL,   -- YYYY-MM monthly bucket
    fluid_type              NVARCHAR(40)    NOT NULL,   -- OIL, GAS, WATER, COND, INJ …
    volume                  NUMERIC(20,4)   NULL,
    volume_ouom             NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    days_on_prod            NUMERIC(5,2)    NULL,
    avg_daily_rate          NUMERIC(20,4)   NULL,
    rate_ouom               NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_prod_volume    PRIMARY KEY (prod_entity_id, period_date, fluid_type),
    CONSTRAINT ck_dv_prod_vol_ai    CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_prod_vol_entity ON dataview.dv_prod_volume(prod_entity_id);
CREATE INDEX ix_dv_prod_vol_date   ON dataview.dv_prod_volume(period_date);
GO

-- =============================================================================
-- 10. FILE CATALOG  (v2 las_catalog + file_catalog unified into dataview)
-- =============================================================================

-- Well log file catalog: LAS / DLIS / LIS
CREATE TABLE dataview.dv_wl_file_catalog (
    catalog_id              NVARCHAR(40)    NOT NULL,   -- SHA1 of full_path
    uwi                     NVARCHAR(40)    NULL REFERENCES dataview.dv_well(uwi),
    full_path               NVARCHAR(1000)  NOT NULL,
    file_name               NVARCHAR(500)   NOT NULL,
    file_ext                NVARCHAR(20)    NULL,
    file_size_kb            NUMERIC(15,2)   NULL,
    file_hash               NVARCHAR(64)    NULL,
    file_format             NVARCHAR(20)    NULL,   -- LAS, DLIS, LIS
    las_version             NVARCHAR(10)    NULL,
    well_name_in_file       NVARCHAR(255)   NULL,
    uwi_in_file             NVARCHAR(40)    NULL,
    service_company         NVARCHAR(255)   NULL,
    log_date                DATETIME2       NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL,
    curve_count             INT             NULL,
    curve_list              NVARCHAR(2000)  NULL,   -- comma-separated mnemonics
    ppdm_loaded_ind         NVARCHAR(1)     NOT NULL DEFAULT 'N',
    ppdm_log_id             NVARCHAR(40)    NULL,   -- soft FK to dv_well_log.log_id
    catalog_status          NVARCHAR(20)    NULL,   -- CATALOGED, PENDING, SKIPPED, ERROR
    catalog_date            DATETIME2       NULL,
    error_msg               NVARCHAR(2000)  NULL,
    root_path               NVARCHAR(500)   NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_wl_file_catalog    PRIMARY KEY (catalog_id),
    CONSTRAINT ck_dv_wl_ppdm_loaded     CHECK (ppdm_loaded_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_wl_cat_uwi    ON dataview.dv_wl_file_catalog(uwi);
CREATE INDEX ix_dv_wl_cat_name   ON dataview.dv_wl_file_catalog(file_name);
CREATE INDEX ix_dv_wl_cat_status ON dataview.dv_wl_file_catalog(catalog_status);
CREATE INDEX ix_dv_wl_cat_root   ON dataview.dv_wl_file_catalog(root_path);
GO

-- Seismic file catalog: SEG-Y / P190
CREATE TABLE dataview.dv_seis_file_catalog (
    catalog_id              NVARCHAR(40)    NOT NULL,   -- SHA1 of full_path
    seis_set_id             NVARCHAR(40)    NULL REFERENCES dataview.dv_seis_set(seis_set_id),
    full_path               NVARCHAR(1000)  NOT NULL,
    file_name               NVARCHAR(500)   NOT NULL,
    file_ext                NVARCHAR(20)    NULL,
    file_size_kb            NUMERIC(15,2)   NULL,
    file_hash               NVARCHAR(64)    NULL,
    file_format             NVARCHAR(20)    NULL,   -- SEGY, P190, SEG2 …
    segy_revision           NVARCHAR(10)    NULL,
    trace_count             INT             NULL,
    sample_rate_ms          NUMERIC(10,4)   NULL,
    record_length_ms        NUMERIC(10,3)   NULL,
    line_name_in_file       NVARCHAR(255)   NULL,
    survey_name_in_file     NVARCHAR(255)   NULL,
    shot_point_count        INT             NULL,
    catalog_status          NVARCHAR(20)    NULL,   -- CATALOGED, PENDING, SKIPPED, ERROR
    catalog_date            DATETIME2       NULL,
    error_msg               NVARCHAR(2000)  NULL,
    root_path               NVARCHAR(500)   NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_seis_file_catalog  PRIMARY KEY (catalog_id)
);
CREATE INDEX ix_dv_seis_cat_set    ON dataview.dv_seis_file_catalog(seis_set_id);
CREATE INDEX ix_dv_seis_cat_name   ON dataview.dv_seis_file_catalog(file_name);
CREATE INDEX ix_dv_seis_cat_status ON dataview.dv_seis_file_catalog(catalog_status);
GO

-- Global file catalog: master inventory across all file types
CREATE TABLE dataview.dv_global_file_catalog (
    inventory_id            NVARCHAR(40)    NOT NULL,   -- SHA1 of full_path
    full_path               NVARCHAR(1000)  NOT NULL,
    file_name               NVARCHAR(500)   NOT NULL,
    file_ext                NVARCHAR(20)    NULL,
    file_size_kb            NUMERIC(15,2)   NULL,
    file_hash               NVARCHAR(64)    NULL,       -- first-64KB SHA1
    file_hash_full          NVARCHAR(64)    NULL,       -- full-file SHA1 (optional)
    duplicate_group         NVARCHAR(64)    NULL,       -- matches file_hash if duplicate
    modified_date           DATETIME2       NULL,
    scan_date               DATETIME2       NOT NULL,
    doc_type_group          NVARCHAR(40)    NULL,   -- Well Logs, Seismic, Spatial, PDF Reports, Office Docs …
    doc_type                NVARCHAR(40)    NULL,   -- LAS, SEGY, P190, SHP, PDF, EXCEL, WORD, UNKNOWN
    catalog_status          NVARCHAR(20)    NULL,   -- CATALOGED, UNCATALOGED, SKIPPED
    catalog_table           NVARCHAR(80)    NULL,   -- dv_wl_file_catalog / dv_seis_file_catalog
    catalog_id              NVARCHAR(40)    NULL,   -- soft FK into catalog_table
    ppdm_loaded_ind         NVARCHAR(1)     NOT NULL DEFAULT 'N',
    root_path               NVARCHAR(500)   NULL,
    uwi                     NVARCHAR(40)    NULL,   -- matched well (nullable — no hard FK)
    well_name               NVARCHAR(255)   NULL,   -- extracted from file header
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_global_file_catalog    PRIMARY KEY (inventory_id),
    CONSTRAINT ck_dv_gfc_ppdm_loaded        CHECK (ppdm_loaded_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_gfc_uwi     ON dataview.dv_global_file_catalog(uwi);
CREATE INDEX ix_dv_gfc_status  ON dataview.dv_global_file_catalog(catalog_status);
CREATE INDEX ix_dv_gfc_root    ON dataview.dv_global_file_catalog(root_path);
CREATE INDEX ix_dv_gfc_type    ON dataview.dv_global_file_catalog(doc_type_group, doc_type);
CREATE INDEX ix_dv_gfc_dupes   ON dataview.dv_global_file_catalog(duplicate_group);
GO

-- =============================================================================
-- 11. SPATIAL
-- =============================================================================

CREATE TABLE dataview.dv_spatial_layer (
    layer_id                NVARCHAR(40)    NOT NULL,
    layer_name              NVARCHAR(255)   NOT NULL,
    layer_type              NVARCHAR(40)    NULL,   -- POINT, LINE, POLYGON, RASTER …
    layer_category          NVARCHAR(40)    NULL,   -- WELL, PIPELINE, BOUNDARY, SEISMIC …
    epsg_code               INT             DEFAULT 4326,
    file_path               NVARCHAR(1000)  NULL,   -- vault-relative path
    feature_count           INT             NULL,
    bbox_min_lat            NUMERIC(15,10)  NULL,
    bbox_max_lat            NUMERIC(15,10)  NULL,
    bbox_min_lon            NUMERIC(15,10)  NULL,
    bbox_max_lon            NUMERIC(15,10)  NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_spatial_layer  PRIMARY KEY (layer_id),
    CONSTRAINT ck_dv_spatial_ai     CHECK (active_ind IN ('Y','N'))
);
GO

-- =============================================================================
-- 12. AUDIT / PIPELINE
-- =============================================================================

CREATE TABLE dataview.dv_load_batch (
    batch_id                NVARCHAR(40)    NOT NULL,
    batch_date              DATETIME2       NOT NULL DEFAULT GETDATE(),
    source_file             NVARCHAR(1000)  NULL,
    source_file_hash        NVARCHAR(64)    NULL,
    file_type               NVARCHAR(40)    NULL,   -- LAS, CSV, XLSX, SHP, JSON …
    dialect                 NVARCHAR(20)    NULL,   -- mssql, oracle, snowflake
    target_schema           NVARCHAR(40)    NULL,   -- dataview, dbo, DEMO …
    target_table            NVARCHAR(100)   NULL,
    rows_staged             INT             NULL,
    rows_promoted           INT             NULL,
    rows_rejected           INT             NULL,
    status                  NVARCHAR(20)    NULL,   -- PENDING, RUNNING, COMPLETE, ERROR
    error_msg               NVARCHAR(2000)  NULL,
    duration_sec            NUMERIC(10,2)   NULL,
    operator_ba_id          NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_load_batch     PRIMARY KEY (batch_id)
);
CREATE INDEX ix_dv_load_batch_date   ON dataview.dv_load_batch(batch_date);
CREATE INDEX ix_dv_load_batch_status ON dataview.dv_load_batch(status);
GO

CREATE TABLE dataview.dv_column_map (
    map_id                  NVARCHAR(40)    NOT NULL,
    source_file_pattern     NVARCHAR(255)   NULL,   -- glob matched to filename
    source_column           NVARCHAR(255)   NOT NULL,
    target_table            NVARCHAR(100)   NOT NULL,
    target_column           NVARCHAR(100)   NOT NULL,
    confidence_score        NUMERIC(5,4)    NULL,   -- 0.0000 – 1.0000
    mapping_method          NVARCHAR(20)    NULL,   -- ML, MANUAL, RULE
    confirmed_ind           NVARCHAR(1)     NOT NULL DEFAULT 'N',
    confirmed_by            NVARCHAR(40)    NULL,
    confirmed_date          DATETIME2       NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_column_map     PRIMARY KEY (map_id),
    CONSTRAINT ck_dv_colmap_conf    CHECK (confirmed_ind IN ('Y','N')),
    CONSTRAINT ck_dv_colmap_ai      CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_colmap_target ON dataview.dv_column_map(target_table, target_column);
GO

CREATE TABLE dataview.dv_data_quality (
    dq_id                   NVARCHAR(40)    NOT NULL,
    entity_type             NVARCHAR(40)    NOT NULL,   -- WELL, SURVEY, FORMATION_TOP …
    entity_id               NVARCHAR(40)    NOT NULL,
    rule_name               NVARCHAR(100)   NOT NULL,
    rule_type               NVARCHAR(40)    NULL,   -- COMPLETENESS, VALIDITY, UNIQUENESS …
    result                  NVARCHAR(10)    NULL,   -- PASS, FAIL, WARN
    dq_score                NUMERIC(5,4)    NULL,
    detail                  NVARCHAR(2000)  NULL,
    check_date              DATETIME2       NOT NULL DEFAULT GETDATE(),
    batch_id                NVARCHAR(40)    NULL REFERENCES dataview.dv_load_batch(batch_id),
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_data_quality   PRIMARY KEY (dq_id)
);
CREATE INDEX ix_dv_dq_entity ON dataview.dv_data_quality(entity_type, entity_id);
CREATE INDEX ix_dv_dq_result ON dataview.dv_data_quality(result);
GO

-- =============================================================================
-- 13. POLITICAL TABLES
-- Seed sources: Census TIGER, GADM, BLM PLSS, BOEM, NRCan
-- =============================================================================

CREATE TABLE dataview.dv_country (
    country_code            NVARCHAR(3)     NOT NULL,   -- ISO 3166-1 alpha-3 (USA, CAN, GBR …)
    country_code_a2         NVARCHAR(2)     NULL,       -- ISO 3166-1 alpha-2 (US, CA, GB …)
    country_name            NVARCHAR(255)   NOT NULL,
    country_name_local      NVARCHAR(255)   NULL,
    continent               NVARCHAR(40)    NULL,
    region                  NVARCHAR(100)   NULL,
    un_m49_code             NVARCHAR(10)    NULL,
    currency_code           NVARCHAR(3)     NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_country        PRIMARY KEY (country_code),
    CONSTRAINT ck_dv_country_ai     CHECK (active_ind IN ('Y','N'))
);
GO

CREATE TABLE dataview.dv_province_state (
    province_state_id       NVARCHAR(10)    NOT NULL,   -- ISO 3166-2 (US-TX, CA-AB …)
    country_code            NVARCHAR(3)     NOT NULL REFERENCES dataview.dv_country(country_code),
    province_state_name     NVARCHAR(255)   NOT NULL,
    province_state_abbrev   NVARCHAR(10)    NULL,
    province_state_type     NVARCHAR(40)    NULL,   -- STATE, PROVINCE, TERRITORY …
    fips_code               NVARCHAR(5)     NULL,   -- US FIPS state code
    capital_city            NVARCHAR(100)   NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_province_state PRIMARY KEY (province_state_id),
    CONSTRAINT ck_dv_ps_ai          CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_ps_country ON dataview.dv_province_state(country_code);
GO

CREATE TABLE dataview.dv_county (
    county_id               NVARCHAR(40)    NOT NULL,   -- country|state_fips|county_fips
    province_state_id       NVARCHAR(10)    NOT NULL REFERENCES dataview.dv_province_state(province_state_id),
    country_code            NVARCHAR(3)     NOT NULL REFERENCES dataview.dv_country(country_code),
    county_name             NVARCHAR(255)   NOT NULL,
    county_type             NVARCHAR(40)    NULL,   -- COUNTY, PARISH, BOROUGH, DISTRICT …
    fips_state_code         NVARCHAR(3)     NULL,
    fips_county_code        NVARCHAR(3)     NULL,
    fips_full               NVARCHAR(5)     NULL,   -- 5-digit FIPS (state + county)
    tiger_geoid             NVARCHAR(20)    NULL,   -- Census TIGER GEOID
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_county         PRIMARY KEY (county_id),
    CONSTRAINT ck_dv_county_ai      CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_county_state ON dataview.dv_county(province_state_id);
CREATE INDEX ix_dv_county_fips  ON dataview.dv_county(fips_full);
GO

CREATE TABLE dataview.dv_basin (
    basin_id                NVARCHAR(40)    NOT NULL,
    basin_name              NVARCHAR(255)   NOT NULL,
    basin_type              NVARCHAR(40)    NULL,   -- SEDIMENTARY, FORELAND, RIFT, PASSIVE MARGIN …
    country_code            NVARCHAR(3)     NULL REFERENCES dataview.dv_country(country_code),
    region                  NVARCHAR(100)   NULL,
    area_km2                NUMERIC(15,4)   NULL,
    centroid_latitude       NUMERIC(15,10)  NULL,
    centroid_longitude      NUMERIC(15,10)  NULL,
    primary_play_type       NVARCHAR(40)    NULL,   -- CONVENTIONAL, UNCONVENTIONAL, MIXED
    gdm_basin_id            NVARCHAR(40)    NULL,   -- external GDM / IHS reference
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_basin          PRIMARY KEY (basin_id),
    CONSTRAINT ck_dv_basin_ai       CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_basin_name    ON dataview.dv_basin(basin_name);
CREATE INDEX ix_dv_basin_country ON dataview.dv_basin(country_code);
GO

CREATE TABLE dataview.dv_plss_township (
    plss_id                 NVARCHAR(20)    NOT NULL,   -- BLM TownID e.g. TX01234567
    state_fips              NVARCHAR(3)     NULL,
    township_num            NVARCHAR(10)    NULL,       -- T04N
    range_num               NVARCHAR(10)    NULL,       -- R14W
    section_num             NVARCHAR(5)     NULL,
    principal_meridian      NVARCHAR(40)    NULL,       -- BLACK HILLS, CIMARRON, SIXTH …
    county_id               NVARCHAR(40)    NULL REFERENCES dataview.dv_county(county_id),
    province_state_id       NVARCHAR(10)    NULL REFERENCES dataview.dv_province_state(province_state_id),
    township_label          NVARCHAR(100)   NULL,       -- T04N R14W Sec 22 (display)
    centroid_latitude       NUMERIC(15,10)  NULL,
    centroid_longitude      NUMERIC(15,10)  NULL,
    bbox_wkt                NVARCHAR(500)   NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_plss_township  PRIMARY KEY (plss_id),
    CONSTRAINT ck_dv_plss_ai        CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_plss_state  ON dataview.dv_plss_township(province_state_id);
CREATE INDEX ix_dv_plss_county ON dataview.dv_plss_township(county_id);
GO

CREATE TABLE dataview.dv_ocs_block (
    ocs_block_id            NVARCHAR(20)    NOT NULL,   -- BOEM block e.g. GC00405
    planning_area           NVARCHAR(100)   NULL,       -- Gulf of Mexico Central …
    area_code               NVARCHAR(10)    NULL,       -- GC, WG, EB, GB, AT, PC …
    block_num               NVARCHAR(10)    NULL,
    block_name              NVARCHAR(255)   NULL,
    protraction_name        NVARCHAR(255)   NULL,       -- BOEM map sheet name
    water_depth_m           NUMERIC(10,2)   NULL,
    country_code            NVARCHAR(3)     NULL REFERENCES dataview.dv_country(country_code),
    centroid_latitude       NUMERIC(15,10)  NULL,
    centroid_longitude      NUMERIC(15,10)  NULL,
    bbox_wkt                NVARCHAR(500)   NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_ocs_block      PRIMARY KEY (ocs_block_id),
    CONSTRAINT ck_dv_ocs_ai         CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_ocs_area ON dataview.dv_ocs_block(area_code, block_num);
GO

-- =============================================================================
-- SUMMARY
-- =============================================================================
-- Schema   : dataview
-- Tables   : 32
--
-- Reference  (4) : dv_r_source, dv_r_well_type, dv_r_well_status, dv_r_uom
-- Entity     (3) : dv_source, dv_business_associate, dv_field
-- Well       (2) : dv_well, dv_well_alias
-- Survey     (2) : dv_well_dir_srvy_hdr, dv_well_dir_srvy_sta
-- Strat      (2) : dv_well_formation_top, dv_strat_interval
-- Logs       (2) : dv_well_log, dv_well_log_curve
-- Seismic    (2) : dv_seis_set, dv_seis_line
-- Production (2) : dv_prod_entity, dv_prod_volume
-- File Cat   (3) : dv_wl_file_catalog, dv_seis_file_catalog, dv_global_file_catalog
-- Spatial    (1) : dv_spatial_layer
-- Audit      (3) : dv_load_batch, dv_column_map, dv_data_quality
-- Political  (6) : dv_country, dv_province_state, dv_county, dv_basin,
--                  dv_plss_township, dv_ocs_block
-- =============================================================================
PRINT 'DataView schema created — 32 tables in dataview schema.';
GO

-- =============================================================================
IF OBJECT_ID('dataview.dv_well_shows',       'U') IS NOT NULL DROP TABLE dataview.dv_well_shows;
IF OBJECT_ID('dataview.dv_well_mud_log',     'U') IS NOT NULL DROP TABLE dataview.dv_well_mud_log;
IF OBJECT_ID('dataview.dv_well_casing',      'U') IS NOT NULL DROP TABLE dataview.dv_well_casing;
IF OBJECT_ID('dataview.dv_well_stimulation', 'U') IS NOT NULL DROP TABLE dataview.dv_well_stimulation;
IF OBJECT_ID('dataview.dv_well_perforation', 'U') IS NOT NULL DROP TABLE dataview.dv_well_perforation;
IF OBJECT_ID('dataview.dv_well_completion',  'U') IS NOT NULL DROP TABLE dataview.dv_well_completion;
IF OBJECT_ID('dataview.dv_well_pressure',    'U') IS NOT NULL DROP TABLE dataview.dv_well_pressure;
IF OBJECT_ID('dataview.dv_well_dst_period',  'U') IS NOT NULL DROP TABLE dataview.dv_well_dst_period;
IF OBJECT_ID('dataview.dv_well_dst',         'U') IS NOT NULL DROP TABLE dataview.dv_well_dst;
IF OBJECT_ID('dataview.dv_well_core_photo',  'U') IS NOT NULL DROP TABLE dataview.dv_well_core_photo;
IF OBJECT_ID('dataview.dv_well_core_sample', 'U') IS NOT NULL DROP TABLE dataview.dv_well_core_sample;
IF OBJECT_ID('dataview.dv_well_core',        'U') IS NOT NULL DROP TABLE dataview.dv_well_core;
GO

-- =============================================================================
-- CORE
-- PPDM: WELL_CORE (header) + WELL_CORE_SAMPLE (plug / sidewall sample)
-- =============================================================================

CREATE TABLE dataview.dv_well_core (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    core_id                 NVARCHAR(40)    NOT NULL,
    core_num                NVARCHAR(10)    NULL,        -- run number (1, 2, 3 …)
    core_type               NVARCHAR(40)    NULL,        -- CONVENTIONAL, SIDEWALL, ROTARY_SIDEWALL, DIAMOND
    core_show               NVARCHAR(40)    NULL,        -- OIL, GAS, WATER, NONE, TRACE
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    depth_datum             NVARCHAR(40)    NULL,
    core_length             NUMERIC(15,4)   NULL,        -- attempted cut length
    recovery_length         NUMERIC(15,4)   NULL,        -- actual recovered length
    recovery_pct            NUMERIC(6,2)    NULL,        -- recovery %
    length_ouom             NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    core_date               DATETIME2       NULL,
    cutting_company_ba_id   NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    analysis_company_ba_id  NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    strat_unit_name         NVARCHAR(255)   NULL,        -- formation cored
    file_path               NVARCHAR(1000)  NULL,        -- vault path to core report / photos
    -- Photo summary (detail in dv_well_core_photo)
    photo_count             INT             NULL,        -- total photos for this core run
    photo_folder_path       NVARCHAR(1000)  NULL,        -- vault folder containing all tray photos
    has_uv_photos           NVARCHAR(1)     NOT NULL DEFAULT 'N',   -- UV fluorescence photos available
    has_thin_section_photos NVARCHAR(1)     NOT NULL DEFAULT 'N',   -- thin section / petrographic photos
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_core      PRIMARY KEY (uwi, core_id),
    CONSTRAINT ck_dv_core_ai        CHECK (active_ind IN ('Y','N')),
    CONSTRAINT ck_dv_core_uv        CHECK (has_uv_photos IN ('Y','N')),
    CONSTRAINT ck_dv_core_ts        CHECK (has_thin_section_photos IN ('Y','N'))
);
CREATE INDEX ix_dv_core_uwi ON dataview.dv_well_core(uwi);
GO

CREATE TABLE dataview.dv_well_core_sample (
    uwi                     NVARCHAR(40)    NOT NULL,
    core_id                 NVARCHAR(40)    NOT NULL,
    sample_id               NVARCHAR(40)    NOT NULL,
    sample_type             NVARCHAR(40)    NULL,        -- PLUG, SIDEWALL, CHIP, FULL_DIAMETER
    sample_depth            NUMERIC(15,4)   NULL,        -- mid-point depth
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    -- Routine core analysis (RCA)
    porosity_frac           NUMERIC(10,6)   NULL,        -- fraction 0–1
    permeability_air_md     NUMERIC(15,4)   NULL,        -- air perm mD
    permeability_klinkenberg_md NUMERIC(15,4) NULL,      -- Klinkenberg-corrected mD
    water_saturation_frac   NUMERIC(10,6)   NULL,
    grain_density_g_cc      NUMERIC(10,4)   NULL,
    bulk_density_g_cc       NUMERIC(10,4)   NULL,
    -- Special core analysis (SCAL) — nullable
    oil_saturation_frac     NUMERIC(10,6)   NULL,
    gas_saturation_frac     NUMERIC(10,6)   NULL,
    formation_factor        NUMERIC(15,4)   NULL,
    cementation_exponent    NUMERIC(10,4)   NULL,        -- m
    saturation_exponent     NUMERIC(10,4)   NULL,        -- n
    -- Lithology
    lithology               NVARCHAR(100)   NULL,
    visual_porosity         NVARCHAR(40)    NULL,        -- TIGHT, FAIR, GOOD, EXCELLENT
    hydrocarbon_show        NVARCHAR(40)    NULL,        -- OIL STAIN, GAS CUT, NONE …
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_core_sample   PRIMARY KEY (uwi, core_id, sample_id),
    CONSTRAINT fk_core_sample_core      FOREIGN KEY (uwi, core_id)
        REFERENCES dataview.dv_well_core(uwi, core_id),
    CONSTRAINT ck_dv_core_sample_ai     CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_core_sample_uwi ON dataview.dv_well_core_sample(uwi);
GO

-- Individual core photos (tray, slab, UV, thin section, plug)
CREATE TABLE dataview.dv_well_core_photo (
    uwi                     NVARCHAR(40)    NOT NULL,
    core_id                 NVARCHAR(40)    NOT NULL,
    photo_id                NVARCHAR(40)    NOT NULL,   -- SHA1 of file_path
    photo_type              NVARCHAR(40)    NULL,       -- TRAY, SLAB, UV, THIN_SECTION, PLUG, SIDEWALL, OVERVIEW
    lighting                NVARCHAR(20)    NULL,       -- WHITE, UV, CROSS_POL, PLANE_POL
    top_depth               NUMERIC(15,4)   NULL,       -- depth represented by photo
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    tray_num                INT             NULL,        -- tray/box number in core set
    photo_date              DATETIME2       NULL,
    file_path               NVARCHAR(1000)  NOT NULL,   -- vault-relative path to image
    file_name               NVARCHAR(500)   NULL,
    file_ext                NVARCHAR(20)    NULL,       -- .jpg, .tif, .png …
    file_size_kb            NUMERIC(15,2)   NULL,
    file_hash               NVARCHAR(64)    NULL,       -- SHA1 for dedup
    resolution_dpi          INT             NULL,
    width_px                INT             NULL,
    height_px               INT             NULL,
    -- Link to sample if photo is of a specific plug/sidewall
    sample_id               NVARCHAR(40)    NULL,       -- soft FK to dv_well_core_sample
    -- Catalogue status
    catalog_id              NVARCHAR(40)    NULL,       -- soft FK to dv_global_file_catalog
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_core_photo    PRIMARY KEY (uwi, core_id, photo_id),
    CONSTRAINT fk_core_photo_core       FOREIGN KEY (uwi, core_id)
        REFERENCES dataview.dv_well_core(uwi, core_id),
    CONSTRAINT ck_dv_core_photo_ai      CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_core_photo_uwi   ON dataview.dv_well_core_photo(uwi);
CREATE INDEX ix_dv_core_photo_type  ON dataview.dv_well_core_photo(photo_type);
CREATE INDEX ix_dv_core_photo_depth ON dataview.dv_well_core_photo(uwi, top_depth, base_depth);
GO

-- =============================================================================
-- DRILL STEM TEST (DST)
-- PPDM: WELL_TEST (header) + WELL_TEST_PERIOD (flow/shut-in periods)
-- =============================================================================

CREATE TABLE dataview.dv_well_dst (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    dst_id                  NVARCHAR(40)    NOT NULL,
    dst_num                 NVARCHAR(10)    NULL,        -- test number
    test_type               NVARCHAR(40)    NULL,        -- DST, RFT, MDT, WFT, PRODUCTION_TEST
    test_date               DATETIME2       NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    depth_datum             NVARCHAR(40)    NULL,
    strat_unit_name         NVARCHAR(255)   NULL,        -- zone tested
    tool_type               NVARCHAR(40)    NULL,        -- OPEN_HOLE, CASED_HOLE
    perforation_top         NUMERIC(15,4)   NULL,
    perforation_base        NUMERIC(15,4)   NULL,
    -- Summary results
    max_shut_in_pressure    NUMERIC(15,4)   NULL,
    final_shut_in_pressure  NUMERIC(15,4)   NULL,
    pressure_ouom           NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    max_oil_rate            NUMERIC(15,4)   NULL,
    max_gas_rate            NUMERIC(15,4)   NULL,
    max_water_rate          NUMERIC(15,4)   NULL,
    rate_ouom               NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    gor                     NUMERIC(15,4)   NULL,        -- gas-oil ratio
    api_gravity             NUMERIC(6,2)    NULL,
    h2s_pct                 NUMERIC(8,4)    NULL,
    co2_pct                 NUMERIC(8,4)    NULL,
    test_result             NVARCHAR(40)    NULL,        -- OIL, GAS, WATER, DRY, INCONCLUSIVE
    contractor_ba_id        NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    file_path               NVARCHAR(1000)  NULL,        -- vault path to DST report
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_dst       PRIMARY KEY (uwi, dst_id),
    CONSTRAINT ck_dv_dst_ai         CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_dst_uwi ON dataview.dv_well_dst(uwi);
GO

CREATE TABLE dataview.dv_well_dst_period (
    uwi                     NVARCHAR(40)    NOT NULL,
    dst_id                  NVARCHAR(40)    NOT NULL,
    period_id               NVARCHAR(40)    NOT NULL,
    period_type             NVARCHAR(40)    NULL,        -- IFP, FF, ISI, FSI, FLOW, SHUT_IN
    period_seq              INT             NULL,        -- sequence number
    duration_min            NUMERIC(10,2)   NULL,        -- duration minutes
    start_pressure          NUMERIC(15,4)   NULL,
    end_pressure            NUMERIC(15,4)   NULL,
    pressure_ouom           NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    avg_oil_rate            NUMERIC(15,4)   NULL,
    avg_gas_rate            NUMERIC(15,4)   NULL,
    avg_water_rate          NUMERIC(15,4)   NULL,
    rate_ouom               NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    choke_size              NVARCHAR(20)    NULL,        -- e.g. 16/64"
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_dst_period    PRIMARY KEY (uwi, dst_id, period_id),
    CONSTRAINT fk_dst_period_dst        FOREIGN KEY (uwi, dst_id)
        REFERENCES dataview.dv_well_dst(uwi, dst_id)
);
CREATE INDEX ix_dv_dst_period_uwi ON dataview.dv_well_dst_period(uwi);
GO

-- Standalone pressure points (RFT / MDT / static BHP)
CREATE TABLE dataview.dv_well_pressure (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    pressure_id             NVARCHAR(40)    NOT NULL,
    pressure_type           NVARCHAR(40)    NULL,        -- RFT, MDT, BHP, BHT, STATIC, GRADIENT
    test_date               DATETIME2       NULL,
    depth                   NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    depth_datum             NVARCHAR(40)    NULL,
    pressure                NUMERIC(15,4)   NULL,
    pressure_ouom           NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    temperature             NUMERIC(10,4)   NULL,
    temperature_ouom        NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    fluid_type              NVARCHAR(40)    NULL,        -- OIL, GAS, WATER, MUD
    mobility                NUMERIC(15,4)   NULL,        -- mD/cP
    strat_unit_name         NVARCHAR(255)   NULL,
    tool_type               NVARCHAR(40)    NULL,        -- RFT, MDT, FIT, LOT
    contractor_ba_id        NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_pressure  PRIMARY KEY (uwi, pressure_id),
    CONSTRAINT ck_dv_pressure_ai    CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_pressure_uwi   ON dataview.dv_well_pressure(uwi);
CREATE INDEX ix_dv_pressure_depth ON dataview.dv_well_pressure(uwi, depth);
GO

-- =============================================================================
-- COMPLETION
-- PPDM: WELL_COMPLETION (header) + WELL_PERFORATION + WELL_STIMULATION
-- =============================================================================

CREATE TABLE dataview.dv_well_completion (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    completion_id           NVARCHAR(40)    NOT NULL,
    completion_type         NVARCHAR(40)    NULL,        -- OPENHOLE, CASED_PERFORATED, GRAVEL_PACK, LINER …
    completion_date         DATETIME2       NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    depth_datum             NVARCHAR(40)    NULL,
    strat_unit_name         NVARCHAR(255)   NULL,        -- producing zone
    completion_status       NVARCHAR(40)    NULL,        -- ACTIVE, ABANDONED, SUSPENDED, PLUGGED
    primary_fluid           NVARCHAR(40)    NULL,        -- OIL, GAS, WATER, CONDENSATE
    tubing_size_in          NUMERIC(6,3)    NULL,
    tubing_depth            NUMERIC(15,4)   NULL,
    artificial_lift_type    NVARCHAR(40)    NULL,        -- ESP, GL, PCP, SUCKER_ROD, NONE
    operator_ba_id          NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    contractor_ba_id        NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_completion    PRIMARY KEY (uwi, completion_id),
    CONSTRAINT ck_dv_completion_ai      CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_completion_uwi ON dataview.dv_well_completion(uwi);
GO

CREATE TABLE dataview.dv_well_perforation (
    uwi                     NVARCHAR(40)    NOT NULL,
    completion_id           NVARCHAR(40)    NOT NULL,
    perf_id                 NVARCHAR(40)    NOT NULL,
    perf_date               DATETIME2       NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    shot_count              INT             NULL,        -- number of shots
    shot_density            NUMERIC(8,2)    NULL,        -- shots per foot/metre
    shot_density_ouom       NVARCHAR(40)    NULL,        -- SPF, SPM
    perf_diameter_in        NUMERIC(6,3)    NULL,
    gun_type                NVARCHAR(100)   NULL,
    phasing_deg             NUMERIC(6,1)    NULL,        -- 60, 90, 120, 180 degrees
    strat_unit_name         NVARCHAR(255)   NULL,
    perf_status             NVARCHAR(40)    NULL,        -- OPEN, SQUEEZED, ABANDONED
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_perforation   PRIMARY KEY (uwi, completion_id, perf_id),
    CONSTRAINT fk_perf_completion       FOREIGN KEY (uwi, completion_id)
        REFERENCES dataview.dv_well_completion(uwi, completion_id),
    CONSTRAINT ck_dv_perf_ai            CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_perf_uwi ON dataview.dv_well_perforation(uwi);
GO

CREATE TABLE dataview.dv_well_stimulation (
    uwi                     NVARCHAR(40)    NOT NULL,
    completion_id           NVARCHAR(40)    NOT NULL,
    stim_id                 NVARCHAR(40)    NOT NULL,
    stim_type               NVARCHAR(40)    NULL,        -- HYDRAULIC_FRAC, ACID, MATRIX_ACID, REFRAC
    stim_date               DATETIME2       NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    stage_count             INT             NULL,
    -- Fluid
    fluid_type              NVARCHAR(100)   NULL,        -- SLICKWATER, CROSSLINK, HYBRID, ACID …
    fluid_volume            NUMERIC(15,2)   NULL,
    fluid_volume_ouom       NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    -- Proppant
    proppant_type           NVARCHAR(100)   NULL,        -- SAND, RESIN_COATED, CERAMIC
    proppant_mesh           NVARCHAR(20)    NULL,        -- 30/50, 40/70, 100 mesh
    proppant_mass           NUMERIC(15,2)   NULL,
    proppant_mass_ouom      NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    -- Treating pressure / rate
    max_treating_pressure   NUMERIC(15,4)   NULL,
    avg_treating_pressure   NUMERIC(15,4)   NULL,
    pressure_ouom           NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    max_pump_rate           NUMERIC(15,4)   NULL,
    rate_ouom               NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    -- ISIP / closure
    isip                    NUMERIC(15,4)   NULL,        -- instantaneous shut-in pressure
    closure_pressure        NUMERIC(15,4)   NULL,
    contractor_ba_id        NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    service_co_ba_id        NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    file_path               NVARCHAR(1000)  NULL,        -- vault path to frac report
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_stimulation   PRIMARY KEY (uwi, completion_id, stim_id),
    CONSTRAINT fk_stim_completion       FOREIGN KEY (uwi, completion_id)
        REFERENCES dataview.dv_well_completion(uwi, completion_id),
    CONSTRAINT ck_dv_stim_ai            CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_stim_uwi ON dataview.dv_well_stimulation(uwi);
GO

-- =============================================================================
-- CASING / TUBULARS
-- PPDM: WELL_CASING
-- =============================================================================

CREATE TABLE dataview.dv_well_casing (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    casing_id               NVARCHAR(40)    NOT NULL,
    casing_type             NVARCHAR(40)    NULL,   -- CONDUCTOR, SURFACE, INTERMEDIATE, PRODUCTION, LINER, TIEBACK
    string_num              INT             NULL,   -- 1 = outermost
    set_date                DATETIME2       NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    depth_datum             NVARCHAR(40)    NULL,
    od_in                   NUMERIC(8,3)    NULL,   -- outer diameter inches
    weight_lb_ft            NUMERIC(8,3)    NULL,   -- lb/ft
    grade                   NVARCHAR(20)    NULL,   -- J55, K55, N80, P110 …
    connection_type         NVARCHAR(40)    NULL,   -- BTC, LTC, PH6, VAM …
    cement_top              NUMERIC(15,4)   NULL,
    cement_base             NUMERIC(15,4)   NULL,
    cement_volume_sacks     NUMERIC(10,2)   NULL,
    cement_type             NVARCHAR(100)   NULL,
    burst_rating_psi        NUMERIC(10,2)   NULL,
    collapse_rating_psi     NUMERIC(10,2)   NULL,
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_casing    PRIMARY KEY (uwi, casing_id),
    CONSTRAINT ck_dv_casing_ai      CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_casing_uwi  ON dataview.dv_well_casing(uwi);
CREATE INDEX ix_dv_casing_type ON dataview.dv_well_casing(uwi, casing_type);
GO

-- =============================================================================
-- MUD LOG
-- PPDM: no direct equivalent — custom DataView tables
-- =============================================================================

CREATE TABLE dataview.dv_well_mud_log (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    mud_log_id              NVARCHAR(40)    NOT NULL,
    log_date                DATETIME2       NULL,
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    contractor_ba_id        NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    mud_logger_ba_id        NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    rop_avg                 NUMERIC(10,4)   NULL,        -- avg rate of penetration
    rop_ouom                NVARCHAR(40)    NULL,        -- M_HR, FT_HR
    mud_type                NVARCHAR(100)   NULL,        -- WBM, OBM, SBM
    mud_weight_avg          NUMERIC(8,3)    NULL,        -- average mud weight
    mud_weight_ouom         NVARCHAR(40)    NULL,        -- PPG, KG_M3
    file_path               NVARCHAR(1000)  NULL,        -- vault path to mud log PDF/LAS
    catalog_id              NVARCHAR(40)    NULL,        -- soft FK to dv_global_file_catalog
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_mud_log   PRIMARY KEY (uwi, mud_log_id),
    CONSTRAINT ck_dv_mud_log_ai     CHECK (active_ind IN ('Y','N'))
);
CREATE INDEX ix_dv_mud_log_uwi ON dataview.dv_well_mud_log(uwi);
GO

-- Hydrocarbon shows recorded on the mud log
CREATE TABLE dataview.dv_well_shows (
    uwi                     NVARCHAR(40)    NOT NULL,
    mud_log_id              NVARCHAR(40)    NOT NULL,
    show_id                 NVARCHAR(40)    NOT NULL,
    show_type               NVARCHAR(40)    NULL,   -- OIL, GAS, OIL_AND_GAS, CONDENSATE, FLUORESCENCE, DEAD_OIL
    show_rating             NVARCHAR(40)    NULL,   -- EXCELLENT, GOOD, FAIR, POOR, TRACE, NONE
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    strat_unit_name         NVARCHAR(255)   NULL,
    lithology               NVARCHAR(100)   NULL,
    -- Gas readings
    total_gas_units         NUMERIC(10,2)   NULL,   -- units (typically ppm or %)
    c1_pct                  NUMERIC(8,4)    NULL,   -- methane %
    c2_pct                  NUMERIC(8,4)    NULL,
    c3_pct                  NUMERIC(8,4)    NULL,
    ic4_pct                 NUMERIC(8,4)    NULL,
    nc4_pct                 NUMERIC(8,4)    NULL,
    ic5_pct                 NUMERIC(8,4)    NULL,
    nc5_pct                 NUMERIC(8,4)    NULL,
    -- Fluorescence
    fluorescence_color      NVARCHAR(40)    NULL,   -- YELLOW, WHITE, BLUE, BROWN …
    fluorescence_intensity  NVARCHAR(20)    NULL,   -- BRIGHT, MODERATE, FAINT
    cut_color               NVARCHAR(40)    NULL,
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_shows     PRIMARY KEY (uwi, mud_log_id, show_id),
    CONSTRAINT fk_shows_mud_log     FOREIGN KEY (uwi, mud_log_id)
        REFERENCES dataview.dv_well_mud_log(uwi, mud_log_id)
);
CREATE INDEX ix_dv_shows_uwi  ON dataview.dv_well_shows(uwi);
CREATE INDEX ix_dv_shows_type ON dataview.dv_well_shows(show_type);
GO

-- =============================================================================
-- SUMMARY
-- =============================================================================
-- Patch 1 adds 12 tables to the dataview schema:
--
--   Core         : dv_well_core, dv_well_core_sample, dv_well_core_photo
--   DST/Pressure : dv_well_dst, dv_well_dst_period, dv_well_pressure
--   Completion   : dv_well_completion, dv_well_perforation, dv_well_stimulation
--   Casing       : dv_well_casing
--   Mud Log      : dv_well_mud_log, dv_well_shows
--
-- Total dataview tables after patch: 44
-- =============================================================================
PRINT 'DataView Patch 1 complete — 12 well subtype tables added (44 total).';
GO

-- =============================================================================
-- DataView Schema — Patch 2
-- Petrophysical interpretation tables
-- Run AFTER dv_schema_ddl.sql + dv_schema_ddl_patch1.sql
-- Requires: dv_well, dv_business_associate, dv_r_uom, dv_r_source,
--           dv_well_log, dv_well_formation_top
-- Database : DataView
-- Created  : 2026-04-30
-- =============================================================================
-- NEW TABLES (2):
--   dv_well_petro_interp  -- petrophysical interpretation run header
--   dv_well_petro_zone    -- zone-averaged results per interpretation
-- =============================================================================

IF OBJECT_ID('dataview.dv_well_petro_zone',  'U') IS NOT NULL DROP TABLE dataview.dv_well_petro_zone;
IF OBJECT_ID('dataview.dv_well_petro_interp','U') IS NOT NULL DROP TABLE dataview.dv_well_petro_interp;
GO

-- =============================================================================
-- PETROPHYSICAL INTERPRETATION RUN
-- PPDM: WELL_INTERPRETATION
-- One row per interpretation pass per well.
-- Captures who ran it, what software, which log inputs, and key parameters.
-- =============================================================================

CREATE TABLE dataview.dv_well_petro_interp (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    interp_id               NVARCHAR(40)    NOT NULL,
    interp_name             NVARCHAR(255)   NULL,       -- descriptive name e.g. "Woodford Final 2024"
    interp_date             DATETIME2       NULL,
    analyst_ba_id           NVARCHAR(40)    NULL REFERENCES dataview.dv_business_associate(ba_id),
    software                NVARCHAR(100)   NULL,       -- Techlog, Interactive Petrophysics, Petrel, Elan …
    software_version        NVARCHAR(40)    NULL,
    -- Log inputs used
    gr_log_id               NVARCHAR(40)    NULL,       -- soft FK to dv_well_log.log_id
    res_log_id              NVARCHAR(40)    NULL,
    density_log_id          NVARCHAR(40)    NULL,
    neutron_log_id          NVARCHAR(40)    NULL,
    sonic_log_id            NVARCHAR(40)    NULL,
    other_log_inputs        NVARCHAR(500)   NULL,       -- comma-separated additional log_ids
    -- Key parameters
    formation_water_resist  NUMERIC(15,6)   NULL,       -- Rw (ohm-m)
    rw_temperature          NUMERIC(10,4)   NULL,       -- temperature at which Rw measured
    temperature_ouom        NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    archie_a                NUMERIC(10,6)   NULL,       -- tortuosity factor (default 1.0)
    archie_m                NUMERIC(10,6)   NULL,       -- cementation exponent (default 2.0)
    archie_n                NUMERIC(10,6)   NULL,       -- saturation exponent (default 2.0)
    shale_volume_method     NVARCHAR(40)    NULL,       -- GR_LINEAR, GR_LARIONOV, SP, RT …
    porosity_method         NVARCHAR(40)    NULL,       -- DENSITY, NEUTRON, SONIC, ND_CROSSPLOT …
    fluid_density_g_cc      NUMERIC(8,4)    NULL,       -- pore fluid density used
    matrix_density_g_cc     NUMERIC(8,4)    NULL,       -- matrix density used
    sw_method               NVARCHAR(40)    NULL,       -- ARCHIE, SIMANDOUX, INDONESIA, WAXMAN_SMITS …
    -- Output file
    output_file_path        NVARCHAR(1000)  NULL,       -- vault path to output LAS / project file
    interp_status           NVARCHAR(40)    NULL,       -- PRELIMINARY, FINAL, SUPERSEDED
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_petro_interp  PRIMARY KEY (uwi, interp_id),
    CONSTRAINT ck_dv_petro_interp_ai    CHECK (active_ind IN ('Y','N')),
    CONSTRAINT ck_dv_petro_interp_stat  CHECK (interp_status IN (
        'PRELIMINARY','FINAL','SUPERSEDED') OR interp_status IS NULL)
);
CREATE INDEX ix_dv_petro_interp_uwi    ON dataview.dv_well_petro_interp(uwi);
CREATE INDEX ix_dv_petro_interp_date   ON dataview.dv_well_petro_interp(interp_date);
CREATE INDEX ix_dv_petro_interp_status ON dataview.dv_well_petro_interp(interp_status);
GO

-- =============================================================================
-- ZONE-AVERAGED PETROPHYSICAL RESULTS
-- PPDM: WELL_ZONE + WELL_ZONE_VALUE (flattened into one table)
-- One row per well × zone × interpretation run.
-- FK to dv_well_formation_top links the zone to its stratigraphic pick.
-- FK to dv_well_petro_interp links back to the parameters used.
-- This is the primary deliverable from a petrophysical study.
-- =============================================================================

CREATE TABLE dataview.dv_well_petro_zone (
    uwi                     NVARCHAR(40)    NOT NULL REFERENCES dataview.dv_well(uwi),
    interp_id               NVARCHAR(40)    NOT NULL,
    zone_id                 NVARCHAR(40)    NOT NULL,
    -- Zone definition
    zone_name               NVARCHAR(255)   NULL,       -- e.g. "Wolfcamp A Upper"
    zone_type               NVARCHAR(40)    NULL,       -- RESERVOIR, NON-RESERVOIR, PAY, TOTAL
    -- Depth extents
    top_depth               NUMERIC(15,4)   NULL,
    base_depth              NUMERIC(15,4)   NULL,
    depth_ouom              NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    depth_datum             NVARCHAR(40)    NULL,
    tvd_top                 NUMERIC(15,4)   NULL,
    tvd_base                NUMERIC(15,4)   NULL,
    -- Link to stratigraphic pick (optional — zone may span multiple picks)
    strat_unit_id           NVARCHAR(40)    NULL,       -- soft FK to dv_well_formation_top
    strat_interp_id         NVARCHAR(40)    NULL,       -- soft FK to dv_well_formation_top
    strat_unit_name         NVARCHAR(255)   NULL,       -- denormalised for convenience
    -- Thickness
    gross_thickness         NUMERIC(15,4)   NULL,       -- gross interval thickness
    net_thickness           NUMERIC(15,4)   NULL,       -- net pay thickness
    net_to_gross            NUMERIC(8,6)    NULL,       -- NTG fraction 0–1
    -- Shale volume
    vsh_avg                 NUMERIC(8,6)    NULL,       -- average Vsh fraction 0–1
    vsh_min                 NUMERIC(8,6)    NULL,
    vsh_max                 NUMERIC(8,6)    NULL,
    -- Porosity
    phi_total_avg           NUMERIC(8,6)    NULL,       -- total porosity fraction
    phi_effective_avg       NUMERIC(8,6)    NULL,       -- effective porosity fraction
    phi_method              NVARCHAR(40)    NULL,       -- DENSITY, NEUTRON, ND_CROSSPLOT …
    -- Water saturation
    sw_avg                  NUMERIC(8,6)    NULL,       -- average Sw fraction 0–1
    sw_min                  NUMERIC(8,6)    NULL,
    sw_max                  NUMERIC(8,6)    NULL,
    sw_method               NVARCHAR(40)    NULL,       -- ARCHIE, SIMANDOUX …
    -- Hydrocarbon saturation
    sh_avg                  NUMERIC(8,6)    NULL,       -- Sh = 1 - Sw
    -- Permeability
    perm_avg_md             NUMERIC(15,4)   NULL,       -- arithmetic mean mD
    perm_geomean_md         NUMERIC(15,4)   NULL,       -- geometric mean mD
    perm_method             NVARCHAR(40)    NULL,       -- TIMUR, COATES, CORE_CALIBRATED …
    -- Bulk volume water / hydrocarbon
    bvw_avg                 NUMERIC(8,6)    NULL,       -- bulk volume water (phi * Sw)
    bvh_avg                 NUMERIC(8,6)    NULL,       -- bulk volume hydrocarbon (phi * Sh)
    -- Fluid type
    fluid_type              NVARCHAR(40)    NULL,       -- OIL, GAS, CONDENSATE, WATER, MIXED
    -- Reservoir quality flags
    pay_flag                NVARCHAR(1)     NOT NULL DEFAULT 'N',   -- Y = net pay
    pay_cutoff_phi          NUMERIC(8,6)    NULL,       -- porosity cutoff used for pay
    pay_cutoff_sw           NUMERIC(8,6)    NULL,       -- Sw cutoff used for pay
    pay_cutoff_vsh          NUMERIC(8,6)    NULL,       -- Vsh cutoff used for pay
    -- Hydrocarbon pore volume
    hcpv                    NUMERIC(20,4)   NULL,       -- HCPV (unit depends on area input)
    hcpv_ouom               NVARCHAR(40)    NULL REFERENCES dataview.dv_r_uom(uom_code),
    active_ind              NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark                  NVARCHAR(2000)  NULL,
    row_created_by          NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date        DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by          NVARCHAR(40)    NULL,
    row_changed_date        DATETIME2       NULL,
    source                  NVARCHAR(40)    NULL REFERENCES dataview.dv_r_source(source),
    CONSTRAINT pk_dv_well_petro_zone    PRIMARY KEY (uwi, interp_id, zone_id),
    CONSTRAINT fk_petro_zone_interp     FOREIGN KEY (uwi, interp_id)
        REFERENCES dataview.dv_well_petro_interp(uwi, interp_id),
    CONSTRAINT ck_dv_petro_zone_ai      CHECK (active_ind IN ('Y','N')),
    CONSTRAINT ck_dv_petro_zone_pay     CHECK (pay_flag IN ('Y','N'))
);
CREATE INDEX ix_dv_petro_zone_uwi       ON dataview.dv_well_petro_zone(uwi);
CREATE INDEX ix_dv_petro_zone_interp    ON dataview.dv_well_petro_zone(uwi, interp_id);
CREATE INDEX ix_dv_petro_zone_strat     ON dataview.dv_well_petro_zone(strat_unit_name);
CREATE INDEX ix_dv_petro_zone_pay       ON dataview.dv_well_petro_zone(pay_flag);
CREATE INDEX ix_dv_petro_zone_fluid     ON dataview.dv_well_petro_zone(fluid_type);
GO

-- =============================================================================
-- SUMMARY
-- =============================================================================
-- Patch 2 adds 2 tables to the dataview schema:
--
--   Petrophysics : dv_well_petro_interp, dv_well_petro_zone
--
-- Total dataview tables after patch 1 + patch 2: 46
-- =============================================================================
PRINT 'DataView Patch 2 complete — 2 petrophysical tables added (46 total).';
GO

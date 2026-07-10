-- schema_sync: DataView -> DataView_Demo / schema file_catalog
SET XACT_ABORT ON;
BEGIN TRAN;

-- new table: file_catalog.DOC_CONTRIBUTION
CREATE TABLE [file_catalog].[DOC_CONTRIBUTION] (
    [CONTRIB_ID] BIGINT IDENTITY(1,1) NOT NULL,
    [UWI14] CHAR(14) NOT NULL,
    [FIELD] VARCHAR(40) NOT NULL,
    [DOC_VALUE] NVARCHAR(400) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [WELL_HEADER_ID] NVARCHAR(64) NULL,
    [STATUS] VARCHAR(12) NOT NULL DEFAULT ('gap'),
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [PUSHED] BIT NOT NULL DEFAULT ((0)),
    CONSTRAINT [PK__DOC_CONT__D12BA61C12F659DD] PRIMARY KEY ([CONTRIB_ID])
);

-- new table: file_catalog._enrich_keys
CREATE TABLE [file_catalog].[_enrich_keys] (
    [WELL_HEADER_ID] NVARCHAR(64) NOT NULL,
    [NAME_NORM] NVARCHAR(400) NULL,
    [UWI14] CHAR(14) NULL,
    CONSTRAINT [PK___enrich___3B6B8700EADAFC9B] PRIMARY KEY ([WELL_HEADER_ID])
);

-- new table: file_catalog.cat_prod_entity
CREATE TABLE [file_catalog].[cat_prod_entity] (
    [prod_entity_id] NVARCHAR(40) NULL,
    [uwi] NVARCHAR(40) NULL,
    [field_id] NVARCHAR(40) NULL,
    [operator_ba_id] NVARCHAR(40) NULL,
    [prod_entity_type] NVARCHAR(40) NULL,
    [prod_entity_name] NVARCHAR(255) NULL,
    [first_prod_date] DATETIME2 NULL,
    [last_prod_date] DATETIME2 NULL,
    [primary_fluid] NVARCHAR(40) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [source] NVARCHAR(40) NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_prod_entity] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_prod_entity_UWI] ON [file_catalog].[cat_prod_entity] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_prod_entity_INV] ON [file_catalog].[cat_prod_entity] ([INVENTORY_ID]);

-- new table: file_catalog.cat_prod_volume
CREATE TABLE [file_catalog].[cat_prod_volume] (
    [prod_entity_id] NVARCHAR(40) NULL,
    [period_date] NVARCHAR(7) NULL,
    [fluid_type] NVARCHAR(40) NULL,
    [volume] NUMERIC(20,4) NULL,
    [volume_ouom] NVARCHAR(40) NULL,
    [days_on_prod] NUMERIC(5,2) NULL,
    [avg_daily_rate] NUMERIC(20,4) NULL,
    [rate_ouom] NVARCHAR(40) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [source] NVARCHAR(40) NULL,
    [UWI] CHAR(14) NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_prod_volume] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_prod_volume_UWI] ON [file_catalog].[cat_prod_volume] ([UWI], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_prod_volume_INV] ON [file_catalog].[cat_prod_volume] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well
CREATE TABLE [file_catalog].[cat_well] (
    [uwi] NVARCHAR(40) NULL,
    [well_name] NVARCHAR(255) NULL,
    [well_num] NVARCHAR(40) NULL,
    [operator_ba_id] NVARCHAR(40) NULL,
    [field_id] NVARCHAR(40) NULL,
    [well_type] NVARCHAR(40) NULL,
    [well_status] NVARCHAR(40) NULL,
    [country] NVARCHAR(40) NULL,
    [province_state] NVARCHAR(100) NULL,
    [county] NVARCHAR(100) NULL,
    [legal_survey_type] NVARCHAR(40) NULL,
    [surface_latitude] NUMERIC(15,10) NULL,
    [surface_longitude] NUMERIC(15,10) NULL,
    [ground_elevation] NUMERIC(15,4) NULL,
    [kb_elevation] NUMERIC(15,4) NULL,
    [spud_date] DATETIME2 NULL,
    [completion_date] DATETIME2 NULL,
    [final_td] NUMERIC(15,4) NULL,
    [depth_datum] NVARCHAR(40) NULL,
    [epsg_code] INT NULL,
    [api_num] NVARCHAR(20) NULL,
    [license_num] NVARCHAR(40) NULL,
    [lease_name] NVARCHAR(255) NULL,
    [onshore_offshore_ind] NVARCHAR(10) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [source] NVARCHAR(40) NULL,
    [abandonment_date] DATETIME2 NULL,
    [bottom_hole_latitude] NUMERIC(15,10) NULL,
    [bottom_hole_longitude] NUMERIC(15,10) NULL,
    [current_operator_ba_id] NVARCHAR(40) NULL,
    [original_operator_ba_id] NVARCHAR(40) NULL,
    [elevation_ouom] NVARCHAR(40) NULL,
    [formation_at_td] NVARCHAR(255) NULL,
    [long_lat_source] NVARCHAR(40) NULL,
    [permit_number] NVARCHAR(40) NULL,
    [producing_formation] NVARCHAR(255) NULL,
    [area] NVARCHAR(100) NULL,
    [operator_name] NVARCHAR(255) NULL,
    [field_name] NVARCHAR(255) NULL,
    [protraction_area] NVARCHAR(100) NULL,
    [h3_r4] NVARCHAR(15) NULL,
    [h3_r5] NVARCHAR(15) NULL,
    [h3_r6] NVARCHAR(15) NULL,
    [h3_r7] NVARCHAR(15) NULL,
    [h3_coord_hash] BINARY(32) NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_UWI] ON [file_catalog].[cat_well] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_INV] ON [file_catalog].[cat_well] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_completion
CREATE TABLE [file_catalog].[cat_well_completion] (
    [uwi] NVARCHAR(40) NULL,
    [completion_id] NVARCHAR(40) NULL,
    [completion_type] NVARCHAR(60) NULL,
    [completion_design] NVARCHAR(60) NULL,
    [well_orientation] NVARCHAR(20) NULL,
    [completion_date] DATE NULL,
    [strat_unit_name] NVARCHAR(60) NULL,
    [top_depth] FLOAT NULL,
    [base_depth] FLOAT NULL,
    [measured_td_ft] FLOAT NULL,
    [lateral_length_ft] FLOAT NULL,
    [depth_ouom] NVARCHAR(20) NULL,
    [depth_datum] NVARCHAR(20) NULL,
    [completion_status] NVARCHAR(40) NULL,
    [primary_fluid] NVARCHAR(20) NULL,
    [stage_count] INT NULL,
    [total_clusters] INT NULL,
    [avg_cluster_spacing_ft] FLOAT NULL,
    [frac_fluid_system] NVARCHAR(40) NULL,
    [proppant_type] NVARCHAR(60) NULL,
    [total_fluid_bbl] FLOAT NULL,
    [total_proppant_lbs] FLOAT NULL,
    [fluid_intensity_bbl_ft] FLOAT NULL,
    [proppant_intensity_lbs_ft] FLOAT NULL,
    [tubing_size_in] FLOAT NULL,
    [tubing_depth] FLOAT NULL,
    [artificial_lift_type] NVARCHAR(40) NULL,
    [operator_ba_id] NVARCHAR(120) NULL,
    [contractor_ba_id] NVARCHAR(120) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [source] NVARCHAR(40) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_completion] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_completion_UWI] ON [file_catalog].[cat_well_completion] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_completion_INV] ON [file_catalog].[cat_well_completion] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_core
CREATE TABLE [file_catalog].[cat_well_core] (
    [uwi] NVARCHAR(40) NULL,
    [core_id] NVARCHAR(40) NULL,
    [core_num] INT NULL,
    [core_type] NVARCHAR(40) NULL,
    [core_show] NVARCHAR(255) NULL,
    [top_depth] FLOAT NULL,
    [base_depth] FLOAT NULL,
    [depth_ouom] NVARCHAR(40) NULL,
    [depth_datum] NVARCHAR(40) NULL,
    [core_length] NVARCHAR(255) NULL,
    [recovery_length] FLOAT NULL,
    [recovery_pct] FLOAT NULL,
    [length_ouom] NVARCHAR(40) NULL,
    [core_date] DATE NULL,
    [cutting_company_ba_id] NVARCHAR(40) NULL,
    [analysis_company_ba_id] NVARCHAR(40) NULL,
    [strat_unit_name] NVARCHAR(40) NULL,
    [file_path] NVARCHAR(500) NULL,
    [photo_count] INT NULL,
    [photo_folder_path] NVARCHAR(500) NULL,
    [has_uv_photos] NVARCHAR(40) NULL,
    [has_thin_section_photos] NVARCHAR(40) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [source] NVARCHAR(40) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_core] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_core_UWI] ON [file_catalog].[cat_well_core] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_core_INV] ON [file_catalog].[cat_well_core] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_core_sample
CREATE TABLE [file_catalog].[cat_well_core_sample] (
    [uwi] NVARCHAR(40) NULL,
    [core_id] NVARCHAR(40) NULL,
    [sample_id] NVARCHAR(40) NULL,
    [sample_type] NVARCHAR(40) NULL,
    [sample_depth] FLOAT NULL,
    [top_depth] FLOAT NULL,
    [base_depth] FLOAT NULL,
    [depth_ouom] NVARCHAR(40) NULL,
    [porosity_frac] FLOAT NULL,
    [permeability_air_md] FLOAT NULL,
    [permeability_klinkenberg_md] FLOAT NULL,
    [water_saturation_frac] FLOAT NULL,
    [grain_density_g_cc] FLOAT NULL,
    [bulk_density_g_cc] FLOAT NULL,
    [oil_saturation_frac] FLOAT NULL,
    [gas_saturation_frac] FLOAT NULL,
    [formation_factor] FLOAT NULL,
    [cementation_exponent] FLOAT NULL,
    [saturation_exponent] FLOAT NULL,
    [lithology] NVARCHAR(40) NULL,
    [visual_porosity] NVARCHAR(40) NULL,
    [hydrocarbon_show] NVARCHAR(40) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [source] NVARCHAR(40) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_core_sample] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_core_sample_UWI] ON [file_catalog].[cat_well_core_sample] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_core_sample_INV] ON [file_catalog].[cat_well_core_sample] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_dir_srvy_hdr
CREATE TABLE [file_catalog].[cat_well_dir_srvy_hdr] (
    [uwi] NVARCHAR(40) NULL,
    [survey_id] NVARCHAR(40) NULL,
    [survey_type] NVARCHAR(40) NULL,
    [survey_date] DATETIME2 NULL,
    [contractor_ba_id] NVARCHAR(40) NULL,
    [depth_datum] NVARCHAR(40) NULL,
    [depth_datum_elevation] NUMERIC(15,4) NULL,
    [survey_top_depth] NUMERIC(15,4) NULL,
    [survey_base_depth] NUMERIC(15,4) NULL,
    [depth_ouom] NVARCHAR(40) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [source] NVARCHAR(40) NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_dir_srvy_hdr] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_dir_srvy_hdr_UWI] ON [file_catalog].[cat_well_dir_srvy_hdr] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_dir_srvy_hdr_INV] ON [file_catalog].[cat_well_dir_srvy_hdr] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_dir_srvy_sta
CREATE TABLE [file_catalog].[cat_well_dir_srvy_sta] (
    [uwi] NVARCHAR(40) NULL,
    [survey_id] NVARCHAR(40) NULL,
    [station_id] NVARCHAR(40) NULL,
    [md] NUMERIC(15,4) NULL,
    [incl] NUMERIC(10,4) NULL,
    [azim] NUMERIC(10,4) NULL,
    [tvd] NUMERIC(15,4) NULL,
    [ns_offset] NUMERIC(15,4) NULL,
    [ew_offset] NUMERIC(15,4) NULL,
    [surface_latitude] NUMERIC(15,10) NULL,
    [surface_longitude] NUMERIC(15,10) NULL,
    [dls] NUMERIC(10,4) NULL,
    [depth_ouom] NVARCHAR(40) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [source] NVARCHAR(40) NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_dir_srvy_sta] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_dir_srvy_sta_UWI] ON [file_catalog].[cat_well_dir_srvy_sta] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_dir_srvy_sta_INV] ON [file_catalog].[cat_well_dir_srvy_sta] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_dst
CREATE TABLE [file_catalog].[cat_well_dst] (
    [uwi] NVARCHAR(40) NULL,
    [dst_id] NVARCHAR(40) NULL,
    [dst_num] INT NULL,
    [test_type] NVARCHAR(40) NULL,
    [test_date] DATE NULL,
    [top_depth] FLOAT NULL,
    [base_depth] FLOAT NULL,
    [depth_ouom] NVARCHAR(40) NULL,
    [depth_datum] NVARCHAR(40) NULL,
    [strat_unit_name] NVARCHAR(40) NULL,
    [tool_type] NVARCHAR(40) NULL,
    [perforation_top] NVARCHAR(255) NULL,
    [perforation_base] NVARCHAR(255) NULL,
    [max_shut_in_pressure] FLOAT NULL,
    [final_shut_in_pressure] FLOAT NULL,
    [pressure_ouom] NVARCHAR(40) NULL,
    [max_oil_rate] FLOAT NULL,
    [max_gas_rate] FLOAT NULL,
    [max_water_rate] FLOAT NULL,
    [rate_ouom] NVARCHAR(40) NULL,
    [gor] FLOAT NULL,
    [api_gravity] FLOAT NULL,
    [h2s_pct] FLOAT NULL,
    [co2_pct] FLOAT NULL,
    [test_result] NVARCHAR(40) NULL,
    [contractor_ba_id] NVARCHAR(40) NULL,
    [file_path] NVARCHAR(500) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [source] NVARCHAR(40) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_dst] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_dst_UWI] ON [file_catalog].[cat_well_dst] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_dst_INV] ON [file_catalog].[cat_well_dst] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_formation_top
CREATE TABLE [file_catalog].[cat_well_formation_top] (
    [uwi] NVARCHAR(40) NULL,
    [strat_unit_id] NVARCHAR(40) NULL,
    [interp_id] NVARCHAR(40) NULL,
    [strat_name_set] NVARCHAR(255) NULL,
    [strat_unit_name] NVARCHAR(255) NULL,
    [strat_unit_type] NVARCHAR(40) NULL,
    [strat_unit_subtype] NVARCHAR(40) NULL,
    [age_top_ma] NUMERIC(10,3) NULL,
    [age_base_ma] NUMERIC(10,3) NULL,
    [lithology] NVARCHAR(100) NULL,
    [top_depth] NUMERIC(15,4) NULL,
    [base_depth] NUMERIC(15,4) NULL,
    [gross_thickness] NUMERIC(16,4) NULL,
    [depth_ouom] NVARCHAR(40) NULL,
    [depth_datum] NVARCHAR(40) NULL,
    [tvd_top] NUMERIC(15,4) NULL,
    [tvd_base] NUMERIC(15,4) NULL,
    [owc_depth] NUMERIC(15,4) NULL,
    [goc_depth] NUMERIC(15,4) NULL,
    [gwc_depth] NUMERIC(15,4) NULL,
    [interp_date] DATETIME2 NULL,
    [interpreter_ba_id] NVARCHAR(40) NULL,
    [confidence_level] NVARCHAR(40) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [source] NVARCHAR(40) NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_formation_top] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_formation_top_UWI] ON [file_catalog].[cat_well_formation_top] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_formation_top_INV] ON [file_catalog].[cat_well_formation_top] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_petro_interp
CREATE TABLE [file_catalog].[cat_well_petro_interp] (
    [uwi] NVARCHAR(40) NULL,
    [interp_id] NVARCHAR(40) NULL,
    [interp_name] NVARCHAR(255) NULL,
    [interp_date] DATE NULL,
    [analyst_ba_id] NVARCHAR(40) NULL,
    [software] NVARCHAR(40) NULL,
    [software_version] NVARCHAR(40) NULL,
    [gr_log_id] NVARCHAR(40) NULL,
    [res_log_id] NVARCHAR(40) NULL,
    [density_log_id] NVARCHAR(40) NULL,
    [neutron_log_id] NVARCHAR(40) NULL,
    [sonic_log_id] NVARCHAR(40) NULL,
    [other_log_inputs] NVARCHAR(500) NULL,
    [formation_water_resist] FLOAT NULL,
    [rw_temperature] FLOAT NULL,
    [temperature_ouom] NVARCHAR(40) NULL,
    [archie_a] FLOAT NULL,
    [archie_m] FLOAT NULL,
    [archie_n] FLOAT NULL,
    [shale_volume_method] NVARCHAR(40) NULL,
    [porosity_method] NVARCHAR(40) NULL,
    [fluid_density_g_cc] FLOAT NULL,
    [matrix_density_g_cc] FLOAT NULL,
    [sw_method] NVARCHAR(40) NULL,
    [output_file_path] NVARCHAR(500) NULL,
    [interp_status] NVARCHAR(40) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [source] NVARCHAR(40) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_petro_interp] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_petro_interp_UWI] ON [file_catalog].[cat_well_petro_interp] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_petro_interp_INV] ON [file_catalog].[cat_well_petro_interp] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_petro_zone
CREATE TABLE [file_catalog].[cat_well_petro_zone] (
    [uwi] NVARCHAR(40) NULL,
    [interp_id] NVARCHAR(40) NULL,
    [zone_id] NVARCHAR(40) NULL,
    [zone_name] NVARCHAR(255) NULL,
    [zone_type] NVARCHAR(40) NULL,
    [top_depth] FLOAT NULL,
    [base_depth] FLOAT NULL,
    [depth_ouom] NVARCHAR(40) NULL,
    [depth_datum] NVARCHAR(40) NULL,
    [tvd_top] FLOAT NULL,
    [tvd_base] FLOAT NULL,
    [strat_unit_id] NVARCHAR(40) NULL,
    [strat_interp_id] NVARCHAR(40) NULL,
    [strat_unit_name] NVARCHAR(40) NULL,
    [gross_thickness] FLOAT NULL,
    [net_thickness] FLOAT NULL,
    [net_to_gross] FLOAT NULL,
    [vsh_avg] FLOAT NULL,
    [vsh_min] FLOAT NULL,
    [vsh_max] FLOAT NULL,
    [phi_total_avg] FLOAT NULL,
    [phi_effective_avg] FLOAT NULL,
    [phi_method] NVARCHAR(40) NULL,
    [sw_avg] FLOAT NULL,
    [sw_min] FLOAT NULL,
    [sw_max] FLOAT NULL,
    [sw_method] NVARCHAR(40) NULL,
    [sh_avg] FLOAT NULL,
    [perm_avg_md] FLOAT NULL,
    [perm_geomean_md] FLOAT NULL,
    [perm_method] NVARCHAR(40) NULL,
    [bvw_avg] FLOAT NULL,
    [bvh_avg] FLOAT NULL,
    [fluid_type] NVARCHAR(40) NULL,
    [pay_flag] NVARCHAR(40) NULL,
    [pay_cutoff_phi] FLOAT NULL,
    [pay_cutoff_sw] FLOAT NULL,
    [pay_cutoff_vsh] FLOAT NULL,
    [hcpv] FLOAT NULL,
    [hcpv_ouom] NVARCHAR(40) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [remark] NVARCHAR(2000) NULL,
    [source] NVARCHAR(40) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [row_changed_by] NVARCHAR(40) NULL,
    [row_changed_date] DATETIME2 NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_petro_zone] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_petro_zone_UWI] ON [file_catalog].[cat_well_petro_zone] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_petro_zone_INV] ON [file_catalog].[cat_well_petro_zone] ([INVENTORY_ID]);

-- new table: file_catalog.cat_well_stimulation
CREATE TABLE [file_catalog].[cat_well_stimulation] (
    [uwi] NVARCHAR(40) NULL,
    [completion_id] NVARCHAR(40) NULL,
    [stim_id] NVARCHAR(40) NULL,
    [stage_num] INT NULL,
    [stim_type] NVARCHAR(40) NULL,
    [stage_date] DATE NULL,
    [stage_top_depth] FLOAT NULL,
    [stage_base_depth] FLOAT NULL,
    [num_clusters] INT NULL,
    [cluster_spacing_ft] FLOAT NULL,
    [fluid_system] NVARCHAR(40) NULL,
    [fluid_volume_bbl] FLOAT NULL,
    [proppant_type] NVARCHAR(60) NULL,
    [proppant_mesh] NVARCHAR(40) NULL,
    [proppant_mass_lbs] FLOAT NULL,
    [max_proppant_conc_ppg] FLOAT NULL,
    [breakdown_pressure_psi] FLOAT NULL,
    [isip_psi] FLOAT NULL,
    [avg_treating_pressure_psi] FLOAT NULL,
    [max_treating_pressure_psi] FLOAT NULL,
    [avg_rate_bpm] FLOAT NULL,
    [max_rate_bpm] FLOAT NULL,
    [screen_out_ind] NVARCHAR(1) NULL,
    [active_ind] NVARCHAR(1) NULL,
    [source] NVARCHAR(40) NULL,
    [row_created_by] NVARCHAR(40) NULL,
    [row_created_date] DATETIME2 NULL,
    [INVENTORY_ID] NVARCHAR(64) NULL,
    [SOURCE_PATH] NVARCHAR(1024) NULL,
    [PROMOTED] BIT NOT NULL DEFAULT ((0)),
    [PROMOTED_AT] DATETIME2 NULL,
    [CAPTURED_AT] DATETIME2 NOT NULL DEFAULT (sysutcdatetime()),
    [CAT_ROW_ID] BIGINT IDENTITY(1,1) NOT NULL,
    CONSTRAINT [PK_cat_well_stimulation] PRIMARY KEY ([CAT_ROW_ID])
);
CREATE NONCLUSTERED INDEX [IX_cat_well_stimulation_UWI] ON [file_catalog].[cat_well_stimulation] ([uwi], [PROMOTED]);
CREATE NONCLUSTERED INDEX [IX_cat_well_stimulation_INV] ON [file_catalog].[cat_well_stimulation] ([INVENTORY_ID]);

-- update table: file_catalog.ASSIGNMENT_EXTENSION
CREATE NONCLUSTERED INDEX [AE_ASGN_IDX] ON [file_catalog].[ASSIGNMENT_EXTENSION] ([ASSIGNMENT_ID]);

-- update table: file_catalog.FILE_CURVE
CREATE NONCLUSTERED INDEX [IX_FC_HEADER] ON [file_catalog].[FILE_CURVE] ([FILE_HEADER_ID]);
CREATE NONCLUSTERED INDEX [IX_FC_MNEMONIC] ON [file_catalog].[FILE_CURVE] ([MNEMONIC]);
CREATE NONCLUSTERED INDEX [FC_HDR_IDX] ON [file_catalog].[FILE_CURVE] ([FILE_HEADER_ID]);
CREATE NONCLUSTERED INDEX [FC_MNM_IDX] ON [file_catalog].[FILE_CURVE] ([MNEMONIC]);

-- update table: file_catalog.FILE_HEADER
CREATE NONCLUSTERED INDEX [FH_UWI_IDX] ON [file_catalog].[FILE_HEADER] ([MATCHED_UWI]);
CREATE NONCLUSTERED INDEX [FH_TYPE_IDX] ON [file_catalog].[FILE_HEADER] ([FILE_TYPE]);
CREATE NONCLUSTERED INDEX [FH_INV_IDX] ON [file_catalog].[FILE_HEADER] ([INVENTORY_ID]);

-- update table: file_catalog.FILE_SEIS_HEADER
CREATE NONCLUSTERED INDEX [IX_FSH_INVENTORY] ON [file_catalog].[FILE_SEIS_HEADER] ([INVENTORY_ID]);
CREATE NONCLUSTERED INDEX [IX_FSH_BBOX_SW] ON [file_catalog].[FILE_SEIS_HEADER] ([BBOX_MIN_LAT], [BBOX_MIN_LON]);
CREATE NONCLUSTERED INDEX [IX_FSH_BBOX_NE] ON [file_catalog].[FILE_SEIS_HEADER] ([BBOX_MAX_LAT], [BBOX_MAX_LON]);

-- update table: file_catalog.FILE_WELL_HEADER
CREATE NONCLUSTERED INDEX [IX_FWH_INVENTORY] ON [file_catalog].[FILE_WELL_HEADER] ([INVENTORY_ID]);
CREATE NONCLUSTERED INDEX [IX_FWH_UWI] ON [file_catalog].[FILE_WELL_HEADER] ([UWI]);
CREATE NONCLUSTERED INDEX [IX_FWH_COORDS] ON [file_catalog].[FILE_WELL_HEADER] ([LATITUDE], [LONGITUDE]);
CREATE NONCLUSTERED INDEX [IX_FWH_STATE] ON [file_catalog].[FILE_WELL_HEADER] ([STATE]);

-- update table: file_catalog.GLOBAL_FILE_CATALOG
ALTER TABLE [file_catalog].[GLOBAL_FILE_CATALOG] ADD [VAULTED] BIT NOT NULL DEFAULT ((0));
CREATE NONCLUSTERED INDEX [IX_GFC_HASH] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([FILE_HASH]);
CREATE NONCLUSTERED INDEX [IX_GFC_DUPLICATE] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([DUPLICATE_GROUP]);
CREATE NONCLUSTERED INDEX [IX_GFC_FILE_TYPE] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([FILE_TYPE_GROUP]);
CREATE NONCLUSTERED INDEX [IX_GFC_REPORT_TYPE] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([REPORT_TYPE]);
CREATE NONCLUSTERED INDEX [IX_GFC_EXTRACTED] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([HEADER_EXTRACTED]);
CREATE NONCLUSTERED INDEX [GFC_EXT_IDX] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([FILE_EXT]);
CREATE NONCLUSTERED INDEX [GFC_STATUS_IDX] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([CATALOG_STATUS]);
CREATE NONCLUSTERED INDEX [GFC_ROOT_IDX] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([ROOT_PATH]);
CREATE NONCLUSTERED INDEX [GFC_HASH_IDX] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([FILE_HASH]);
CREATE NONCLUSTERED INDEX [GFC_DUP_IDX] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([DUPLICATE_GROUP]);
CREATE NONCLUSTERED INDEX [GFC_GROUP_IDX] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([FILE_TYPE_GROUP]);
CREATE NONCLUSTERED INDEX [GFC_ASSIGN_IDX] ON [file_catalog].[GLOBAL_FILE_CATALOG] ([CATALOG_STATUS], [FILE_TYPE_GROUP], [FILE_EXT], [FILE_NAME], [INVENTORY_ID]);

-- update table: file_catalog.INVENTORY_ASSIGNMENT
CREATE NONCLUSTERED INDEX [IA_GROUP_IDX] ON [file_catalog].[INVENTORY_ASSIGNMENT] ([GROUP_ID]);
CREATE NONCLUSTERED INDEX [IA_ASSIGNED_IDX] ON [file_catalog].[INVENTORY_ASSIGNMENT] ([ASSIGNED_TO]);
CREATE NONCLUSTERED INDEX [IA_STATUS_IDX] ON [file_catalog].[INVENTORY_ASSIGNMENT] ([STATUS]);
CREATE NONCLUSTERED INDEX [IA_DUE_IDX] ON [file_catalog].[INVENTORY_ASSIGNMENT] ([DUE_DATE]);

-- update table: file_catalog.INVENTORY_GROUP
CREATE NONCLUSTERED INDEX [IG_STATUS_IDX] ON [file_catalog].[INVENTORY_GROUP] ([STATUS]);

-- update table: file_catalog.INVENTORY_GROUP_FILE
CREATE NONCLUSTERED INDEX [IGF_ASGN_IDX] ON [file_catalog].[INVENTORY_GROUP_FILE] ([ASSIGNMENT_ID]);
CREATE NONCLUSTERED INDEX [IGF_GROUP_IDX] ON [file_catalog].[INVENTORY_GROUP_FILE] ([GROUP_ID]);
CREATE NONCLUSTERED INDEX [IGF_INV_IDX] ON [file_catalog].[INVENTORY_GROUP_FILE] ([INVENTORY_ID]);
CREATE NONCLUSTERED INDEX [IGF_SKIP_IDX] ON [file_catalog].[INVENTORY_GROUP_FILE] ([SKIPPED_IND]);

-- update table: file_catalog.INVENTORY_USER
CREATE UNIQUE NONCLUSTERED INDEX [UQ__INVENTOR__161CF7248CCF6CAF] ON [file_catalog].[INVENTORY_USER] ([EMAIL]);

COMMIT;

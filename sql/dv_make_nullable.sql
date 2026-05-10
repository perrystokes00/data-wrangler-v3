-- ============================================================
-- DataView v3 — Make optional columns nullable in 14 new tables
-- Only columns NOT populated by generate_dataview_testdata.py
-- Run against DataView after dv_future_tables.sql
-- ============================================================

USE DataView;

-- dv_well_core — cutting_company_ba_id and analysis_company_ba_id are optional
ALTER TABLE dataview.dv_well_core ALTER COLUMN cutting_company_ba_id NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_core ALTER COLUMN analysis_company_ba_id NVARCHAR(40) NULL;

-- dv_well_core_sample — oil/gas saturation and some petrophysics are optional
ALTER TABLE dataview.dv_well_core_sample ALTER COLUMN oil_saturation_frac FLOAT NULL;
ALTER TABLE dataview.dv_well_core_sample ALTER COLUMN gas_saturation_frac FLOAT NULL;
ALTER TABLE dataview.dv_well_core_sample ALTER COLUMN formation_factor FLOAT NULL;
ALTER TABLE dataview.dv_well_core_sample ALTER COLUMN cementation_exponent FLOAT NULL;
ALTER TABLE dataview.dv_well_core_sample ALTER COLUMN saturation_exponent FLOAT NULL;

-- dv_well_completion — tubing_depth optional
ALTER TABLE dataview.dv_well_completion ALTER COLUMN tubing_depth FLOAT NULL;
ALTER TABLE dataview.dv_well_completion ALTER COLUMN tubing_size_in FLOAT NULL;
ALTER TABLE dataview.dv_well_completion ALTER COLUMN artificial_lift_type NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_completion ALTER COLUMN strat_unit_name NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_completion ALTER COLUMN top_depth FLOAT NULL;
ALTER TABLE dataview.dv_well_completion ALTER COLUMN base_depth FLOAT NULL;
ALTER TABLE dataview.dv_well_completion ALTER COLUMN depth_ouom NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_completion ALTER COLUMN depth_datum NVARCHAR(40) NULL;

-- dv_well_dst — some fields optional
ALTER TABLE dataview.dv_well_dst ALTER COLUMN perforation_top FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN perforation_base FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN max_shut_in_pressure FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN max_oil_rate FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN max_gas_rate FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN max_water_rate FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN gor FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN api_gravity FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN h2s_pct FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN co2_pct FLOAT NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN strat_unit_name NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_dst ALTER COLUMN tool_type NVARCHAR(40) NULL;

-- dv_well_dst_period — choke optional
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN choke_size FLOAT NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN avg_oil_rate FLOAT NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN avg_gas_rate FLOAT NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN avg_water_rate FLOAT NULL;

-- dv_well_mud_log — base_depth optional (top only required)
ALTER TABLE dataview.dv_well_mud_log ALTER COLUMN base_depth FLOAT NULL;
ALTER TABLE dataview.dv_well_mud_log ALTER COLUMN rop_avg FLOAT NULL;
ALTER TABLE dataview.dv_well_mud_log ALTER COLUMN mud_weight_avg FLOAT NULL;

-- dv_well_perforation — optional fields
ALTER TABLE dataview.dv_well_perforation ALTER COLUMN phasing_deg NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_perforation ALTER COLUMN perf_diameter_in FLOAT NULL;
ALTER TABLE dataview.dv_well_perforation ALTER COLUMN strat_unit_name NVARCHAR(40) NULL;

-- dv_well_shows — gas chromatography optional
ALTER TABLE dataview.dv_well_shows ALTER COLUMN total_gas_units FLOAT NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN c1_pct FLOAT NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN c2_pct FLOAT NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN c3_pct FLOAT NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN ic4_pct FLOAT NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN nc4_pct FLOAT NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN ic5_pct FLOAT NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN nc5_pct FLOAT NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN fluorescence_color NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN fluorescence_intensity NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN cut_color NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN strat_unit_name NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_shows ALTER COLUMN show_rating NVARCHAR(40) NULL;

-- dv_well_stimulation — optional fields
ALTER TABLE dataview.dv_well_stimulation ALTER COLUMN proppant_mesh NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_stimulation ALTER COLUMN isip FLOAT NULL;
ALTER TABLE dataview.dv_well_stimulation ALTER COLUMN closure_pressure FLOAT NULL;
ALTER TABLE dataview.dv_well_stimulation ALTER COLUMN max_pump_rate FLOAT NULL;

-- dv_well_petro_interp — optional analytical params
ALTER TABLE dataview.dv_well_petro_interp ALTER COLUMN formation_water_resist FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_interp ALTER COLUMN rw_temperature FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_interp ALTER COLUMN archie_a FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_interp ALTER COLUMN archie_m FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_interp ALTER COLUMN archie_n FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_interp ALTER COLUMN fluid_density_g_cc FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_interp ALTER COLUMN matrix_density_g_cc FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_interp ALTER COLUMN interp_status NVARCHAR(40) NULL;

-- dv_well_petro_zone — optional zone params
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN tvd_top FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN tvd_base FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN strat_unit_name NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN gross_thickness FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN vsh_min FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN vsh_max FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN sw_min FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN sw_max FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN perm_geomean_md FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN bvw_avg FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN bvh_avg FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN hcpv FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN pay_flag NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN pay_cutoff_phi FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN pay_cutoff_sw FLOAT NULL;
ALTER TABLE dataview.dv_well_petro_zone ALTER COLUMN pay_cutoff_vsh FLOAT NULL;

-- dv_well_pressure — optional fields
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN mobility FLOAT NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN strat_unit_name NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN tool_type NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN fluid_type NVARCHAR(40) NULL;

-- dv_well_casing — optional fields
ALTER TABLE dataview.dv_well_casing ALTER COLUMN cement_top FLOAT NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN cement_base FLOAT NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN cement_volume_sacks FLOAT NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN cement_type NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN burst_rating_psi FLOAT NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN collapse_rating_psi FLOAT NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN connection_type NVARCHAR(40) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN set_date DATE NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN depth_datum NVARCHAR(40) NULL;

-- dv_well_core_photo — optional fields
ALTER TABLE dataview.dv_well_core_photo ALTER COLUMN photo_date DATE NULL;
ALTER TABLE dataview.dv_well_core_photo ALTER COLUMN resolution_dpi INT NULL;
ALTER TABLE dataview.dv_well_core_photo ALTER COLUMN width_px INT NULL;
ALTER TABLE dataview.dv_well_core_photo ALTER COLUMN height_px INT NULL;

PRINT 'Nullable columns updated — constraints preserved on required fields.';

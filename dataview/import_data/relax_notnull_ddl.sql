-- Relax over-constrained NOT NULL measurement columns.
-- Generated from dataview_schema_full.json (db DataView_Demo, schema dataview, snapshot 2026-07-11T13:41:44).
-- KEEPS NOT NULL: primary key, uwi, active_ind, source, row_created_by/date.
-- Review before running. Take a backup first.

-- dv_well_casing: 16 column(s) relaxed (PK casing_id, uwi kept NOT NULL)
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [casing_type] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [set_date] date NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [top_depth] float NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [base_depth] float NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [depth_ouom] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [depth_datum] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [od_in] nvarchar(255) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [weight_lb_ft] float NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [grade] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [connection_type] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [cement_top] nvarchar(255) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [cement_base] nvarchar(255) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [cement_volume_sacks] float NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [cement_type] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [burst_rating_psi] float NULL;
ALTER TABLE dataview.dv_well_casing ALTER COLUMN [collapse_rating_psi] float NULL;
GO

-- dv_well_dst_period: 10 column(s) relaxed (PK dst_id, period_id, uwi kept NOT NULL)
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [period_type] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [period_seq] int NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [duration_min] float NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [start_pressure] float NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [end_pressure] float NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [pressure_ouom] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [avg_oil_rate] float NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [avg_gas_rate] float NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [avg_water_rate] float NULL;
ALTER TABLE dataview.dv_well_dst_period ALTER COLUMN [rate_ouom] nvarchar(40) NULL;
GO

-- dv_well_pressure: 13 column(s) relaxed (PK pressure_id, uwi kept NOT NULL)
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [pressure_type] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [test_date] date NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [depth] nvarchar(255) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [depth_ouom] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [depth_datum] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [pressure] nvarchar(255) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [pressure_ouom] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [temperature] float NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [fluid_type] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [mobility] float NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [strat_unit_name] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [tool_type] nvarchar(40) NULL;
ALTER TABLE dataview.dv_well_pressure ALTER COLUMN [contractor_ba_id] nvarchar(40) NULL;
GO

-- 39 column(s) relaxed in total.

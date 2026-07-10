USE [DataView]
GO
/****** Object:  User [pmstokes00]    Script Date: 2026-05-15 10:58:33 AM ******/
CREATE USER [pmstokes00] FOR LOGIN [pmstokes00] WITH DEFAULT_SCHEMA=[dbo]
GO
/****** Object:  Schema [dataview]    Script Date: 2026-05-15 10:58:33 AM ******/
CREATE SCHEMA [dataview]
GO
/****** Object:  Schema [dataview_gom]    Script Date: 2026-05-15 10:58:33 AM ******/
CREATE SCHEMA [dataview_gom]
GO
/****** Object:  Schema [file_catalog]    Script Date: 2026-05-15 10:58:33 AM ******/
CREATE SCHEMA [file_catalog]
GO
/****** Object:  Schema [las_catalog]    Script Date: 2026-05-15 10:58:33 AM ******/
CREATE SCHEMA [las_catalog]
GO
/****** Object:  Table [dataview].[document_location]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[document_location](
	[doc_loc_id] [bigint] IDENTITY(1,1) NOT NULL,
	[inventory_id] [nvarchar](40) NOT NULL,
	[source_table] [varchar](50) NOT NULL,
	[latitude] [decimal](11, 7) NOT NULL,
	[longitude] [decimal](11, 7) NOT NULL,
	[coord_precision] [tinyint] NULL,
	[file_path] [nvarchar](1000) NULL,
	[file_format] [nvarchar](20) NULL,
	[doc_type] [nvarchar](100) NULL,
	[uwi_in_doc] [nvarchar](40) NULL,
	[well_name_in_doc] [nvarchar](255) NULL,
	[operator_in_doc] [nvarchar](255) NULL,
	[state_in_doc] [nvarchar](50) NULL,
	[county_in_doc] [nvarchar](100) NULL,
	[precision_ok] [bit] NULL,
	[state_bbox_ok] [bit] NULL,
	[county_match_ok] [bit] NULL,
	[duplicate_of] [bigint] NULL,
	[confidence] [decimal](5, 4) NULL,
	[curation_status] [nvarchar](20) NOT NULL,
	[curated_by] [nvarchar](100) NULL,
	[curated_date] [datetime2](7) NULL,
	[curation_notes] [nvarchar](max) NULL,
	[promoted_to_well_id] [bigint] NULL,
	[promoted_date] [datetime2](7) NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_date] [datetime2](7) NOT NULL,
 CONSTRAINT [PK_document_location] PRIMARY KEY CLUSTERED 
(
	[doc_loc_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_basin]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_basin](
	[basin_id] [nvarchar](40) NOT NULL,
	[basin_name] [nvarchar](255) NOT NULL,
	[basin_type] [nvarchar](40) NULL,
	[country_code] [nvarchar](3) NULL,
	[region] [nvarchar](100) NULL,
	[area_km2] [numeric](15, 4) NULL,
	[centroid_latitude] [numeric](15, 10) NULL,
	[centroid_longitude] [numeric](15, 10) NULL,
	[primary_play_type] [nvarchar](40) NULL,
	[gdm_basin_id] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_basin] PRIMARY KEY CLUSTERED 
(
	[basin_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_business_associate]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_business_associate](
	[ba_id] [nvarchar](40) NOT NULL,
	[ba_type] [nvarchar](40) NULL,
	[ba_name] [nvarchar](255) NOT NULL,
	[ba_name_alias] [nvarchar](255) NULL,
	[short_name] [nvarchar](40) NULL,
	[address_1] [nvarchar](255) NULL,
	[address_2] [nvarchar](255) NULL,
	[city] [nvarchar](100) NULL,
	[state_province] [nvarchar](100) NULL,
	[postal_code] [nvarchar](20) NULL,
	[country] [nvarchar](40) NULL,
	[phone_num] [nvarchar](40) NULL,
	[email_addr] [nvarchar](255) NULL,
	[duns_num] [nvarchar](20) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_business_associate] PRIMARY KEY CLUSTERED 
(
	[ba_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_column_map]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_column_map](
	[map_id] [nvarchar](40) NOT NULL,
	[source_file_pattern] [nvarchar](255) NULL,
	[source_column] [nvarchar](255) NOT NULL,
	[target_table] [nvarchar](100) NOT NULL,
	[target_column] [nvarchar](100) NOT NULL,
	[confidence_score] [numeric](5, 4) NULL,
	[mapping_method] [nvarchar](20) NULL,
	[confirmed_ind] [nvarchar](1) NOT NULL,
	[confirmed_by] [nvarchar](40) NULL,
	[confirmed_date] [datetime2](7) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_column_map] PRIMARY KEY CLUSTERED 
(
	[map_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_country]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_country](
	[country_code] [nvarchar](3) NOT NULL,
	[country_code_a2] [nvarchar](2) NULL,
	[country_name] [nvarchar](255) NOT NULL,
	[country_name_local] [nvarchar](255) NULL,
	[continent] [nvarchar](40) NULL,
	[region] [nvarchar](100) NULL,
	[un_m49_code] [nvarchar](10) NULL,
	[currency_code] [nvarchar](3) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_country] PRIMARY KEY CLUSTERED 
(
	[country_code] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_county]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_county](
	[county_id] [nvarchar](40) NOT NULL,
	[province_state_id] [nvarchar](10) NOT NULL,
	[country_code] [nvarchar](3) NOT NULL,
	[county_name] [nvarchar](255) NOT NULL,
	[county_type] [nvarchar](40) NULL,
	[fips_state_code] [nvarchar](3) NULL,
	[fips_county_code] [nvarchar](3) NULL,
	[fips_full] [nvarchar](5) NULL,
	[tiger_geoid] [nvarchar](20) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_county] PRIMARY KEY CLUSTERED 
(
	[county_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_data_quality]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_data_quality](
	[dq_id] [nvarchar](40) NOT NULL,
	[entity_type] [nvarchar](40) NOT NULL,
	[entity_id] [nvarchar](40) NOT NULL,
	[rule_name] [nvarchar](100) NOT NULL,
	[rule_type] [nvarchar](40) NULL,
	[result] [nvarchar](10) NULL,
	[dq_score] [numeric](5, 4) NULL,
	[detail] [nvarchar](2000) NULL,
	[check_date] [datetime2](7) NOT NULL,
	[batch_id] [nvarchar](40) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_data_quality] PRIMARY KEY CLUSTERED 
(
	[dq_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_field]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_field](
	[field_id] [nvarchar](40) NOT NULL,
	[field_name] [nvarchar](255) NOT NULL,
	[field_type] [nvarchar](40) NULL,
	[country] [nvarchar](40) NULL,
	[province_state] [nvarchar](100) NULL,
	[county] [nvarchar](100) NULL,
	[basin_name] [nvarchar](255) NULL,
	[operator_ba_id] [nvarchar](40) NULL,
	[discovery_date] [datetime2](7) NULL,
	[field_status] [nvarchar](40) NULL,
	[onshore_offshore_ind] [nvarchar](10) NULL,
	[surface_latitude] [numeric](15, 10) NULL,
	[surface_longitude] [numeric](15, 10) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_field] PRIMARY KEY CLUSTERED 
(
	[field_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_global_file_catalog]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_global_file_catalog](
	[inventory_id] [nvarchar](40) NOT NULL,
	[full_path] [nvarchar](1000) NOT NULL,
	[file_name] [nvarchar](500) NOT NULL,
	[file_ext] [nvarchar](20) NULL,
	[file_size_kb] [numeric](15, 2) NULL,
	[file_hash] [nvarchar](64) NULL,
	[file_hash_full] [nvarchar](64) NULL,
	[duplicate_group] [nvarchar](64) NULL,
	[modified_date] [datetime2](7) NULL,
	[scan_date] [datetime2](7) NOT NULL,
	[doc_type_group] [nvarchar](40) NULL,
	[doc_type] [nvarchar](40) NULL,
	[catalog_status] [nvarchar](20) NULL,
	[catalog_table] [nvarchar](80) NULL,
	[catalog_id] [nvarchar](40) NULL,
	[ppdm_loaded_ind] [nvarchar](1) NOT NULL,
	[root_path] [nvarchar](500) NULL,
	[uwi] [nvarchar](40) NULL,
	[well_name] [nvarchar](255) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_global_file_catalog] PRIMARY KEY CLUSTERED 
(
	[inventory_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_load_batch]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_load_batch](
	[batch_id] [nvarchar](40) NOT NULL,
	[batch_date] [datetime2](7) NOT NULL,
	[source_file] [nvarchar](1000) NULL,
	[source_file_hash] [nvarchar](64) NULL,
	[file_type] [nvarchar](40) NULL,
	[dialect] [nvarchar](20) NULL,
	[target_schema] [nvarchar](40) NULL,
	[target_table] [nvarchar](100) NULL,
	[rows_staged] [int] NULL,
	[rows_promoted] [int] NULL,
	[rows_rejected] [int] NULL,
	[status] [nvarchar](20) NULL,
	[error_msg] [nvarchar](2000) NULL,
	[duration_sec] [numeric](10, 2) NULL,
	[operator_ba_id] [nvarchar](40) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_load_batch] PRIMARY KEY CLUSTERED 
(
	[batch_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_ocs_block]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_ocs_block](
	[ocs_block_id] [nvarchar](20) NOT NULL,
	[planning_area] [nvarchar](100) NULL,
	[area_code] [nvarchar](10) NULL,
	[block_num] [nvarchar](10) NULL,
	[block_name] [nvarchar](255) NULL,
	[protraction_name] [nvarchar](255) NULL,
	[water_depth_m] [numeric](10, 2) NULL,
	[country_code] [nvarchar](3) NULL,
	[centroid_latitude] [numeric](15, 10) NULL,
	[centroid_longitude] [numeric](15, 10) NULL,
	[bbox_wkt] [nvarchar](500) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_ocs_block] PRIMARY KEY CLUSTERED 
(
	[ocs_block_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_plss_township]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_plss_township](
	[plss_id] [nvarchar](20) NOT NULL,
	[state_fips] [nvarchar](3) NULL,
	[township_num] [nvarchar](10) NULL,
	[range_num] [nvarchar](10) NULL,
	[section_num] [nvarchar](5) NULL,
	[principal_meridian] [nvarchar](40) NULL,
	[county_id] [nvarchar](40) NULL,
	[province_state_id] [nvarchar](10) NULL,
	[township_label] [nvarchar](100) NULL,
	[centroid_latitude] [numeric](15, 10) NULL,
	[centroid_longitude] [numeric](15, 10) NULL,
	[bbox_wkt] [nvarchar](500) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_plss_township] PRIMARY KEY CLUSTERED 
(
	[plss_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_prod_entity]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_prod_entity](
	[prod_entity_id] [nvarchar](40) NOT NULL,
	[uwi] [nvarchar](40) NULL,
	[field_id] [nvarchar](40) NULL,
	[operator_ba_id] [nvarchar](40) NULL,
	[prod_entity_type] [nvarchar](40) NULL,
	[prod_entity_name] [nvarchar](255) NULL,
	[first_prod_date] [datetime2](7) NULL,
	[last_prod_date] [datetime2](7) NULL,
	[primary_fluid] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_prod_entity] PRIMARY KEY CLUSTERED 
(
	[prod_entity_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_prod_volume]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_prod_volume](
	[prod_entity_id] [nvarchar](40) NOT NULL,
	[period_date] [nvarchar](7) NOT NULL,
	[fluid_type] [nvarchar](40) NOT NULL,
	[volume] [numeric](20, 4) NULL,
	[volume_ouom] [nvarchar](40) NULL,
	[days_on_prod] [numeric](5, 2) NULL,
	[avg_daily_rate] [numeric](20, 4) NULL,
	[rate_ouom] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_prod_volume] PRIMARY KEY CLUSTERED 
(
	[prod_entity_id] ASC,
	[period_date] ASC,
	[fluid_type] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_province_state]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_province_state](
	[province_state_id] [nvarchar](10) NOT NULL,
	[country_code] [nvarchar](3) NOT NULL,
	[province_state_name] [nvarchar](255) NOT NULL,
	[province_state_abbrev] [nvarchar](10) NULL,
	[province_state_type] [nvarchar](40) NULL,
	[fips_code] [nvarchar](5) NULL,
	[capital_city] [nvarchar](100) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_province_state] PRIMARY KEY CLUSTERED 
(
	[province_state_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_r_source]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_r_source](
	[source] [nvarchar](40) NOT NULL,
	[short_name] [nvarchar](40) NULL,
	[long_name] [nvarchar](255) NULL,
	[remark] [nvarchar](2000) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_r_source] PRIMARY KEY CLUSTERED 
(
	[source] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_r_uom]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_r_uom](
	[uom_code] [nvarchar](40) NOT NULL,
	[unit_of_measure] [nvarchar](255) NULL,
	[uom_description] [nvarchar](2000) NULL,
	[uom_type] [nvarchar](40) NULL,
	[si_equivalent] [numeric](20, 10) NULL,
	[si_uom_code] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_r_uom] PRIMARY KEY CLUSTERED 
(
	[uom_code] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_r_well_status]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_r_well_status](
	[well_status] [nvarchar](40) NOT NULL,
	[short_name] [nvarchar](40) NULL,
	[long_name] [nvarchar](255) NULL,
	[remark] [nvarchar](2000) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_r_well_status] PRIMARY KEY CLUSTERED 
(
	[well_status] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_r_well_type]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_r_well_type](
	[well_type] [nvarchar](40) NOT NULL,
	[short_name] [nvarchar](40) NULL,
	[long_name] [nvarchar](255) NULL,
	[remark] [nvarchar](2000) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_r_well_type] PRIMARY KEY CLUSTERED 
(
	[well_type] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
CREATE TABLE [dataview].[dv_r_depth_datum](
	[depth_datum] [nvarchar](40) NOT NULL,
	[short_name] [nvarchar](40) NULL,
	[long_name] [nvarchar](255) NULL,
	[remark] [nvarchar](2000) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_r_depth_datum] PRIMARY KEY CLUSTERED 
(
	[depth_datum] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_seis_file_catalog]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_seis_file_catalog](
	[catalog_id] [nvarchar](40) NOT NULL,
	[seis_set_id] [nvarchar](40) NULL,
	[full_path] [nvarchar](1000) NOT NULL,
	[file_name] [nvarchar](500) NOT NULL,
	[file_ext] [nvarchar](20) NULL,
	[file_size_kb] [numeric](15, 2) NULL,
	[file_hash] [nvarchar](64) NULL,
	[file_format] [nvarchar](20) NULL,
	[segy_revision] [nvarchar](10) NULL,
	[trace_count] [int] NULL,
	[sample_rate_ms] [numeric](10, 4) NULL,
	[record_length_ms] [numeric](10, 3) NULL,
	[line_name_in_file] [nvarchar](255) NULL,
	[survey_name_in_file] [nvarchar](255) NULL,
	[shot_point_count] [int] NULL,
	[catalog_status] [nvarchar](20) NULL,
	[catalog_date] [datetime2](7) NULL,
	[error_msg] [nvarchar](2000) NULL,
	[root_path] [nvarchar](500) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_seis_file_catalog] PRIMARY KEY CLUSTERED 
(
	[catalog_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_seis_line]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_seis_line](
	[seis_set_id] [nvarchar](40) NOT NULL,
	[line_id] [nvarchar](40) NOT NULL,
	[line_name] [nvarchar](255) NULL,
	[line_type] [nvarchar](40) NULL,
	[shot_point_start] [numeric](15, 4) NULL,
	[shot_point_end] [numeric](15, 4) NULL,
	[cdp_start] [int] NULL,
	[cdp_end] [int] NULL,
	[record_length_ms] [numeric](10, 3) NULL,
	[sample_rate_ms] [numeric](10, 4) NULL,
	[trace_count] [int] NULL,
	[file_path] [nvarchar](1000) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_seis_line] PRIMARY KEY CLUSTERED 
(
	[seis_set_id] ASC,
	[line_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_seis_set]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_seis_set](
	[seis_set_id] [nvarchar](40) NOT NULL,
	[seis_set_name] [nvarchar](255) NOT NULL,
	[seis_set_type] [nvarchar](40) NULL,
	[survey_date] [datetime2](7) NULL,
	[contractor_ba_id] [nvarchar](40) NULL,
	[operator_ba_id] [nvarchar](40) NULL,
	[country] [nvarchar](40) NULL,
	[province_state] [nvarchar](100) NULL,
	[basin_name] [nvarchar](255) NULL,
	[survey_area_km2] [numeric](15, 4) NULL,
	[bbox_min_lat] [numeric](15, 10) NULL,
	[bbox_max_lat] [numeric](15, 10) NULL,
	[bbox_min_lon] [numeric](15, 10) NULL,
	[bbox_max_lon] [numeric](15, 10) NULL,
	[epsg_code] [int] NULL,
	[file_path] [nvarchar](1000) NULL,
	[catalog_id] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_seis_set] PRIMARY KEY CLUSTERED 
(
	[seis_set_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_source]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_source](
	[source] [nvarchar](40) NOT NULL,
	[source_type] [nvarchar](40) NULL,
	[short_name] [nvarchar](40) NULL,
	[long_name] [nvarchar](255) NULL,
	[description] [nvarchar](2000) NULL,
	[url] [nvarchar](1000) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source_ref] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_source] PRIMARY KEY CLUSTERED 
(
	[source] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_spatial_layer]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_spatial_layer](
	[layer_id] [nvarchar](40) NOT NULL,
	[layer_name] [nvarchar](255) NOT NULL,
	[layer_type] [nvarchar](40) NULL,
	[layer_category] [nvarchar](40) NULL,
	[epsg_code] [int] NULL,
	[file_path] [nvarchar](1000) NULL,
	[feature_count] [int] NULL,
	[bbox_min_lat] [numeric](15, 10) NULL,
	[bbox_max_lat] [numeric](15, 10) NULL,
	[bbox_min_lon] [numeric](15, 10) NULL,
	[bbox_max_lon] [numeric](15, 10) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
	[geometry_wkt] [nvarchar](max) NULL,
	[source_type] [nvarchar](40) NULL,
	[style_color] [nvarchar](20) NULL,
	[style_weight] [numeric](5, 2) NULL,
	[style_opacity] [numeric](5, 2) NULL,
	[style_fill_color] [nvarchar](20) NULL,
	[style_fill_opacity] [numeric](5, 2) NULL,
	[style_dash] [nvarchar](40) NULL,
	[tooltip_fields] [nvarchar](500) NULL,
	[display_order] [int] NULL,
 CONSTRAINT [pk_dv_spatial_layer] PRIMARY KEY CLUSTERED 
(
	[layer_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_stg_well]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_stg_well](
	[_stg_row_id] [int] IDENTITY(1,1) NOT NULL,
	[_stg_source] [nvarchar](40) NULL,
	[_stg_loaded_at] [datetime2](7) NULL,
	[API_NUMBER] [nvarchar](500) NULL,
	[API_NUM_NODASH] [nvarchar](500) NULL,
	[LEASE] [nvarchar](500) NULL,
	[WELL] [nvarchar](500) NULL,
	[FIELD] [nvarchar](500) NULL,
	[LATITUDE] [nvarchar](500) NULL,
	[LONGITUDE] [nvarchar](500) NULL,
	[LONG_LAT_SOURCE] [nvarchar](500) NULL,
	[ORIG_OPERATOR] [nvarchar](500) NULL,
	[CURR_OPERATOR] [nvarchar](500) NULL,
	[ELEVATION] [nvarchar](500) NULL,
	[ELEV_REF] [nvarchar](500) NULL,
	[SURFACE_ELEVATION_LIDAR] [nvarchar](500) NULL,
	[DEPTH] [nvarchar](500) NULL,
	[FORMATION_AT_TOTAL_DEPTH] [nvarchar](500) NULL,
	[PRODUCE_FORM] [nvarchar](500) NULL,
	[PERMIT] [nvarchar](500) NULL,
	[SPUD] [nvarchar](500) NULL,
	[COMPLETION] [nvarchar](500) NULL,
	[KCC_PERMIT] [nvarchar](500) NULL,
	[STATUS] [nvarchar](500) NULL,
	[COMMENTS] [nvarchar](500) NULL,
	[LEASE_WELL_NAME] [nvarchar](500) NULL,
PRIMARY KEY CLUSTERED 
(
	[_stg_row_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_strat_interval]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_strat_interval](
	[uwi] [nvarchar](40) NOT NULL,
	[strat_unit_id] [nvarchar](40) NOT NULL,
	[interp_id] [nvarchar](40) NOT NULL,
	[interval_id] [nvarchar](40) NOT NULL,
	[interval_type] [nvarchar](40) NULL,
	[interval_name] [nvarchar](255) NULL,
	[top_depth] [numeric](15, 4) NULL,
	[base_depth] [numeric](15, 4) NULL,
	[net_thickness] [numeric](15, 4) NULL,
	[depth_ouom] [nvarchar](40) NULL,
	[porosity] [numeric](10, 4) NULL,
	[water_saturation] [numeric](10, 4) NULL,
	[permeability] [numeric](15, 4) NULL,
	[perm_ouom] [nvarchar](40) NULL,
	[fluid_type] [nvarchar](40) NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_strat_interval] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[strat_unit_id] ASC,
	[interp_id] ASC,
	[interval_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well](
	[uwi] [nvarchar](40) NOT NULL,
	[well_name] [nvarchar](255) NULL,
	[well_num] [nvarchar](40) NULL,
	[operator_ba_id] [nvarchar](40) NULL,
	[field_id] [nvarchar](40) NULL,
	[well_type] [nvarchar](40) NULL,
	[well_status] [nvarchar](40) NULL,
	[country] [nvarchar](3) NULL,
	[province_state] [nvarchar](10) NULL,
	[county] [nvarchar](40) NULL,
	[legal_survey_type] [nvarchar](40) NULL,
	[surface_latitude] [numeric](15, 10) NULL,
	[surface_longitude] [numeric](15, 10) NULL,
	[ground_elevation] [numeric](15, 4) NULL,
	[kb_elevation] [numeric](15, 4) NULL,
	[spud_date] [datetime2](7) NULL,
	[completion_date] [datetime2](7) NULL,
	[final_td] [numeric](15, 4) NULL,
	[depth_datum] [nvarchar](40) NULL,
	[epsg_code] [int] NULL,
	[api_num] [nvarchar](20) NULL,
	[license_num] [nvarchar](40) NULL,
	[lease_name] [nvarchar](255) NULL,
	[onshore_offshore_ind] [nvarchar](10) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
	[abandonment_date] [datetime2](7) NULL,
	[bottom_hole_latitude] [numeric](15, 10) NULL,
	[bottom_hole_longitude] [numeric](15, 10) NULL,
	[current_operator_ba_id] [nvarchar](40) NULL,
	[original_operator_ba_id] [nvarchar](40) NULL,
	[elevation_ouom] [nvarchar](40) NULL,
	[formation_at_td] [nvarchar](255) NULL,
	[long_lat_source] [nvarchar](40) NULL,
	[permit_number] [nvarchar](40) NULL,
	[producing_formation] [nvarchar](255) NULL,
 CONSTRAINT [pk_dv_well] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_alias]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_alias](
	[uwi] [nvarchar](40) NOT NULL,
	[alias_id] [nvarchar](40) NOT NULL,
	[alias_name] [nvarchar](255) NOT NULL,
	[alias_type] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_well_alias] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[alias_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_casing]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_casing](
	[uwi] [nvarchar](40) NOT NULL,
	[casing_id] [nvarchar](40) NOT NULL,
	[casing_type] [nvarchar](40) NOT NULL,
	[string_num] [int] NULL,
	[set_date] [date] NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[depth_datum] [nvarchar](40) NOT NULL,
	[od_in] [nvarchar](255) NOT NULL,
	[weight_lb_ft] [float] NOT NULL,
	[grade] [nvarchar](40) NOT NULL,
	[connection_type] [nvarchar](40) NOT NULL,
	[cement_top] [nvarchar](255) NOT NULL,
	[cement_base] [nvarchar](255) NOT NULL,
	[cement_volume_sacks] [float] NOT NULL,
	[cement_type] [nvarchar](40) NOT NULL,
	[burst_rating_psi] [float] NOT NULL,
	[collapse_rating_psi] [float] NOT NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_casing] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[casing_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_completion]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_completion](
	[uwi] [nvarchar](40) NOT NULL,
	[completion_id] [nvarchar](40) NOT NULL,
	[completion_type] [nvarchar](40) NOT NULL,
	[completion_date] [date] NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[depth_datum] [nvarchar](40) NOT NULL,
	[strat_unit_name] [nvarchar](40) NOT NULL,
	[completion_status] [nvarchar](40) NOT NULL,
	[primary_fluid] [nvarchar](40) NOT NULL,
	[tubing_size_in] [float] NOT NULL,
	[tubing_depth] [float] NOT NULL,
	[artificial_lift_type] [nvarchar](40) NOT NULL,
	[operator_ba_id] [nvarchar](40) NOT NULL,
	[contractor_ba_id] [nvarchar](40) NOT NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_completion] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[completion_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_core]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_core](
	[uwi] [nvarchar](40) NOT NULL,
	[core_id] [nvarchar](40) NOT NULL,
	[core_num] [int] NOT NULL,
	[core_type] [nvarchar](40) NOT NULL,
	[core_show] [nvarchar](255) NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[depth_datum] [nvarchar](40) NOT NULL,
	[core_length] [nvarchar](255) NOT NULL,
	[recovery_length] [float] NOT NULL,
	[recovery_pct] [float] NOT NULL,
	[length_ouom] [nvarchar](40) NOT NULL,
	[core_date] [date] NOT NULL,
	[cutting_company_ba_id] [nvarchar](40) NOT NULL,
	[analysis_company_ba_id] [nvarchar](40) NOT NULL,
	[strat_unit_name] [nvarchar](40) NOT NULL,
	[file_path] [nvarchar](500) NULL,
	[photo_count] [int] NOT NULL,
	[photo_folder_path] [nvarchar](500) NULL,
	[has_uv_photos] [nvarchar](40) NOT NULL,
	[has_thin_section_photos] [nvarchar](40) NOT NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_core] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[core_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_core_photo]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_core_photo](
	[uwi] [nvarchar](40) NOT NULL,
	[core_id] [nvarchar](40) NOT NULL,
	[photo_id] [nvarchar](40) NOT NULL,
	[photo_type] [nvarchar](40) NOT NULL,
	[lighting] [nvarchar](255) NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[tray_num] [int] NOT NULL,
	[photo_date] [date] NOT NULL,
	[file_path] [nvarchar](500) NULL,
	[file_name] [nvarchar](255) NULL,
	[file_ext] [nvarchar](20) NULL,
	[file_size_kb] [float] NOT NULL,
	[file_hash] [nvarchar](64) NULL,
	[resolution_dpi] [float] NOT NULL,
	[width_px] [float] NOT NULL,
	[height_px] [float] NOT NULL,
	[sample_id] [nvarchar](40) NULL,
	[catalog_id] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_core_photo] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[core_id] ASC,
	[photo_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_core_sample]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_core_sample](
	[uwi] [nvarchar](40) NOT NULL,
	[core_id] [nvarchar](40) NOT NULL,
	[sample_id] [nvarchar](40) NOT NULL,
	[sample_type] [nvarchar](40) NULL,
	[sample_depth] [float] NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[porosity_frac] [float] NOT NULL,
	[permeability_air_md] [float] NOT NULL,
	[permeability_klinkenberg_md] [float] NOT NULL,
	[water_saturation_frac] [float] NOT NULL,
	[grain_density_g_cc] [float] NOT NULL,
	[bulk_density_g_cc] [float] NOT NULL,
	[oil_saturation_frac] [float] NULL,
	[gas_saturation_frac] [float] NULL,
	[formation_factor] [float] NULL,
	[cementation_exponent] [float] NULL,
	[saturation_exponent] [float] NULL,
	[lithology] [nvarchar](40) NULL,
	[visual_porosity] [nvarchar](40) NULL,
	[hydrocarbon_show] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_core_sample] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[core_id] ASC,
	[sample_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_dir_srvy_hdr]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_dir_srvy_hdr](
	[uwi] [nvarchar](40) NOT NULL,
	[survey_id] [nvarchar](40) NOT NULL,
	[survey_type] [nvarchar](40) NULL,
	[survey_date] [datetime2](7) NULL,
	[contractor_ba_id] [nvarchar](40) NULL,
	[depth_datum] [nvarchar](40) NULL,
	[depth_datum_elevation] [numeric](15, 4) NULL,
	[survey_top_depth] [numeric](15, 4) NULL,
	[survey_base_depth] [numeric](15, 4) NULL,
	[depth_ouom] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_well_dir_srvy_hdr] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[survey_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_dir_srvy_sta]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_dir_srvy_sta](
	[uwi] [nvarchar](40) NOT NULL,
	[survey_id] [nvarchar](40) NOT NULL,
	[station_id] [nvarchar](40) NOT NULL,
	[md] [numeric](15, 4) NULL,
	[incl] [numeric](10, 4) NULL,
	[azim] [numeric](10, 4) NULL,
	[tvd] [numeric](15, 4) NULL,
	[ns_offset] [numeric](15, 4) NULL,
	[ew_offset] [numeric](15, 4) NULL,
	[surface_latitude] [numeric](15, 10) NULL,
	[surface_longitude] [numeric](15, 10) NULL,
	[dls] [numeric](10, 4) NULL,
	[depth_ouom] [nvarchar](40) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_well_dir_srvy_sta] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[survey_id] ASC,
	[station_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_dst]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_dst](
	[uwi] [nvarchar](40) NOT NULL,
	[dst_id] [nvarchar](40) NOT NULL,
	[dst_num] [int] NOT NULL,
	[test_type] [nvarchar](40) NOT NULL,
	[test_date] [date] NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[depth_datum] [nvarchar](40) NOT NULL,
	[strat_unit_name] [nvarchar](40) NOT NULL,
	[tool_type] [nvarchar](40) NOT NULL,
	[perforation_top] [nvarchar](255) NOT NULL,
	[perforation_base] [nvarchar](255) NOT NULL,
	[max_shut_in_pressure] [float] NULL,
	[final_shut_in_pressure] [float] NOT NULL,
	[pressure_ouom] [nvarchar](40) NOT NULL,
	[max_oil_rate] [float] NULL,
	[max_gas_rate] [float] NULL,
	[max_water_rate] [float] NULL,
	[rate_ouom] [nvarchar](40) NOT NULL,
	[gor] [float] NULL,
	[api_gravity] [float] NULL,
	[h2s_pct] [float] NOT NULL,
	[co2_pct] [float] NOT NULL,
	[test_result] [nvarchar](40) NOT NULL,
	[contractor_ba_id] [nvarchar](40) NOT NULL,
	[file_path] [nvarchar](500) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_dst] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[dst_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_dst_period]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_dst_period](
	[uwi] [nvarchar](40) NOT NULL,
	[dst_id] [nvarchar](40) NOT NULL,
	[period_id] [nvarchar](40) NOT NULL,
	[period_type] [nvarchar](40) NOT NULL,
	[period_seq] [int] NOT NULL,
	[duration_min] [float] NOT NULL,
	[start_pressure] [float] NOT NULL,
	[end_pressure] [float] NOT NULL,
	[pressure_ouom] [nvarchar](40) NOT NULL,
	[avg_oil_rate] [float] NOT NULL,
	[avg_gas_rate] [float] NOT NULL,
	[avg_water_rate] [float] NOT NULL,
	[rate_ouom] [nvarchar](40) NOT NULL,
	[choke_size] [nvarchar](20) NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
 CONSTRAINT [pk_dv_well_dst_period] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[dst_id] ASC,
	[period_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_formation_top]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_formation_top](
	[uwi] [nvarchar](40) NOT NULL,
	[strat_unit_id] [nvarchar](40) NOT NULL,
	[interp_id] [nvarchar](40) NOT NULL,
	[strat_name_set] [nvarchar](255) NULL,
	[strat_unit_name] [nvarchar](255) NULL,
	[strat_unit_type] [nvarchar](40) NULL,
	[strat_unit_subtype] [nvarchar](40) NULL,
	[age_top_ma] [numeric](10, 3) NULL,
	[age_base_ma] [numeric](10, 3) NULL,
	[lithology] [nvarchar](100) NULL,
	[top_depth] [numeric](15, 4) NULL,
	[base_depth] [numeric](15, 4) NULL,
	[gross_thickness]  AS (case when [base_depth] IS NOT NULL AND [top_depth] IS NOT NULL then [base_depth]-[top_depth]  end),
	[depth_ouom] [nvarchar](40) NULL,
	[depth_datum] [nvarchar](40) NULL,
	[tvd_top] [numeric](15, 4) NULL,
	[tvd_base] [numeric](15, 4) NULL,
	[owc_depth] [numeric](15, 4) NULL,
	[goc_depth] [numeric](15, 4) NULL,
	[gwc_depth] [numeric](15, 4) NULL,
	[interp_date] [datetime2](7) NULL,
	[interpreter_ba_id] [nvarchar](40) NULL,
	[confidence_level] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_well_formation_top] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[strat_unit_id] ASC,
	[interp_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_identifier]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_identifier](
	[well_id] [uniqueidentifier] NOT NULL,
	[identifier_type] [nvarchar](20) NOT NULL,
	[identifier_value] [nvarchar](40) NOT NULL,
	[source_system] [nvarchar](40) NULL,
	[loaded_date] [datetime2](0) NOT NULL,
	[is_primary] [bit] NOT NULL,
 CONSTRAINT [pk_dv_well_identifier] PRIMARY KEY CLUSTERED 
(
	[well_id] ASC,
	[identifier_type] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_log]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_log](
	[uwi] [nvarchar](40) NOT NULL,
	[log_id] [nvarchar](40) NOT NULL,
	[log_type] [nvarchar](40) NULL,
	[run_num] [nvarchar](10) NULL,
	[log_date] [datetime2](7) NULL,
	[service_company_ba_id] [nvarchar](40) NULL,
	[depth_datum] [nvarchar](40) NULL,
	[top_depth] [numeric](15, 4) NULL,
	[base_depth] [numeric](15, 4) NULL,
	[depth_ouom] [nvarchar](40) NULL,
	[null_value] [numeric](15, 4) NULL,
	[file_path] [nvarchar](1000) NULL,
	[file_format] [nvarchar](20) NULL,
	[catalog_id] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_well_log] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[log_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_log_curve]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_log_curve](
	[uwi] [nvarchar](40) NOT NULL,
	[log_id] [nvarchar](40) NOT NULL,
	[curve_id] [nvarchar](40) NOT NULL,
	[mnemonic] [nvarchar](40) NOT NULL,
	[mnemonic_alias] [nvarchar](40) NULL,
	[curve_description] [nvarchar](255) NULL,
	[curve_unit] [nvarchar](40) NULL,
	[null_value] [numeric](15, 4) NULL,
	[top_depth] [numeric](15, 4) NULL,
	[base_depth] [numeric](15, 4) NULL,
	[depth_ouom] [nvarchar](40) NULL,
	[min_value] [numeric](20, 6) NULL,
	[max_value] [numeric](20, 6) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_well_log_curve] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[log_id] ASC,
	[curve_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_mud_log]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_mud_log](
	[uwi] [nvarchar](40) NOT NULL,
	[mud_log_id] [nvarchar](40) NOT NULL,
	[log_date] [date] NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[contractor_ba_id] [nvarchar](40) NULL,
	[rop_avg] [float] NOT NULL,
	[rop_ouom] [nvarchar](255) NOT NULL,
	[mud_type] [nvarchar](40) NOT NULL,
	[mud_weight_avg] [float] NOT NULL,
	[mud_weight_ouom] [nvarchar](40) NULL,
	[file_path] [nvarchar](500) NULL,
	[catalog_id] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[mud_logger_ba_id] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_well_mud_log] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[mud_log_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_perforation]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_perforation](
	[uwi] [nvarchar](40) NOT NULL,
	[completion_id] [nvarchar](40) NOT NULL,
	[perf_id] [nvarchar](40) NOT NULL,
	[perf_date] [date] NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[shot_count] [int] NOT NULL,
	[shot_density] [float] NOT NULL,
	[shot_density_ouom] [nvarchar](40) NULL,
	[perf_diameter_in] [nvarchar](255) NOT NULL,
	[gun_type] [nvarchar](40) NOT NULL,
	[phasing_deg] [nvarchar](40) NOT NULL,
	[strat_unit_name] [nvarchar](40) NOT NULL,
	[perf_status] [nvarchar](40) NOT NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_perforation] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[completion_id] ASC,
	[perf_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_petro_interp]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_petro_interp](
	[uwi] [nvarchar](40) NOT NULL,
	[interp_id] [nvarchar](40) NOT NULL,
	[interp_name] [nvarchar](255) NOT NULL,
	[interp_date] [date] NOT NULL,
	[analyst_ba_id] [nvarchar](40) NULL,
	[software] [nvarchar](40) NOT NULL,
	[software_version] [nvarchar](40) NOT NULL,
	[gr_log_id] [nvarchar](40) NULL,
	[res_log_id] [nvarchar](40) NULL,
	[density_log_id] [nvarchar](40) NULL,
	[neutron_log_id] [nvarchar](40) NULL,
	[sonic_log_id] [nvarchar](40) NULL,
	[other_log_inputs] [nvarchar](500) NULL,
	[formation_water_resist] [float] NOT NULL,
	[rw_temperature] [float] NOT NULL,
	[temperature_ouom] [nvarchar](40) NULL,
	[archie_a] [float] NOT NULL,
	[archie_m] [float] NOT NULL,
	[archie_n] [float] NOT NULL,
	[shale_volume_method] [nvarchar](40) NULL,
	[porosity_method] [nvarchar](40) NULL,
	[fluid_density_g_cc] [float] NOT NULL,
	[matrix_density_g_cc] [float] NOT NULL,
	[sw_method] [nvarchar](40) NOT NULL,
	[output_file_path] [nvarchar](500) NULL,
	[interp_status] [nvarchar](40) NOT NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_petro_interp] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[interp_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_petro_zone]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_petro_zone](
	[uwi] [nvarchar](40) NOT NULL,
	[interp_id] [nvarchar](40) NOT NULL,
	[zone_id] [nvarchar](40) NOT NULL,
	[zone_name] [nvarchar](255) NOT NULL,
	[zone_type] [nvarchar](40) NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[depth_datum] [nvarchar](40) NOT NULL,
	[tvd_top] [float] NULL,
	[tvd_base] [float] NULL,
	[strat_unit_id] [nvarchar](40) NOT NULL,
	[strat_interp_id] [nvarchar](40) NOT NULL,
	[strat_unit_name] [nvarchar](40) NOT NULL,
	[gross_thickness] [float] NOT NULL,
	[net_thickness] [float] NOT NULL,
	[net_to_gross] [float] NOT NULL,
	[vsh_avg] [float] NULL,
	[vsh_min] [float] NULL,
	[vsh_max] [float] NULL,
	[phi_total_avg] [float] NULL,
	[phi_effective_avg] [float] NULL,
	[phi_method] [nvarchar](40) NOT NULL,
	[sw_avg] [float] NULL,
	[sw_min] [float] NULL,
	[sw_max] [float] NULL,
	[sw_method] [nvarchar](40) NOT NULL,
	[sh_avg] [float] NULL,
	[perm_avg_md] [float] NULL,
	[perm_geomean_md] [float] NULL,
	[perm_method] [nvarchar](40) NOT NULL,
	[bvw_avg] [float] NOT NULL,
	[bvh_avg] [float] NOT NULL,
	[fluid_type] [nvarchar](40) NOT NULL,
	[pay_flag] [nvarchar](40) NOT NULL,
	[pay_cutoff_phi] [float] NULL,
	[pay_cutoff_sw] [float] NULL,
	[pay_cutoff_vsh] [float] NULL,
	[hcpv] [float] NULL,
	[hcpv_ouom] [nvarchar](40) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_petro_zone] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[interp_id] ASC,
	[zone_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_pressure]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_pressure](
	[uwi] [nvarchar](40) NOT NULL,
	[pressure_id] [nvarchar](40) NOT NULL,
	[pressure_type] [nvarchar](40) NOT NULL,
	[test_date] [date] NOT NULL,
	[depth] [nvarchar](255) NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[depth_datum] [nvarchar](40) NOT NULL,
	[pressure] [nvarchar](255) NOT NULL,
	[pressure_ouom] [nvarchar](40) NOT NULL,
	[temperature] [float] NOT NULL,
	[temperature_ouom] [nvarchar](40) NULL,
	[fluid_type] [nvarchar](40) NOT NULL,
	[mobility] [float] NOT NULL,
	[strat_unit_name] [nvarchar](40) NOT NULL,
	[tool_type] [nvarchar](40) NOT NULL,
	[contractor_ba_id] [nvarchar](40) NOT NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_pressure] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[pressure_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_shows]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_shows](
	[uwi] [nvarchar](40) NOT NULL,
	[mud_log_id] [nvarchar](40) NOT NULL,
	[show_id] [nvarchar](40) NOT NULL,
	[show_type] [nvarchar](40) NOT NULL,
	[show_rating] [nvarchar](255) NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[strat_unit_name] [nvarchar](40) NOT NULL,
	[lithology] [nvarchar](40) NOT NULL,
	[total_gas_units] [float] NOT NULL,
	[c1_pct] [float] NOT NULL,
	[c2_pct] [float] NOT NULL,
	[c3_pct] [float] NOT NULL,
	[ic4_pct] [float] NOT NULL,
	[nc4_pct] [float] NOT NULL,
	[ic5_pct] [float] NULL,
	[nc5_pct] [float] NULL,
	[fluorescence_color] [nvarchar](40) NULL,
	[fluorescence_intensity] [nvarchar](40) NULL,
	[cut_color] [nvarchar](40) NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NULL,
 CONSTRAINT [pk_dv_well_shows] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[mud_log_id] ASC,
	[show_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_well_stimulation]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_well_stimulation](
	[uwi] [nvarchar](40) NOT NULL,
	[completion_id] [nvarchar](40) NOT NULL,
	[stim_id] [nvarchar](40) NOT NULL,
	[stim_type] [nvarchar](40) NOT NULL,
	[stim_date] [date] NOT NULL,
	[top_depth] [float] NOT NULL,
	[base_depth] [float] NOT NULL,
	[depth_ouom] [nvarchar](40) NOT NULL,
	[stage_count] [int] NULL,
	[fluid_type] [nvarchar](40) NOT NULL,
	[fluid_volume] [float] NOT NULL,
	[fluid_volume_ouom] [nvarchar](40) NULL,
	[proppant_type] [nvarchar](40) NOT NULL,
	[proppant_mesh] [nvarchar](40) NOT NULL,
	[proppant_mass] [float] NOT NULL,
	[proppant_mass_ouom] [nvarchar](40) NULL,
	[max_treating_pressure] [float] NOT NULL,
	[avg_treating_pressure] [float] NOT NULL,
	[pressure_ouom] [nvarchar](40) NOT NULL,
	[max_pump_rate] [float] NOT NULL,
	[rate_ouom] [nvarchar](40) NOT NULL,
	[isip] [float] NOT NULL,
	[closure_pressure] [float] NOT NULL,
	[contractor_ba_id] [nvarchar](40) NULL,
	[file_path] [nvarchar](500) NULL,
	[active_ind] [nvarchar](1) NOT NULL,
	[remark] [nvarchar](2000) NULL,
	[source] [nvarchar](40) NOT NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[service_co_ba_id] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_well_stimulation] PRIMARY KEY CLUSTERED 
(
	[uwi] ASC,
	[completion_id] ASC,
	[stim_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[dv_wl_file_catalog]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[dv_wl_file_catalog](
	[catalog_id] [nvarchar](40) NOT NULL,
	[uwi] [nvarchar](40) NULL,
	[full_path] [nvarchar](1000) NOT NULL,
	[file_name] [nvarchar](500) NOT NULL,
	[file_ext] [nvarchar](20) NULL,
	[file_size_kb] [numeric](15, 2) NULL,
	[file_hash] [nvarchar](64) NULL,
	[file_format] [nvarchar](20) NULL,
	[las_version] [nvarchar](10) NULL,
	[well_name_in_file] [nvarchar](255) NULL,
	[uwi_in_file] [nvarchar](40) NULL,
	[service_company] [nvarchar](255) NULL,
	[log_date] [datetime2](7) NULL,
	[top_depth] [numeric](15, 4) NULL,
	[base_depth] [numeric](15, 4) NULL,
	[depth_ouom] [nvarchar](40) NULL,
	[curve_count] [int] NULL,
	[curve_list] [nvarchar](2000) NULL,
	[ppdm_loaded_ind] [nvarchar](1) NOT NULL,
	[ppdm_log_id] [nvarchar](40) NULL,
	[catalog_status] [nvarchar](20) NULL,
	[catalog_date] [datetime2](7) NULL,
	[error_msg] [nvarchar](2000) NULL,
	[root_path] [nvarchar](500) NULL,
	[row_created_by] [nvarchar](40) NOT NULL,
	[row_created_date] [datetime2](7) NOT NULL,
	[row_changed_by] [nvarchar](40) NULL,
	[row_changed_date] [datetime2](7) NULL,
	[source] [nvarchar](40) NULL,
 CONSTRAINT [pk_dv_wl_file_catalog] PRIMARY KEY CLUSTERED 
(
	[catalog_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview].[state_polygon]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview].[state_polygon](
	[state_abbrev] [varchar](2) NOT NULL,
	[state_name] [nvarchar](50) NOT NULL,
	[fips_code] [varchar](2) NULL,
	[min_lat] [decimal](11, 7) NULL,
	[max_lat] [decimal](11, 7) NULL,
	[min_lon] [decimal](11, 7) NULL,
	[max_lon] [decimal](11, 7) NULL,
	[state_polygon] [geography] NULL,
	[loaded_date] [datetime2](7) NULL,
	[source] [nvarchar](100) NULL,
 CONSTRAINT [PK_state_polygon] PRIMARY KEY CLUSTERED 
(
	[state_abbrev] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
/****** Object:  Table [dataview_gom].[directional_survey_point]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview_gom].[directional_survey_point](
	[survey_point_id] [bigint] IDENTITY(1,1) NOT NULL,
	[api_well_number] [nvarchar](20) NOT NULL,
	[well_id] [uniqueidentifier] NULL,
	[survey_point_md] [decimal](10, 2) NULL,
	[incl_ang] [decimal](8, 3) NULL,
	[azimuth] [decimal](8, 3) NULL,
	[survey_point_tvd] [decimal](10, 2) NULL,
	[latitude] [decimal](11, 7) NULL,
	[longitude] [decimal](11, 7) NULL,
	[last_update] [date] NULL,
	[source_file] [nvarchar](255) NULL,
	[loaded_date] [datetime2](0) NOT NULL,
	[row_changed_date] [datetime2](0) NOT NULL,
 CONSTRAINT [PK_dvgom_directional_survey_point] PRIMARY KEY CLUSTERED 
(
	[survey_point_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [dataview_gom].[well]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dataview_gom].[well](
	[well_id] [uniqueidentifier] NOT NULL,
	[api_well_number] [nvarchar](20) NOT NULL,
	[well_name] [nvarchar](40) NULL,
	[well_name_suffix] [nvarchar](20) NULL,
	[surface_lease_number] [nvarchar](20) NULL,
	[bottom_lease_number] [nvarchar](20) NULL,
	[bottom_area_code] [nvarchar](10) NULL,
	[bottom_block_number] [nvarchar](20) NULL,
	[region] [nvarchar](40) NULL,
	[company_name] [nvarchar](255) NULL,
	[spud_date] [date] NULL,
	[total_depth_date] [date] NULL,
	[status_date] [date] NULL,
	[bh_total_md_ft] [decimal](10, 2) NULL,
	[true_vertical_depth_ft] [decimal](10, 2) NULL,
	[tvd_subsea_ft] [decimal](10, 2) NULL,
	[rkb_ft] [decimal](10, 2) NULL,
	[kop_ft] [decimal](10, 2) NULL,
	[water_depth_ft] [decimal](10, 2) NULL,
	[type_code] [nvarchar](10) NULL,
	[status_code] [nvarchar](10) NULL,
	[casing_cut_code] [nvarchar](10) NULL,
	[underwater_comp_stub] [nvarchar](10) NULL,
	[surface_latitude] [decimal](11, 7) NULL,
	[surface_longitude] [decimal](11, 7) NULL,
	[bottom_latitude] [decimal](11, 7) NULL,
	[bottom_longitude] [decimal](11, 7) NULL,
	[source_file] [nvarchar](255) NULL,
	[loaded_date] [datetime2](0) NOT NULL,
	[row_changed_date] [datetime2](0) NOT NULL,
 CONSTRAINT [pk_dv_well_gom] PRIMARY KEY CLUSTERED 
(
	[well_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_dv_well_gom_api] UNIQUE NONCLUSTERED 
(
	[api_well_number] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[ASSIGNMENT_EXTENSION]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[ASSIGNMENT_EXTENSION](
	[EXTENSION_ID] [nvarchar](64) NOT NULL,
	[ASSIGNMENT_ID] [nvarchar](64) NOT NULL,
	[ORIGINAL_DUE_DATE] [date] NOT NULL,
	[NEW_DUE_DATE] [date] NOT NULL,
	[EXTENDED_BY] [nvarchar](64) NOT NULL,
	[EXTENDED_DATE] [datetime2](7) NOT NULL,
	[REASON] [nvarchar](500) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[EXTENSION_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[AUDIT_LOG]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[AUDIT_LOG](
	[AUDIT_ID] [nvarchar](40) NOT NULL,
	[EVENT_TIME] [datetime2](7) NOT NULL,
	[EVENT_TYPE] [nvarchar](50) NOT NULL,
	[USER_ID] [nvarchar](40) NULL,
	[USER_NAME] [nvarchar](255) NULL,
	[TARGET_ID] [nvarchar](40) NULL,
	[TARGET_TYPE] [nvarchar](50) NULL,
	[TARGET_NAME] [nvarchar](500) NULL,
	[OLD_VALUE] [nvarchar](max) NULL,
	[NEW_VALUE] [nvarchar](max) NULL,
	[NOTES] [nvarchar](1000) NULL,
	[SESSION_ID] [nvarchar](40) NULL,
PRIMARY KEY CLUSTERED 
(
	[AUDIT_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[CATALOG_SETTING]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[CATALOG_SETTING](
	[SETTING_KEY] [nvarchar](100) NOT NULL,
	[SETTING_VALUE] [nvarchar](900) NULL,
	[DESCRIPTION] [nvarchar](500) NULL,
	[UPDATED_DATE] [datetime2](7) NULL,
	[UPDATED_BY] [nvarchar](100) NULL,
 CONSTRAINT [PK_CATALOG_SETTING] PRIMARY KEY CLUSTERED 
(
	[SETTING_KEY] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[FILE_CURVE]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[FILE_CURVE](
	[FILE_CURVE_ID] [nvarchar](40) NOT NULL,
	[FILE_HEADER_ID] [nvarchar](40) NOT NULL,
	[MNEMONIC] [nvarchar](40) NOT NULL,
	[UNIT] [nvarchar](40) NULL,
	[DESCRIPTION] [nvarchar](200) NULL,
	[SORT_ORDER] [int] NULL,
 CONSTRAINT [PK_FILE_CURVE] PRIMARY KEY CLUSTERED 
(
	[FILE_CURVE_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[FILE_HEADER]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[FILE_HEADER](
	[FILE_HEADER_ID] [nvarchar](40) NOT NULL,
	[INVENTORY_ID] [nvarchar](64) NULL,
	[FILE_TYPE] [nvarchar](10) NOT NULL,
	[FILE_PATH] [nvarchar](900) NOT NULL,
	[FILE_NAME] [nvarchar](260) NOT NULL,
	[FILE_SIZE_KB] [decimal](15, 2) NULL,
	[MATCHED_UWI] [nvarchar](40) NULL,
	[MATCH_METHOD] [nvarchar](20) NULL,
	[MATCH_SCORE] [decimal](5, 2) NULL,
	[WELL_NAME] [nvarchar](200) NULL,
	[HEADER_TEXT] [nvarchar](max) NULL,
	[CATALOGED_BY] [nvarchar](64) NULL,
	[CATALOG_DATE] [datetime2](7) NULL,
	[ACTIVE_IND] [nvarchar](1) NOT NULL,
	[SOURCE] [nvarchar](100) NULL,
PRIMARY KEY CLUSTERED 
(
	[FILE_HEADER_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[FILE_SEIS_HEADER]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[FILE_SEIS_HEADER](
	[SEIS_HEADER_ID] [nvarchar](40) NOT NULL,
	[INVENTORY_ID] [nvarchar](40) NOT NULL,
	[SURVEY_NAME] [nvarchar](255) NULL,
	[LINE_NAME] [nvarchar](255) NULL,
	[SEIS_SET_TYPE] [nvarchar](40) NULL,
	[SURVEY_DATE] [nvarchar](20) NULL,
	[CONTRACTOR] [nvarchar](255) NULL,
	[BBOX_MIN_LAT] [decimal](11, 7) NULL,
	[BBOX_MAX_LAT] [decimal](11, 7) NULL,
	[BBOX_MIN_LON] [decimal](11, 7) NULL,
	[BBOX_MAX_LON] [decimal](11, 7) NULL,
	[EPSG_CODE] [int] NULL,
	[SAMPLE_INTERVAL] [decimal](10, 3) NULL,
	[TRACE_COUNT] [int] NULL,
	[SHOT_FIRST] [nvarchar](20) NULL,
	[SHOT_LAST] [nvarchar](20) NULL,
	[EXTRACTED_DATE] [datetime2](7) NOT NULL,
	[EXTRACTED_BY] [nvarchar](64) NOT NULL,
	[IL_MIN] [int] NULL,
	[IL_MAX] [int] NULL,
	[XL_MIN] [int] NULL,
	[XL_MAX] [int] NULL,
	[SURVEY_OUTLINE] [nvarchar](max) NULL,
 CONSTRAINT [PK_FILE_SEIS_HEADER] PRIMARY KEY CLUSTERED 
(
	[SEIS_HEADER_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[FILE_WELL_HEADER]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[FILE_WELL_HEADER](
	[WELL_HEADER_ID] [nvarchar](40) NOT NULL,
	[INVENTORY_ID] [nvarchar](40) NOT NULL,
	[UWI] [nvarchar](40) NULL,
	[WELL_NAME] [nvarchar](255) NULL,
	[OPERATOR] [nvarchar](255) NULL,
	[WELL_FIELD] [nvarchar](100) NULL,
	[STATE] [nvarchar](50) NULL,
	[COUNTY] [nvarchar](100) NULL,
	[LATITUDE] [decimal](11, 7) NULL,
	[LONGITUDE] [decimal](11, 7) NULL,
	[COORD_PRECISION] [tinyint] NULL,
	[TOTAL_DEPTH] [decimal](15, 5) NULL,
	[SPUD_DATE] [nvarchar](20) NULL,
	[RIG_RELEASE] [nvarchar](20) NULL,
	[REPORT_TYPE] [nvarchar](50) NULL,
	[SURVEY_TYPE] [nvarchar](50) NULL,
	[CONTRACTOR] [nvarchar](255) NULL,
	[CONFIDENCE] [decimal](5, 2) NULL,
	[EXTRACTED_DATE] [datetime2](7) NOT NULL,
	[EXTRACTED_BY] [nvarchar](64) NOT NULL,
 CONSTRAINT [PK_FILE_WELL_HEADER] PRIMARY KEY CLUSTERED 
(
	[WELL_HEADER_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[GLOBAL_FILE_CATALOG]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[GLOBAL_FILE_CATALOG](
	[INVENTORY_ID] [nvarchar](40) NOT NULL,
	[FILE_PATH] [nvarchar](1000) NOT NULL,
	[FILE_NAME] [nvarchar](500) NOT NULL,
	[FILE_EXT] [nvarchar](20) NULL,
	[FILE_SIZE_KB] [numeric](15, 2) NULL,
	[FILE_HASH] [nvarchar](64) NULL,
	[FILE_HASH_FULL] [nvarchar](64) NULL,
	[DUPLICATE_GROUP] [nvarchar](64) NULL,
	[MODIFIED_DATE] [datetime2](7) NULL,
	[SCAN_DATE] [datetime2](7) NOT NULL,
	[ROOT_PATH] [nvarchar](500) NULL,
	[FILE_TYPE_GROUP] [nvarchar](50) NULL,
	[DOC_TYPE] [nvarchar](100) NULL,
	[REPORT_TYPE] [nvarchar](100) NULL,
	[HEADER_EXTRACTED] [nvarchar](1) NULL,
	[FLAG_DELETE] [nvarchar](1) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NOT NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NOT NULL,
	[EXTRACTION_STATUS] [nvarchar](20) NULL,
	[CATALOG_SCORE] [int] NULL,
	[CATALOG_READINESS] [nvarchar](20) NULL,
	[CATALOG_ISSUES] [nvarchar](2000) NULL,
	[MATCHED_UWI] [nvarchar](40) NULL,
	[MATCH_METHOD] [nvarchar](40) NULL,
	[CATALOG_STATUS] [nvarchar](20) NULL,
	[CATALOG_TABLE] [nvarchar](100) NULL,
 CONSTRAINT [PK_GLOBAL_FILE_CATALOG] PRIMARY KEY CLUSTERED 
(
	[INVENTORY_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[INVENTORY_ASSIGNMENT]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[INVENTORY_ASSIGNMENT](
	[ASSIGNMENT_ID] [nvarchar](64) NOT NULL,
	[GROUP_ID] [nvarchar](64) NOT NULL,
	[ASSIGNED_TO] [nvarchar](64) NOT NULL,
	[ASSIGNED_BY] [nvarchar](64) NOT NULL,
	[ASSIGNED_DATE] [datetime2](7) NOT NULL,
	[DUE_DATE] [date] NULL,
	[COMPLETED_DATE] [datetime2](7) NULL,
	[STATUS] [nvarchar](20) NOT NULL,
	[NOTES] [nvarchar](1000) NULL,
	[FILE_COUNT] [int] NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[ASSIGNMENT_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[INVENTORY_GROUP]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[INVENTORY_GROUP](
	[GROUP_ID] [nvarchar](64) NOT NULL,
	[GROUP_NAME] [nvarchar](200) NOT NULL,
	[DESCRIPTION] [nvarchar](500) NULL,
	[FILE_TYPE] [nvarchar](20) NULL,
	[ROOT_PATH] [nvarchar](500) NULL,
	[TOTAL_FILES] [int] NOT NULL,
	[STATUS] [nvarchar](20) NOT NULL,
	[CREATED_BY] [nvarchar](64) NULL,
	[CREATED_DATE] [datetime2](7) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[GROUP_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[INVENTORY_GROUP_FILE]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[INVENTORY_GROUP_FILE](
	[GROUP_FILE_ID] [nvarchar](64) NOT NULL,
	[GROUP_ID] [nvarchar](64) NOT NULL,
	[ASSIGNMENT_ID] [nvarchar](64) NOT NULL,
	[INVENTORY_ID] [nvarchar](64) NOT NULL,
	[ADDED_BY] [nvarchar](64) NULL,
	[ADDED_DATE] [datetime2](7) NOT NULL,
	[CATALOGED_IND] [nvarchar](1) NOT NULL,
	[CATALOGED_DATE] [datetime2](7) NULL,
	[SKIPPED_IND] [nvarchar](1) NOT NULL,
	[SKIP_REASON] [nvarchar](500) NULL,
PRIMARY KEY CLUSTERED 
(
	[GROUP_FILE_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [file_catalog].[INVENTORY_USER]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [file_catalog].[INVENTORY_USER](
	[USER_ID] [nvarchar](64) NOT NULL,
	[FULL_NAME] [nvarchar](200) NOT NULL,
	[EMAIL] [nvarchar](200) NOT NULL,
	[PASSWORD_HASH] [nvarchar](64) NOT NULL,
	[ROLE] [nvarchar](20) NOT NULL,
	[ACTIVE_IND] [nvarchar](1) NOT NULL,
	[LAST_LOGIN] [datetime2](7) NULL,
	[CREATED_DATE] [datetime2](7) NOT NULL,
	[CREATED_BY] [nvarchar](64) NULL,
PRIMARY KEY CLUSTERED 
(
	[USER_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
UNIQUE NONCLUSTERED 
(
	[EMAIL] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[DLIS_CHANNEL]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[DLIS_CHANNEL](
	[DLIS_FILE_ID] [nvarchar](40) NOT NULL,
	[LOGICAL_FILE_IDX] [numeric](5, 0) NOT NULL,
	[FRAME_NAME] [nvarchar](100) NOT NULL,
	[CHANNEL_NAME] [nvarchar](40) NOT NULL,
	[LONG_NAME] [nvarchar](255) NULL,
	[UNITS] [nvarchar](40) NULL,
	[DIMENSION] [nvarchar](40) NULL,
	[IS_INDEX] [nvarchar](1) NOT NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [DLISCH_PK] PRIMARY KEY CLUSTERED 
(
	[DLIS_FILE_ID] ASC,
	[LOGICAL_FILE_IDX] ASC,
	[FRAME_NAME] ASC,
	[CHANNEL_NAME] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[DLIS_FILE]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[DLIS_FILE](
	[DLIS_FILE_ID] [nvarchar](40) NOT NULL,
	[REPOSITORY_ID] [nvarchar](40) NOT NULL,
	[UWI] [nvarchar](40) NOT NULL,
	[FILE_NAME] [nvarchar](500) NOT NULL,
	[FILE_SIZE_KB] [numeric](15, 2) NULL,
	[FILE_HASH] [nvarchar](64) NULL,
	[LOGICAL_FILE_COUNT] [numeric](5, 0) NULL,
	[CATALOG_DATE] [datetime2](7) NULL,
	[LAST_SEEN_DATE] [datetime2](7) NULL,
	[ACTIVE_IND] [nvarchar](1) NOT NULL,
	[REMARK] [nvarchar](2000) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [DLISFILE_PK] PRIMARY KEY CLUSTERED 
(
	[DLIS_FILE_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[DLIS_FRAME]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[DLIS_FRAME](
	[DLIS_FILE_ID] [nvarchar](40) NOT NULL,
	[LOGICAL_FILE_IDX] [numeric](5, 0) NOT NULL,
	[FRAME_NAME] [nvarchar](100) NOT NULL,
	[INDEX_CHANNEL] [nvarchar](40) NULL,
	[INDEX_TYPE] [nvarchar](40) NULL,
	[TOP_DEPTH] [numeric](15, 5) NULL,
	[BASE_DEPTH] [numeric](15, 5) NULL,
	[DEPTH_UOM] [nvarchar](20) NULL,
	[DEPTH_UOM_STD] [nvarchar](5) NULL,
	[TOP_DEPTH_M] [numeric](15, 3) NULL,
	[BASE_DEPTH_M] [numeric](15, 3) NULL,
	[SPACING] [numeric](15, 5) NULL,
	[CHANNEL_COUNT] [numeric](5, 0) NULL,
	[SAMPLE_COUNT] [numeric](15, 0) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [DLISFR_PK] PRIMARY KEY CLUSTERED 
(
	[DLIS_FILE_ID] ASC,
	[LOGICAL_FILE_IDX] ASC,
	[FRAME_NAME] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[DLIS_LOGICAL_FILE]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[DLIS_LOGICAL_FILE](
	[DLIS_FILE_ID] [nvarchar](40) NOT NULL,
	[LOGICAL_FILE_IDX] [numeric](5, 0) NOT NULL,
	[DESCRIPTION] [nvarchar](255) NULL,
	[WELL_NAME] [nvarchar](255) NULL,
	[WELL_ID] [nvarchar](100) NULL,
	[COMPANY] [nvarchar](255) NULL,
	[FIELD_NAME] [nvarchar](255) NULL,
	[PRODUCER_NAME] [nvarchar](255) NULL,
	[PRODUCT] [nvarchar](255) NULL,
	[VERSION] [nvarchar](100) NULL,
	[FILE_SET_NAME] [nvarchar](255) NULL,
	[RUN_NUMBER] [nvarchar](40) NULL,
	[CREATION_TIME] [datetime2](7) NULL,
	[ORDER_NUMBER] [nvarchar](40) NULL,
	[FRAME_COUNT] [numeric](5, 0) NULL,
	[CHANNEL_COUNT] [numeric](5, 0) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [DLISLF_PK] PRIMARY KEY CLUSTERED 
(
	[DLIS_FILE_ID] ASC,
	[LOGICAL_FILE_IDX] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[DLIS_PARAMETER]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[DLIS_PARAMETER](
	[DLIS_FILE_ID] [nvarchar](40) NOT NULL,
	[LOGICAL_FILE_IDX] [numeric](5, 0) NOT NULL,
	[PARAMETER_NAME] [nvarchar](40) NOT NULL,
	[LONG_NAME] [nvarchar](255) NULL,
	[VALUE] [nvarchar](500) NULL,
	[UNITS] [nvarchar](40) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [DLISPM_PK] PRIMARY KEY CLUSTERED 
(
	[DLIS_FILE_ID] ASC,
	[LOGICAL_FILE_IDX] ASC,
	[PARAMETER_NAME] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[LAS_FILE]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[LAS_FILE](
	[LAS_FILE_ID] [nvarchar](40) NOT NULL,
	[REPOSITORY_ID] [nvarchar](40) NOT NULL,
	[UWI] [nvarchar](40) NOT NULL,
	[WELL_NAME] [nvarchar](255) NULL,
	[FILE_NAME] [nvarchar](500) NOT NULL,
	[FILE_SIZE_KB] [numeric](15, 2) NULL,
	[LAS_VERSION] [nvarchar](10) NULL,
	[OPERATOR] [nvarchar](255) NULL,
	[FIELD] [nvarchar](255) NULL,
	[COUNTRY] [nvarchar](255) NULL,
	[STATE_PROVINCE] [nvarchar](255) NULL,
	[COUNTY] [nvarchar](255) NULL,
	[TOP_DEPTH] [numeric](15, 5) NULL,
	[BASE_DEPTH] [numeric](15, 5) NULL,
	[DEPTH_STEP] [numeric](15, 5) NULL,
	[DEPTH_UOM] [nvarchar](10) NULL,
	[LOG_DATE] [nvarchar](50) NULL,
	[SERVICE_COMPANY] [nvarchar](255) NULL,
	[CURVE_COUNT] [numeric](10, 0) NULL,
	[SAMPLE_COUNT] [numeric](15, 0) NULL,
	[FILE_HASH] [nvarchar](64) NULL,
	[CATALOG_DATE] [datetime2](7) NULL,
	[LAST_SEEN_DATE] [datetime2](7) NULL,
	[ACTIVE_IND] [nvarchar](1) NOT NULL,
	[REMARK] [nvarchar](2000) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [LASFILE_PK] PRIMARY KEY CLUSTERED 
(
	[LAS_FILE_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[LAS_FILE_CURVE]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[LAS_FILE_CURVE](
	[LAS_FILE_ID] [nvarchar](40) NOT NULL,
	[CURVE_ID] [nvarchar](40) NOT NULL,
	[CURVE_UNIT] [nvarchar](40) NULL,
	[CURVE_DESCRIPTION] [nvarchar](255) NULL,
	[CURVE_TYPE] [nvarchar](40) NULL,
	[API_CODE] [nvarchar](40) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [LASCURVE_PK] PRIMARY KEY CLUSTERED 
(
	[LAS_FILE_ID] ASC,
	[CURVE_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[LAS_FILE_PARAMETER]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[LAS_FILE_PARAMETER](
	[LAS_FILE_ID] [nvarchar](40) NOT NULL,
	[PARAMETER_NAME] [nvarchar](40) NOT NULL,
	[PARAMETER_VALUE] [nvarchar](500) NULL,
	[PARAMETER_UNIT] [nvarchar](40) NULL,
	[SECTION] [nvarchar](10) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [LASPARM_PK] PRIMARY KEY CLUSTERED 
(
	[LAS_FILE_ID] ASC,
	[PARAMETER_NAME] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[LIS_CHANNEL]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[LIS_CHANNEL](
	[LIS_FILE_ID] [nvarchar](40) NOT NULL,
	[CHANNEL_NAME] [nvarchar](40) NOT NULL,
	[UNITS] [nvarchar](40) NULL,
	[DESCRIPTION] [nvarchar](255) NULL,
	[IS_INDEX] [nvarchar](1) NOT NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [LISCH_PK] PRIMARY KEY CLUSTERED 
(
	[LIS_FILE_ID] ASC,
	[CHANNEL_NAME] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[LIS_FILE]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[LIS_FILE](
	[LIS_FILE_ID] [nvarchar](40) NOT NULL,
	[REPOSITORY_ID] [nvarchar](40) NOT NULL,
	[UWI] [nvarchar](40) NOT NULL,
	[FILE_NAME] [nvarchar](500) NOT NULL,
	[FILE_SIZE_KB] [numeric](15, 2) NULL,
	[FILE_HASH] [nvarchar](64) NULL,
	[WELL_NAME] [nvarchar](255) NULL,
	[COMPANY] [nvarchar](255) NULL,
	[FIELD_NAME] [nvarchar](255) NULL,
	[LOG_DATE] [nvarchar](50) NULL,
	[SERVICE_COMPANY] [nvarchar](255) NULL,
	[TOP_DEPTH] [numeric](15, 5) NULL,
	[BASE_DEPTH] [numeric](15, 5) NULL,
	[DEPTH_UOM] [nvarchar](10) NULL,
	[CHANNEL_COUNT] [numeric](5, 0) NULL,
	[SAMPLE_COUNT] [numeric](15, 0) NULL,
	[CATALOG_DATE] [datetime2](7) NULL,
	[LAST_SEEN_DATE] [datetime2](7) NULL,
	[ACTIVE_IND] [nvarchar](1) NOT NULL,
	[REMARK] [nvarchar](2000) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [LISFILE_PK] PRIMARY KEY CLUSTERED 
(
	[LIS_FILE_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[SEIS_FILE_CATALOG]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[SEIS_FILE_CATALOG](
	[SEIS_FILE_ID] [nvarchar](40) NOT NULL,
	[REPOSITORY_ID] [nvarchar](40) NULL,
	[FILE_FORMAT] [nvarchar](10) NOT NULL,
	[FILE_NAME] [nvarchar](500) NOT NULL,
	[FILE_SIZE_KB] [numeric](15, 2) NULL,
	[FILE_HASH] [nvarchar](64) NULL,
	[SEIS_SET_ID] [nvarchar](40) NULL,
	[SEIS_LINE_ID] [nvarchar](40) NULL,
	[SEIS_SET_SUBID] [nvarchar](40) NULL,
	[SURVEY_NAME] [nvarchar](255) NULL,
	[LINE_NAME] [nvarchar](255) NULL,
	[VESSEL_NAME] [nvarchar](255) NULL,
	[CLIENT_NAME] [nvarchar](255) NULL,
	[DIMENSIONALITY] [nvarchar](10) NULL,
	[SAMPLE_INTERVAL_US] [numeric](10, 2) NULL,
	[SAMPLE_COUNT] [numeric](10, 0) NULL,
	[TRACE_COUNT] [numeric](15, 0) NULL,
	[DATA_FORMAT] [nvarchar](40) NULL,
	[SEGY_REVISION] [nvarchar](10) NULL,
	[RECORD_COUNT] [numeric](10, 0) NULL,
	[SHOT_COUNT] [numeric](10, 0) NULL,
	[FIRST_SHOT_POINT] [numeric](10, 2) NULL,
	[LAST_SHOT_POINT] [numeric](10, 2) NULL,
	[NAV_SYSTEM] [nvarchar](40) NULL,
	[ACQ_DATE_START] [nvarchar](30) NULL,
	[ACQ_DATE_END] [nvarchar](30) NULL,
	[MIN_LAT] [numeric](12, 7) NULL,
	[MAX_LAT] [numeric](12, 7) NULL,
	[MIN_LON] [numeric](12, 7) NULL,
	[MAX_LON] [numeric](12, 7) NULL,
	[MIN_X] [numeric](18, 3) NULL,
	[MAX_X] [numeric](18, 3) NULL,
	[MIN_Y] [numeric](18, 3) NULL,
	[MAX_Y] [numeric](18, 3) NULL,
	[COORD_SYSTEM] [nvarchar](255) NULL,
	[MIN_DEPTH_MS] [numeric](12, 3) NULL,
	[MAX_DEPTH_MS] [numeric](12, 3) NULL,
	[MIN_INLINE] [numeric](10, 0) NULL,
	[MAX_INLINE] [numeric](10, 0) NULL,
	[MIN_CROSSLINE] [numeric](10, 0) NULL,
	[MAX_CROSSLINE] [numeric](10, 0) NULL,
	[CATALOG_DATE] [datetime2](7) NULL,
	[LAST_SEEN_DATE] [datetime2](7) NULL,
	[ACTIVE_IND] [nvarchar](1) NOT NULL,
	[REMARK] [nvarchar](2000) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
	[DEPTH_UOM] [nvarchar](10) NULL,
 CONSTRAINT [SEISCAT_PK] PRIMARY KEY CLUSTERED 
(
	[SEIS_FILE_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[SEIS_FILE_HEADER]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[SEIS_FILE_HEADER](
	[SEIS_FILE_ID] [nvarchar](40) NOT NULL,
	[LINE_NO] [numeric](5, 0) NOT NULL,
	[HEADER_TEXT] [nvarchar](80) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
 CONSTRAINT [SEISHDR_PK] PRIMARY KEY CLUSTERED 
(
	[SEIS_FILE_ID] ASC,
	[LINE_NO] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[WL_FILE_UWI_MAP]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[WL_FILE_UWI_MAP](
	[MAP_ID] [nvarchar](40) NOT NULL,
	[FILE_PATH] [nvarchar](500) NOT NULL,
	[FILE_NAME] [nvarchar](255) NOT NULL,
	[FILE_FORMAT] [nvarchar](10) NOT NULL,
	[REPOSITORY_ID] [nvarchar](40) NULL,
	[UWI] [nvarchar](40) NULL,
	[HEADER_WELL_ID] [nvarchar](255) NULL,
	[MATCH_METHOD] [nvarchar](20) NULL,
	[MATCH_SCORE] [numeric](5, 1) NULL,
	[MATCH_WELL_NAME] [nvarchar](255) NULL,
	[STATUS] [nvarchar](20) NOT NULL,
	[FILE_SIZE_KB] [numeric](15, 2) NULL,
	[REMARK] [nvarchar](2000) NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [WLMAP_PK] PRIMARY KEY CLUSTERED 
(
	[MAP_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
/****** Object:  Table [las_catalog].[WL_REPOSITORY]    Script Date: 2026-05-15 10:58:33 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [las_catalog].[WL_REPOSITORY](
	[REPOSITORY_ID] [nvarchar](40) NOT NULL,
	[REPOSITORY_NAME] [nvarchar](200) NOT NULL,
	[REPOSITORY_TYPE] [nvarchar](40) NOT NULL,
	[BASE_PATH] [nvarchar](500) NOT NULL,
	[ACTIVE_IND] [nvarchar](1) NOT NULL,
	[REMARK] [nvarchar](2000) NULL,
	[SOURCE] [nvarchar](40) NOT NULL,
	[ROW_CREATED_BY] [nvarchar](30) NULL,
	[ROW_CREATED_DATE] [datetime2](7) NULL,
	[ROW_CHANGED_BY] [nvarchar](30) NULL,
	[ROW_CHANGED_DATE] [datetime2](7) NULL,
 CONSTRAINT [LASREP_PK] PRIMARY KEY CLUSTERED 
(
	[REPOSITORY_ID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dataview].[document_location] ADD  CONSTRAINT [DF_docloc_curation_status]  DEFAULT ('extracted') FOR [curation_status]
GO
ALTER TABLE [dataview].[document_location] ADD  CONSTRAINT [DF_docloc_row_created]  DEFAULT (sysutcdatetime()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[document_location] ADD  CONSTRAINT [DF_docloc_row_changed]  DEFAULT (sysutcdatetime()) FOR [row_changed_date]
GO
ALTER TABLE [dataview].[dv_basin] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_basin] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_basin] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_business_associate] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_business_associate] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_business_associate] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_column_map] ADD  DEFAULT ('N') FOR [confirmed_ind]
GO
ALTER TABLE [dataview].[dv_column_map] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_column_map] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_column_map] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_country] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_country] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_country] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_county] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_county] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_county] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_data_quality] ADD  DEFAULT (getdate()) FOR [check_date]
GO
ALTER TABLE [dataview].[dv_data_quality] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_data_quality] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_field] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_field] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_field] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_global_file_catalog] ADD  DEFAULT ('N') FOR [ppdm_loaded_ind]
GO
ALTER TABLE [dataview].[dv_global_file_catalog] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_global_file_catalog] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_load_batch] ADD  DEFAULT (getdate()) FOR [batch_date]
GO
ALTER TABLE [dataview].[dv_load_batch] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_load_batch] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_ocs_block] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_ocs_block] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_ocs_block] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_plss_township] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_plss_township] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_plss_township] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_prod_entity] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_prod_entity] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_prod_entity] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_prod_volume] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_prod_volume] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_prod_volume] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_province_state] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_province_state] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_province_state] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_r_source] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_r_source] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_r_source] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_r_uom] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_r_uom] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_r_uom] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_r_well_status] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_r_well_status] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_r_well_status] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_r_well_type] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_r_well_type] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_r_well_type] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_seis_file_catalog] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_seis_file_catalog] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_seis_line] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_seis_line] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_seis_line] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_seis_set] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_seis_set] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_seis_set] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_source] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_source] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_source] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT ((4326)) FOR [epsg_code]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT ('GEOJSON') FOR [source_type]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT ('#1a73e8') FOR [style_color]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT ((1.5)) FOR [style_weight]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT ((0.8)) FOR [style_opacity]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT ((0.0)) FOR [style_fill_opacity]
GO
ALTER TABLE [dataview].[dv_spatial_layer] ADD  DEFAULT ((0)) FOR [display_order]
GO
ALTER TABLE [dataview].[dv_stg_well] ADD  DEFAULT (getdate()) FOR [_stg_loaded_at]
GO
ALTER TABLE [dataview].[dv_strat_interval] ADD  DEFAULT ('1') FOR [interp_id]
GO
ALTER TABLE [dataview].[dv_strat_interval] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_strat_interval] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_well] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_alias] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_alias] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_well_alias] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_casing] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_casing] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_completion] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_completion] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_core] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_core] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_core_photo] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_core_photo] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_core_sample] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_core_sample] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_hdr] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_hdr] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_hdr] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_sta] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_sta] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_dst] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_dst] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_dst_period] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_formation_top] ADD  DEFAULT ('1') FOR [interp_id]
GO
ALTER TABLE [dataview].[dv_well_formation_top] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_formation_top] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_well_formation_top] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_identifier] ADD  DEFAULT (sysutcdatetime()) FOR [loaded_date]
GO
ALTER TABLE [dataview].[dv_well_identifier] ADD  DEFAULT ((0)) FOR [is_primary]
GO
ALTER TABLE [dataview].[dv_well_log] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_log] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_well_log] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_log_curve] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_log_curve] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_well_log_curve] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_mud_log] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_mud_log] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_perforation] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_perforation] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_petro_interp] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_petro_interp] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_petro_zone] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_petro_zone] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_pressure] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_pressure] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_shows] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_well_stimulation] ADD  DEFAULT ('Y') FOR [active_ind]
GO
ALTER TABLE [dataview].[dv_well_stimulation] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview].[dv_wl_file_catalog] ADD  DEFAULT ('N') FOR [ppdm_loaded_ind]
GO
ALTER TABLE [dataview].[dv_wl_file_catalog] ADD  DEFAULT ('SYSTEM') FOR [row_created_by]
GO
ALTER TABLE [dataview].[dv_wl_file_catalog] ADD  DEFAULT (getdate()) FOR [row_created_date]
GO
ALTER TABLE [dataview_gom].[directional_survey_point] ADD  CONSTRAINT [DF_dvgom_dsp_loaded]  DEFAULT (sysutcdatetime()) FOR [loaded_date]
GO
ALTER TABLE [dataview_gom].[directional_survey_point] ADD  CONSTRAINT [DF_dvgom_dsp_changed]  DEFAULT (sysutcdatetime()) FOR [row_changed_date]
GO
ALTER TABLE [dataview_gom].[well] ADD  DEFAULT (sysutcdatetime()) FOR [loaded_date]
GO
ALTER TABLE [dataview_gom].[well] ADD  DEFAULT (sysutcdatetime()) FOR [row_changed_date]
GO
ALTER TABLE [file_catalog].[ASSIGNMENT_EXTENSION] ADD  DEFAULT (getdate()) FOR [EXTENDED_DATE]
GO
ALTER TABLE [file_catalog].[AUDIT_LOG] ADD  DEFAULT (getutcdate()) FOR [EVENT_TIME]
GO
ALTER TABLE [file_catalog].[FILE_HEADER] ADD  DEFAULT (getdate()) FOR [CATALOG_DATE]
GO
ALTER TABLE [file_catalog].[FILE_HEADER] ADD  DEFAULT ('Y') FOR [ACTIVE_IND]
GO
ALTER TABLE [file_catalog].[FILE_SEIS_HEADER] ADD  CONSTRAINT [DF_FSH_EXTRACTED_DATE]  DEFAULT (sysutcdatetime()) FOR [EXTRACTED_DATE]
GO
ALTER TABLE [file_catalog].[FILE_SEIS_HEADER] ADD  CONSTRAINT [DF_FSH_EXTRACTED_BY]  DEFAULT ('DataWrangler') FOR [EXTRACTED_BY]
GO
ALTER TABLE [file_catalog].[FILE_WELL_HEADER] ADD  CONSTRAINT [DF_FWH_EXTRACTED_DATE]  DEFAULT (sysutcdatetime()) FOR [EXTRACTED_DATE]
GO
ALTER TABLE [file_catalog].[FILE_WELL_HEADER] ADD  CONSTRAINT [DF_FWH_EXTRACTED_BY]  DEFAULT ('DataWrangler') FOR [EXTRACTED_BY]
GO
ALTER TABLE [file_catalog].[GLOBAL_FILE_CATALOG] ADD  CONSTRAINT [DF_GFC_SCAN_DATE]  DEFAULT (sysutcdatetime()) FOR [SCAN_DATE]
GO
ALTER TABLE [file_catalog].[GLOBAL_FILE_CATALOG] ADD  CONSTRAINT [DF_GFC_ROW_CREATED_DATE]  DEFAULT (sysutcdatetime()) FOR [ROW_CREATED_DATE]
GO
ALTER TABLE [file_catalog].[GLOBAL_FILE_CATALOG] ADD  CONSTRAINT [DF_GFC_ROW_CHANGED_DATE]  DEFAULT (sysutcdatetime()) FOR [ROW_CHANGED_DATE]
GO
ALTER TABLE [file_catalog].[INVENTORY_ASSIGNMENT] ADD  DEFAULT (getdate()) FOR [ASSIGNED_DATE]
GO
ALTER TABLE [file_catalog].[INVENTORY_ASSIGNMENT] ADD  DEFAULT ('OPEN') FOR [STATUS]
GO
ALTER TABLE [file_catalog].[INVENTORY_ASSIGNMENT] ADD  DEFAULT ((0)) FOR [FILE_COUNT]
GO
ALTER TABLE [file_catalog].[INVENTORY_GROUP] ADD  DEFAULT ((0)) FOR [TOTAL_FILES]
GO
ALTER TABLE [file_catalog].[INVENTORY_GROUP] ADD  DEFAULT ('OPEN') FOR [STATUS]
GO
ALTER TABLE [file_catalog].[INVENTORY_GROUP] ADD  DEFAULT (getdate()) FOR [CREATED_DATE]
GO
ALTER TABLE [file_catalog].[INVENTORY_GROUP_FILE] ADD  DEFAULT (getdate()) FOR [ADDED_DATE]
GO
ALTER TABLE [file_catalog].[INVENTORY_GROUP_FILE] ADD  DEFAULT ('N') FOR [CATALOGED_IND]
GO
ALTER TABLE [file_catalog].[INVENTORY_GROUP_FILE] ADD  DEFAULT ('N') FOR [SKIPPED_IND]
GO
ALTER TABLE [file_catalog].[INVENTORY_USER] ADD  DEFAULT ('CATALOGER') FOR [ROLE]
GO
ALTER TABLE [file_catalog].[INVENTORY_USER] ADD  DEFAULT ('Y') FOR [ACTIVE_IND]
GO
ALTER TABLE [file_catalog].[INVENTORY_USER] ADD  DEFAULT (getdate()) FOR [CREATED_DATE]
GO
ALTER TABLE [las_catalog].[DLIS_CHANNEL] ADD  DEFAULT ('N') FOR [IS_INDEX]
GO
ALTER TABLE [las_catalog].[DLIS_FILE] ADD  DEFAULT ('Y') FOR [ACTIVE_IND]
GO
ALTER TABLE [las_catalog].[LAS_FILE] ADD  DEFAULT ('Y') FOR [ACTIVE_IND]
GO
ALTER TABLE [las_catalog].[LIS_CHANNEL] ADD  DEFAULT ('N') FOR [IS_INDEX]
GO
ALTER TABLE [las_catalog].[LIS_FILE] ADD  DEFAULT ('Y') FOR [ACTIVE_IND]
GO
ALTER TABLE [las_catalog].[SEIS_FILE_CATALOG] ADD  DEFAULT ('Y') FOR [ACTIVE_IND]
GO
ALTER TABLE [las_catalog].[WL_FILE_UWI_MAP] ADD  DEFAULT ('PENDING') FOR [STATUS]
GO
ALTER TABLE [las_catalog].[WL_REPOSITORY] ADD  DEFAULT ('Y') FOR [ACTIVE_IND]
GO
ALTER TABLE [dataview].[dv_basin]  WITH CHECK ADD CONSTRAINT [FK_dv_basin_country_code] FOREIGN KEY([country_code])
REFERENCES [dataview].[dv_country] ([country_code])
GO
ALTER TABLE [dataview].[dv_basin]  WITH CHECK ADD CONSTRAINT [FK_dv_basin_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_business_associate]  WITH CHECK ADD CONSTRAINT [FK_dv_business_associate_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_column_map]  WITH CHECK ADD CONSTRAINT [FK_dv_column_map_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_country]  WITH CHECK ADD CONSTRAINT [FK_dv_country_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_county]  WITH CHECK ADD CONSTRAINT [FK_dv_county_country_code] FOREIGN KEY([country_code])
REFERENCES [dataview].[dv_country] ([country_code])
GO
ALTER TABLE [dataview].[dv_county]  WITH CHECK ADD CONSTRAINT [FK_dv_county_province_state_id] FOREIGN KEY([province_state_id])
REFERENCES [dataview].[dv_province_state] ([province_state_id])
GO
ALTER TABLE [dataview].[dv_county]  WITH CHECK ADD CONSTRAINT [FK_dv_county_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_data_quality]  WITH CHECK ADD CONSTRAINT [FK_dv_data_quality_batch_id] FOREIGN KEY([batch_id])
REFERENCES [dataview].[dv_load_batch] ([batch_id])
GO
ALTER TABLE [dataview].[dv_data_quality]  WITH CHECK ADD CONSTRAINT [FK_dv_data_quality_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_field]  WITH CHECK ADD CONSTRAINT [FK_dv_field_operator_ba_id] FOREIGN KEY([operator_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_field]  WITH CHECK ADD CONSTRAINT [FK_dv_field_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_global_file_catalog]  WITH CHECK ADD CONSTRAINT [FK_dv_global_file_catalog_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_load_batch]  WITH CHECK ADD CONSTRAINT [FK_dv_load_batch_operator_ba_id] FOREIGN KEY([operator_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_load_batch]  WITH CHECK ADD CONSTRAINT [FK_dv_load_batch_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_ocs_block]  WITH CHECK ADD CONSTRAINT [FK_dv_ocs_block_country_code] FOREIGN KEY([country_code])
REFERENCES [dataview].[dv_country] ([country_code])
GO
ALTER TABLE [dataview].[dv_ocs_block]  WITH CHECK ADD CONSTRAINT [FK_dv_ocs_block_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_plss_township]  WITH CHECK ADD CONSTRAINT [FK_dv_plss_township_county_id] FOREIGN KEY([county_id])
REFERENCES [dataview].[dv_county] ([county_id])
GO
ALTER TABLE [dataview].[dv_plss_township]  WITH CHECK ADD CONSTRAINT [FK_dv_plss_township_province_state_id] FOREIGN KEY([province_state_id])
REFERENCES [dataview].[dv_province_state] ([province_state_id])
GO
ALTER TABLE [dataview].[dv_plss_township]  WITH CHECK ADD CONSTRAINT [FK_dv_plss_township_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_prod_entity]  WITH CHECK ADD CONSTRAINT [FK_dv_prod_entity_field_id] FOREIGN KEY([field_id])
REFERENCES [dataview].[dv_field] ([field_id])
GO
ALTER TABLE [dataview].[dv_prod_entity]  WITH CHECK ADD CONSTRAINT [FK_dv_prod_entity_operator_ba_id] FOREIGN KEY([operator_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_prod_entity]  WITH CHECK ADD CONSTRAINT [FK_dv_prod_entity_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_prod_entity]  WITH CHECK ADD CONSTRAINT [FK_dv_prod_entity_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_prod_volume]  WITH CHECK ADD CONSTRAINT [FK_dv_prod_volume_prod_entity_id] FOREIGN KEY([prod_entity_id])
REFERENCES [dataview].[dv_prod_entity] ([prod_entity_id])
GO
ALTER TABLE [dataview].[dv_prod_volume]  WITH CHECK ADD CONSTRAINT [FK_dv_prod_volume_rate_ouom] FOREIGN KEY([rate_ouom])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_prod_volume]  WITH CHECK ADD CONSTRAINT [FK_dv_prod_volume_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_prod_volume]  WITH CHECK ADD CONSTRAINT [FK_dv_prod_volume_volume_ouom] FOREIGN KEY([volume_ouom])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_province_state]  WITH CHECK ADD CONSTRAINT [FK_dv_province_state_country_code] FOREIGN KEY([country_code])
REFERENCES [dataview].[dv_country] ([country_code])
GO
ALTER TABLE [dataview].[dv_province_state]  WITH CHECK ADD CONSTRAINT [FK_dv_province_state_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_seis_file_catalog]  WITH CHECK ADD CONSTRAINT [FK_dv_seis_file_catalog_seis_set_id] FOREIGN KEY([seis_set_id])
REFERENCES [dataview].[dv_seis_set] ([seis_set_id])
GO
ALTER TABLE [dataview].[dv_seis_file_catalog]  WITH CHECK ADD CONSTRAINT [FK_dv_seis_file_catalog_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_seis_line]  WITH CHECK ADD CONSTRAINT [FK_dv_seis_line_seis_set_id] FOREIGN KEY([seis_set_id])
REFERENCES [dataview].[dv_seis_set] ([seis_set_id])
GO
ALTER TABLE [dataview].[dv_seis_line]  WITH CHECK ADD CONSTRAINT [FK_dv_seis_line_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_seis_set]  WITH CHECK ADD CONSTRAINT [FK_dv_seis_set_contractor_ba_id] FOREIGN KEY([contractor_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_seis_set]  WITH CHECK ADD CONSTRAINT [FK_dv_seis_set_operator_ba_id] FOREIGN KEY([operator_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_seis_set]  WITH CHECK ADD CONSTRAINT [FK_dv_seis_set_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_source]  WITH CHECK ADD CONSTRAINT [FK_dv_source_source_ref] FOREIGN KEY([source_ref])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_spatial_layer]  WITH CHECK ADD CONSTRAINT [FK_dv_spatial_layer_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_strat_interval]  WITH CHECK ADD CONSTRAINT [FK_dv_strat_interval_depth_ouom] FOREIGN KEY([depth_ouom])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_strat_interval]  WITH CHECK ADD CONSTRAINT [FK_dv_strat_interval_perm_ouom] FOREIGN KEY([perm_ouom])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_strat_interval]  WITH CHECK ADD CONSTRAINT [FK_dv_strat_interval_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_strat_interval]  WITH CHECK ADD  CONSTRAINT [fk_strat_interval_top] FOREIGN KEY([uwi], [strat_unit_id], [interp_id])
REFERENCES [dataview].[dv_well_formation_top] ([uwi], [strat_unit_id], [interp_id])
GO
ALTER TABLE [dataview].[dv_strat_interval] CHECK CONSTRAINT [fk_strat_interval_top]
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD CONSTRAINT [FK_dv_well_current_operator_ba_id] FOREIGN KEY([current_operator_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD CONSTRAINT [FK_dv_well_field_id] FOREIGN KEY([field_id])
REFERENCES [dataview].[dv_field] ([field_id])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD CONSTRAINT [FK_dv_well_operator_ba_id] FOREIGN KEY([operator_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD CONSTRAINT [FK_dv_well_original_operator_ba_id] FOREIGN KEY([original_operator_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD CONSTRAINT [FK_dv_well_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD CONSTRAINT [FK_dv_well_well_status] FOREIGN KEY([well_status])
REFERENCES [dataview].[dv_r_well_status] ([well_status])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD CONSTRAINT [FK_dv_well_well_type] FOREIGN KEY([well_type])
REFERENCES [dataview].[dv_r_well_type] ([well_type])
GO
ALTER TABLE [dataview].[dv_well_alias]  WITH CHECK ADD CONSTRAINT [FK_dv_well_alias_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_alias]  WITH CHECK ADD CONSTRAINT [FK_dv_well_alias_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_casing]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_casing_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_casing] CHECK CONSTRAINT [fk_dv_well_casing_source]
GO
ALTER TABLE [dataview].[dv_well_casing]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_casing_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_casing] CHECK CONSTRAINT [fk_dv_well_casing_uwi]
GO
ALTER TABLE [dataview].[dv_well_completion]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_completion_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_completion] CHECK CONSTRAINT [fk_dv_well_completion_source]
GO
ALTER TABLE [dataview].[dv_well_completion]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_completion_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_completion] CHECK CONSTRAINT [fk_dv_well_completion_uwi]
GO
ALTER TABLE [dataview].[dv_well_core]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_core_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_core] CHECK CONSTRAINT [fk_dv_well_core_source]
GO
ALTER TABLE [dataview].[dv_well_core]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_core_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_core] CHECK CONSTRAINT [fk_dv_well_core_uwi]
GO
ALTER TABLE [dataview].[dv_well_core_photo]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_core_photo_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_core_photo] CHECK CONSTRAINT [fk_dv_well_core_photo_source]
GO
ALTER TABLE [dataview].[dv_well_core_photo]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_core_photo_uwi_core_id] FOREIGN KEY([uwi], [core_id])
REFERENCES [dataview].[dv_well_core] ([uwi], [core_id])
GO
ALTER TABLE [dataview].[dv_well_core_photo] CHECK CONSTRAINT [fk_dv_well_core_photo_uwi_core_id]
GO
ALTER TABLE [dataview].[dv_well_core_sample]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_core_sample_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_core_sample] CHECK CONSTRAINT [fk_dv_well_core_sample_source]
GO
ALTER TABLE [dataview].[dv_well_core_sample]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_core_sample_uwi_core_id] FOREIGN KEY([uwi], [core_id])
REFERENCES [dataview].[dv_well_core] ([uwi], [core_id])
GO
ALTER TABLE [dataview].[dv_well_core_sample] CHECK CONSTRAINT [fk_dv_well_core_sample_uwi_core_id]
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_hdr]  WITH CHECK ADD CONSTRAINT [FK_dv_well_dir_srvy_hdr_contractor_ba_id] FOREIGN KEY([contractor_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_hdr]  WITH CHECK ADD CONSTRAINT [FK_dv_well_dir_srvy_hdr_depth_ouom] FOREIGN KEY([depth_ouom])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_hdr]  WITH CHECK ADD CONSTRAINT [FK_dv_well_dir_srvy_hdr_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_hdr]  WITH CHECK ADD CONSTRAINT [FK_dv_well_dir_srvy_hdr_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_sta]  WITH CHECK ADD CONSTRAINT [FK_dv_well_dir_srvy_sta_depth_ouom] FOREIGN KEY([depth_ouom])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_sta]  WITH CHECK ADD CONSTRAINT [FK_dv_well_dir_srvy_sta_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_sta]  WITH CHECK ADD  CONSTRAINT [fk_srvy_sta_hdr] FOREIGN KEY([uwi], [survey_id])
REFERENCES [dataview].[dv_well_dir_srvy_hdr] ([uwi], [survey_id])
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_sta] CHECK CONSTRAINT [fk_srvy_sta_hdr]
GO
ALTER TABLE [dataview].[dv_well_dst]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_dst_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_dst] CHECK CONSTRAINT [fk_dv_well_dst_source]
GO
ALTER TABLE [dataview].[dv_well_dst]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_dst_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_dst] CHECK CONSTRAINT [fk_dv_well_dst_uwi]
GO
ALTER TABLE [dataview].[dv_well_dst_period]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_dst_period_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_dst_period] CHECK CONSTRAINT [fk_dv_well_dst_period_source]
GO
ALTER TABLE [dataview].[dv_well_dst_period]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_dst_period_uwi_dst_id] FOREIGN KEY([uwi], [dst_id])
REFERENCES [dataview].[dv_well_dst] ([uwi], [dst_id])
GO
ALTER TABLE [dataview].[dv_well_dst_period] CHECK CONSTRAINT [fk_dv_well_dst_period_uwi_dst_id]
GO
ALTER TABLE [dataview].[dv_well_formation_top]  WITH CHECK ADD CONSTRAINT [FK_dv_well_formation_top_depth_ouom] FOREIGN KEY([depth_ouom])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_well_formation_top]  WITH CHECK ADD CONSTRAINT [FK_dv_well_formation_top_interpreter_ba_id] FOREIGN KEY([interpreter_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_well_formation_top]  WITH CHECK ADD CONSTRAINT [FK_dv_well_formation_top_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_formation_top]  WITH CHECK ADD CONSTRAINT [FK_dv_well_formation_top_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_log]  WITH CHECK ADD CONSTRAINT [FK_dv_well_log_depth_ouom] FOREIGN KEY([depth_ouom])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_well_log]  WITH CHECK ADD CONSTRAINT [FK_dv_well_log_service_company_ba_id] FOREIGN KEY([service_company_ba_id])
REFERENCES [dataview].[dv_business_associate] ([ba_id])
GO
ALTER TABLE [dataview].[dv_well_log]  WITH CHECK ADD CONSTRAINT [FK_dv_well_log_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_log]  WITH CHECK ADD CONSTRAINT [FK_dv_well_log_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_log_curve]  WITH CHECK ADD CONSTRAINT [FK_dv_well_log_curve_curve_unit] FOREIGN KEY([curve_unit])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_well_log_curve]  WITH CHECK ADD CONSTRAINT [FK_dv_well_log_curve_depth_ouom] FOREIGN KEY([depth_ouom])
REFERENCES [dataview].[dv_r_uom] ([uom_code])
GO
ALTER TABLE [dataview].[dv_well_log_curve]  WITH CHECK ADD CONSTRAINT [FK_dv_well_log_curve_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_log_curve]  WITH CHECK ADD  CONSTRAINT [fk_log_curve_log] FOREIGN KEY([uwi], [log_id])
REFERENCES [dataview].[dv_well_log] ([uwi], [log_id])
GO
ALTER TABLE [dataview].[dv_well_log_curve] CHECK CONSTRAINT [fk_log_curve_log]
GO
ALTER TABLE [dataview].[dv_well_mud_log]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_mud_log_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_mud_log] CHECK CONSTRAINT [fk_dv_well_mud_log_source]
GO
ALTER TABLE [dataview].[dv_well_mud_log]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_mud_log_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_mud_log] CHECK CONSTRAINT [fk_dv_well_mud_log_uwi]
GO
ALTER TABLE [dataview].[dv_well_perforation]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_perforation_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_perforation] CHECK CONSTRAINT [fk_dv_well_perforation_source]
GO
ALTER TABLE [dataview].[dv_well_perforation]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_perforation_uwi_completion_id] FOREIGN KEY([uwi], [completion_id])
REFERENCES [dataview].[dv_well_completion] ([uwi], [completion_id])
GO
ALTER TABLE [dataview].[dv_well_perforation] CHECK CONSTRAINT [fk_dv_well_perforation_uwi_completion_id]
GO
ALTER TABLE [dataview].[dv_well_petro_interp]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_petro_interp_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_petro_interp] CHECK CONSTRAINT [fk_dv_well_petro_interp_source]
GO
ALTER TABLE [dataview].[dv_well_petro_interp]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_petro_interp_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_petro_interp] CHECK CONSTRAINT [fk_dv_well_petro_interp_uwi]
GO
ALTER TABLE [dataview].[dv_well_petro_zone]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_petro_zone_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_petro_zone] CHECK CONSTRAINT [fk_dv_well_petro_zone_source]
GO
ALTER TABLE [dataview].[dv_well_petro_zone]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_petro_zone_uwi_interp_id] FOREIGN KEY([uwi], [interp_id])
REFERENCES [dataview].[dv_well_petro_interp] ([uwi], [interp_id])
GO
ALTER TABLE [dataview].[dv_well_petro_zone] CHECK CONSTRAINT [fk_dv_well_petro_zone_uwi_interp_id]
GO
ALTER TABLE [dataview].[dv_well_pressure]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_pressure_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_pressure] CHECK CONSTRAINT [fk_dv_well_pressure_source]
GO
ALTER TABLE [dataview].[dv_well_pressure]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_pressure_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [dataview].[dv_well_pressure] CHECK CONSTRAINT [fk_dv_well_pressure_uwi]
GO
ALTER TABLE [dataview].[dv_well_shows]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_shows_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_shows] CHECK CONSTRAINT [fk_dv_well_shows_source]
GO
ALTER TABLE [dataview].[dv_well_shows]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_shows_uwi_mud_log_id] FOREIGN KEY([uwi], [mud_log_id])
REFERENCES [dataview].[dv_well_mud_log] ([uwi], [mud_log_id])
GO
ALTER TABLE [dataview].[dv_well_shows] CHECK CONSTRAINT [fk_dv_well_shows_uwi_mud_log_id]
GO
ALTER TABLE [dataview].[dv_well_stimulation]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_stimulation_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_well_stimulation] CHECK CONSTRAINT [fk_dv_well_stimulation_source]
GO
ALTER TABLE [dataview].[dv_well_stimulation]  WITH CHECK ADD  CONSTRAINT [fk_dv_well_stimulation_uwi_completion_id] FOREIGN KEY([uwi], [completion_id])
REFERENCES [dataview].[dv_well_completion] ([uwi], [completion_id])
GO
ALTER TABLE [dataview].[dv_well_stimulation] CHECK CONSTRAINT [fk_dv_well_stimulation_uwi_completion_id]
GO
ALTER TABLE [dataview].[dv_wl_file_catalog]  WITH CHECK ADD CONSTRAINT [FK_dv_wl_file_catalog_source] FOREIGN KEY([source])
REFERENCES [dataview].[dv_r_source] ([source])
GO
ALTER TABLE [dataview].[dv_wl_file_catalog]  WITH CHECK ADD CONSTRAINT [FK_dv_wl_file_catalog_uwi] FOREIGN KEY([uwi])
REFERENCES [dataview].[dv_well] ([uwi])
GO
ALTER TABLE [las_catalog].[DLIS_CHANNEL]  WITH CHECK ADD  CONSTRAINT [DLISCH_FR_FK] FOREIGN KEY([DLIS_FILE_ID], [LOGICAL_FILE_IDX], [FRAME_NAME])
REFERENCES [las_catalog].[DLIS_FRAME] ([DLIS_FILE_ID], [LOGICAL_FILE_IDX], [FRAME_NAME])
GO
ALTER TABLE [las_catalog].[DLIS_CHANNEL] CHECK CONSTRAINT [DLISCH_FR_FK]
GO
ALTER TABLE [las_catalog].[DLIS_FILE]  WITH CHECK ADD  CONSTRAINT [DLISFILE_REP_FK] FOREIGN KEY([REPOSITORY_ID])
REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID])
GO
ALTER TABLE [las_catalog].[DLIS_FILE] CHECK CONSTRAINT [DLISFILE_REP_FK]
GO
ALTER TABLE [las_catalog].[DLIS_FRAME]  WITH CHECK ADD  CONSTRAINT [DLISFR_LF_FK] FOREIGN KEY([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
REFERENCES [las_catalog].[DLIS_LOGICAL_FILE] ([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
GO
ALTER TABLE [las_catalog].[DLIS_FRAME] CHECK CONSTRAINT [DLISFR_LF_FK]
GO
ALTER TABLE [las_catalog].[DLIS_LOGICAL_FILE]  WITH CHECK ADD  CONSTRAINT [DLISLF_FILE_FK] FOREIGN KEY([DLIS_FILE_ID])
REFERENCES [las_catalog].[DLIS_FILE] ([DLIS_FILE_ID])
GO
ALTER TABLE [las_catalog].[DLIS_LOGICAL_FILE] CHECK CONSTRAINT [DLISLF_FILE_FK]
GO
ALTER TABLE [las_catalog].[DLIS_PARAMETER]  WITH CHECK ADD  CONSTRAINT [DLISPM_LF_FK] FOREIGN KEY([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
REFERENCES [las_catalog].[DLIS_LOGICAL_FILE] ([DLIS_FILE_ID], [LOGICAL_FILE_IDX])
GO
ALTER TABLE [las_catalog].[DLIS_PARAMETER] CHECK CONSTRAINT [DLISPM_LF_FK]
GO
ALTER TABLE [las_catalog].[LAS_FILE]  WITH CHECK ADD  CONSTRAINT [LASFILE_REP_FK] FOREIGN KEY([REPOSITORY_ID])
REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID])
GO
ALTER TABLE [las_catalog].[LAS_FILE] CHECK CONSTRAINT [LASFILE_REP_FK]
GO
ALTER TABLE [las_catalog].[LAS_FILE_CURVE]  WITH CHECK ADD  CONSTRAINT [LASCURVE_FILE_FK] FOREIGN KEY([LAS_FILE_ID])
REFERENCES [las_catalog].[LAS_FILE] ([LAS_FILE_ID])
GO
ALTER TABLE [las_catalog].[LAS_FILE_CURVE] CHECK CONSTRAINT [LASCURVE_FILE_FK]
GO
ALTER TABLE [las_catalog].[LAS_FILE_PARAMETER]  WITH CHECK ADD  CONSTRAINT [LASPARM_FILE_FK] FOREIGN KEY([LAS_FILE_ID])
REFERENCES [las_catalog].[LAS_FILE] ([LAS_FILE_ID])
GO
ALTER TABLE [las_catalog].[LAS_FILE_PARAMETER] CHECK CONSTRAINT [LASPARM_FILE_FK]
GO
ALTER TABLE [las_catalog].[LIS_CHANNEL]  WITH CHECK ADD  CONSTRAINT [LISCH_FILE_FK] FOREIGN KEY([LIS_FILE_ID])
REFERENCES [las_catalog].[LIS_FILE] ([LIS_FILE_ID])
GO
ALTER TABLE [las_catalog].[LIS_CHANNEL] CHECK CONSTRAINT [LISCH_FILE_FK]
GO
ALTER TABLE [las_catalog].[LIS_FILE]  WITH CHECK ADD  CONSTRAINT [LISFILE_REP_FK] FOREIGN KEY([REPOSITORY_ID])
REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID])
GO
ALTER TABLE [las_catalog].[LIS_FILE] CHECK CONSTRAINT [LISFILE_REP_FK]
GO
ALTER TABLE [las_catalog].[SEIS_FILE_CATALOG]  WITH CHECK ADD  CONSTRAINT [SEISCAT_REP_FK] FOREIGN KEY([REPOSITORY_ID])
REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID])
GO
ALTER TABLE [las_catalog].[SEIS_FILE_CATALOG] CHECK CONSTRAINT [SEISCAT_REP_FK]
GO
ALTER TABLE [las_catalog].[SEIS_FILE_HEADER]  WITH CHECK ADD  CONSTRAINT [SEISHDR_FILE_FK] FOREIGN KEY([SEIS_FILE_ID])
REFERENCES [las_catalog].[SEIS_FILE_CATALOG] ([SEIS_FILE_ID])
GO
ALTER TABLE [las_catalog].[SEIS_FILE_HEADER] CHECK CONSTRAINT [SEISHDR_FILE_FK]
GO
ALTER TABLE [las_catalog].[WL_FILE_UWI_MAP]  WITH CHECK ADD  CONSTRAINT [WLMAP_REP_FK] FOREIGN KEY([REPOSITORY_ID])
REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID])
GO
ALTER TABLE [las_catalog].[WL_FILE_UWI_MAP] CHECK CONSTRAINT [WLMAP_REP_FK]
GO
ALTER TABLE [dataview].[dv_basin]  WITH CHECK ADD  CONSTRAINT [ck_dv_basin_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_basin] CHECK CONSTRAINT [ck_dv_basin_ai]
GO
ALTER TABLE [dataview].[dv_business_associate]  WITH CHECK ADD  CONSTRAINT [ck_dv_ba_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_business_associate] CHECK CONSTRAINT [ck_dv_ba_ai]
GO
ALTER TABLE [dataview].[dv_column_map]  WITH CHECK ADD  CONSTRAINT [ck_dv_colmap_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_column_map] CHECK CONSTRAINT [ck_dv_colmap_ai]
GO
ALTER TABLE [dataview].[dv_column_map]  WITH CHECK ADD  CONSTRAINT [ck_dv_colmap_conf] CHECK  (([confirmed_ind]='N' OR [confirmed_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_column_map] CHECK CONSTRAINT [ck_dv_colmap_conf]
GO
ALTER TABLE [dataview].[dv_country]  WITH CHECK ADD  CONSTRAINT [ck_dv_country_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_country] CHECK CONSTRAINT [ck_dv_country_ai]
GO
ALTER TABLE [dataview].[dv_county]  WITH CHECK ADD  CONSTRAINT [ck_dv_county_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_county] CHECK CONSTRAINT [ck_dv_county_ai]
GO
ALTER TABLE [dataview].[dv_field]  WITH CHECK ADD  CONSTRAINT [ck_dv_field_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_field] CHECK CONSTRAINT [ck_dv_field_ai]
GO
ALTER TABLE [dataview].[dv_global_file_catalog]  WITH CHECK ADD  CONSTRAINT [ck_dv_gfc_ppdm_loaded] CHECK  (([ppdm_loaded_ind]='N' OR [ppdm_loaded_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_global_file_catalog] CHECK CONSTRAINT [ck_dv_gfc_ppdm_loaded]
GO
ALTER TABLE [dataview].[dv_ocs_block]  WITH CHECK ADD  CONSTRAINT [ck_dv_ocs_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_ocs_block] CHECK CONSTRAINT [ck_dv_ocs_ai]
GO
ALTER TABLE [dataview].[dv_plss_township]  WITH CHECK ADD  CONSTRAINT [ck_dv_plss_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_plss_township] CHECK CONSTRAINT [ck_dv_plss_ai]
GO
ALTER TABLE [dataview].[dv_prod_entity]  WITH CHECK ADD  CONSTRAINT [ck_dv_prod_ent_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_prod_entity] CHECK CONSTRAINT [ck_dv_prod_ent_ai]
GO
ALTER TABLE [dataview].[dv_prod_volume]  WITH CHECK ADD  CONSTRAINT [ck_dv_prod_vol_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_prod_volume] CHECK CONSTRAINT [ck_dv_prod_vol_ai]
GO
ALTER TABLE [dataview].[dv_province_state]  WITH CHECK ADD  CONSTRAINT [ck_dv_ps_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_province_state] CHECK CONSTRAINT [ck_dv_ps_ai]
GO
ALTER TABLE [dataview].[dv_r_source]  WITH CHECK ADD  CONSTRAINT [ck_dv_r_source_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_r_source] CHECK CONSTRAINT [ck_dv_r_source_ai]
GO
ALTER TABLE [dataview].[dv_r_uom]  WITH CHECK ADD  CONSTRAINT [ck_dv_r_uom_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_r_uom] CHECK CONSTRAINT [ck_dv_r_uom_ai]
GO
ALTER TABLE [dataview].[dv_r_well_status]  WITH CHECK ADD  CONSTRAINT [ck_dv_r_wstatus_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_r_well_status] CHECK CONSTRAINT [ck_dv_r_wstatus_ai]
GO
ALTER TABLE [dataview].[dv_r_well_type]  WITH CHECK ADD  CONSTRAINT [ck_dv_r_wtype_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_r_well_type] CHECK CONSTRAINT [ck_dv_r_wtype_ai]
GO
ALTER TABLE [dataview].[dv_seis_line]  WITH CHECK ADD  CONSTRAINT [ck_dv_seis_line_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_seis_line] CHECK CONSTRAINT [ck_dv_seis_line_ai]
GO
ALTER TABLE [dataview].[dv_seis_set]  WITH CHECK ADD  CONSTRAINT [ck_dv_seis_set_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_seis_set] CHECK CONSTRAINT [ck_dv_seis_set_ai]
GO
ALTER TABLE [dataview].[dv_source]  WITH CHECK ADD  CONSTRAINT [ck_dv_source_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_source] CHECK CONSTRAINT [ck_dv_source_ai]
GO
ALTER TABLE [dataview].[dv_spatial_layer]  WITH CHECK ADD  CONSTRAINT [ck_dv_spatial_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_spatial_layer] CHECK CONSTRAINT [ck_dv_spatial_ai]
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD  CONSTRAINT [ck_dv_well_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_well] CHECK CONSTRAINT [ck_dv_well_ai]
GO
ALTER TABLE [dataview].[dv_well_alias]  WITH CHECK ADD  CONSTRAINT [ck_dv_walias_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_well_alias] CHECK CONSTRAINT [ck_dv_walias_ai]
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_hdr]  WITH CHECK ADD  CONSTRAINT [ck_dv_srvy_hdr_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_well_dir_srvy_hdr] CHECK CONSTRAINT [ck_dv_srvy_hdr_ai]
GO
ALTER TABLE [dataview].[dv_well_formation_top]  WITH CHECK ADD  CONSTRAINT [ck_dv_fmt_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_well_formation_top] CHECK CONSTRAINT [ck_dv_fmt_ai]
GO
ALTER TABLE [dataview].[dv_well_log]  WITH CHECK ADD  CONSTRAINT [ck_dv_well_log_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_well_log] CHECK CONSTRAINT [ck_dv_well_log_ai]
GO
ALTER TABLE [dataview].[dv_well_log_curve]  WITH CHECK ADD  CONSTRAINT [ck_dv_log_curve_ai] CHECK  (([active_ind]='N' OR [active_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_well_log_curve] CHECK CONSTRAINT [ck_dv_log_curve_ai]
GO
ALTER TABLE [dataview].[dv_wl_file_catalog]  WITH CHECK ADD  CONSTRAINT [ck_dv_wl_ppdm_loaded] CHECK  (([ppdm_loaded_ind]='N' OR [ppdm_loaded_ind]='Y'))
GO
ALTER TABLE [dataview].[dv_wl_file_catalog] CHECK CONSTRAINT [ck_dv_wl_ppdm_loaded]
GO

-- ============ dv_well reference FKs (added) ============
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD  CONSTRAINT [FK_dv_well_well_type] FOREIGN KEY([well_type])
REFERENCES [dataview].[dv_r_well_type] ([well_type])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD  CONSTRAINT [FK_dv_well_well_status] FOREIGN KEY([well_status])
REFERENCES [dataview].[dv_r_well_status] ([well_status])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD  CONSTRAINT [FK_dv_well_country] FOREIGN KEY([country])
REFERENCES [dataview].[dv_country] ([country_code])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD  CONSTRAINT [FK_dv_well_province_state] FOREIGN KEY([province_state])
REFERENCES [dataview].[dv_province_state] ([province_state_id])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD  CONSTRAINT [FK_dv_well_county] FOREIGN KEY([county])
REFERENCES [dataview].[dv_county] ([county_id])
GO
ALTER TABLE [dataview].[dv_well]  WITH CHECK ADD  CONSTRAINT [FK_dv_well_depth_datum] FOREIGN KEY([depth_datum])
REFERENCES [dataview].[dv_r_depth_datum] ([depth_datum])
GO

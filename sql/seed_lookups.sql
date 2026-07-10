/*  seed_lookups.sql  — dv_r_well_type / dv_r_well_status / dv_r_depth_datum
    Source: PPDM/industry vocabularies (r_well_status_type, r_well_status, r_well_datum_type).
    Case-insensitive duplicates collapsed (SQL Server CI collation treats Oil==OIL).
    Run against the DB built from dataview_ddl_clean.sql. Each block seeds only if empty.  */
SET NOCOUNT ON;

IF NOT EXISTS (SELECT 1 FROM [dataview].[dv_r_well_type])
INSERT [dataview].[dv_r_well_type] (well_type,short_name,long_name,active_ind,row_created_by,row_created_date)
VALUES (N'Oil',N'OIL',N'Oil',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Oil & Gas',N'O&G',N'Oil & Gas',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Oil & Condensate',N'O&C',N'Oil & Condensate',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Gas',N'GAS',N'Gas',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Gas & Condensate',N'G&C',N'Gas & Condensate',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Condensate',N'COND',N'Condensate',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Water',N'WTR',N'Water',N'Y',N'lookup_seed',SYSUTCDATETIME());
GO

IF NOT EXISTS (SELECT 1 FROM [dataview].[dv_r_well_status])
INSERT [dataview].[dv_r_well_status] (well_status,long_name,active_ind,row_created_by,row_created_date)
VALUES (N'Location',N'Location',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Producer',N'Producer',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Shut In',N'Shut In',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Abandoned',N'Abandoned',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Plugged and Abandoned',N'Plugged and Abandoned',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Suspended',N'Suspended',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'Reclaimed',N'Reclaimed',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'In-Active',N'In-Active',N'Y',N'lookup_seed',SYSUTCDATETIME());
GO

IF NOT EXISTS (SELECT 1 FROM [dataview].[dv_r_depth_datum])
INSERT [dataview].[dv_r_depth_datum] (depth_datum,long_name,active_ind,row_created_by,row_created_date)
VALUES (N'GROUND LEVEL',N'Ground Level Elevation',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'MEAN SEA LEVEL',N'Mean Sea Level',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'DERRICK FLOOR',N'Derrick Floor Elevation',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'KELLY BUSHING',N'Kelly Bushing Elevation',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'ROTARY TABLE',N'Rotary Table Elevation',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'CASING FLANGE',N'Casing Flange',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'CROWN BLOCK',N'Crown Block',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'KB',N'Kelly Bushing',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'DF',N'Derrick Floor',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'RT',N'Rotary Table',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'GL',N'Ground Level',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'MSL',N'Mean Sea Level',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'CSF',N'Casing Flange',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'CB',N'Crown Block',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'SUBSEA',N'Subsea',N'Y',N'lookup_seed',SYSUTCDATETIME()),
       (N'UNKNOWN',N'Unknown',N'Y',N'lookup_seed',SYSUTCDATETIME());
GO

-- patch_dv_well_columns.sql
-- Adds new columns to dataview.dv_well
-- Replaces ground_elevation_ouom and kb_elevation_ouom with single elevation_ouom
-- Safe to run multiple times — each change is wrapped in an existence check.

USE DataView;
GO

-- ── New columns ────────────────────────────────────────────────────────

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'abandonment_date')
    ALTER TABLE dataview.dv_well ADD abandonment_date DATETIME2 NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'bottom_hole_latitude')
    ALTER TABLE dataview.dv_well ADD bottom_hole_latitude NUMERIC(15,10) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'bottom_hole_longitude')
    ALTER TABLE dataview.dv_well ADD bottom_hole_longitude NUMERIC(15,10) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'current_operator_ba_id')
    ALTER TABLE dataview.dv_well ADD current_operator_ba_id NVARCHAR(40) NULL
        REFERENCES dataview.dv_business_associate(ba_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'original_operator_ba_id')
    ALTER TABLE dataview.dv_well ADD original_operator_ba_id NVARCHAR(40) NULL
        REFERENCES dataview.dv_business_associate(ba_id);
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'elevation_ouom')
    ALTER TABLE dataview.dv_well ADD elevation_ouom NVARCHAR(40) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'formation_at_td')
    ALTER TABLE dataview.dv_well ADD formation_at_td NVARCHAR(255) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'long_lat_source')
    ALTER TABLE dataview.dv_well ADD long_lat_source NVARCHAR(40) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'permit_number')
    ALTER TABLE dataview.dv_well ADD permit_number NVARCHAR(40) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'producing_formation')
    ALTER TABLE dataview.dv_well ADD producing_formation NVARCHAR(255) NULL;
GO

-- ── Migrate existing ouom data before dropping old columns ─────────────
-- Copy ground_elevation_ouom into elevation_ouom where not already set
IF EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'ground_elevation_ouom')
BEGIN
    UPDATE dataview.dv_well
    SET elevation_ouom = ground_elevation_ouom
    WHERE elevation_ouom IS NULL AND ground_elevation_ouom IS NOT NULL;
END
GO

-- ── Drop old ouom columns ──────────────────────────────────────────────
IF EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'ground_elevation_ouom')
    ALTER TABLE dataview.dv_well DROP COLUMN ground_elevation_ouom;
GO

IF EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_well') AND name = 'kb_elevation_ouom')
    ALTER TABLE dataview.dv_well DROP COLUMN kb_elevation_ouom;
GO

-- ── Verify ────────────────────────────────────────────────────────────
SELECT
    column_name,
    data_type + CASE
        WHEN character_maximum_length IS NOT NULL
            THEN '(' + CAST(character_maximum_length AS VARCHAR) + ')'
        WHEN numeric_precision IS NOT NULL AND data_type = 'numeric'
            THEN '(' + CAST(numeric_precision AS VARCHAR) + ','
                     + CAST(numeric_scale AS VARCHAR) + ')'
        ELSE '' END AS data_type,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'dataview'
  AND table_name   = 'dv_well'
ORDER BY ordinal_position;
GO

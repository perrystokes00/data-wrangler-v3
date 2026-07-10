-- patch_spatial_layer.sql
-- Patches dv_spatial_layer to match what dv_spatial_loader.py expects.
-- Safe to run multiple times — each ALTER is wrapped in an existence check.

USE DataView;  -- change to your database name if different
GO

-- Create table if it doesn't exist at all
IF OBJECT_ID('dataview.dv_spatial_layer', 'U') IS NULL
CREATE TABLE dataview.dv_spatial_layer (
    layer_id            NVARCHAR(40)    NOT NULL,
    layer_name          NVARCHAR(255)   NOT NULL,
    layer_type          NVARCHAR(40)    NULL,
    layer_category      NVARCHAR(40)    NULL,
    source_type         NVARCHAR(40)    NULL DEFAULT 'GEOJSON',
    epsg_code           INT             DEFAULT 4326,
    file_path           NVARCHAR(1000)  NULL,
    geometry_wkt        NVARCHAR(MAX)   NULL,
    feature_count       INT             NULL,
    bbox_min_lat        NUMERIC(15,10)  NULL,
    bbox_max_lat        NUMERIC(15,10)  NULL,
    bbox_min_lon        NUMERIC(15,10)  NULL,
    bbox_max_lon        NUMERIC(15,10)  NULL,
    style_color         NVARCHAR(20)    NULL DEFAULT '#1a73e8',
    style_weight        NUMERIC(5,2)    NULL DEFAULT 1.5,
    style_opacity       NUMERIC(5,2)    NULL DEFAULT 0.8,
    style_fill_color    NVARCHAR(20)    NULL,
    style_fill_opacity  NUMERIC(5,2)    NULL DEFAULT 0.0,
    style_dash          NVARCHAR(40)    NULL,
    tooltip_fields      NVARCHAR(500)   NULL,
    display_order       INT             NULL DEFAULT 0,
    active_ind          NVARCHAR(1)     NOT NULL DEFAULT 'Y',
    remark              NVARCHAR(2000)  NULL,
    row_created_by      NVARCHAR(40)    NOT NULL DEFAULT 'SYSTEM',
    row_created_date    DATETIME2       NOT NULL DEFAULT GETDATE(),
    row_changed_by      NVARCHAR(40)    NULL,
    row_changed_date    DATETIME2       NULL,
    source              NVARCHAR(40)    NULL,
    CONSTRAINT pk_dv_spatial_layer PRIMARY KEY (layer_id),
    CONSTRAINT ck_dv_spatial_ai    CHECK (active_ind IN ('Y','N'))
);
GO

-- If table already exists, patch missing columns one by one
IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'geometry_wkt')
    ALTER TABLE dataview.dv_spatial_layer ADD geometry_wkt NVARCHAR(MAX) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'source_type')
    ALTER TABLE dataview.dv_spatial_layer ADD source_type NVARCHAR(40) NULL DEFAULT 'GEOJSON';
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'style_color')
    ALTER TABLE dataview.dv_spatial_layer ADD style_color NVARCHAR(20) NULL DEFAULT '#1a73e8';
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'style_weight')
    ALTER TABLE dataview.dv_spatial_layer ADD style_weight NUMERIC(5,2) NULL DEFAULT 1.5;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'style_opacity')
    ALTER TABLE dataview.dv_spatial_layer ADD style_opacity NUMERIC(5,2) NULL DEFAULT 0.8;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'style_fill_color')
    ALTER TABLE dataview.dv_spatial_layer ADD style_fill_color NVARCHAR(20) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'style_fill_opacity')
    ALTER TABLE dataview.dv_spatial_layer ADD style_fill_opacity NUMERIC(5,2) NULL DEFAULT 0.0;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'style_dash')
    ALTER TABLE dataview.dv_spatial_layer ADD style_dash NVARCHAR(40) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'tooltip_fields')
    ALTER TABLE dataview.dv_spatial_layer ADD tooltip_fields NVARCHAR(500) NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'display_order')
    ALTER TABLE dataview.dv_spatial_layer ADD display_order INT NULL DEFAULT 0;
GO

IF NOT EXISTS (SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dataview.dv_spatial_layer')
    AND name = 'source')
    ALTER TABLE dataview.dv_spatial_layer ADD source NVARCHAR(40) NULL;
GO

-- Verify
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'dataview'
  AND table_name   = 'dv_spatial_layer'
ORDER BY ordinal_position;
GO

-- ============================================================
-- dataview.dv_well_legal
-- Per-well legal location (PLSS) for surface and bottom hole
-- Linked to dv_well by UWI
-- ============================================================
USE DataView;
GO

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES
               WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME='dv_well_legal')
BEGIN
    CREATE TABLE dataview.dv_well_legal (
        uwi                 NVARCHAR(20)   NOT NULL,
        location_type        NVARCHAR(10)   NOT NULL,  -- 'SURFACE' or 'BOTTOM'
        section              NVARCHAR(10)   NULL,
        township             NVARCHAR(10)   NULL,
        township_dir         NVARCHAR(5)    NULL,      -- N or S
        range_num            NVARCHAR(10)   NULL,
        range_dir            NVARCHAR(5)    NULL,      -- E or W
        quarter_1            NVARCHAR(10)   NULL,      -- e.g. SW, NE
        quarter_2            NVARCHAR(10)   NULL,      -- e.g. NW, SE
        footage_1            NVARCHAR(50)   NULL,      -- e.g. 1650 FNL
        footage_2            NVARCHAR(50)   NULL,      -- e.g. 990 FEL
        principal_meridian   NVARCHAR(40)   NULL,
        source               NVARCHAR(20)   NULL,
        active_ind           NVARCHAR(1)    NOT NULL DEFAULT 'Y',
        row_created_by       NVARCHAR(40)   NOT NULL DEFAULT SUSER_SNAME(),
        row_created_date     DATETIME2      NOT NULL DEFAULT GETDATE(),
        CONSTRAINT pk_dv_well_legal PRIMARY KEY (uwi, location_type),
        CONSTRAINT fk_dv_well_legal_well FOREIGN KEY (uwi)
            REFERENCES dataview.dv_well(uwi)
    );

    PRINT 'Created dataview.dv_well_legal';
END
ELSE
    PRINT 'dataview.dv_well_legal already exists';
GO

USE DataView;
GO

IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.TABLES
               WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME='dv_well_extension')
BEGIN
    CREATE TABLE dataview.dv_well_extension (
        uwi           NVARCHAR(40)  NOT NULL,
        attr_name     NVARCHAR(100) NOT NULL,
        attr_value    NVARCHAR(500) NULL,
        source        NVARCHAR(20)  NOT NULL,
        CONSTRAINT pk_dv_well_ext PRIMARY KEY (uwi, attr_name, source),
        CONSTRAINT fk_dv_well_ext FOREIGN KEY (uwi)
            REFERENCES dataview.dv_well(uwi)
    );
    CREATE INDEX ix_dv_well_ext_source ON dataview.dv_well_extension(source);
    PRINT 'Created dataview.dv_well_extension';
END
ELSE
    PRINT 'dataview.dv_well_extension already exists';
GO

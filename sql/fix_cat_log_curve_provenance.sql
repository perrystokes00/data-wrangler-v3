/* ---------------------------------------------------------------------------
   fix_cat_log_curve_provenance.sql

   cat_log_curve was created by the curve registry, not the mirror builder, so
   it has the data columns but none of the promote-tracking (provenance) columns
   that every other cat_* table carries. Now that promote *discovers* it, the
   eligibility query (m.PROMOTED = 0) fails with "Invalid column name 'PROMOTED'".

   This retrofits the missing columns in place — idempotent, keeps all existing
   rows. Adds exactly what build_catalog_mirror.build_ddl appends:
       INVENTORY_ID, SOURCE_PATH, PROMOTED, PROMOTED_AT, CAPTURED_AT, CAT_ROW_ID
   plus the UWI gate helper and the two mirror indexes.
--------------------------------------------------------------------------- */
USE DataView;
GO
SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
GO

-- gate helper: promote keys every row on a clean UWI
IF COL_LENGTH('file_catalog.cat_log_curve','UWI') IS NULL
    ALTER TABLE file_catalog.cat_log_curve ADD UWI CHAR(14) NULL;

IF COL_LENGTH('file_catalog.cat_log_curve','INVENTORY_ID') IS NULL
    ALTER TABLE file_catalog.cat_log_curve ADD INVENTORY_ID NVARCHAR(64) NULL;

IF COL_LENGTH('file_catalog.cat_log_curve','SOURCE_PATH') IS NULL
    ALTER TABLE file_catalog.cat_log_curve ADD SOURCE_PATH NVARCHAR(1024) NULL;

IF COL_LENGTH('file_catalog.cat_log_curve','PROMOTED') IS NULL
    ALTER TABLE file_catalog.cat_log_curve
        ADD PROMOTED BIT NOT NULL
            CONSTRAINT DF_cat_log_curve_PROMOTED DEFAULT 0;

IF COL_LENGTH('file_catalog.cat_log_curve','PROMOTED_AT') IS NULL
    ALTER TABLE file_catalog.cat_log_curve ADD PROMOTED_AT DATETIME2 NULL;

IF COL_LENGTH('file_catalog.cat_log_curve','CAPTURED_AT') IS NULL
    ALTER TABLE file_catalog.cat_log_curve
        ADD CAPTURED_AT DATETIME2 NOT NULL
            CONSTRAINT DF_cat_log_curve_CAP DEFAULT SYSUTCDATETIME();

-- IDENTITY (not PK, to avoid colliding with any existing key); gives the
-- monotonic value promote uses as the dedup tiebreak. Existing 179 rows get
-- 1..179 in physical order.
IF COL_LENGTH('file_catalog.cat_log_curve','CAT_ROW_ID') IS NULL
    ALTER TABLE file_catalog.cat_log_curve ADD CAT_ROW_ID BIGINT IDENTITY(1,1);
GO

-- mirror indexes (match the other cat_* tables)
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'IX_cat_log_curve_UWI'
                 AND object_id = OBJECT_ID('file_catalog.cat_log_curve'))
    CREATE INDEX IX_cat_log_curve_UWI
        ON file_catalog.cat_log_curve (UWI, PROMOTED);

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'IX_cat_log_curve_INV'
                 AND object_id = OBJECT_ID('file_catalog.cat_log_curve'))
    CREATE INDEX IX_cat_log_curve_INV
        ON file_catalog.cat_log_curve (INVENTORY_ID);
GO

-- verify
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = 'file_catalog' AND TABLE_NAME = 'cat_log_curve'
ORDER BY ORDINAL_POSITION;
GO

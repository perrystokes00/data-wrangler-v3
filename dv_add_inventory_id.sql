/* ============================================================================
   dv_add_inventory_id.sql  —  DataView v3
   ----------------------------------------------------------------------------
   Adds an INVENTORY_ID lineage column to the dv_* DETAIL tables so that
   promote_catalog can "move it up" idempotently: when a file is re-cataloged,
   promote deletes that file's prior rows (scoped by INVENTORY_ID) before
   inserting the new ones, instead of duplicating. Other files' contributions
   to the same well are untouched (the scope is the source file, not the well).

   The dv_well HEADER is intentionally excluded — it is one row per well,
   created once and fill-null updated on UWI, never file-scoped.

   INVENTORY_ID matches GLOBAL_FILE_CATALOG.INVENTORY_ID (= SHA1(path.upper)).
   Type mirrors the cat_* provenance column: NVARCHAR(64) NULL.

   Idempotent: re-running is a no-op. Review, then run with sqlcmd:
     sqlcmd -S PERRY\SQLEXPRESS -d DataView -E -b -i dv_add_inventory_id.sql
   ============================================================================ */
SET NOCOUNT ON;

DECLARE @tables TABLE (name SYSNAME);
INSERT INTO @tables (name) VALUES
    ('dv_well_formation_top'),
    ('dv_well_dir_srvy_hdr'),
    ('dv_well_dir_srvy_sta'),
    ('dv_well_core'),
    ('dv_well_core_sample'),
    ('dv_well_petro_interp'),
    ('dv_well_petro_zone'),
    ('dv_well_completion'),
    ('dv_well_stimulation'),
    ('dv_well_dst'),
    ('dv_prod_entity'),
    ('dv_prod_volume');

DECLARE @t SYSNAME, @full NVARCHAR(300), @sql NVARCHAR(MAX);
DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT name FROM @tables;
OPEN c;
FETCH NEXT FROM c INTO @t;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @full = N'dataview.' + @t;

    IF OBJECT_ID(@full, 'U') IS NULL
    BEGIN
        PRINT '-- SKIP ' + @full + ' : table not found';
    END
    ELSE
    BEGIN
        -- 1) add the column if missing
        IF COL_LENGTH(@full, 'INVENTORY_ID') IS NULL
        BEGIN
            SET @sql = N'ALTER TABLE ' + @full +
                       N' ADD INVENTORY_ID NVARCHAR(64) NULL;';
            EXEC sp_executesql @sql;
            PRINT '-- added INVENTORY_ID to ' + @full;
        END
        ELSE
            PRINT '-- INVENTORY_ID already present on ' + @full;

        -- 2) index it (used by the per-file replace DELETE) if missing
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes
            WHERE name = N'IX_' + @t + N'_INV'
              AND object_id = OBJECT_ID(@full))
        BEGIN
            SET @sql = N'CREATE INDEX [IX_' + @t + N'_INV] ON ' + @full +
                       N' (INVENTORY_ID);';
            EXEC sp_executesql @sql;
            PRINT '-- indexed INVENTORY_ID on ' + @full;
        END
    END

    FETCH NEXT FROM c INTO @t;
END
CLOSE c;
DEALLOCATE c;
PRINT '-- done';

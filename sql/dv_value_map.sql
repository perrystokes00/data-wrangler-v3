/* ================================================================
   dv_value_map.sql   ·   DataView v3
   Canonical value-standardization map. Conforms raw source values
   to canonical reference vocabulary at load time so wells from
   every source filter consistently.

     (target_column, source_value)  ->  canonical_value
     e.g. ('well_type','Gas Well') -> 'GAS'
          ('well_status','Producing') -> 'ACTIVE'

   Collation is CI, so a single row covers all case variants of a
   source_value (Gas / GAS / gas all match one mapping).

   NOTE: the two GO lines separate the CREATE batch from the seed
   batch. If your client does not support GO (e.g. DBeaver/ADS in
   a mode that splits on ';'), just delete the two 'GO' lines and
   run it - the ';' terminators execute each statement in order.
   ================================================================ */

IF OBJECT_ID('dataview.dv_value_map') IS NULL
BEGIN
    CREATE TABLE dataview.dv_value_map (
        map_id            INT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_dv_value_map PRIMARY KEY,
        target_table      NVARCHAR(128)  NOT NULL,   -- e.g. 'dv_well'
        target_column     NVARCHAR(128)  NOT NULL,   -- e.g. 'well_type'
        source_value      NVARCHAR(255)  NOT NULL,   -- raw variant from a source
        canonical_value   NVARCHAR(255)  NOT NULL,   -- the standard value to store
        confirmed_ind     CHAR(1)        NOT NULL CONSTRAINT DF_dvm_conf DEFAULT 'Y',
        active_ind        CHAR(1)        NOT NULL CONSTRAINT DF_dvm_act  DEFAULT 'Y',
        source            NVARCHAR(40)   NULL,        -- optional: scope to one source
        remark            NVARCHAR(2000) NULL,
        row_created_by    NVARCHAR(40)   NOT NULL CONSTRAINT DF_dvm_cby  DEFAULT SUSER_SNAME(),
        row_created_date  DATETIME2      NOT NULL CONSTRAINT DF_dvm_cdt  DEFAULT GETUTCDATE(),
        row_changed_by    NVARCHAR(40)   NULL,
        row_changed_date  DATETIME2      NULL,
        -- one mapping per (column, source value); CI collation folds case
        CONSTRAINT UQ_dv_value_map UNIQUE (target_column, source_value)
    );
END
GO

/* Starter seed - EXAMPLES ONLY. Review against YOUR actual source values
   (the resolution panel and the Stage-6 editor show you the real variants).
   Canonical sets:
     well_type   : OIL GAS WATER INJECTION DRY_HOLE OTHER LOCATION
     well_status : ACTIVE PLUGGED CANCELLED LOCATION UNKNOWN              */
INSERT INTO dataview.dv_value_map
    (target_table, target_column, source_value, canonical_value, remark)
SELECT 'dv_well', v.target_column, v.source_value, v.canonical_value, 'starter seed - review'
FROM (VALUES
    ('well_type',   'Gas Well',            'GAS'),
    ('well_type',   'Oil Well',            'OIL'),
    ('well_type',   'Oil & Gas',           'OIL'),
    ('well_type',   'Dry',                 'DRY_HOLE'),
    ('well_type',   'Dry Hole',            'DRY_HOLE'),
    ('well_type',   'Water Well',          'WATER'),
    ('well_type',   'Injection Well',      'INJECTION'),
    ('well_type',   'Permitted Location',  'LOCATION'),
    ('well_status', 'Producing',           'ACTIVE'),
    ('well_status', 'Active',              'ACTIVE'),
    ('well_status', 'P & A',               'PLUGGED'),
    ('well_status', 'P&A',                 'PLUGGED'),
    ('well_status', 'Plugged & Abandoned', 'PLUGGED'),
    ('well_status', 'Abandoned',           'PLUGGED'),
    ('well_status', 'Cancelled',           'CANCELLED'),
    ('well_status', 'Canceled',            'CANCELLED'),
    ('well_status', 'Permitted',           'LOCATION'),
    ('well_status', 'Location',            'LOCATION')
) AS v(target_column, source_value, canonical_value)
WHERE NOT EXISTS (
    SELECT 1 FROM dataview.dv_value_map m
    WHERE m.target_column = v.target_column
      AND m.source_value  = v.source_value
);
GO

SELECT target_column, COUNT(*) AS mappings
FROM dataview.dv_value_map
GROUP BY target_column
ORDER BY target_column;

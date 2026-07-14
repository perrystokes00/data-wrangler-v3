"""
setup_database.py
=================
Data Wrangler database initialisation — creates all schemas and tables
in dependency order for a fresh PPDM 3.9 installation.

Can be run:
  1. From the pipeline Stage 1 "Initialise Database" button
  2. Standalone: python setup_database.py

Migration system:
  - file_catalog.DW_SCHEMA_VERSION tracks applied migrations
  - Each migration is idempotent (IF NOT EXISTS guards)
  - New migrations are appended to MIGRATIONS list
  - Run at every startup — skips already-applied migrations
"""
from __future__ import annotations
from sqlalchemy import text

# ── Version tracking table ────────────────────────────────────────────────────

_VERSION_DDL = """
IF NOT EXISTS (
    SELECT 1 FROM sys.tables t
    JOIN sys.schemas s ON t.schema_id=s.schema_id
    WHERE s.name='file_catalog' AND t.name='DW_SCHEMA_VERSION'
)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='file_catalog')
        EXEC('CREATE SCHEMA [file_catalog]')
    CREATE TABLE file_catalog.DW_SCHEMA_VERSION (
        MIGRATION_ID    NVARCHAR(10)   NOT NULL PRIMARY KEY,
        DESCRIPTION     NVARCHAR(255)  NOT NULL,
        APPLIED_DATE    DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
        DW_VERSION      NVARCHAR(20)   NULL
    )
END
"""

# ── Migrations — append only, never edit existing entries ─────────────────────

MIGRATIONS = [

    ("001", "Create file_catalog schema", """
        IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='file_catalog')
            EXEC('CREATE SCHEMA [file_catalog]')
    """),

    ("002", "Create las_catalog schema", """
        IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='las_catalog')
            EXEC('CREATE SCHEMA [las_catalog]')
    """),

    ("003", "Create INVENTORY_USER table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='INVENTORY_USER'
        )
        CREATE TABLE file_catalog.INVENTORY_USER (
            USER_ID          NVARCHAR(40)   NOT NULL PRIMARY KEY,
            FULL_NAME        NVARCHAR(255)  NOT NULL,
            EMAIL            NVARCHAR(255)  NOT NULL UNIQUE,
            PASSWORD_HASH    NVARCHAR(64)   NOT NULL,
            ROLE             NVARCHAR(20)   NOT NULL DEFAULT 'CATALOGER',
            ACTIVE_IND       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
            LAST_LOGIN       DATETIME2      NULL,
            CREATED_DATE     DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            ROW_CHANGED_DATE DATETIME2      NULL
        )
    """),

    ("004", "Create INVENTORY_SETTING table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='INVENTORY_SETTING'
        )
        CREATE TABLE file_catalog.INVENTORY_SETTING (
            SETTING_KEY     NVARCHAR(100)  NOT NULL PRIMARY KEY,
            SETTING_VALUE   NVARCHAR(2000) NULL,
            DESCRIPTION     NVARCHAR(500)  NULL,
            UPDATED_DATE    DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            UPDATED_BY      NVARCHAR(255)  NULL
        )
    """),

    ("005", "Create INVENTORY_GROUP table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='INVENTORY_GROUP'
        )
        CREATE TABLE file_catalog.INVENTORY_GROUP (
            GROUP_ID         NVARCHAR(40)   NOT NULL PRIMARY KEY,
            GROUP_NAME       NVARCHAR(255)  NOT NULL,
            FILE_TYPE        NVARCHAR(50)   NULL,
            CREATED_BY       NVARCHAR(40)   NULL,
            CREATED_DATE     DATETIME2      NOT NULL DEFAULT GETUTCDATE()
        )
    """),

    ("006", "Create INVENTORY_ASSIGNMENT table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='INVENTORY_ASSIGNMENT'
        )
        CREATE TABLE file_catalog.INVENTORY_ASSIGNMENT (
            ASSIGNMENT_ID    NVARCHAR(40)   NOT NULL PRIMARY KEY,
            GROUP_ID         NVARCHAR(40)   NOT NULL,
            ASSIGNED_TO      NVARCHAR(40)   NULL,
            ASSIGNED_BY      NVARCHAR(40)   NULL,
            ASSIGNED_DATE    DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            DUE_DATE         DATE           NULL,
            STATUS           NVARCHAR(20)   NOT NULL DEFAULT 'OPEN',
            FILE_COUNT       INT            NULL,
            COMPLETED_DATE   DATETIME2      NULL
        )
    """),

    ("007", "Create GLOBAL_FILE_CATALOG table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='GLOBAL_FILE_CATALOG'
        )
        CREATE TABLE file_catalog.GLOBAL_FILE_CATALOG (
            INVENTORY_ID     NVARCHAR(40)   NOT NULL PRIMARY KEY,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_EXT         NVARCHAR(20)   NULL,
            FILE_TYPE_GROUP  NVARCHAR(50)   NULL,
            FILE_SIZE_KB     FLOAT          NULL,
            FILE_PATH        NVARCHAR(2000) NULL,
            REPOSITORY_ID    NVARCHAR(40)   NULL,
            CATALOG_STATUS   NVARCHAR(20)   NOT NULL DEFAULT 'UNCATALOGED',
            DUPLICATE_OF     NVARCHAR(40)   NULL,
            SCAN_DATE        DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            LAST_SEEN_DATE   DATETIME2      NULL
        )
    """),

    ("008", "Create INVENTORY_GROUP_FILE table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='INVENTORY_GROUP_FILE'
        )
        CREATE TABLE file_catalog.INVENTORY_GROUP_FILE (
            GROUP_FILE_ID    NVARCHAR(40)   NOT NULL PRIMARY KEY,
            GROUP_ID         NVARCHAR(40)   NOT NULL,
            ASSIGNMENT_ID    NVARCHAR(40)   NOT NULL,
            INVENTORY_ID     NVARCHAR(40)   NOT NULL,
            ADDED_BY         NVARCHAR(40)   NULL,
            ADDED_DATE       DATETIME2      NOT NULL DEFAULT GETUTCDATE()
        )
    """),

    ("009", "Create WL_REPOSITORY table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog' AND t.name='WL_REPOSITORY'
        )
        CREATE TABLE las_catalog.WL_REPOSITORY (
            REPOSITORY_ID    NVARCHAR(40)   NOT NULL PRIMARY KEY,
            REPOSITORY_NAME  NVARCHAR(255)  NOT NULL,
            BASE_PATH        NVARCHAR(2000) NULL,
            DESCRIPTION      NVARCHAR(500)  NULL,
            ACTIVE_IND       NVARCHAR(1)    NOT NULL DEFAULT 'Y',
            CREATED_DATE     DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            CREATED_BY       NVARCHAR(255)  NULL
        )
    """),

    ("010", "Create LAS_FILE table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog' AND t.name='LAS_FILE'
        )
        CREATE TABLE las_catalog.LAS_FILE (
            LAS_FILE_ID      NVARCHAR(40)   NOT NULL PRIMARY KEY,
            REPOSITORY_ID    NVARCHAR(40)   NULL,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_SIZE_KB     FLOAT          NULL,
            UWI              NVARCHAR(40)   NULL,
            WELL_NAME        NVARCHAR(255)  NULL,
            LAS_VERSION      NVARCHAR(10)   NULL,
            WRAP_MODE        NVARCHAR(10)   NULL,
            DEPTH_START      FLOAT          NULL,
            DEPTH_STOP       FLOAT          NULL,
            DEPTH_STEP       FLOAT          NULL,
            DEPTH_UNIT       NVARCHAR(20)   NULL,
            NULL_VALUE       NVARCHAR(20)   NULL,
            CURVE_COUNT      INT            NULL,
            CATALOG_DATE     DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            CATALOGED_BY     NVARCHAR(255)  NULL
        )
    """),

    ("011", "Create LAS_FILE_CURVE table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog' AND t.name='LAS_FILE_CURVE'
        )
        CREATE TABLE las_catalog.LAS_FILE_CURVE (
            CURVE_ID         NVARCHAR(40)   NOT NULL PRIMARY KEY,
            LAS_FILE_ID      NVARCHAR(40)   NOT NULL,
            MNEMONIC         NVARCHAR(50)   NULL,
            UNIT             NVARCHAR(20)   NULL,
            DESCRIPTION      NVARCHAR(255)  NULL,
            CURVE_ORDER      INT            NULL
        )
    """),

    ("012", "Create LAS_FILE_PARAMETER table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog' AND t.name='LAS_FILE_PARAMETER'
        )
        CREATE TABLE las_catalog.LAS_FILE_PARAMETER (
            PARAM_ID         NVARCHAR(40)   NOT NULL PRIMARY KEY,
            LAS_FILE_ID      NVARCHAR(40)   NOT NULL,
            MNEMONIC         NVARCHAR(50)   NULL,
            VALUE            NVARCHAR(500)  NULL,
            UNIT             NVARCHAR(20)   NULL,
            DESCRIPTION      NVARCHAR(255)  NULL
        )
    """),

    ("013", "Create DLIS_FILE table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog' AND t.name='DLIS_FILE'
        )
        CREATE TABLE las_catalog.DLIS_FILE (
            DLIS_FILE_ID     NVARCHAR(40)   NOT NULL PRIMARY KEY,
            REPOSITORY_ID    NVARCHAR(40)   NULL,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_SIZE_KB     FLOAT          NULL,
            UWI              NVARCHAR(40)   NULL,
            WELL_NAME        NVARCHAR(255)  NULL,
            LOGICAL_FILE_COUNT INT          NULL,
            CATALOG_DATE     DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            CATALOGED_BY     NVARCHAR(255)  NULL
        )
    """),

    ("014", "Create DLIS sub-tables", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog' AND t.name='DLIS_LOGICAL_FILE'
        )
        CREATE TABLE las_catalog.DLIS_LOGICAL_FILE (
            LOGICAL_FILE_ID  NVARCHAR(40)   NOT NULL PRIMARY KEY,
            DLIS_FILE_ID     NVARCHAR(40)   NOT NULL,
            LOGICAL_FILE_IDX INT            NULL,
            WELL_NAME        NVARCHAR(255)  NULL,
            FIELD_NAME       NVARCHAR(255)  NULL,
            COMPANY          NVARCHAR(255)  NULL
        )
    """),

    ("015", "Create LIS_FILE table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog' AND t.name='LIS_FILE'
        )
        CREATE TABLE las_catalog.LIS_FILE (
            LIS_FILE_ID      NVARCHAR(40)   NOT NULL PRIMARY KEY,
            REPOSITORY_ID    NVARCHAR(40)   NULL,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_SIZE_KB     FLOAT          NULL,
            UWI              NVARCHAR(40)   NULL,
            WELL_NAME        NVARCHAR(255)  NULL,
            CATALOG_DATE     DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            CATALOGED_BY     NVARCHAR(255)  NULL
        )
    """),

    ("016", "Create SEIS_FILE_CATALOG table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog' AND t.name='SEIS_FILE_CATALOG'
        )
        CREATE TABLE las_catalog.SEIS_FILE_CATALOG (
            SEIS_FILE_ID     NVARCHAR(40)   NOT NULL PRIMARY KEY,
            REPOSITORY_ID    NVARCHAR(40)   NULL,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_FORMAT      NVARCHAR(20)   NULL,
            FILE_SIZE_KB     FLOAT          NULL,
            SURVEY_NAME      NVARCHAR(255)  NULL,
            LINE_NAME        NVARCHAR(255)  NULL,
            CATALOG_DATE     DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            CATALOGED_BY     NVARCHAR(255)  NULL
        )
    """),

    ("017", "Create FILE_WELL_HEADER table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='FILE_WELL_HEADER'
        )
        CREATE TABLE file_catalog.FILE_WELL_HEADER (
            FILE_HEADER_ID   NVARCHAR(40)   NOT NULL PRIMARY KEY,
            INVENTORY_ID     NVARCHAR(40)   NULL,
            CATALOG_FILE_ID  NVARCHAR(40)   NULL,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_FORMAT      NVARCHAR(10)   NOT NULL,
            UWI              NVARCHAR(40)   NULL,
            MNEMONIC         NVARCHAR(50)   NOT NULL,
            VALUE            NVARCHAR(500)  NULL,
            UNIT             NVARCHAR(50)   NULL,
            DESCRIPTION      NVARCHAR(500)  NULL,
            ROW_CREATED_DATE DATETIME2      NOT NULL DEFAULT GETUTCDATE()
        )
    """),

    ("018", "Create FILE_SEIS_HEADER table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='FILE_SEIS_HEADER'
        )
        CREATE TABLE file_catalog.FILE_SEIS_HEADER (
            SEIS_HEADER_ID   NVARCHAR(40)   NOT NULL PRIMARY KEY,
            INVENTORY_ID     NVARCHAR(40)   NULL,
            CATALOG_FILE_ID  NVARCHAR(40)   NULL,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_FORMAT      NVARCHAR(10)   NOT NULL,
            SURVEY_NAME      NVARCHAR(255)  NULL,
            FIELD_NAME       NVARCHAR(200)  NOT NULL,
            VALUE            NVARCHAR(1000) NULL,
            SOURCE           NVARCHAR(20)   NULL,
            ROW_CREATED_DATE DATETIME2      NOT NULL DEFAULT GETUTCDATE()
        )
    """),

    ("019", "Create WELL_HEADER_STAGING table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='WELL_HEADER_STAGING'
        )
        CREATE TABLE file_catalog.WELL_HEADER_STAGING (
            STAGE_ID         NVARCHAR(40)   NOT NULL PRIMARY KEY,
            BATCH_ID         NVARCHAR(40)   NOT NULL,
            FILE_NAME        NVARCHAR(500)  NULL,
            UWI              NVARCHAR(40)   NULL,
            WELL_NAME        NVARCHAR(255)  NULL,
            COMPANY          NVARCHAR(255)  NULL,
            FIELD            NVARCHAR(255)  NULL,
            COUNTY           NVARCHAR(255)  NULL,
            STATE            NVARCHAR(255)  NULL,
            COUNTRY          NVARCHAR(255)  NULL,
            LATITUDE         NVARCHAR(50)   NULL,
            LONGITUDE        NVARCHAR(50)   NULL,
            KB_ELEV          NVARCHAR(50)   NULL,
            GL_ELEV          NVARCHAR(50)   NULL,
            SPUD_DATE        NVARCHAR(50)   NULL,
            COMP_DATE        NVARCHAR(50)   NULL,
            STATUS           NVARCHAR(20)   NOT NULL DEFAULT 'PENDING',
            REVIEW_NOTES     NVARCHAR(500)  NULL,
            UPLOADED_DATE    DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            APPLIED_DATE     DATETIME2      NULL
        )
    """),

    ("020", "Create SEIS_HEADER_STAGING table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='SEIS_HEADER_STAGING'
        )
        CREATE TABLE file_catalog.SEIS_HEADER_STAGING (
            STAGE_ID          NVARCHAR(40)   NOT NULL PRIMARY KEY,
            BATCH_ID          NVARCHAR(40)   NOT NULL,
            FILE_NAME         NVARCHAR(500)  NULL,
            SURVEY_NAME       NVARCHAR(255)  NULL,
            LINE_NAME         NVARCHAR(255)  NULL,
            SAMPLE_INTERVAL   NVARCHAR(50)   NULL,
            SAMPLES_PER_TRACE NVARCHAR(50)   NULL,
            DATA_FORMAT_CODE  NVARCHAR(50)   NULL,
            ACQ_DATE          NVARCHAR(50)   NULL,
            OPERATOR          NVARCHAR(255)  NULL,
            CLIENT            NVARCHAR(255)  NULL,
            COUNTRY           NVARCHAR(255)  NULL,
            STATUS            NVARCHAR(20)   NOT NULL DEFAULT 'PENDING',
            REVIEW_NOTES      NVARCHAR(500)  NULL,
            UPLOADED_DATE     DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            APPLIED_DATE      DATETIME2      NULL
        )
    """),

    ("021", "Create AUDIT_LOG table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='AUDIT_LOG'
        )
        CREATE TABLE file_catalog.AUDIT_LOG (
            AUDIT_ID     NVARCHAR(40)   NOT NULL PRIMARY KEY,
            EVENT_TIME   DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            EVENT_TYPE   NVARCHAR(50)   NOT NULL,
            USER_ID      NVARCHAR(40)   NULL,
            USER_NAME    NVARCHAR(255)  NULL,
            TARGET_ID    NVARCHAR(40)   NULL,
            TARGET_TYPE  NVARCHAR(50)   NULL,
            TARGET_NAME  NVARCHAR(500)  NULL,
            OLD_VALUE    NVARCHAR(MAX)  NULL,
            NEW_VALUE    NVARCHAR(MAX)  NULL,
            NOTES        NVARCHAR(1000) NULL,
            SESSION_ID   NVARCHAR(40)   NULL
        )
    """),

    ("022", "Create DW_SCHEMA_VERSION index", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes i
            JOIN sys.tables t ON i.object_id=t.object_id
            JOIN sys.schemas s ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog'
              AND t.name='AUDIT_LOG'
              AND i.name='IX_AUDIT_LOG_TIME'
        )
        CREATE INDEX IX_AUDIT_LOG_TIME
            ON file_catalog.AUDIT_LOG (EVENT_TIME DESC)
    """),

    ("023", "Create GLOBAL_FILE_CATALOG status index", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes i
            JOIN sys.tables t ON i.object_id=t.object_id
            JOIN sys.schemas s ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog'
              AND t.name='GLOBAL_FILE_CATALOG'
              AND i.name='IX_GFC_STATUS'
        )
        CREATE INDEX IX_GFC_STATUS
            ON file_catalog.GLOBAL_FILE_CATALOG (CATALOG_STATUS, FILE_EXT)
    """),

    ("024", "Create LAS_FILE UWI index", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.indexes i
            JOIN sys.tables t ON i.object_id=t.object_id
            JOIN sys.schemas s ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog'
              AND t.name='LAS_FILE'
              AND i.name='IX_LAS_FILE_UWI'
        )
        CREATE INDEX IX_LAS_FILE_UWI
            ON las_catalog.LAS_FILE (UWI)
    """),

    ("027", "Create PDF_SURVEY_CATALOG table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='PDF_SURVEY_CATALOG'
        )
        CREATE TABLE file_catalog.PDF_SURVEY_CATALOG (
            FILE_ID          NVARCHAR(40)   NOT NULL PRIMARY KEY,
            FILE_PATH        NVARCHAR(2000) NOT NULL,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_SIZE_KB     FLOAT          NULL,
            PAGE_COUNT       INT            NULL,
            REPORT_TYPE      NVARCHAR(50)   NULL,
            WELL_NAME        NVARCHAR(255)  NULL,
            UWI              NVARCHAR(40)   NULL,
            OPERATOR         NVARCHAR(255)  NULL,
            FIELD_NAME       NVARCHAR(255)  NULL,
            STATE            NVARCHAR(10)   NULL,
            SURVEY_TYPE      NVARCHAR(40)   NULL,
            STATION_COUNT    INT            NULL,
            CONFIDENCE       FLOAT          NULL,
            LOAD_STATUS      NVARCHAR(20)   NOT NULL DEFAULT 'PENDING',
            SURVEY_ID        NVARCHAR(40)   NULL,
            LOADED_COUNT     INT            NULL,
            SCAN_DATE        DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            LOAD_DATE        DATETIME2      NULL,
            ERROR_MSG        NVARCHAR(1000) NULL
        )
    """),

    ("026", "Create SHAPEFILE_CATALOG table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='file_catalog' AND t.name='SHAPEFILE_CATALOG'
        )
        CREATE TABLE file_catalog.SHAPEFILE_CATALOG (
            FILE_ID          NVARCHAR(40)   NOT NULL PRIMARY KEY,
            FILE_PATH        NVARCHAR(2000) NOT NULL,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_EXT         NVARCHAR(20)   NULL,
            FILE_SIZE_KB     FLOAT          NULL,
            PARENT_FOLDER    NVARCHAR(255)  NULL,
            FEATURE_TYPE     NVARCHAR(50)   NULL,
            PPDM_TARGET      NVARCHAR(100)  NULL,
            GEOMETRY_TYPE    NVARCHAR(50)   NULL,
            FEATURE_COUNT    INT            NULL,
            CRS              NVARCHAR(255)  NULL,
            CRS_EPSG         INT            NULL,
            ATTRIBUTES       NVARCHAR(MAX)  NULL,
            COLUMN_MAP       NVARCHAR(MAX)  NULL,
            BOUNDS           NVARCHAR(500)  NULL,
            CONFIDENCE       FLOAT          NULL,
            LOAD_STATUS      NVARCHAR(20)   NOT NULL DEFAULT 'PENDING',
            LOADED_COUNT     INT            NULL,
            SKIPPED_COUNT    INT            NULL,
            SCAN_DATE        DATETIME2      NOT NULL DEFAULT GETUTCDATE(),
            LOAD_DATE        DATETIME2      NULL,
            ERROR_MSG        NVARCHAR(1000) NULL
        )
    """),

    ("025", "Create WL_FILE_MAP table", """
        IF NOT EXISTS (
            SELECT 1 FROM sys.tables t JOIN sys.schemas s
            ON t.schema_id=s.schema_id
            WHERE s.name='las_catalog' AND t.name='WL_FILE_UWI_MAP'
        )
        CREATE TABLE las_catalog.WL_FILE_UWI_MAP (
            MAP_ID           NVARCHAR(40)   NOT NULL PRIMARY KEY,
            REPOSITORY_ID    NVARCHAR(40)   NULL,
            FILE_NAME        NVARCHAR(500)  NOT NULL,
            FILE_EXT         NVARCHAR(20)   NULL,
            UWI              NVARCHAR(40)   NULL,
            WELL_NAME        NVARCHAR(255)  NULL,
            MATCH_METHOD     NVARCHAR(50)   NULL,
            MATCH_SCORE      FLOAT          NULL,
            CONFIRMED        NVARCHAR(1)    NOT NULL DEFAULT 'N',
            CREATED_DATE     DATETIME2      NOT NULL DEFAULT GETUTCDATE()
        )
    """),

]


# ── Runner ────────────────────────────────────────────────────────────────────

def _adapt_ddl(ddl: str, dialect: str) -> str:
    """Translate SQL Server DDL to Oracle or Snowflake."""
    if dialect == "mssql":
        return ddl

    # Common substitutions
    subs_common = [
        ("DATETIME2",      "TIMESTAMP"       if dialect == "oracle" else "TIMESTAMP_NTZ"),
        ("NVARCHAR(MAX)",  "CLOB"            if dialect == "oracle" else "TEXT"),
        ("GETUTCDATE()",   "SYSTIMESTAMP"    if dialect == "oracle" else "CURRENT_TIMESTAMP()"),
        ("NVARCHAR(",      "NVARCHAR2("      if dialect == "oracle" else "VARCHAR("),
    ]
    for old, new in subs_common:
        ddl = ddl.replace(old, new)

    if dialect == "snowflake":
        # Snowflake: remove bracket identifiers, IF NOT EXISTS supported
        import re
        ddl = re.sub(r"\[(\w+)\]", r'""', ddl)
        # sys.schemas → INFORMATION_SCHEMA
        ddl = ddl.replace("sys.schemas", "INFORMATION_SCHEMA.SCHEMATA")
        # EXEC(...) → not needed, schemas created with IF NOT EXISTS
        ddl = re.sub(r"EXEC\('[^']+'\)", "", ddl)

    if dialect == "oracle":
        import re
        # Remove bracket identifiers
        ddl = re.sub(r"\[(\w+)\]", r'""', ddl)
        # IF NOT EXISTS → wrap in PL/SQL
        if "IF NOT EXISTS" in ddl and "CREATE TABLE" in ddl:
            # Extract schema and table name
            m = re.search(r'CREATE TABLE\s+"?(\w+)"?\."?(\w+)"?', ddl)
            if m:
                sch, tbl = m.group(1).upper(), m.group(2).upper()
                body = re.search(r'(\(.*\))', ddl, re.DOTALL)
                if body:
                    return f"""
DECLARE v INTEGER;
BEGIN
    SELECT COUNT(*) INTO v FROM all_tables
    WHERE owner='{sch}' AND table_name='{tbl}';
    IF v=0 THEN
        EXECUTE IMMEDIATE 'CREATE TABLE "{sch}"."{tbl}" {body.group(1).replace(chr(39), chr(39)+chr(39))}';
    END IF;
END;"""
        if "IF NOT EXISTS" in ddl and "CREATE SCHEMA" in ddl:
            return "-- Oracle: schema/user must be pre-created by DBA"
        if "IF NOT EXISTS" in ddl and "CREATE INDEX" in ddl:
            m = re.search(r"CREATE INDEX\s+\[?(\w+)\]?", ddl)
            idx = m.group(1) if m else "IDX"
            ddl = re.sub(r"IF NOT EXISTS.*?(?=CREATE INDEX)", "", ddl, flags=re.DOTALL)

    return ddl


def run_migrations(engine, dw_version: str = "2.0") -> dict:
    """
    Run all pending migrations. Returns summary dict:
      {
        "applied": ["001", "002", ...],
        "skipped": ["003", ...],
        "failed":  [("004", "error message"), ...],
        "total":   25,
      }
    """
    result = {"applied": [], "skipped": [], "failed": [], "total": len(MIGRATIONS)}

    # 1. Ensure version table exists (bootstrap)
    try:
        with engine.begin() as con:
            # Create file_catalog schema first if needed
            con.execute(text(
                "IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='file_catalog') "
                "EXEC('CREATE SCHEMA [file_catalog]')"
            ))
            con.execute(text(_VERSION_DDL))
    except Exception as e:
        result["failed"].append(("000", f"Bootstrap failed: {e}"))
        return result

    # 2. Get already-applied migrations
    try:
        with engine.connect() as con:
            applied = {r[0] for r in con.execute(text(
                "SELECT MIGRATION_ID FROM file_catalog.DW_SCHEMA_VERSION"
            )).fetchall()}
    except Exception:
        applied = set()

    # 3. Run pending migrations
    for mid, desc, ddl in MIGRATIONS:
        if mid in applied:
            result["skipped"].append(mid)
            continue
        try:
            # Auto-detect dialect and adapt DDL
            _url = str(engine.url).lower()
            _d   = ("oracle" if "oracle" in _url
                    else "snowflake" if "snowflake" in _url
                    else "mssql")
            adapted = _adapt_ddl(ddl.strip(), _d)
            _vsn_tbl = ('"FILE_CATALOG"."DW_SCHEMA_VERSION"'
                        if _d in ("oracle","snowflake")
                        else "file_catalog.DW_SCHEMA_VERSION")
            _now = ("SYSTIMESTAMP" if _d == "oracle"
                    else "CURRENT_TIMESTAMP()" if _d == "snowflake"
                    else "GETUTCDATE()")
            with engine.begin() as con:
                con.execute(text(adapted))
                con.execute(text(
                    f"INSERT INTO {_vsn_tbl} "
                    f"(MIGRATION_ID, DESCRIPTION, APPLIED_DATE, DW_VERSION) "
                    f"VALUES (:mid, :desc, {_now}, :ver)"
                ), {"mid": mid, "desc": desc, "ver": dw_version})
            result["applied"].append(mid)
        except Exception as e:
            result["failed"].append((mid, str(e)))

    return result


def get_version_status(engine) -> list[dict]:
    """Return list of all applied migrations with dates."""
    try:
        _url = str(engine.url).lower()
        _d   = ("oracle" if "oracle" in _url
                else "snowflake" if "snowflake" in _url
                else "mssql")
        _vsn_tbl = ('"FILE_CATALOG"."DW_SCHEMA_VERSION"'
                    if _d in ("oracle","snowflake")
                    else "file_catalog.DW_SCHEMA_VERSION")
        with engine.connect() as con:
            rows = con.execute(text(
                f"SELECT MIGRATION_ID, DESCRIPTION, APPLIED_DATE, DW_VERSION "
                f"FROM {_vsn_tbl} "
                f"ORDER BY MIGRATION_ID"
            )).fetchall()
        return [{"id": r[0], "description": r[1],
                 "applied": r[2], "version": r[3]} for r in rows]
    except Exception:
        return []


# ── Standalone runner ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from sqlalchemy import create_engine

    if len(sys.argv) < 2:
        print("Usage: python setup_database.py <connection_string>")
        print("Example: python setup_database.py "
              "'mssql+pyodbc://user:pw@server/db?driver=ODBC+Driver+17+for+SQL+Server'")
        sys.exit(1)

    engine = create_engine(sys.argv[1])
    print(f"Running {len(MIGRATIONS)} migrations...")
    result = run_migrations(engine)
    print(f"\n✅ Applied:  {len(result['applied'])} — {result['applied']}")
    print(f"⏭  Skipped:  {len(result['skipped'])}")
    print(f"❌ Failed:   {len(result['failed'])}")
    for mid, err in result["failed"]:
        print(f"   {mid}: {err}")

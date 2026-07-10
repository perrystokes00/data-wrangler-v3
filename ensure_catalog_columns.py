"""
ensure_catalog_columns.py — add any GLOBAL_FILE_CATALOG columns the pipeline
writes that are missing in this database. Idempotent; each ALTER is isolated so
one failure can't roll back the others. Fixes "Invalid column name" errors
(e.g. SPATIAL_OUTLINE) on schemas created before a column was added.

    py ensure_catalog_columns.py                  # defaults below
    py ensure_catalog_columns.py "PERRY\\SQLEXPRESS" DataView_Demo
"""
import sys
import worker_core as w
from sqlalchemy import text

SERVER = sys.argv[1] if len(sys.argv) > 1 else r"PERRY\SQLEXPRESS"
DB     = sys.argv[2] if len(sys.argv) > 2 else "DataView_Demo"
e = w.make_engine(SERVER, DB)

TABLE = "file_catalog.GLOBAL_FILE_CATALOG"

# Columns the scan / extract / enrich / vault / promote stages write.
COLS = [
    ("CATALOG_SCORE",     "INT NULL"),
    ("CATALOG_READINESS", "NVARCHAR(20) NULL"),
    ("CATALOG_STATUS",    "NVARCHAR(20) NULL"),
    ("MATCHED_UWI",       "NVARCHAR(40) NULL"),
    ("CATALOG_ISSUES",    "NVARCHAR(1000) NULL"),
    ("SPATIAL_OUTLINE",   "NVARCHAR(MAX) NULL"),
    ("CATALOG_TABLE",     "NVARCHAR(128) NULL"),
    ("HEADER_EXTRACTED",  "CHAR(1) NULL"),
    ("FILE_TYPE_GROUP",   "NVARCHAR(40) NULL"),
    ("UWI14",             "CHAR(14) NULL"),
    ("SURVEY_NAME",       "NVARCHAR(255) NULL"),
    ("VAULT_PATH",        "NVARCHAR(900) NULL"),
    ("VAULTED_AT",        "DATETIME2 NULL"),
    ("PROMOTED_AT",       "DATETIME2 NULL"),
    ("ROW_CHANGED_DATE",  "DATETIME2 NULL"),
]

with e.connect() as c:
    have = {r[0].upper() for r in c.execute(text("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='file_catalog'
          AND TABLE_NAME='GLOBAL_FILE_CATALOG'"""))}

added = 0
for col, typ in COLS:
    if col.upper() in have:
        print(f"{col:20} present")
        continue
    try:
        with e.begin() as c:
            c.execute(text(f"ALTER TABLE {TABLE} ADD {col} {typ}"))
        print(f"{col:20} ADDED   ({typ})")
        added += 1
    except Exception as ex:
        print(f"{col:20} FAILED  {str(ex).splitlines()[0][:100]}")

print(f"\n{added} column(s) added.")

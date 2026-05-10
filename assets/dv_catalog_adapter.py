"""
modules/dv_catalog_adapter.py
==============================
DataView v3 — Catalog Schema Adapter

Patches file_inventory and file_inventory_governance to write to the
dataview schema (dv_global_file_catalog etc.) instead of the v2
file_catalog schema.

Import this module BEFORE importing file_inventory or
file_inventory_governance and the redirection happens automatically.

Usage in v3 pages:
    import modules.dv_catalog_adapter  # must be first
    from modules.file_inventory import crawl_paths, ensure_inventory_schema
    from modules.file_inventory_governance import ensure_governance_schema

Architecture:
    v2 target : file_catalog.GLOBAL_FILE_CATALOG
    v3 target : dataview.dv_global_file_catalog

    v2 governance tables : file_catalog.INVENTORY_USER / GROUP / ASSIGNMENT
    v3 governance tables : dataview.dv_inv_user / dv_inv_group / dv_inv_assignment

    Vault root default : C:\\Bulk
"""
from __future__ import annotations

import sys

# =============================================================================
# PATCH file_inventory constants
# =============================================================================

def _patch_file_inventory():
    import importlib
    mod_name = "modules.file_inventory"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        mod = importlib.import_module(mod_name)

    # Redirect schema and table name
    mod.INVENTORY_SCHEMA = "dataview"
    mod.INVENTORY_TABLE  = "dv_global_file_catalog"

    # Patch VAULT_ROOT default
    mod.DEFAULT_VAULT_ROOT = r"C:\Bulk"

    # Patch the _ddl_create_schema function to create dataview.dv_global_file_catalog
    # instead of file_catalog.GLOBAL_FILE_CATALOG
    _orig_ddl = mod._ddl_create_schema

    def _patched_ddl(dialect: str):
        if dialect == "sqlserver":
            return (
                "IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'dataview') "
                "EXEC('CREATE SCHEMA [dataview]')"
            )
        return _orig_ddl(dialect)

    mod._ddl_create_schema = _patched_ddl

    # Patch _ddl_create_table to use dataview.dv_global_file_catalog
    _orig_table = mod._ddl_create_table

    def _patched_table(dialect: str):
        if dialect == "sqlserver":
            return """
                IF NOT EXISTS (
                    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = 'dataview'
                      AND TABLE_NAME   = 'dv_global_file_catalog'
                )
                CREATE TABLE [dataview].[dv_global_file_catalog] (
                    [INVENTORY_ID]    NVARCHAR(64)   NOT NULL,
                    [FULL_PATH]       NVARCHAR(1000) NOT NULL,
                    [FILE_NAME]       NVARCHAR(500)  NOT NULL,
                    [FILE_EXT]        NVARCHAR(20)   NULL,
                    [FILE_SIZE_KB]    NUMERIC(15,2)  NULL,
                    [FILE_HASH]       NVARCHAR(64)   NULL,
                    [FILE_HASH_FULL]  NVARCHAR(64)   NULL,
                    [DUPLICATE_GROUP] NVARCHAR(64)   NULL,
                    [MODIFIED_DATE]   DATETIME2      NULL,
                    [SCAN_DATE]       DATETIME2      NOT NULL DEFAULT GETDATE(),
                    [DOC_TYPE_GROUP]  NVARCHAR(40)   NULL,
                    [DOC_TYPE]        NVARCHAR(40)   NULL,
                    [CATALOG_STATUS]  NVARCHAR(20)   NULL DEFAULT 'UNCATALOGED',
                    [CATALOG_TABLE]   NVARCHAR(80)   NULL,
                    [CATALOG_ID]      NVARCHAR(40)   NULL,
                    [PPDM_LOADED_IND] NVARCHAR(1)    NOT NULL DEFAULT 'N',
                    [ROOT_PATH]       NVARCHAR(500)  NULL,
                    [UWI]             NVARCHAR(40)   NULL,
                    [WELL_NAME]       NVARCHAR(255)  NULL,
                    [ROW_CREATED_BY]  NVARCHAR(40)   NOT NULL DEFAULT 'SYSTEM',
                    [ROW_CREATED_DATE] DATETIME2     NOT NULL DEFAULT GETDATE(),
                    [ROW_CHANGED_BY]  NVARCHAR(40)   NULL,
                    [ROW_CHANGED_DATE] DATETIME2     NULL,
                    [SOURCE]          NVARCHAR(40)   NULL,
                    CONSTRAINT [PK_dv_global_file_catalog]
                        PRIMARY KEY ([INVENTORY_ID])
                )
            """
        return _orig_table(dialect)

    mod._ddl_create_table = _patched_table

    # Patch the qualified table name helper used in queries
    def _dv_gfc(dialect: str) -> str:
        if dialect == "sqlserver":
            return "[dataview].[dv_global_file_catalog]"
        return "dv_global_file_catalog"

    mod._gfc_table = _dv_gfc

    return mod


# =============================================================================
# PATCH file_inventory_governance constants
# =============================================================================

def _patch_governance():
    import importlib
    mod_name = "modules.file_inventory_governance"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
    else:
        mod = importlib.import_module(mod_name)

    # Map old file_catalog table names to dataview equivalents
    _TABLE_MAP = {
        "INVENTORY_USER":       "dv_inv_user",
        "INVENTORY_GROUP":      "dv_inv_group",
        "INVENTORY_ASSIGNMENT": "dv_inv_assignment",
        "ASSIGNMENT_EXTENSION": "dv_inv_assignment_ext",
        "INVENTORY_GROUP_FILE": "dv_inv_group_file",
    }

    # Override the schema name helper
    _orig_schema_tbl = getattr(mod, "_schema_table", None)

    def _dv_schema_table(name: str) -> str:
        dv_name = _TABLE_MAP.get(name, name.lower())
        return f"dataview.{dv_name}"

    mod._schema_table = _dv_schema_table
    mod.GOVERNANCE_SCHEMA = "dataview"
    mod.TABLE_MAP = _TABLE_MAP

    return mod


# =============================================================================
# VAULT CONFIGURATION
# =============================================================================

VAULT_ROOT = r"C:\Bulk"

VAULT_STRUCTURE = {
    "raw":      r"C:\Bulk\raw",
    "curated":  r"C:\Bulk\curated",
    "enriched": r"C:\Bulk\enriched",
    "archive":  r"C:\Bulk\archive",
}

DOC_TYPE_MAP = {
    # Digital logs
    ".las":  ("Well Logs",   "LAS"),
    ".LAS":  ("Well Logs",   "LAS"),
    ".dlis": ("Well Logs",   "DLIS"),
    ".DLIS": ("Well Logs",   "DLIS"),
    ".lis":  ("Well Logs",   "LIS"),
    ".LIS":  ("Well Logs",   "LIS"),
    # Seismic
    ".sgy":  ("Seismic",     "SEGY"),
    ".segy": ("Seismic",     "SEGY"),
    ".SGY":  ("Seismic",     "SEGY"),
    ".SEGY": ("Seismic",     "SEGY"),
    ".p190": ("Seismic",     "P190"),
    ".P190": ("Seismic",     "P190"),
    # Office
    ".pdf":  ("Documents",   "PDF"),
    ".PDF":  ("Documents",   "PDF"),
    ".xlsx": ("Office",      "EXCEL"),
    ".XLSX": ("Office",      "EXCEL"),
    ".xls":  ("Office",      "EXCEL"),
    ".docx": ("Office",      "WORD"),
    ".DOCX": ("Office",      "WORD"),
    ".doc":  ("Office",      "WORD"),
    # Spatial
    ".shp":  ("Spatial",     "SHP"),
    ".SHP":  ("Spatial",     "SHP"),
    ".geojson": ("Spatial",  "GEOJSON"),
    # Tabular
    ".csv":  ("Tabular",     "CSV"),
    ".CSV":  ("Tabular",     "CSV"),
    ".tsv":  ("Tabular",     "TSV"),
    # Images
    ".tif":  ("Images",      "TIFF"),
    ".tiff": ("Images",      "TIFF"),
    ".jpg":  ("Images",      "JPEG"),
    ".jpeg": ("Images",      "JPEG"),
    ".png":  ("Images",      "PNG"),
}


def get_doc_type(ext: str):
    """Return (doc_type_group, doc_type) for a file extension."""
    return DOC_TYPE_MAP.get(ext, ("Other", "UNKNOWN"))


# =============================================================================
# ENSURE VAULT FOLDER STRUCTURE
# =============================================================================

def ensure_vault(root: str = VAULT_ROOT) -> dict[str, str]:
    """
    Create the vault folder structure under root if it doesn't exist.
    Returns {tier: path} dict.
    Manager can set a different root — default is C:\\Bulk.
    """
    import os
    tiers = ["raw", "curated", "enriched", "archive"]
    result = {}
    for tier in tiers:
        path = os.path.join(root, tier)
        os.makedirs(path, exist_ok=True)
        result[tier] = path
    return result


# =============================================================================
# AUTO-APPLY PATCHES ON IMPORT
# =============================================================================

try:
    _patch_file_inventory()
except Exception as _e:
    import warnings
    warnings.warn(f"dv_catalog_adapter: file_inventory patch failed — {_e}")

try:
    _patch_governance()
except Exception as _e:
    import warnings
    warnings.warn(f"dv_catalog_adapter: governance patch failed — {_e}")

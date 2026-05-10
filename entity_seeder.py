"""
entity_seeder.py
================
Bulk seeds reference tables, dv_business_associate, and dv_field
from well row data, then back-fills operator_ba_id and field_id.

Seed order (respects FK dependencies):
  1. dv_r_source         — source reference table (no FK deps)
  2. dv_r_well_type      — well type codes
  3. dv_r_well_status    — well status codes
  4. dv_business_associate — operators (FK → dv_r_source)
  5. dv_field             — fields (FK → dv_r_source)
  6. Back-fill well rows with operator_ba_id and field_id

Usage:
    from entity_seeder import seed_entities
    rows = seed_entities(rows, engine, source="KGS", loader_tag="KS_KGS_LOADER")
    # rows now have operator_ba_id and field_id populated
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

CHUNK_SIZE = 2000

# All known source values across all translators
ALL_SOURCES = [
    ("RRC",      "RRC",       "Texas Railroad Commission"),
    ("KGS",      "KGS",       "Kansas Geological Survey"),
    ("NDIC",     "NDIC",      "North Dakota Industrial Commission"),
    ("COGCC",    "COGCC",     "Colorado Oil & Gas Conservation Commission"),
    ("IHS",      "IHS",       "IHS Markit"),
    ("ENVERUS",  "ENVERUS",   "Enverus DrillingInfo"),
    ("GIS",      "GIS",       "ESRI Shapefile"),
    ("LAS",      "LAS",       "LAS Well Log"),
    ("PPDM",     "PPDM",      "PPDM Association"),
    ("DATAVIEW", "DataView",  "DataView v3 internal source"),
    ("IMPORT",   "Import",    "Bulk import via pipeline"),
    ("MANUAL",   "Manual",    "Manually entered data"),
    ("BLM_PLSS", "BLM PLSS",  "Bureau of Land Management PLSS"),
    ("BOEM",     "BOEM",      "Bureau of Ocean Energy Management"),
    ("NRCAN",    "NRCan",     "Natural Resources Canada"),
    ("TIGER",    "Census TIGER", "US Census Bureau TIGER/Line"),
    ("GADM",     "GADM",      "Global Administrative Areas"),
]

# Standard well type codes
WELL_TYPES = [
    ("OIL",       "Oil",       "Oil well"),
    ("GAS",       "Gas",       "Gas well"),
    ("WATER",     "Water",     "Water well"),
    ("INJECTION", "Injection", "Injection well"),
    ("DRY_HOLE",  "Dry Hole",  "Dry hole"),
    ("OTHER",     "Other",     "Other well type"),
    ("LOCATION",  "Location",  "Location only — not yet drilled"),
]

# Standard well status codes
WELL_STATUSES = [
    ("ACTIVE",    "Active",    "Well is active and producing"),
    ("PLUGGED",   "Plugged",   "Well has been plugged and abandoned"),
    ("CANCELLED", "Cancelled", "Permit cancelled before drilling"),
    ("LOCATION",  "Location",  "Location permitted — not yet spud"),
    ("UNKNOWN",   "Unknown",   "Status unknown"),
]


def sha1_id(value: str) -> str:
    """40-character SHA1 hex of the UTF-8 encoded value."""
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def seed_entities(
    rows: list[dict],
    engine,
    source: str = "IMPORT",
    loader_tag: str = "ENTITY_SEEDER",
) -> list[dict]:
    """
    Full entity seed pipeline. Call before any dv_well inserts.
    Returns rows with operator_ba_id and field_id back-filled.
    """
    # Step 1 — seed reference tables (no FK deps — always safe first)
    seed_reference_tables(engine, loader_tag)

    # Step 2 — seed operators → dv_business_associate
    rows = _seed_business_associates(rows, engine, source, loader_tag)

    # Step 3 — seed fields → dv_field
    rows = _seed_fields(rows, engine, source, loader_tag)

    return rows


def seed_reference_tables(engine, loader_tag: str = "ENTITY_SEEDER") -> None:
    """
    Seed dv_r_source, dv_r_well_type, dv_r_well_status with all
    known values. Safe to call repeatedly — IF NOT EXISTS on all inserts.
    """
    print("  Seeding reference tables (dv_r_source, dv_r_well_type, dv_r_well_status)...")

    # dv_r_source
    src_sql = """
        IF NOT EXISTS (SELECT 1 FROM dataview.dv_r_source WHERE source = ?)
        INSERT INTO dataview.dv_r_source (
            source, short_name, long_name, active_ind,
            row_created_by, row_created_date, row_changed_by, row_changed_date
        ) VALUES (?, ?, ?, 'Y', ?, GETDATE(), ?, GETDATE())
    """
    src_params = [
        (code, code, short, long, loader_tag, loader_tag)
        for code, short, long in ALL_SOURCES
    ]
    _execute_many(engine, src_sql, src_params)

    # dv_r_well_type
    wt_sql = """
        IF NOT EXISTS (SELECT 1 FROM dataview.dv_r_well_type WHERE well_type = ?)
        INSERT INTO dataview.dv_r_well_type (
            well_type, short_name, long_name, active_ind,
            row_created_by, row_created_date, row_changed_by, row_changed_date
        ) VALUES (?, ?, ?, 'Y', ?, GETDATE(), ?, GETDATE())
    """
    wt_params = [
        (code, code, short, long, loader_tag, loader_tag)
        for code, short, long in WELL_TYPES
    ]
    _execute_many(engine, wt_sql, wt_params)

    # dv_r_well_status
    ws_sql = """
        IF NOT EXISTS (SELECT 1 FROM dataview.dv_r_well_status WHERE well_status = ?)
        INSERT INTO dataview.dv_r_well_status (
            well_status, short_name, long_name, active_ind,
            row_created_by, row_created_date, row_changed_by, row_changed_date
        ) VALUES (?, ?, ?, 'Y', ?, GETDATE(), ?, GETDATE())
    """
    ws_params = [
        (code, code, short, long, loader_tag, loader_tag)
        for code, short, long in WELL_STATUSES
    ]
    _execute_many(engine, ws_sql, ws_params)

    print("  Reference tables seeded.")


# ── Business Associate ────────────────────────────────────────────────

def _seed_business_associates(
    rows: list[dict],
    engine,
    source: str,
    loader_tag: str,
) -> list[dict]:
    op_map: dict[str, str] = {}
    for r in rows:
        name = (r.get("_operator") or "").strip()
        if name and name.lower() not in ("unavailable", "unknown", ""):
            op_map[name] = sha1_id(name)

    if not op_map:
        return rows

    print(f"  Seeding {len(op_map):,} unique operators into dv_business_associate...")
    existing = _fetch_existing_ids(engine, "dataview.dv_business_associate", "ba_id")
    new_ops  = {n: bid for n, bid in op_map.items() if bid not in existing}

    if new_ops:
        sql = """
            IF NOT EXISTS (SELECT 1 FROM dataview.dv_business_associate WHERE ba_id = ?)
            INSERT INTO dataview.dv_business_associate (
                ba_id, ba_type, ba_name, short_name,
                active_ind, source, row_created_by, row_changed_by
            ) VALUES (?, 'COMPANY', ?, ?, 'Y', ?, ?, ?)
        """
        params = [
            (bid, bid, name, name[:40], source, loader_tag, loader_tag)
            for name, bid in new_ops.items()
        ]
        _execute_many(engine, sql, params)
        print(f"  Inserted {len(new_ops):,} new business associates")
    else:
        print(f"  All {len(op_map):,} operators already exist")

    for r in rows:
        name = (r.get("_operator") or "").strip()
        if name and name in op_map:
            r["operator_ba_id"] = op_map[name]

    return rows


# ── Field ─────────────────────────────────────────────────────────────

def _seed_fields(
    rows: list[dict],
    engine,
    source: str,
    loader_tag: str,
) -> list[dict]:
    field_map: dict[str, str] = {}
    for r in rows:
        name = (r.get("_field_name") or "").strip()
        if name and name.lower() not in ("unknown", "wildcat", ""):
            field_map[name] = sha1_id(name)

    if not field_map:
        return rows

    print(f"  Seeding {len(field_map):,} unique fields into dv_field...")
    existing   = _fetch_existing_ids(engine, "dataview.dv_field", "field_id")
    new_fields = {n: fid for n, fid in field_map.items() if fid not in existing}

    if new_fields:
        sql = """
            IF NOT EXISTS (SELECT 1 FROM dataview.dv_field WHERE field_id = ?)
            INSERT INTO dataview.dv_field (
                field_id, field_name, field_type,
                active_ind, source, row_created_by, row_changed_by
            ) VALUES (?, ?, 'OIL', 'Y', ?, ?, ?)
        """
        params = [
            (fid, fid, name, source, loader_tag, loader_tag)
            for name, fid in new_fields.items()
        ]
        _execute_many(engine, sql, params)
        print(f"  Inserted {len(new_fields):,} new fields")
    else:
        print(f"  All {len(field_map):,} fields already exist")

    for r in rows:
        name = (r.get("_field_name") or "").strip()
        if name and name in field_map:
            r["field_id"] = field_map[name]

    return rows


# ── Helpers ───────────────────────────────────────────────────────────

def _fetch_existing_ids(engine, table: str, id_col: str) -> set:
    import pandas as pd
    from sqlalchemy import text
    with engine.connect() as con:
        return set(
            pd.read_sql(text(f"SELECT [{id_col}] FROM {table}"), con)[id_col].tolist()
        )


def _execute_many(engine, sql: str, params: list[tuple]) -> None:
    if not params:
        return
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        cursor.fast_executemany = True
        for i in range(0, len(params), CHUNK_SIZE):
            cursor.executemany(sql, params[i:i+CHUNK_SIZE])
            raw_conn.commit()
        cursor.close()
    except Exception as e:
        raw_conn.rollback()
        print(f"  Entity seed error: {e}")
    finally:
        raw_conn.close()

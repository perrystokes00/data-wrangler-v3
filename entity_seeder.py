"""
entity_seeder.py
================
Bulk seeds reference tables, dv_business_associate, and dv_field
from well row data, then back-fills operator_ba_id and field_id.

** PATCHED 2026-06: ID hashing now delegates to hash_keys.entity_id **
   (UTF-16-LE, UPPER+TRIM, uppercase) so IDs are IDENTICAL to the
   pipeline / fk_entity / SQL Server HASHBYTES recipe. The old local
   sha1_id() (UTF-8, .strip() only, lowercase) produced incompatible
   ba_id/field_id values and orphaned every operator FK when the same
   dv_business_associate was shared with the staging pipeline.

   ⚠ Existing dv_business_associate / dv_field rows written by the OLD
   recipe must be reconciled (re-seeded under the canonical id) or they
   remain orphaned. See reconcile_entity_ids.sql.

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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from hash_keys import entity_id   # canonical: UTF-16-LE, UPPER+TRIM, uppercase

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
    # ── deep-extract document loaders (office/pdf/witsml/dlis) ──
    # These emit their own SOURCE codes; promote FKs into dv_r_source and HOLDS
    # rows on any unseeded code, so they must be seeded here or document data
    # (tops, dir survey, production, completion) parks in the mirror unpromoted.
    ("DATA_LOADER",        "DataLoader",  "Generic tabular data loader"),
    ("OFFICE",             "Office",      "Office document (xlsx/docx/csv)"),
    ("WITSML",             "WITSML",      "WITSML XML"),
    ("DLIS",               "DLIS",        "DLIS log"),
    ("LIS",                "LIS",         "LIS log"),
    ("DIRECTIONAL_SURVEY", "DirSurvey",   "Directional survey document"),
    ("PDF",                "PDF",         "PDF document"),
    ("OSDU",               "OSDU",        "OSDU / JSON well log"),
    ("SHAPEFILE",          "Shapefile",   "ESRI shapefile"),
    ("SEGY",               "SEGY",        "SEG-Y seismic"),
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

    # dv_r_uom — canonical set + any units actually present in the catalog
    _seed_uom(engine, loader_tag)

    print("  Reference tables seeded.")


# ── Unit of Measure ───────────────────────────────────────────────────
# Canonical UOM codes seen across KGS/vendor LAS headers. Messy variants
# (FT/FEET/F, OHM-M/OHMM, GAPI/api) are all seeded as-is so promote never
# holds a curve on the curve_unit/depth_ouom FK; normalization to canonical
# units is a separate data-quality task.
CANON_UOM = [
    "FT", "FEET", "F", "M", "IN", "INCH",
    "GAPI", "API", "NAPI", "API-N", "API-GR",
    "OHM-M", "OHMM", "OHM", "OHM/M", "M.OHM", "MMHO", "MMHO/M", "MMHO-M",
    "G/CC", "G/C3", "GM/CC", "KG/M3", "K/M3", "B/CM3",
    "US/F", "US/FT", "USEC", "USEC/FT", "USPF", "US", "SEC", "MSEC", "MS", "S",
    "MV", "V", "V/V", "PU", "DEC", "DECP", "DEC(LS)", "FRAC", "PERC", "PERCENT",
    "%", "PPM", "CPS", "LB", "LBS", "LBF", "PSI", "DEG", "DEGF", "DIM",
    "BARN", "BARN/E", "B/E", "CU", "C/C", "CFCF", "FT3", "F3", "FT3/FT3",
    "FT/MIN", "FT/HR", "F/HR", "FPM", "MD", "MIN/FT", "MINUTES", "NONE",
    "UNITS", "POROSITY", "DELT-CPS", "SC/S", "----",
    # ── deep-extract document loader units (case-sensitive FK, seed both cases) ──
    # tops loader writes depth_ouom='ft' (lowercase); dir-survey 'FT'; production
    # BBL/MCF; office 0.1 in. Seed the exact strings the loaders emit so promote
    # never holds a document row on the depth_ouom/volume_ouom/rate_ouom FK.
    "ft", "m", "in", "0.1 in", "BBL", "bbl", "MCF", "mcf", "FT3", "ft3",
    "M3", "m3", "BBL/D", "MCF/D", "STB/D", "gAPI", "gapi", "degC", "kPa",
    "g", "g/cm3", "m/h", "M/HR", "mS/m", "mV", "ohm.m", "1/s", "c/min", "deg",
]

def _seed_uom(engine, loader_tag: str = "ENTITY_SEEDER") -> None:
    """Seed dv_r_uom with the canonical set plus any distinct curve_unit /
    depth_ouom already present in the catalog. Also ensure dv_r_source has 'LAS'."""
    print("  Seeding dv_r_uom (+ ensuring dv_r_source has LAS)...")

    # collect codes: canonical + whatever the loaded catalog actually carries
    codes = {c.strip() for c in CANON_UOM if c and c.strip()}
    try:
        with engine.connect() as con:
            from sqlalchemy import text as _t
            for q in (
                "SELECT DISTINCT curve_unit FROM file_catalog.cat_well_log_curve WHERE curve_unit IS NOT NULL",
                "SELECT DISTINCT depth_ouom FROM file_catalog.cat_well_log_curve WHERE depth_ouom IS NOT NULL",
                "SELECT DISTINCT depth_ouom FROM file_catalog.cat_well_log WHERE depth_ouom IS NOT NULL",
                # deep-extract document tables — their units must be seeded too
                "SELECT DISTINCT depth_ouom FROM file_catalog.cat_well_formation_top WHERE depth_ouom IS NOT NULL",
                "SELECT DISTINCT depth_ouom FROM file_catalog.cat_well_dir_srvy_sta WHERE depth_ouom IS NOT NULL",
                "SELECT DISTINCT volume_ouom FROM file_catalog.cat_prod_volume WHERE volume_ouom IS NOT NULL",
                "SELECT DISTINCT rate_ouom FROM file_catalog.cat_prod_volume WHERE rate_ouom IS NOT NULL",
            ):
                for r in con.execute(_t(q)):
                    v = (r[0] or "").strip() if isinstance(r[0], str) else r[0]
                    if v:
                        codes.add(str(v))
    except Exception as e:
        print(f"    (catalog UOM scan skipped: {str(e)[:60]})")

    uom_sql = """
        IF NOT EXISTS (SELECT 1 FROM dataview.dv_r_uom WHERE uom_code = ?)
        INSERT INTO dataview.dv_r_uom (
            uom_code, unit_of_measure, uom_description, active_ind,
            row_created_by, row_created_date, row_changed_by, row_changed_date
        ) VALUES (?, ?, ?, 'Y', ?, GETDATE(), ?, GETDATE())
    """
    uom_params = [(c, c, c, c, loader_tag, loader_tag) for c in sorted(codes)]
    _execute_many(engine, uom_sql, uom_params)

    # ensure LAS source exists (curves carry source='LAS')
    las_sql = """
        IF NOT EXISTS (SELECT 1 FROM dataview.dv_r_source WHERE source = ?)
        INSERT INTO dataview.dv_r_source (
            source, short_name, long_name, active_ind,
            row_created_by, row_created_date, row_changed_by, row_changed_date
        ) VALUES (?, ?, ?, 'Y', ?, GETDATE(), ?, GETDATE())
    """
    _execute_many(engine, las_sql, [("LAS", "LAS", "LAS well log", "LAS", loader_tag, loader_tag)])
    print(f"  dv_r_uom seeded ({len(uom_params)} codes).")


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
            bid = entity_id(name)          # canonical id
            if bid:
                op_map[name] = bid

    if not op_map:
        return rows

    print(f"  Seeding {len(op_map):,} unique operators into dv_business_associate...")
    existing = _fetch_existing_ids(engine, "dataview.dv_business_associate", "ba_id")
    # existing ids may be stored upper/lower from older runs — compare upper
    existing_upper = {str(e).upper() for e in existing}
    new_ops  = {n: bid for n, bid in op_map.items() if bid.upper() not in existing_upper}

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
            fid = entity_id(name)          # canonical id
            if fid:
                field_map[name] = fid

    if not field_map:
        return rows

    print(f"  Seeding {len(field_map):,} unique fields into dv_field...")
    existing   = _fetch_existing_ids(engine, "dataview.dv_field", "field_id")
    existing_upper = {str(e).upper() for e in existing}
    new_fields = {n: fid for n, fid in field_map.items() if fid.upper() not in existing_upper}

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

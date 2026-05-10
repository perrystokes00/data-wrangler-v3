"""
dv_standards_seed.py
====================
DataView v3 — Idempotent reference table seeder.

Call seed_all_standards(engine) at loader startup (before any dv_well inserts).
Each table is only touched if it has zero rows — safe to call repeatedly.

Tables seeded:
  dv_r_source       — data source codes
  dv_r_well_type    — canonical well type codes
  dv_r_well_status  — canonical well status codes
  dv_r_uom          — units of measure
"""
from __future__ import annotations

from sqlalchemy import text

# ── Canonical reference data ──────────────────────────────────────────

SOURCES = [
    ("RRC",       "RRC",          "Texas Railroad Commission"),
    ("KGS",       "KGS",          "Kansas Geological Survey"),
    ("NDIC",      "NDIC",         "North Dakota Industrial Commission"),
    ("COGCC",     "COGCC",        "Colorado Oil & Gas Conservation Commission"),
    ("IHS",       "IHS",          "IHS Markit"),
    ("ENVERUS",   "ENVERUS",      "Enverus DrillingInfo"),
    ("GIS",       "GIS",          "ESRI Shapefile"),
    ("LAS",       "LAS",          "LAS Well Log"),
    ("PPDM",      "PPDM",         "PPDM Association"),
    ("DATAVIEW",  "DataView",     "DataView v3 internal source"),
    ("IMPORT",    "Import",       "Bulk import via pipeline"),
    ("MANUAL",    "Manual",       "Manually entered data"),
    ("BLM_PLSS",  "BLM PLSS",    "Bureau of Land Management PLSS"),
    ("BOEM",      "BOEM",         "Bureau of Ocean Energy Management"),
    ("NRCAN",     "NRCan",        "Natural Resources Canada"),
    ("TIGER",     "Census TIGER", "US Census Bureau TIGER/Line"),
    ("GADM",      "GADM",         "Global Administrative Areas"),
]

# (well_type, short_name, long_name)
WELL_TYPES = [
    ("OIL",         "Oil",          "Oil producer"),
    ("GAS",         "Gas",          "Gas producer"),
    ("OIL_GAS",     "Oil/Gas",      "Oil and gas producer"),
    ("WATER",       "Water",        "Water well"),
    ("INJECTION",   "Injection",    "Injection well"),
    ("WATER_INJ",   "Water Inj",    "Water injection well"),
    ("WATER_DISP",  "Water Disp",   "Water disposal well"),
    ("DRY_HOLE",    "Dry Hole",     "Dry hole — no commercial production"),
    ("CBM",         "CBM",          "Coalbed methane well"),
    ("GEOTHERMAL",  "Geothermal",   "Geothermal well"),
    ("STRATIGRAPHIC","Strat",       "Stratigraphic test"),
    ("SERVICE",     "Service",      "Service well"),
    ("OBSERVATION", "Observation",  "Observation / monitor well"),
    ("LOCATION",    "Location",     "Location permitted — not yet spud"),
    ("OTHER",       "Other",        "Other / unclassified"),
    ("UNKNOWN",     "Unknown",      "Well type unknown"),
]

# (well_status, short_name, long_name)
WELL_STATUSES = [
    ("ACTIVE",               "Active",    "Well is active and producing"),
    ("SHUT_IN",              "Shut In",   "Well temporarily shut in"),
    ("PLUGGED_AND_ABANDONED","P&A",       "Well plugged and abandoned"),
    ("PLUGGED",              "Plugged",   "Well plugged — not yet abandoned"),
    ("ABANDONED",            "Abandoned", "Well abandoned without plugging"),
    ("DRILLING",    "Drilling",     "Well currently being drilled"),
    ("COMPLETING",  "Completing",   "Well in completion phase"),
    ("INJECTION",   "Injection",    "Active injection well"),
    ("LOCATION",    "Location",     "Location only — not yet spud"),
    ("CANCELLED",   "Cancelled",    "Permit cancelled before spud"),
    ("EXPIRED",     "Expired",      "Permit expired"),
    ("WORKOVER",    "Workover",     "Well undergoing workover"),
    ("PRODUCING",   "Producing",    "Well producing — synonym for ACTIVE"),
    ("INACTIVE",    "Inactive",     "Well inactive"),
    ("UNKNOWN",     "Unknown",      "Status unknown"),
]

# (uom_code, short_name, long_name, quantity_type)
UOMS = [
    ("FT",    "ft",    "Feet",               "LENGTH"),
    ("M",     "m",     "Metres",             "LENGTH"),
    ("BOPD",  "bopd",  "Barrels oil per day","RATE"),
    ("BWPD",  "bwpd",  "Barrels water/day",  "RATE"),
    ("MCFD",  "mcfd",  "Mcf per day",        "RATE"),
    ("MMCFD", "mmcfd", "MMcf per day",       "RATE"),
    ("PSI",   "psi",   "Pounds per sq inch", "PRESSURE"),
    ("KPA",   "kPa",   "Kilopascals",        "PRESSURE"),
    ("DEG_F", "°F",    "Degrees Fahrenheit", "TEMPERATURE"),
    ("DEG_C", "°C",    "Degrees Celsius",    "TEMPERATURE"),
    ("BBL",   "bbl",   "Barrels",            "VOLUME"),
    ("MCF",   "mcf",   "Thousand cubic feet","VOLUME"),
    ("MMCF",  "mmcf",  "Million cubic feet", "VOLUME"),
]


# ── Seed functions ────────────────────────────────────────────────────

def _count(conn, table: str) -> int:
    row = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
    return row[0] if row else 0


def seed_sources(engine) -> int:
    """Seed dv_r_source. Returns rows inserted."""
    with engine.begin() as conn:
        if _count(conn, "dataview.dv_r_source") > 0:
            return 0
        inserted = 0
        for source, short_name, long_name in SOURCES:
            conn.execute(text("""
                INSERT INTO dataview.dv_r_source
                    (source, short_name, long_name, active_ind,
                     row_created_by, row_created_date,
                     row_changed_by, row_changed_date)
                VALUES
                    (:source, :short, :long, 'Y',
                     'SYSTEM', GETDATE(), 'SYSTEM', GETDATE())
            """), {"source": source, "short": short_name, "long": long_name})
            inserted += 1
        return inserted


def seed_well_types(engine) -> int:
    """Seed dv_r_well_type. Returns rows inserted."""
    with engine.begin() as conn:
        if _count(conn, "dataview.dv_r_well_type") > 0:
            return 0
        inserted = 0
        for well_type, short_name, long_name in WELL_TYPES:
            conn.execute(text("""
                INSERT INTO dataview.dv_r_well_type
                    (well_type, short_name, long_name, active_ind,
                     row_created_by, row_created_date,
                     row_changed_by, row_changed_date)
                VALUES
                    (:wt, :short, :long, 'Y',
                     'SYSTEM', GETDATE(), 'SYSTEM', GETDATE())
            """), {"wt": well_type, "short": short_name, "long": long_name})
            inserted += 1
        return inserted


def seed_well_statuses(engine) -> int:
    """Seed dv_r_well_status. Returns rows inserted."""
    with engine.begin() as conn:
        if _count(conn, "dataview.dv_r_well_status") > 0:
            return 0
        inserted = 0
        for well_status, short_name, long_name in WELL_STATUSES:
            conn.execute(text("""
                INSERT INTO dataview.dv_r_well_status
                    (well_status, short_name, long_name, active_ind,
                     row_created_by, row_created_date,
                     row_changed_by, row_changed_date)
                VALUES
                    (:ws, :short, :long, 'Y',
                     'SYSTEM', GETDATE(), 'SYSTEM', GETDATE())
            """), {"ws": well_status, "short": short_name, "long": long_name})
            inserted += 1
        return inserted


def seed_uoms(engine) -> int:
    """Seed dv_r_uom. Returns rows inserted."""
    with engine.begin() as conn:
        if _count(conn, "dataview.dv_r_uom") > 0:
            return 0
        inserted = 0
        for uom_code, short_name, long_name, qty_type in UOMS:
            conn.execute(text("""
                INSERT INTO dataview.dv_r_uom
                    (uom_code, short_name, long_name, quantity_type, active_ind,
                     row_created_by, row_created_date,
                     row_changed_by, row_changed_date)
                VALUES
                    (:uom, :short, :long, :qty, 'Y',
                     'SYSTEM', GETDATE(), 'SYSTEM', GETDATE())
            """), {"uom": uom_code, "short": short_name,
                   "long": long_name, "qty": qty_type})
            inserted += 1
        return inserted


def seed_all_standards(engine, verbose: bool = False) -> dict:
    """
    Idempotently seed all reference tables.
    Call this at loader startup before any dv_well inserts.

    Returns dict of {table_name: rows_inserted}.
    Tables with existing rows are skipped (returns 0).
    """
    results = {}

    results["dv_r_source"]      = seed_sources(engine)
    results["dv_r_well_type"]   = seed_well_types(engine)
    results["dv_r_well_status"] = seed_well_statuses(engine)
    results["dv_r_uom"]         = seed_uoms(engine)

    if verbose:
        for tbl, n in results.items():
            if n > 0:
                print(f"  ✓ Seeded {tbl}: {n} rows")
            else:
                print(f"  — {tbl}: already populated, skipped")

    return results


# ── KGS composite STATUS parser ──────────────────────────────────────────────
# KGS STATUS codes encode both well type and operational status in one field.
# Patterns:
#   BASE           → well active, type = BASE
#   BASE-P&A       → well plugged, type = BASE
#   BASE(subtype)  → active, type refined by subtype
#   BASE-P&A(sub)  → plugged, type refined by subtype
#   D&A            → dry hole, abandoned
#   LOC / INTENT   → location, not yet drilled

import re as _re

_KGS_BASE_TYPE: dict[str, str] = {
    "OIL":     "OIL",
    "GAS":     "GAS",
    "O&G":     "OIL_GAS",
    "EOR":     "INJECTION",
    "SWD":     "WATER_DISP",
    "INJ":     "INJECTION",
    "CBM":     "CBM",
    "SERVICE": "SERVICE",
    "D&A":     "DRY_HOLE",
    "LOC":     "LOCATION",
    "INTENT":  "LOCATION",
    "OTHER":   "OTHER",
}

_KGS_SUBTYPE_TYPE: dict[str, str] = {
    "STRAT":                "STRATIGRAPHIC",
    "WATER":                "WATER",
    "GAS-INJ":              "INJECTION",
    "OBS":                  "OBSERVATION",
    "GSW":                  "INJECTION",
    "INJ OR EOR":           "INJECTION",
    "INJ":                  "INJECTION",
    "OIL&GAS-INJ":          "INJECTION",
    "TA":                   "OTHER",
    "CATH":                 "SERVICE",
    "LH":                   "OTHER",
    "GAS-STG":              "OTHER",
    "SWD-P&A":              "WATER_DISP",
    "1O&1SWD":              "OTHER",
    "CLASS1":               "INJECTION",
    "CLASS ONE (OLD)":      "INJECTION",
    "SHUT-IN":              "OTHER",
    "GAS":                  "GAS",
    "OIL/GAS":              "OIL_GAS",
    "HY":                   "OTHER",
    "ABD LOC":              "LOCATION",
    "GAS INJ":              "INJECTION",
    "2OIL":                 "OIL",
    "2 OIL":                "OIL",
    "GAS SHUT-IN":          "GAS",
    "HELIUM":               "OTHER",
    "SERVICE":              "SERVICE",
    "PLUGGED":              "OTHER",
    "UNKNOWN":              "OTHER",
    "OIL&GAS-INJ":          "INJECTION",
}

def _parse_kgs_composite(raw: str) -> tuple[str, str]:
    """
    Parse a KGS composite STATUS value into (well_type, well_status).
    Returns canonical codes matching dv_r_well_type / dv_r_well_status.
    """
    s = raw.strip().upper()

    is_pa = "-P&A" in s
    s_clean = s.replace("-P&A", "")

    m = _re.match(r'^([^(]+)\(([^)]*)\)$', s_clean)
    if m:
        base    = m.group(1).strip()
        subtype = m.group(2).strip()
    else:
        base    = s_clean.strip("()").strip()
        subtype = ""

    # Resolve well_type
    well_type = _KGS_BASE_TYPE.get(base, "OTHER")
    if well_type == "OTHER" and subtype:
        well_type = _KGS_SUBTYPE_TYPE.get(subtype, "OTHER")

    # Resolve well_status
    if is_pa:
        well_status = "PLUGGED_AND_ABANDONED"
    elif base == "D&A":
        well_status = "PLUGGED_AND_ABANDONED"
    elif base in ("LOC", "INTENT"):
        well_status = "LOCATION"
    elif subtype in ("TA", "SHUT-IN"):
        well_status = "SHUT_IN"
    elif subtype == "GAS SHUT-IN":
        well_status = "SHUT_IN"
    elif subtype == "ABD LOC":
        well_status = "PLUGGED_AND_ABANDONED"
    elif subtype == "PLUGGED":
        well_status = "PLUGGED_AND_ABANDONED"
    else:
        well_status = "ACTIVE"

    return well_type, well_status


def map_well_type(raw: str | None) -> str | None:
    """Translate a raw KGS STATUS string to a canonical dv_r_well_type code."""
    if not raw or not raw.strip():
        return None
    well_type, _ = _parse_kgs_composite(raw)
    return well_type


def map_well_status(raw: str | None) -> str | None:
    """Translate a raw KGS STATUS string to a canonical dv_r_well_status code."""
    if not raw or not raw.strip():
        return None
    _, well_status = _parse_kgs_composite(raw)
    return well_status


def map_kgs_status(raw: str | None) -> tuple[str | None, str | None]:
    """
    Parse a KGS STATUS value into (well_type, well_status) in one call.
    Use this in the KGS translator when STATUS is the only type/status field.
    """
    if not raw or not raw.strip():
        return None, None
    return _parse_kgs_composite(raw)

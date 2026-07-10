"""
translators/ks_kgs_well_header.py
===================================
Translator for Kansas Geological Survey well header CSV files.

Download: https://www.kgs.ku.edu/Magellan/WellLogs/

Dirty data handled:
  - API_NUM_NODASH in scientific notation (1.5007E+13) — forced to string
  - Operator names with embedded commas in quoted fields
  - ELEVATION column contains value + datum e.g. "1782, KB"
  - STATUS codes are compound e.g. "OIL-P&A", "SWD-P&A"
  - Lines with >43 cols due to unescaped commas in COMMENTS field
  - Dates in DD-Mon-YY format e.g. "21-Oct-57"
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dw_utils import parse_date, clean, null_if_empty, uwi_from_api, audit_row

SOURCE      = "KGS"
LOADER_TAG  = "KS_KGS_LOADER"
STATE_FIPS  = "20"          # Kansas
PROVINCE    = "KS"
COUNTRY     = "US"

# KGS STATUS → well_type, well_status
STATUS_MAP = {
    "OIL":                   ("OIL",       "ACTIVE"),
    "GAS":                   ("GAS",       "ACTIVE"),
    "SWD":                   ("WATER",     "ACTIVE"),
    "EOR":                   ("INJECTION", "ACTIVE"),
    "LOC":                   ("OIL",       "LOCATION"),
    "O&G":                   ("OIL",       "ACTIVE"),
    "D&A":                   ("DRY_HOLE",  "PLUGGED"),
    "OIL-P&A":               ("OIL",       "PLUGGED"),
    "GAS-P&A":               ("GAS",       "PLUGGED"),
    "SWD-P&A":               ("WATER",     "PLUGGED"),
    "EOR-P&A":               ("INJECTION", "PLUGGED"),
    "O&G-P&A":               ("OIL",       "PLUGGED"),
    "OTHER-P&A(STRAT)":      ("OTHER",     "PLUGGED"),
    "OTHER-P&A(LH)":         ("OTHER",     "PLUGGED"),
    "OTHER-P&A(TA)":         ("OTHER",     "PLUGGED"),
    "OTHER-P&A(INJ or EOR)": ("INJECTION", "PLUGGED"),
    "OTHER(TA)":              ("OTHER",     "ACTIVE"),
}

# Columns to force-read as string (prevent scientific notation)
STRING_COLS = {"API_NUMBER", "API_NUM_NODASH", "KID", "OIL_KID", "GAS_KID",
               "OIL_DOR_ID", "GAS_DOR_ID"}

# Output columns for dv_well insert — matches actual dv_well schema
DV_WELL_COLS = [
    "uwi", "well_name", "well_type", "well_status",
    "province_state", "country", "county",
    "operator_ba_id", "field_id",
    "final_td", "depth_datum",
    "spud_date", "completion_date", "api_num",
    "surface_latitude", "surface_longitude",
    "active_ind", "source", "remark",
    "row_created_by", "row_changed_by",
]


# ── Inbound ───────────────────────────────────────────────────────────

def read(file_path: str, limit: int | None = None) -> tuple[list[dict], list[str]]:
    """
    Parse a KGS well header CSV file.
    Returns (rows, errors) where rows are dicts keyed by dv_well field names.
    """
    rows   = []
    errors = []
    path   = Path(file_path)

    print(f"Parsing {path.name} ({path.stat().st_size / 1024 / 1024:.1f} MB)...")

    with open(file_path, encoding="latin-1", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for i, raw in enumerate(reader):
            if limit and i >= limit:
                break
            try:
                row = _map_row(raw, i + 2)
                if row:
                    rows.append(row)
            except Exception as e:
                errors.append(f"Row {i+2}: {e}")

    print(f"Parsed {len(rows):,} rows, {len(errors)} errors")
    return rows, errors


def _map_row(raw: dict, line_num: int) -> dict | None:
    # Force string columns
    for col in STRING_COLS:
        if col in raw:
            raw[col] = str(raw[col]).strip()

    api_raw = raw.get("API_NUMBER", "").strip()
    uwi     = uwi_from_api(api_raw, state_fips=STATE_FIPS)
    if not uwi:
        return None

    # Well name = LEASE + WELL
    lease = clean(raw.get("LEASE", ""))
    well  = clean(raw.get("WELL", ""))
    well_name = f"{lease} {well}".strip() or "UNKNOWN"

    # Operator
    operator = null_if_empty(clean(raw.get("CURR_OPERATOR", "")))
    if not operator:
        operator = null_if_empty(clean(raw.get("ORIG_OPERATOR", "")))

    # Elevation — split "1782, KB" → value + datum
    elev_raw = raw.get("ELEVATION", "").strip()
    elev_val = None
    elev_datum = None
    if elev_raw:
        m = re.match(r"^([\d.\-]+)\s*,?\s*([A-Z]{2,3})?$", elev_raw)
        if m:
            try:
                elev_val = float(m.group(1))
            except ValueError:
                pass
            elev_datum = m.group(2) if m.group(2) else raw.get("ELEV_REF", "").strip() or "KB"
        else:
            elev_datum = raw.get("ELEV_REF", "").strip() or "KB"

    # Depth
    depth_raw = raw.get("DEPTH", "").strip()
    final_td  = None
    if depth_raw:
        try:
            final_td = int(float(depth_raw))
        except ValueError:
            pass

    # Coordinates
    lat = lon = None
    try:
        lat = float(raw.get("LATITUDE", ""))
        lon = float(raw.get("LONGITUDE", ""))
    except (ValueError, TypeError):
        pass

    # Dates
    spud   = parse_date(raw.get("SPUD", ""))
    compl  = parse_date(raw.get("COMPLETION", ""))
    plug   = parse_date(raw.get("PLUGGING", ""))
    permit = parse_date(raw.get("PERMIT", ""))

    # Status → well_type + well_status
    status_raw = raw.get("STATUS", "").strip()
    well_type, well_status = STATUS_MAP.get(status_raw, ("OIL", "UNKNOWN"))

    # County
    county = null_if_empty(clean(raw.get("COUNTY", ""))) or ""

    # API number formatted
    api_num = api_raw

    # Remark
    remark = null_if_empty(clean(raw.get("COMMENTS", "")))
    if remark and len(remark) > 2000:
        remark = remark[:1997] + "..."

    # Build remark from operator + field + formation info
    field_nm   = null_if_empty(clean(raw.get("FIELD", "")))
    formation  = null_if_empty(clean(raw.get("FORMATION_AT_TOTAL_DEPTH", "")))
    remark_parts = []
    if operator:          remark_parts.append(f"Operator: {operator[:60]}")
    if field_nm:          remark_parts.append(f"Field: {field_nm[:60]}")
    if formation:         remark_parts.append(f"Formation: {formation[:40]}")
    if remark:            remark_parts.append(remark[:200])
    full_remark = " | ".join(remark_parts)[:2000] or None

    return {
        "uwi":               uwi,
        "well_name":         well_name[:80],
        "well_type":         well_type,
        "well_status":       well_status,
        "province_state":    PROVINCE,
        "country":           COUNTRY,
        "county":            county[:50],
        "final_td":          final_td,
        "depth_datum":       elev_datum or "KB",
        "spud_date":         spud,
        "completion_date":   compl,
        "api_num":           api_num[:40],
        "surface_latitude":  lat,
        "surface_longitude": lon,
        "active_ind":        "Y" if well_status == "ACTIVE" else "N",
        "source":            SOURCE,
        "remark":            full_remark,
        "row_created_by":    LOADER_TAG,
        "row_changed_by":    LOADER_TAG,
        # Extra fields for downstream use (not inserted to dv_well)
        "_operator":         operator,
        "_field_name":       field_nm,
        "_status_raw":       status_raw,
        "_plug_date":        plug,
        "_permit_date":      permit,
    }


# ── Outbound ──────────────────────────────────────────────────────────

OUTBOUND_MAP = {
    "API_NUMBER":    "api_num",
    "LEASE":         "well_name",
    "FIELD":         "field_name",
    "LATITUDE":      "surface_latitude",
    "LONGITUDE":     "surface_longitude",
    "CURR_OPERATOR": "operator_name",
    "DEPTH":         "final_td",
    "SPUD":          "spud_date",
    "COMPLETION":    "completion_date",
    "PLUGGING":      "plug_date",
    "STATUS":        "well_status",
    "COMMENTS":      "_remark",
}


def write(rows: list[dict], output_path: str) -> int:
    """Write dv_well rows to KGS-compatible CSV."""
    if not rows:
        return 0
    headers = list(OUTBOUND_MAP.keys())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            out = {out_col: r.get(dv_field, "") for out_col, dv_field in OUTBOUND_MAP.items()}
            writer.writerow(out)
    print(f"Wrote {len(rows):,} rows to {output_path}")
    return len(rows)

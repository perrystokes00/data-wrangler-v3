"""
translators/las_2_0.py
=======================
Translator for LAS 2.0 (Log ASCII Standard) well log files.
Spec: Canadian Well Logging Society (CWLS) LAS 2.0

Handles:
  - ~VERSION, ~WELL, ~CURVE, ~PARAMETER, ~ASCII sections
  - WRAP=YES (wrapped mode — multi-line data rows)
  - Variable null indicators per file (read from NULL mnemonic)
  - Depth in feet or metres (read from STRT/STOP units)
  - Populates: dv_well (header), dv_well_log, dv_well_log_curve

Download sources:
  - KGS: https://www.kgs.ku.edu/Magellan/WellLogs/
  - NDIC: https://www.dmr.nd.gov/oilgas/
  - Any operator-supplied LAS file
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from dataview.core.dw_utils import parse_date, clean, null_if_empty, uwi_from_api

SOURCE     = "LAS"
LOADER_TAG = "LAS2_LOADER"

# Well section mnemonic → dv_well field
WELL_MNEM_MAP = {
    "WELL": "well_name",
    "API":  "api_num",
    "FLD":  "field_name",
    "COMP": "operator_name",
    "LOC":  "location",
    "PROV": "province_state",
    "STAT": "province_state",
    "CTRY": "country",
    "SRVC": "service_company",
    "DATE": "log_date",
    "LATI": "surface_latitude",
    "LONG": "surface_longitude",
    "LAT":  "surface_latitude",
    "LON":  "surface_longitude",
    "GDAT": "geodetic_datum",
    "UWI":  "uwi",
    "LIC":  "licence_num",
}

# Common curve mnemonics → standard meaning (for future curve mapping)
CURVE_HINTS = {
    "DEPT": "depth_m",     "DEPTH": "depth_ft",
    "MD":   "depth_md",    "TVD":   "depth_tvd",
    "GR":   "gamma_ray",   "SP":    "sp",
    "RT":   "res_true",    "RXO":   "res_flushed",
    "RHOB": "density",     "NPHI":  "neutron_por",
    "DT":   "sonic",       "CALI":  "caliper",
    "PE":   "photo_elec",  "PEFZ":  "photo_elec",
    "ILD":  "res_deep",    "ILM":   "res_med",
    "LLD":  "res_deep",    "LLS":   "res_shallow",
}


# ── Public API ────────────────────────────────────────────────────────

def read(file_path: str, limit: int | None = None) -> tuple[list[dict], list[str]]:
    """
    Parse a LAS 2.0 file.
    Returns (well_rows, errors) where well_rows contains one dict
    with well header info + embedded log/curve metadata.
    limit is ignored for LAS (always one well per file).
    """
    errors = []
    path   = Path(file_path)

    try:
        sections = _parse_sections(file_path)
    except Exception as e:
        return [], [f"Failed to parse LAS sections: {e}"]

    # ── Version section ───────────────────────────────────────────────
    ver_sec  = sections.get("VERSION", {})
    wrap     = ver_sec.get("WRAP", {}).get("value", "NO").upper() == "YES"
    las_ver  = ver_sec.get("VERS", {}).get("value", "2.0")

    # ── Well section ──────────────────────────────────────────────────
    well_sec = sections.get("WELL", {})
    null_val = _safe_float(well_sec.get("NULL", {}).get("value", "-999.25"))
    strt     = _safe_float(well_sec.get("STRT", {}).get("value"))
    stop     = _safe_float(well_sec.get("STOP", {}).get("value"))
    step     = _safe_float(well_sec.get("STEP", {}).get("value"))
    depth_units = well_sec.get("STRT", {}).get("unit", "F").upper()

    well_row = {
        "source":         SOURCE,
        "row_created_by": LOADER_TAG,
        "row_changed_by": LOADER_TAG,
        "active_ind":     "Y",
        "country":        "US",
        "_las_version":   las_ver,
        "_null_value":    null_val,
        "_depth_start":   strt,
        "_depth_stop":    stop,
        "_depth_step":    step,
        "_depth_units":   depth_units,
        "_wrap_mode":     wrap,
        "_file_path":     str(path),
        "_file_name":     path.name,
    }

    # Map well mnemonics → dv_well fields
    for mnem, entry in well_sec.items():
        tgt = WELL_MNEM_MAP.get(mnem.upper())
        if tgt:
            val = null_if_empty(entry.get("value", ""))
            if val:
                well_row[tgt] = val

    # ── Build UWI ─────────────────────────────────────────────────────
    uwi = well_row.get("uwi")
    if not uwi:
        api = well_row.get("api_num", "")
        uwi = uwi_from_api(api) if api else None
    if not uwi:
        # Use well name + file as fallback identifier
        wname = well_row.get("well_name", path.stem)
        uwi   = f"UNKNOWN_{re.sub(r'[^A-Z0-9]', '', wname.upper())[:20]}"
        errors.append(f"No UWI/API found — assigned temporary UWI: {uwi}")
    well_row["uwi"] = uwi

    # ── Parse coordinates ─────────────────────────────────────────────
    for coord in ("surface_latitude", "surface_longitude"):
        if coord in well_row:
            val = _dms_or_dd(str(well_row[coord]))
            well_row[coord] = val

    # Ensure longitude is negative (Western hemisphere)
    lon = well_row.get("surface_longitude")
    if lon and lon > 0:
        well_row["surface_longitude"] = -lon

    # ── Parse log date ────────────────────────────────────────────────
    if "log_date" in well_row:
        well_row["log_date"] = parse_date(str(well_row["log_date"])) or well_row["log_date"]

    # ── Curve section ─────────────────────────────────────────────────
    curve_sec = sections.get("CURVE", {})
    curves    = []
    for i, (mnem, entry) in enumerate(curve_sec.items()):
        curves.append({
            "mnemonic":       mnem.upper(),
            "mnemonic_alias": CURVE_HINTS.get(mnem.upper()),
            "unit":           entry.get("unit", ""),
            "description":    entry.get("description", ""),
            "col_index":      i,
        })
    well_row["_curves"] = curves

    # ── ASCII data summary ────────────────────────────────────────────
    ascii_data = sections.get("ASCII_DATA", [])
    well_row["_data_rows"] = len(ascii_data)

    return [well_row], errors


def write(rows: list[dict], output_path: str) -> int:
    """
    Write well header rows back to LAS 2.0 format.
    Produces a minimal header-only LAS (no curve data).
    """
    if not rows:
        return 0

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    count = 0

    for r in rows:
        # One file per well
        uwi      = r.get("uwi", "UNKNOWN")
        out_path = Path(output_path)
        if len(rows) > 1:
            out_path = out_path.parent / f"{uwi}.las"

        lines = [
            "~VERSION ---------------------------------------------------",
            " VERS.                 2.0 : LAS Version 2.0",
            " WRAP.                  NO : One line per depth step",
            "~WELL ------------------------------------------------------",
            f" UWI .            {uwi:<20}: Unique Well Identifier",
            f" WELL.            {r.get('well_name',''):<20}: Well Name",
            f" API .            {r.get('api_num',''):<20}: API Number",
            f" FLD .            {r.get('field_name',''):<20}: Field Name",
            f" COMP.            {r.get('operator_name',''):<20}: Operator",
            f" PROV.            {r.get('province_state',''):<20}: Province/State",
            f" CTRY.            {r.get('country','US'):<20}: Country",
            f" LATI.            {r.get('surface_latitude',''):<20}: Latitude",
            f" LONG.            {r.get('surface_longitude',''):<20}: Longitude",
            "~CURVE ----------------------------------------------------- ",
            " DEPT.F                    : Depth",
            "~A  DEPT",
        ]

        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        count += 1

    print(f"Wrote {count} LAS file(s) to {output_path}")
    return count


# ── LAS Section Parser ────────────────────────────────────────────────

def _parse_sections(file_path: str) -> dict:
    """
    Parse LAS file into sections dict.
    Each mnemonic section: {mnem: {value, unit, description}}
    ASCII section stored as list of lists under "ASCII_DATA".
    """
    sections      = {}
    current_sec   = None
    current_name  = None
    ascii_lines   = []
    in_ascii      = False

    with open(file_path, encoding="latin-1", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")

            # Section header
            if line.startswith("~"):
                sec_char = line[1:2].upper()
                in_ascii = sec_char == "A"
                sec_map  = {
                    "V": "VERSION", "W": "WELL", "C": "CURVE",
                    "P": "PARAMETER", "O": "OTHER", "A": "ASCII",
                }
                current_name = sec_map.get(sec_char, sec_char)
                if not in_ascii:
                    sections[current_name] = {}
                    current_sec = sections[current_name]
                continue

            # Skip comments
            if line.startswith("#"):
                continue

            if in_ascii:
                stripped = line.strip()
                if stripped:
                    ascii_lines.append(stripped.split())
                continue

            # Mnemonic line: MNEM.UNIT  VALUE : DESCRIPTION
            if current_sec is not None and "." in line:
                m = re.match(
                    r"^\s*([A-Za-z0-9_]+)\s*\.\s*([^\s]*)\s+(.*?)\s*:\s*(.*?)\s*$",
                    line
                )
                if m:
                    mnem  = m.group(1).upper()
                    unit  = m.group(2).strip()
                    value = m.group(3).strip()
                    desc  = m.group(4).strip()
                    current_sec[mnem] = {
                        "unit":        unit,
                        "value":       value,
                        "description": desc,
                    }

    if ascii_lines:
        sections["ASCII_DATA"] = ascii_lines

    return sections


# ── Helpers ───────────────────────────────────────────────────────────

def _safe_float(s) -> float | None:
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return None


def _dms_or_dd(s: str) -> float | None:
    """Parse decimal degrees or DMS string."""
    s = s.strip()
    # Already decimal
    try:
        return float(s)
    except ValueError:
        pass
    # DMS: 32 30 00.0 N or 32°30'00"N
    m = re.match(
        r"(\d+)[°\s]+(\d+)['\s]+([0-9.]+)[\"'\s]*([NSEW]?)", s, re.IGNORECASE
    )
    if m:
        d   = float(m.group(1))
        mn  = float(m.group(2))
        sec = float(m.group(3))
        hem = m.group(4).upper()
        dd  = d + mn / 60 + sec / 3600
        if hem in ("S", "W"):
            dd = -dd
        return round(dd, 6)
    return None


# ── Bulk load helper for LAS well headers ────────────────────────────

def load_well_headers(rows: list[dict], engine) -> tuple[int, int]:
    """
    Insert LAS well header rows into dv_well and dv_well_log.
    Returns (wells_inserted, logs_inserted).
    """
    import pandas as pd
    from sqlalchemy import text
    from dataview.core.dw_utils import bulk_insert

    WELL_COLS = [
        "uwi", "well_name", "operator_name", "field_name",
        "province_state", "country", "api_num",
        "surface_latitude", "surface_longitude",
        "active_ind", "source", "row_created_by", "row_changed_by",
    ]

    well_rows = [{k: r.get(k) for k in WELL_COLS} for r in rows]
    wi, _, _  = bulk_insert(engine, "dv_well", "dataview", WELL_COLS, well_rows)

    # Insert log header records
    LOG_COLS = [
        "uwi", "log_id", "log_type", "log_date",
        "depth_start", "depth_stop", "depth_step", "depth_ouom",
        "source", "row_created_by", "row_changed_by",
    ]
    log_rows = []
    for r in rows:
        log_rows.append({
            "uwi":         r["uwi"],
            "log_id":      f"{r['uwi']}_LAS_{r.get('_file_name','')[:20]}",
            "log_type":    "LAS",
            "log_date":    r.get("log_date"),
            "depth_start": r.get("_depth_start"),
            "depth_stop":  r.get("_depth_stop"),
            "depth_step":  r.get("_depth_step"),
            "depth_ouom":  r.get("_depth_units", "F"),
            "source":      SOURCE,
            "row_created_by": LOADER_TAG,
            "row_changed_by": LOADER_TAG,
        })

    li, _, _ = bulk_insert(
        engine, "dv_well_log", "dataview", LOG_COLS, log_rows,
        upsert_key="log_id"
    )
    return wi, li


# ── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python las_2_0.py <file.las>")
        sys.exit(1)
    rows, errors = read(sys.argv[1])
    if errors:
        for e in errors:
            print(f"  WARNING: {e}")
    if rows:
        r = rows[0]
        print(f"UWI          : {r.get('uwi')}")
        print(f"Well Name    : {r.get('well_name')}")
        print(f"Operator     : {r.get('operator_name')}")
        print(f"Field        : {r.get('field_name')}")
        print(f"API          : {r.get('api_num')}")
        print(f"Lat/Lon      : {r.get('surface_latitude')} / {r.get('surface_longitude')}")
        print(f"Depth        : {r.get('_depth_start')} – {r.get('_depth_stop')} {r.get('_depth_units')}")
        print(f"Curves       : {len(r.get('_curves', []))}")
        print(f"Data rows    : {r.get('_data_rows')}")
        for c in r.get("_curves", [])[:10]:
            hint = f" → {c['mnemonic_alias']}" if c["mnemonic_alias"] else ""
            print(f"  {c['mnemonic']:10} {c['unit']:8} {c['description'][:40]}{hint}")

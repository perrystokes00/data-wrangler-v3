"""
translators/tx_rrc_w1_permit.py
================================
Translator for Texas RRC W-1 Drilling Permit file.

Extracts lat/lon from record type 14 and updates existing dv_well rows.
Load tx_rrc_well_master first — this translator only enriches, never inserts.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dw_utils import bulk_update

SOURCE     = "RRC"
LOADER_TAG = "TX_RRC_W1_PERMIT"


def read(file_path: str, limit: int | None = None) -> tuple[list[dict], list[str]]:
    """
    Parse W-1 file, extract lat/lon from record type 14.
    Returns rows with uwi, surface_latitude, surface_longitude.
    """
    path   = Path(file_path)
    rows   = []
    errors = []

    print(f"Parsing {path.name} ({path.stat().st_size / 1024 / 1024:.1f} MB)...")

    with open(file_path, encoding="latin-1", errors="replace") as f:
        for i, line in enumerate(f):
            if limit and len(rows) >= limit:
                break
            line = line.rstrip("\n")
            if not line.startswith("14:"):
                continue
            try:
                # Record 14 format: 14:API:LAT:LON (approximate — adjust if needed)
                parts = line.split(":")
                if len(parts) < 4:
                    continue
                api_raw = parts[1].strip()
                lat_raw = parts[2].strip()
                lon_raw = parts[3].strip()

                lat = _dms_to_dd(lat_raw) or _safe_float(lat_raw)
                lon = _dms_to_dd(lon_raw) or _safe_float(lon_raw)

                if lat is None or lon is None:
                    continue
                # Ensure lon is negative (West)
                if lon and lon > 0:
                    lon = -lon

                # Build UWI from API
                digits = re.sub(r"[^0-9]", "", api_raw)
                if len(digits) < 10:
                    continue
                uwi = f"US{digits[:2]}{digits[2:5]}{digits[5:10]}{digits[10:12].zfill(2) if len(digits)>=12 else '00'}0000"

                rows.append({
                    "uwi":               uwi,
                    "surface_latitude":  lat,
                    "surface_longitude": lon,
                    "source":            SOURCE,
                    "row_changed_by":    LOADER_TAG,
                })
            except Exception as e:
                errors.append(f"Line {i+1}: {e}")

    print(f"Parsed {len(rows):,} coordinate records, {len(errors)} errors")
    return rows, errors


def enrich(rows: list[dict], engine) -> int:
    """
    Update surface_latitude / surface_longitude on existing dv_well rows.
    This is the primary use — not a standard insert.
    """
    if not rows:
        return 0
    updated = bulk_update(
        engine, "dv_well", "dataview",
        ["surface_latitude", "surface_longitude"],
        "uwi", rows, loader_tag=LOADER_TAG,
    )
    print(f"Enriched {updated:,} wells with coordinates")
    return updated


def _dms_to_dd(s: str) -> float | None:
    """Convert DMS string (DDMMSS or DD-MM-SS) to decimal degrees."""
    s = s.strip().replace("-", "").replace(" ", "")
    if len(s) == 6 and s.isdigit():
        d = int(s[0:2])
        m = int(s[2:4])
        sec = int(s[4:6])
        return round(d + m / 60 + sec / 3600, 6)
    return None


def _safe_float(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def write(rows: list[dict], output_path: str) -> int:
    """W-1 is inbound-only."""
    raise NotImplementedError("W-1 is inbound only — no outbound format defined")

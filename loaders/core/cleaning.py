"""
loaders/core/cleaning.py — Shared cleaning utilities for source plugins.

All plugins should use these for consistency. If a plugin needs different
behavior (e.g. a source-specific date format), it can define its own
cleaner and use these as the basis.
"""

from __future__ import annotations

import re
from datetime import datetime


# -----------------------------------------------------------------------------
# Canonical column order for dataview.dv_well
# -----------------------------------------------------------------------------
# This is the list of columns the runner will write to dv_well, in order.
# Plugins populate a subset; missing columns become NULL.
#
# Keep this in sync with the dv_well DDL. The runner uses this as the
# authoritative column order for the dv_well staging CSV.
DV_WELL_COLUMNS = [
    "uwi",
    "well_name",
    "well_num",
    "operator_ba_id",
    "field_id",
    "well_type",
    "well_status",
    "country",
    "province_state",
    "county",
    "legal_survey_type",
    "surface_latitude",
    "surface_longitude",
    "ground_elevation",
    "kb_elevation",
    "spud_date",
    "completion_date",
    "final_td",
    "depth_datum",
    "epsg_code",
    "api_num",
    "license_num",
    "lease_name",
    "onshore_offshore_ind",
    "active_ind",
    "remark",
    "row_created_by",
    "row_created_date",
    "row_changed_by",
    "row_changed_date",
    "source",
    "abandonment_date",
    "bottom_hole_latitude",
    "bottom_hole_longitude",
    "current_operator_ba_id",
    "original_operator_ba_id",
    "elevation_ouom",
    "formation_at_td",
    "long_lat_source",
    "permit_number",
    "producing_formation",
    "area",
    "operator_name",
    "field_name",
    "protraction_area",
    "h3_r4",
    "h3_r5",
    "h3_r6",
    "h3_r7",
    "h3_coord_hash",
]


# Canonical column order for dataview.dv_well_identifier
DV_IDENTIFIER_COLUMNS = [
    "well_id",
    "identifier_type",
    "identifier_value",
    "source_system",
    "loaded_date",
    "is_primary",
]


# -----------------------------------------------------------------------------
# Text cleaning
# -----------------------------------------------------------------------------
_NULL_LITERALS = {"", "unavailable", "unknown", "n/a", "na", "null", "none"}


def clean_text(s: str | None, maxlen: int | None = None) -> str | None:
    """
    Normalize a text value:
      - None / empty / 'unavailable'/'unknown'/etc → None
      - Strip leading/trailing whitespace
      - Replace embedded \\r\\n / \\n / \\r / \\t with space
      - Collapse runs of whitespace
      - Replace pipe with space (BCP field delimiter safety)
      - Truncate to maxlen if specified

    This is what every plugin should use for free-text cleaning so the
    BCP transport stays robust.
    """
    if s is None:
        return None
    s = s.strip()
    if not s or s.lower() in _NULL_LITERALS:
        return None

    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = s.replace("|", " ")

    if maxlen and len(s) > maxlen:
        s = s[:maxlen]

    return s.strip() or None


def parse_float(s: str | None) -> float | None:
    """Parse a numeric field; return None on missing or invalid."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_int(s: str | None) -> int | None:
    """Parse an integer field; return None on missing or invalid."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


# -----------------------------------------------------------------------------
# Date parsing — sources have wildly different conventions
# -----------------------------------------------------------------------------
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def parse_kgs_date(s: str | None) -> str | None:
    """
    Parse KGS date strings → ISO 'YYYY-MM-DD'.

    KGS publishes two formats over the years:
      - 4-digit year: '01-MAY-1964'  (current convention, most rows)
      - 2-digit year: '01-MAY-64'    (legacy; YY <= 30 → 20YY else 19YY)

    Examples:
      '01-MAY-1964'  → '1964-05-01'
      '01-Apr-69'    → '1969-04-01'
      '15-Mar-25'    → '2025-03-15'
      ''             → None
      'bogus'        → None
    """
    if not s or not str(s).strip():
        return None
    parts = str(s).strip().split("-")
    if len(parts) != 3:
        return None
    try:
        day = int(parts[0])
        mon = _MONTH_MAP.get(parts[1].upper()[:3])
        if mon is None:
            return None
        y = int(parts[2])
        # 4-digit year passes through, 2-digit year uses the 1931-2030 window
        if y >= 100:
            year = y
        else:
            year = 2000 + y if y <= 30 else 1900 + y
        d = datetime(year, mon, day)
        return d.strftime("%Y-%m-%d")
    except (ValueError, IndexError):
        return None


def parse_iso_date(s: str | None) -> str | None:
    """Parse ISO 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'. Returns ISO date."""
    if not s or not str(s).strip():
        return None
    s = str(s).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

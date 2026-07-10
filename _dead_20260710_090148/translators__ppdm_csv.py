"""
translators/ppdm_csv.py
========================
Translator for PPDM 3.9 CSV exports.

Column names map 1:1 to DataView schema — direct passthrough with
minimal transformation. Used for migrating data between PPDM systems
or importing exports from other PPDM-compliant applications.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dw_utils import parse_date, clean, null_if_empty

SOURCE     = "PPDM"
LOADER_TAG = "PPDM_CSV_LOADER"

# PPDM 3.9 well column → dv_well field (direct where names differ)
FIELD_MAP = {
    "UWI":              "uwi",
    "WELL_NAME":        "well_name",
    "WELL_NUM":         "well_num",
    "WELL_TYPE":        "well_type",
    "WELL_STATUS":      "well_status",
    "PROVINCE_STATE":   "province_state",
    "COUNTRY":          "country",
    "COUNTY":           "county",
    "OPERATOR_BA_ID":   "operator_name",   # may be ID or name depending on export
    "FIELD_ID":         "field_name",
    "FINAL_TD":         "final_td",
    "DEPTH_DATUM":      "depth_datum",
    "SPUD_DATE":        "spud_date",
    "COMPLETION_DATE":  "completion_date",
    "API_NUM":          "api_num",
    "SURFACE_LATITUDE": "surface_latitude",
    "SURFACE_LONGITUDE":"surface_longitude",
    "ACTIVE_IND":       "active_ind",
    "SOURCE":           "source",
    "REMARK":           "remark",
    "ROW_CREATED_BY":   "row_created_by",
    "ROW_CREATED_DATE": "row_created_date",
    "ROW_CHANGED_BY":   "row_changed_by",
    "ROW_CHANGED_DATE": "row_changed_date",
}

DATE_COLS = {"spud_date", "completion_date", "row_created_date", "row_changed_date"}
FLOAT_COLS = {"surface_latitude", "surface_longitude", "final_td"}


def read(file_path: str, limit: int | None = None) -> tuple[list[dict], list[str]]:
    """Parse PPDM 3.9 CSV — direct column passthrough."""
    rows   = []
    errors = []

    with open(file_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for i, raw in enumerate(reader):
            if limit and i >= limit:
                break
            try:
                row = {}
                for src_col, tgt_field in FIELD_MAP.items():
                    val = null_if_empty(raw.get(src_col, "").strip())
                    if val is None:
                        continue
                    if tgt_field in DATE_COLS:
                        val = parse_date(val) or val
                    elif tgt_field in FLOAT_COLS:
                        val = _sf(val)
                    row[tgt_field] = val

                if not row.get("uwi"):
                    errors.append(f"Row {i+2}: no UWI")
                    continue

                # Ensure required fields
                row.setdefault("source",         SOURCE)
                row.setdefault("active_ind",     "Y")
                row.setdefault("row_created_by", LOADER_TAG)
                row.setdefault("row_changed_by", LOADER_TAG)
                rows.append(row)

            except Exception as e:
                errors.append(f"Row {i+2}: {e}")

    print(f"Parsed {len(rows):,} PPDM rows, {len(errors)} errors")
    return rows, errors


def write(rows: list[dict], output_path: str) -> int:
    """Write dv_well rows to PPDM 3.9 CSV format."""
    if not rows:
        return 0

    # Reverse the field map
    rev_map  = {v: k for k, v in FIELD_MAP.items()}
    headers  = list(FIELD_MAP.keys())

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            out = {ppdm_col: r.get(dv_field, "")
                   for ppdm_col, dv_field in FIELD_MAP.items()}
            writer.writerow(out)

    print(f"Wrote {len(rows):,} rows to {output_path}")
    return len(rows)


def _sf(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None

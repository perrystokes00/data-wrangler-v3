"""
translators/nd_ndic_well_header.py
====================================
Tier 2 stub — North Dakota Industrial Commission well header.
ML column mapper completes this on first real file.
Download: https://www.dmr.nd.gov/oilgas/
"""
from __future__ import annotations
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dw_utils import parse_date, clean, null_if_empty, uwi_from_api

SOURCE     = "NDIC"
LOADER_TAG = "ND_NDIC_LOADER"
STATE_FIPS = "38"   # North Dakota

# Field hints for ML mapper — update after first confirmed load
FIELD_HINTS = {
    "File No":          "well_id",
    "API":              "api_num",
    "Well Name":        "well_name",
    "Latitude":         "surface_latitude",
    "Longitude":        "surface_longitude",
    "Current Operator": "operator_name",
    "Spud Date":        "spud_date",
    "Completion Date":  "completion_date",
    "Status":           "well_status",
    "Field":            "field_name",
    "Total Depth":      "final_td",
    "County":           "county",
}


def read(file_path: str, limit: int | None = None) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    with open(file_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for i, raw in enumerate(reader):
            if limit and i >= limit:
                break
            try:
                api = raw.get("API", raw.get("APINum", "")).strip()
                uwi = uwi_from_api(api, STATE_FIPS)
                if not uwi:
                    continue
                rows.append({
                    "uwi":             uwi,
                    "well_name":       clean(raw.get("Well Name", raw.get("WellName", "")))[:80],
                    "operator_name":   clean(raw.get("Current Operator", raw.get("Operator", "")))[:80],
                    "field_name":      clean(raw.get("Field", ""))[:80],
                    "county":          clean(raw.get("County", ""))[:50],
                    "surface_latitude": _safe_float(raw.get("Latitude")),
                    "surface_longitude":_safe_float(raw.get("Longitude")),
                    "spud_date":       parse_date(raw.get("Spud Date", "")),
                    "completion_date": parse_date(raw.get("Completion Date", "")),
                    "well_status":     clean(raw.get("Status", "UNKNOWN"))[:40],
                    "well_type":       "OIL",
                    "province_state":  "ND",
                    "country":         "US",
                    "api_num":         api[:40],
                    "active_ind":      "Y",
                    "source":          SOURCE,
                    "row_created_by":  LOADER_TAG,
                    "row_changed_by":  LOADER_TAG,
                })
            except Exception as e:
                errors.append(f"Row {i+2}: {e}")
    return rows, errors


def write(rows: list[dict], output_path: str) -> int:
    headers = ["uwi","api_num","well_name","operator_name","field_name",
               "county","surface_latitude","surface_longitude",
               "spud_date","completion_date","well_status","source"]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def _safe_float(s):
    try: return float(s)
    except: return None

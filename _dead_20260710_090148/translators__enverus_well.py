"""
translators/enverus_well.py
=============================
Tier 2 stub — Enverus / DrillingInfo well header export.
"""
from __future__ import annotations
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dw_utils import parse_date, clean, uwi_from_api

SOURCE     = "ENVERUS"
LOADER_TAG = "ENVERUS_LOADER"

FIELD_HINTS = {
    "API14":                "api_num",
    "Well Name":            "well_name",
    "Operator":             "operator_name",
    "Spud Date":            "spud_date",
    "Completion Date":      "completion_date",
    "Producing Formation":  "produce_formation",
    "Latitude (WGS84)":     "surface_latitude",
    "Longitude (WGS84)":    "surface_longitude",
    "Field Name":           "field_name",
    "County":               "county",
    "State":                "province_state",
    "Total Depth (ft)":     "final_td",
    "Well Type":            "well_type",
    "Well Status":          "well_status",
}

STATE_FIPS_MAP = {
    "TX":"42","KS":"20","ND":"38","CO":"08","WY":"56",
    "OK":"40","NM":"35","MT":"30","LA":"22",
}


def read(file_path: str, limit: int | None = None) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    with open(file_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for i, raw in enumerate(reader):
            if limit and i >= limit:
                break
            try:
                api = raw.get("API14", raw.get("API", "")).strip()
                state_abbr = clean(raw.get("State", "")).upper()
                fips = STATE_FIPS_MAP.get(state_abbr, "00")
                uwi  = uwi_from_api(api, fips)
                if not uwi:
                    continue
                td = None
                try: td = int(float(raw.get("Total Depth (ft)", "") or 0)) or None
                except: pass
                rows.append({
                    "uwi":              uwi,
                    "well_name":        clean(raw.get("Well Name", ""))[:80],
                    "operator_name":    clean(raw.get("Operator", ""))[:80],
                    "field_name":       clean(raw.get("Field Name", ""))[:80],
                    "county":           clean(raw.get("County", ""))[:50],
                    "province_state":   state_abbr[:40],
                    "country":          "US",
                    "surface_latitude": _sf(raw.get("Latitude (WGS84)")),
                    "surface_longitude":_sf(raw.get("Longitude (WGS84)")),
                    "spud_date":        parse_date(raw.get("Spud Date", "")),
                    "completion_date":  parse_date(raw.get("Completion Date", "")),
                    "well_type":        clean(raw.get("Well Type", "OIL"))[:40],
                    "well_status":      clean(raw.get("Well Status", "UNKNOWN"))[:40],
                    "final_td":         td,
                    "api_num":          api[:40],
                    "active_ind":       "Y",
                    "source":           SOURCE,
                    "row_created_by":   LOADER_TAG,
                    "row_changed_by":   LOADER_TAG,
                })
            except Exception as e:
                errors.append(f"Row {i+2}: {e}")
    return rows, errors


def write(rows, output_path):
    headers = ["uwi","api_num","well_name","operator_name","field_name",
               "county","province_state","surface_latitude","surface_longitude",
               "spud_date","completion_date","well_type","well_status","source"]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    return len(rows)

def _sf(s):
    try: return float(s)
    except: return None

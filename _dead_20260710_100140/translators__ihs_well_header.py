"""
translators/ihs_well_header.py
================================
Tier 2 stub — IHS Markit / Enerdeq well header export.
"""
from __future__ import annotations
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dw_utils import parse_date, clean, uwi_from_api

SOURCE     = "IHS"
LOADER_TAG = "IHS_LOADER"

FIELD_HINTS = {
    "UWI":                "uwi",
    "Well Name":          "well_name",
    "Operator Name":      "operator_name",
    "Spud Date":          "spud_date",
    "Completion Date":    "completion_date",
    "Formation":          "formation",
    "Total Depth":        "final_td",
    "Producing Formation":"produce_formation",
    "Latitude":           "surface_latitude",
    "Longitude":          "surface_longitude",
    "Field Name":         "field_name",
    "County":             "county",
    "State":              "province_state",
}

STATE_FIPS_MAP = {
    "TX":"42","KS":"20","ND":"38","CO":"08","WY":"56",
    "OK":"40","NM":"35","MT":"30","LA":"22","PA":"42",
}


def read(file_path: str, limit: int | None = None) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    with open(file_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for i, raw in enumerate(reader):
            if limit and i >= limit:
                break
            try:
                uwi_raw = raw.get("UWI", "").strip()
                uwi = uwi_raw if uwi_raw.startswith("US") else uwi_from_api(
                    raw.get("API", uwi_raw),
                    STATE_FIPS_MAP.get(raw.get("State", "").strip().upper(), "00")
                )
                if not uwi:
                    continue
                td = None
                try: td = int(float(raw.get("Total Depth", "") or 0)) or None
                except: pass
                rows.append({
                    "uwi":              uwi,
                    "well_name":        clean(raw.get("Well Name", ""))[:80],
                    "operator_name":    clean(raw.get("Operator Name", ""))[:80],
                    "field_name":       clean(raw.get("Field Name", ""))[:80],
                    "county":           clean(raw.get("County", ""))[:50],
                    "province_state":   clean(raw.get("State", ""))[:40],
                    "country":          "US",
                    "surface_latitude": _sf(raw.get("Latitude")),
                    "surface_longitude":_sf(raw.get("Longitude")),
                    "spud_date":        parse_date(raw.get("Spud Date", "")),
                    "completion_date":  parse_date(raw.get("Completion Date", "")),
                    "well_status":      clean(raw.get("Well Status", "UNKNOWN"))[:40],
                    "well_type":        clean(raw.get("Well Type", "OIL"))[:40],
                    "final_td":         td,
                    "active_ind":       "Y",
                    "source":           SOURCE,
                    "row_created_by":   LOADER_TAG,
                    "row_changed_by":   LOADER_TAG,
                })
            except Exception as e:
                errors.append(f"Row {i+2}: {e}")
    return rows, errors


def write(rows, output_path):
    headers = ["uwi","well_name","operator_name","field_name","county",
               "province_state","surface_latitude","surface_longitude",
               "spud_date","completion_date","well_status","well_type","source"]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    return len(rows)

def _sf(s):
    try: return float(s)
    except: return None

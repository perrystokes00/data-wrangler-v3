"""
translators/co_cogcc_well.py
==============================
Tier 2 stub — Colorado Oil & Gas Conservation Commission.
Download: https://ecmc.state.co.us/
"""
from __future__ import annotations
import csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dw_utils import parse_date, clean, uwi_from_api

SOURCE     = "COGCC"
LOADER_TAG = "CO_COGCC_LOADER"
STATE_FIPS = "08"   # Colorado

FIELD_HINTS = {
    "APINum":      "api_num",
    "WellName":    "well_name",
    "Operator":    "operator_name",
    "Latitude":    "surface_latitude",
    "Longitude":   "surface_longitude",
    "SpudDate":    "spud_date",
    "WellStatus":  "well_status",
    "County":      "county",
    "Field":       "field_name",
    "TotalDepth":  "final_td",
}


def read(file_path: str, limit: int | None = None) -> tuple[list[dict], list[str]]:
    rows, errors = [], []
    with open(file_path, encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for i, raw in enumerate(reader):
            if limit and i >= limit:
                break
            try:
                api = raw.get("APINum", raw.get("API", "")).strip()
                uwi = uwi_from_api(api, STATE_FIPS)
                if not uwi:
                    continue
                td = None
                try: td = int(float(raw.get("TotalDepth", "") or 0)) or None
                except: pass
                rows.append({
                    "uwi":              uwi,
                    "well_name":        clean(raw.get("WellName", ""))[:80],
                    "operator_name":    clean(raw.get("Operator", ""))[:80],
                    "field_name":       clean(raw.get("Field", ""))[:80],
                    "county":           clean(raw.get("County", ""))[:50],
                    "surface_latitude": _sf(raw.get("Latitude")),
                    "surface_longitude":_sf(raw.get("Longitude")),
                    "spud_date":        parse_date(raw.get("SpudDate", "")),
                    "completion_date":  parse_date(raw.get("CompletionDate", "")),
                    "well_status":      clean(raw.get("WellStatus", "UNKNOWN"))[:40],
                    "well_type":        "OIL",
                    "final_td":         td,
                    "province_state":   "CO",
                    "country":          "US",
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
               "county","surface_latitude","surface_longitude",
               "spud_date","completion_date","well_status","source"]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    return len(rows)

def _sf(s):
    try: return float(s)
    except: return None

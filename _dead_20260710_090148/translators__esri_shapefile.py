"""
translators/esri_shapefile.py
==============================
Translator for ESRI Shapefile well point layers.

Requires: pip install geopandas pyproj

Handles:
  - Any CRS — reprojects to WGS84 (EPSG:4326) automatically
  - DBF column names truncated to 10 chars — ML-assisted mapping
  - Point geometry → surface_latitude / surface_longitude
  - Polygon geometry → centroid coordinates

Inbound: .shp → dv_well rows
Outbound: dv_well rows → .shp point layer
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dw_utils import parse_date, clean, null_if_empty, uwi_from_api

SOURCE     = "GIS"
LOADER_TAG = "SHP_LOADER"

# Common shapefile DBF column names (10-char truncated) → dv_well fields
# These cover the most common well point layer schemas
FIELD_MAP_HINTS = {
    # API / UWI
    "API":          "api_num",    "API_NUM":    "api_num",
    "API14":        "api_num",    "UWI":        "uwi",
    "API_NUMBER":   "api_num",    "APINUM":     "api_num",
    # Well identity
    "WELL_NAME":    "well_name",  "WELLNAME":   "well_name",
    "WELL_NM":      "well_name",  "NAME":       "well_name",
    "LEASE_NAME":   "well_name",  "LEASENAME":  "well_name",
    # Operator
    "OPERATOR":     "operator_name", "OPER":    "operator_name",
    "CURR_OPER":    "operator_name", "OPERATR":  "operator_name",
    "COMPANY":      "operator_name",
    # Field
    "FIELD":        "field_name", "FIELD_NM":   "field_name",
    "FIELDNAME":    "field_name", "FLD_NAME":   "field_name",
    # Location
    "COUNTY":       "county",     "COUNTY_NM":  "county",
    "STATE":        "province_state", "PROV":   "province_state",
    "COUNTRY":      "country",
    # Status / type
    "STATUS":       "well_status", "WELL_STAT": "well_status",
    "WELL_TYPE":    "well_type",   "WELLTYPE":  "well_type",
    "TYPE":         "well_type",
    # Depth / dates
    "TOTAL_DEPT":   "final_td",   "TD":         "final_td",
    "DEPTH":        "final_td",   "TOTAL_D":    "final_td",
    "SPUD_DATE":    "spud_date",  "SPUD":       "spud_date",
    "COMP_DATE":    "completion_date", "COMPL":  "completion_date",
}

# Output fields for shapefile export
EXPORT_FIELDS = [
    "uwi", "well_name", "operator_name", "field_name",
    "well_type", "well_status", "county", "province_state",
    "spud_date", "completion_date", "final_td", "api_num", "source",
]


def read(file_path: str, limit: int | None = None) -> tuple[list[dict], list[str]]:
    """
    Read a shapefile and return dv_well row dicts.
    Reprojects to WGS84 and extracts point coordinates.
    """
    errors = []
    try:
        import geopandas as gpd
    except ImportError:
        return [], ["geopandas not installed — pip install geopandas pyproj"]

    try:
        gdf = gpd.read_file(file_path)
    except Exception as e:
        return [], [f"Failed to read shapefile: {e}"]

    # Reproject to WGS84
    try:
        gdf = gdf.to_crs("EPSG:4326")
    except Exception as e:
        errors.append(f"CRS reprojection warning: {e}")

    if limit:
        gdf = gdf.head(limit)

    rows = []
    for idx, rec in gdf.iterrows():
        try:
            row = _map_record(rec, errors)
            if row:
                rows.append(row)
        except Exception as e:
            errors.append(f"Record {idx}: {e}")

    print(f"Read {len(rows):,} shapefile records, {len(errors)} errors")
    return rows, errors


def _map_record(rec, errors: list) -> dict | None:
    """Map a single GeoDataFrame record to a dv_well dict."""
    # Extract coordinates from geometry
    geom = rec.get("geometry")
    lat = lon = None
    if geom is not None:
        try:
            if geom.geom_type == "Point":
                lon, lat = geom.x, geom.y
            elif geom.geom_type in ("Polygon", "MultiPolygon"):
                centroid = geom.centroid
                lon, lat = centroid.x, centroid.y
        except Exception:
            pass

    # Map DBF columns to dv_well fields
    out = {}
    for col in rec.index:
        if col == "geometry":
            continue
        col_up = str(col).upper().strip()
        tgt    = FIELD_MAP_HINTS.get(col_up)
        if tgt:
            val = null_if_empty(str(rec[col]).strip() if rec[col] is not None else "")
            if val:
                out[tgt] = val

    out["surface_latitude"]  = lat
    out["surface_longitude"] = lon

    # Build UWI
    uwi = out.get("uwi")
    if not uwi:
        api = out.get("api_num", "")
        uwi = uwi_from_api(api) if api else None
    if not uwi:
        errors.append(f"No UWI/API for record — skipped")
        return None
    out["uwi"] = uwi

    # Parse dates
    for dc in ("spud_date", "completion_date"):
        if dc in out:
            out[dc] = parse_date(str(out[dc])) or None

    # Numeric
    for nc in ("final_td",):
        if nc in out:
            try:
                out[nc] = int(float(out[nc]))
            except (ValueError, TypeError):
                out[nc] = None

    out.setdefault("source",         SOURCE)
    out.setdefault("active_ind",     "Y")
    out.setdefault("country",        "US")
    out.setdefault("well_type",      "OIL")
    out.setdefault("row_created_by", LOADER_TAG)
    out.setdefault("row_changed_by", LOADER_TAG)
    return out


def write(rows: list[dict], output_path: str) -> int:
    """
    Write dv_well rows to an ESRI Shapefile point layer.
    Output CRS: WGS84 (EPSG:4326).
    """
    if not rows:
        return 0
    try:
        import geopandas as gpd
        from shapely.geometry import Point
        import pandas as pd
    except ImportError:
        raise ImportError("pip install geopandas shapely")

    valid = [r for r in rows
             if r.get("surface_latitude") and r.get("surface_longitude")]
    if not valid:
        print("No rows with coordinates — nothing to write")
        return 0

    records   = [{f: r.get(f, "") for f in EXPORT_FIELDS} for r in valid]
    geometry  = [Point(r["surface_longitude"], r["surface_latitude"]) for r in valid]
    gdf       = gpd.GeoDataFrame(records, geometry=geometry, crs="EPSG:4326")

    # Truncate column names to 10 chars for DBF compatibility
    gdf.columns = [c[:10] if c != "geometry" else c for c in gdf.columns]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(output_path)
    print(f"Wrote {len(valid):,} point features to {output_path}")
    return len(valid)

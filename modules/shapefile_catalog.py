"""
modules/shapefile_catalog.py
============================
Shapefile inventory, classification, column mapping and PPDM loading.

Supports:
  - .shp (ESRI Shapefile)
  - .geojson / .json
  - .gpkg (GeoPackage)
  - .kml (Google KML)

Pipeline:
  1. scan_directory()     → find all spatial files
  2. classify_shapefile() → detect feature type + PPDM target
  3. map_columns()        → match attributes to PPDM columns
  4. normalize_crs()      → convert to WGS84
  5. load_to_ppdm()       → insert into PPDM target table
"""
from __future__ import annotations
import os, re, uuid, json
from pathlib import Path
from typing import Optional

# ── Feature type constants ────────────────────────────────────────────────────
FT_WELL        = "WELL"
FT_FIELD       = "FIELD"
FT_LEASE       = "LEASE"
FT_SEISMIC_2D  = "SEISMIC_2D"
FT_SEISMIC_3D  = "SEISMIC_3D"
FT_PIPELINE    = "PIPELINE"
FT_FACILITY    = "FACILITY"
FT_BOUNDARY    = "BOUNDARY"
FT_OTHER       = "OTHER"
FT_REVIEW      = "REVIEW_REQUIRED"

# PPDM target tables per feature type
PPDM_TARGETS = {
    FT_WELL:       "dbo.WELL",
    FT_FIELD:      "dbo.FIELD",
    FT_LEASE:      "dbo.LAND_TRACT",
    FT_SEISMIC_2D: "dbo.SEIS_LINE",
    FT_SEISMIC_3D: "dbo.SEIS_SET",
    FT_PIPELINE:   "dbo.FACILITY",
    FT_FACILITY:   "dbo.FACILITY",
    FT_BOUNDARY:   None,
    FT_OTHER:      None,
    FT_REVIEW:     None,
}

SUPPORTED_EXTENSIONS = {'.shp', '.geojson', '.json', '.gpkg', '.kml'}

# ── Column matching patterns ──────────────────────────────────────────────────
COLUMN_PATTERNS = {
    "UWI": [
        r"^uwi$", r"^api$", r"^api_num$", r"^api14$", r"^api10$",
        r"^well_id$", r"^wellid$", r"^apinum$", r"^api_no$",
    ],
    "WELL_NAME": [
        r"^well_?name$", r"^wellnm$", r"^well_nm$", r"^w_name$",
        r"^name$", r"^well$", r"^borehole$",
    ],
    "OPERATOR": [
        r"^operator$", r"^oprtr$", r"^oprtr_nm$", r"^op$",
        r"^company$", r"^owner$", r"^lessee$",
    ],
    "LATITUDE": [
        r"^lat$", r"^latitude$", r"^lat_dd$", r"^y_?coord$",
        r"^y$", r"^lat_wgs84$", r"^surf_lat$",
    ],
    "LONGITUDE": [
        r"^lon$", r"^long$", r"^longitude$", r"^long_dd$",
        r"^x_?coord$", r"^x$", r"^lon_wgs84$", r"^surf_lon$",
    ],
    "FIELD_NAME": [
        r"^field$", r"^field_?name$", r"^fieldnm$", r"^fld_name$",
        r"^reservoir$", r"^pool$",
    ],
    "COUNTY": [
        r"^county$", r"^cnty$", r"^county_?name$", r"^cnty_nm$",
    ],
    "STATE": [
        r"^state$", r"^st$", r"^state_?cd$", r"^province$",
    ],
    "COUNTRY": [
        r"^country$", r"^ctry$", r"^country_?cd$", r"^nation$",
    ],
    "SURVEY_NAME": [
        r"^survey$", r"^survey_?name$", r"^seis_?name$",
        r"^seismic$", r"^line_?name$", r"^linename$",
    ],
    "SPUD_DATE": [
        r"^spud$", r"^spud_?date$", r"^spuddate$", r"^drill_?date$",
    ],
    "COMPLETION_DATE": [
        r"^comp_?date$", r"^completiondate$", r"^compl_?dt$",
    ],
    "KB_ELEV": [
        r"^kb$", r"^kb_?elev$", r"^kelly_?bushing$", r"^kb_elev$",
    ],
    "STATUS": [
        r"^status$", r"^well_?status$", r"^w_status$", r"^wstatus$",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Scanner
# ══════════════════════════════════════════════════════════════════════════════

def scan_directory(root_path: str,
                   progress_cb=None) -> list[dict]:
    import geopandas as gpd
    """
    Recursively scan a directory for spatial files.
    Returns list of file info dicts.
    """
    root = Path(root_path)
    results = []
    all_files = []

    for ext in SUPPORTED_EXTENSIONS:
        all_files.extend(root.rglob(f"*{ext}"))

    # Deduplicate — .shp and its sidecar files
    seen = set()
    for fp in sorted(all_files):
        stem = fp.stem.lower()
        key  = str(fp.parent / stem)
        if key in seen:
            continue
        seen.add(key)

        info = {
            "file_id":      uuid.uuid4().hex[:20].upper(),
            "file_path":    str(fp),
            "file_name":    fp.name,
            "file_ext":     fp.suffix.lower(),
            "file_size_kb": round(fp.stat().st_size / 1024, 1),
            "parent_folder": fp.parent.name,
            "status":       "PENDING",
        }
        results.append(info)

        if progress_cb:
            progress_cb(len(results))

    return results


# ══════════════════════════════════════════════════════════════════════════════
# 2. Classifier
# ══════════════════════════════════════════════════════════════════════════════

def _score_columns(cols: list[str], pattern_key: str) -> float:
    """Return 0-1 confidence that columns contain pattern_key field."""
    cols_lower = [c.lower() for c in cols]
    for pat in COLUMN_PATTERNS.get(pattern_key, []):
        for col in cols_lower:
            if re.match(pat, col):
                return 1.0
    return 0.0


def classify_shapefile(file_path: str) -> dict:
    import geopandas as gpd
    """
    Load and classify a shapefile. Returns classification dict.
    Does not load all data — reads only schema + first few rows.
    """
    result = {
        "file_path":      file_path,
        "feature_type":   FT_REVIEW,
        "ppdm_target":    None,
        "geometry_type":  None,
        "feature_count":  0,
        "crs":            None,
        "crs_epsg":       None,
        "attributes":     [],
        "column_map":     {},  # detected PPDM column → source column
        "sample_data":    {},  # actual values extracted from DBF columns
        "confidence":     0.0,
        "error":          None,
        "bounds":         None,
    }

    try:
        gdf = gpd.read_file(file_path, rows=10)

        result["geometry_type"] = (gdf.geometry.geom_type.mode()[0]
                                   if not gdf.empty else "Unknown")
        result["crs"]           = str(gdf.crs) if gdf.crs else "Unknown"
        result["crs_epsg"]      = (gdf.crs.to_epsg()
                                   if gdf.crs else None)
        result["attributes"]    = [c for c in gdf.columns
                                   if c != "geometry"]

        # Get full count without loading all data
        try:
            full = gpd.read_file(file_path)
            result["feature_count"] = len(full)
            bounds = full.total_bounds  # [minx, miny, maxx, maxy]
            result["bounds"] = {
                "minx": round(float(bounds[0]), 4),
                "miny": round(float(bounds[1]), 4),
                "maxx": round(float(bounds[2]), 4),
                "maxy": round(float(bounds[3]), 4),
            }
        except Exception:
            result["feature_count"] = -1

        cols     = result["attributes"]
        geom     = result["geometry_type"]
        fname    = Path(file_path).stem.lower()

        # ── Column matching ───────────────────────────────────────────────────
        col_map = {}
        for ppdm_col, patterns in COLUMN_PATTERNS.items():
            for col in cols:
                for pat in patterns:
                    if re.match(pat, col.lower()):
                        col_map[ppdm_col] = col
                        break

        result["column_map"] = col_map

        # ── Sample attribute values from matched DBF columns ──────────────────
        # Now that we know which columns hold which PPDM fields, pull a
        # representative sample of actual values. gdf already has 10 rows.
        sample_data: dict = {}

        if "UWI" in col_map:
            vals = gdf[col_map["UWI"]].dropna().astype(str).str.strip()
            sample_data["sample_uwis"] = [v for v in vals if v][:5]

        if "WELL_NAME" in col_map:
            vals = gdf[col_map["WELL_NAME"]].dropna().astype(str).str.strip()
            sample_data["sample_well_names"] = [v for v in vals if v][:5]

        if "OPERATOR" in col_map:
            # Use the full dataset for operators to get the dominant names
            try:
                full_ops = gpd.read_file(
                    file_path, include_fields=[col_map["OPERATOR"]])
                ops = (full_ops[col_map["OPERATOR"]]
                       .dropna().astype(str).str.strip()
                       .replace("", None).dropna()
                       .value_counts().head(5).index.tolist())
                sample_data["top_operators"] = ops
            except Exception:
                vals = gdf[col_map["OPERATOR"]].dropna().astype(str).str.strip()
                sample_data["top_operators"] = [v for v in vals if v][:5]

        if "FIELD_NAME" in col_map:
            vals = gdf[col_map["FIELD_NAME"]].dropna().astype(str).str.strip()
            sample_data["sample_fields"] = [v for v in vals if v][:5]

        if "SURVEY_NAME" in col_map:
            vals = gdf[col_map["SURVEY_NAME"]].dropna().astype(str).str.strip()
            sample_data["sample_surveys"] = [v for v in vals if v][:5]

        if "STATUS" in col_map:
            vals = gdf[col_map["STATUS"]].dropna().astype(str).str.strip()
            unique_statuses = list(dict.fromkeys(v for v in vals if v))
            sample_data["statuses"] = unique_statuses[:10]

        # Date range for spud / completion dates using full dataset
        for date_key in ("SPUD_DATE", "COMPLETION_DATE"):
            if date_key in col_map:
                try:
                    import pandas as pd
                    full_d = gpd.read_file(
                        file_path, include_fields=[col_map[date_key]])
                    dates = pd.to_datetime(
                        full_d[col_map[date_key]], errors="coerce").dropna()
                    if len(dates):
                        sample_data[f"{date_key.lower()}_range"] = (
                            f"{dates.min().strftime('%Y-%m-%d')} – "
                            f"{dates.max().strftime('%Y-%m-%d')}"
                        )
                except Exception:
                    pass

        result["sample_data"] = sample_data

        # ── Feature type classification ───────────────────────────────────────
        has_uwi     = "UWI"       in col_map
        has_well    = "WELL_NAME" in col_map
        has_field   = "FIELD_NAME" in col_map
        has_survey  = "SURVEY_NAME" in col_map
        has_lat     = "LATITUDE"  in col_map
        has_lon     = "LONGITUDE" in col_map

        is_point    = "Point"      in geom
        is_line     = "LineString" in geom or "Line" in geom
        is_poly     = "Polygon"    in geom

        # Filename signals
        fn_well   = bool(re.search(r"well|borehole|uwi|api", fname))
        fn_field  = bool(re.search(r"field|reservoir|pool", fname))
        fn_lease  = bool(re.search(r"lease|tract|block|unit", fname))
        fn_seis   = bool(re.search(r"seis|seismic|survey|2d|3d|line", fname))
        fn_pipe   = bool(re.search(r"pipe|pipeline|gather", fname))
        fn_fac    = bool(re.search(r"facility|platform|tank|station", fname))
        fn_bound  = bool(re.search(r"boundary|border|county|state|country", fname))

        # Score each feature type
        scores = {
            FT_WELL:       (is_point and (has_uwi or has_well or fn_well)) * (
                            2 + has_uwi + has_well + has_lat),
            FT_FIELD:      (is_poly and (has_field or fn_field)) * (
                            2 + has_field),
            FT_LEASE:      (is_poly and fn_lease) * 2,
            FT_SEISMIC_2D: (is_line and (has_survey or fn_seis)) * (
                            2 + has_survey),
            FT_SEISMIC_3D: (is_poly and (has_survey or fn_seis)) * (
                            2 + has_survey),
            FT_PIPELINE:   (is_line and (fn_pipe)) * 2,
            FT_FACILITY:   (is_point and fn_fac) * 2,
            FT_BOUNDARY:   (is_poly and fn_bound) * 2,
        }

        best_type  = max(scores, key=scores.get)
        best_score = scores[best_type]

        if best_score > 0:
            result["feature_type"] = best_type
            result["ppdm_target"]  = PPDM_TARGETS[best_type]
            result["confidence"]   = min(1.0, best_score / 5.0)
        else:
            result["feature_type"] = FT_REVIEW
            result["confidence"]   = 0.0

    except Exception as e:
        result["error"] = str(e)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 3. CRS Normalizer
# ══════════════════════════════════════════════════════════════════════════════

def normalize_crs(gdf) -> object:
    """Convert any CRS to WGS84 (EPSG:4326) decimal degrees."""
    import geopandas as gpd
    if gdf.crs is None:
        # Assume WGS84 if no CRS defined
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


# ══════════════════════════════════════════════════════════════════════════════
# 4. PPDM Loader
# ══════════════════════════════════════════════════════════════════════════════

def load_wells_to_ppdm(gdf,
                        col_map: dict,
                        engine,
                        dialect: str = "mssql",
                        source: str  = "SHAPEFILE",
                        dry_run: bool = False) -> dict:
    """
    Load Well features from a GeoDataFrame into dbo.WELL.
    Returns {"loaded": n, "skipped": n, "errors": [...]}
    """
    from sqlalchemy import text
    from modules.catalog_dialect import now_expr

    now = now_expr(dialect)
    result = {"loaded": 0, "skipped": 0, "errors": []}

    # Normalize CRS
    gdf = normalize_crs(gdf)

    # Extract lat/lon from geometry if not in attributes
    if "LATITUDE" not in col_map:
        gdf["_lat"] = gdf.geometry.y
        col_map["LATITUDE"] = "_lat"
    if "LONGITUDE" not in col_map:
        gdf["_lon"] = gdf.geometry.x
        col_map["LONGITUDE"] = "_lon"

    for _, row in gdf.iterrows():
        try:
            uwi       = str(row.get(col_map.get("UWI",""), "")).strip()
            well_name = str(row.get(col_map.get("WELL_NAME",""), "")).strip()
            operator  = str(row.get(col_map.get("OPERATOR",""), "")).strip()
            lat       = row.get(col_map.get("LATITUDE","_lat"), None)
            lon       = row.get(col_map.get("LONGITUDE","_lon"), None)
            county    = str(row.get(col_map.get("COUNTY",""), "")).strip()
            state     = str(row.get(col_map.get("STATE",""), "")).strip()
            country   = str(row.get(col_map.get("COUNTRY","US"), "US")).strip()

            if not uwi and not well_name:
                result["skipped"] += 1
                continue

            # Generate UWI if missing
            if not uwi:
                uwi = f"SHP-{uuid.uuid4().hex[:14].upper()}"

            if dry_run:
                result["loaded"] += 1
                continue

            with engine.begin() as con:
                # Check if UWI already exists
                exists = con.execute(text(
                    "SELECT COUNT(*) FROM dbo.WELL WHERE UWI=:uwi"
                ), {"uwi": uwi}).scalar()

                if exists:
                    result["skipped"] += 1
                    continue

                con.execute(text(f"""
                    INSERT INTO dbo.WELL
                    (UWI, WELL_NAME, OPERATOR,
                     SURFACE_LATITUDE, SURFACE_LONGITUDE,
                     ROW_CREATED_BY, ROW_CREATED_DATE,
                     ROW_CHANGED_BY, ROW_CHANGED_DATE,
                     ROW_QUALITY, SOURCE)
                    VALUES
                    (:uwi, :wn, :op,
                     :lat, :lon,
                     :by, {now},
                     :by, {now},
                     :qual, :src)
                """), {
                    "uwi":  uwi[:40],
                    "wn":   well_name[:255] if well_name else None,
                    "op":   operator[:255]  if operator  else None,
                    "lat":  float(lat)  if lat  else None,
                    "lon":  float(lon)  if lon  else None,
                    "src":  source[:40],
                    "by":   "DataWrangler",
                    "qual": "BRONZE",
                })
            result["loaded"] += 1

        except Exception as e:
            result["errors"].append(str(e))

    return result


def load_fields_to_ppdm(gdf,
                         col_map: dict,
                         engine,
                         dialect: str = "mssql",
                         source: str  = "SHAPEFILE",
                         dry_run: bool = False) -> dict:
    """Load Field polygons into dbo.FIELD."""
    from sqlalchemy import text
    from modules.catalog_dialect import now_expr

    now    = now_expr(dialect)
    result = {"loaded": 0, "skipped": 0, "errors": []}
    gdf    = normalize_crs(gdf)

    for _, row in gdf.iterrows():
        try:
            field_name = str(row.get(
                col_map.get("FIELD_NAME",""), "")).strip()
            country    = str(row.get(
                col_map.get("COUNTRY",""), "US")).strip()

            if not field_name:
                result["skipped"] += 1; continue

            field_id = f"SHP-{uuid.uuid4().hex[:14].upper()}"

            if dry_run:
                result["loaded"] += 1; continue

            with engine.begin() as con:
                exists = con.execute(text(
                    "SELECT COUNT(*) FROM dbo.FIELD "
                    "WHERE FIELD_NAME=:fn"
                ), {"fn": field_name}).scalar()
                if exists:
                    result["skipped"] += 1; continue

                con.execute(text(f"""
                    INSERT INTO dbo.FIELD
                    (FIELD_ID, FIELD_NAME, COUNTRY_NAME,
                     SOURCE, ROW_CREATED_BY, ROW_CREATED_DATE)
                    VALUES (:fid, :fn, :ctry, :src, :by, {now})
                """), {
                    "fid":  field_id,
                    "fn":   field_name[:255],
                    "ctry": country[:40],
                    "src":  source[:40],
                    "by":   "DataWrangler",
                })
            result["loaded"] += 1

        except Exception as e:
            result["errors"].append(str(e))

    return result


def load_to_ppdm(file_path: str,
                  feature_type: str,
                  col_map: dict,
                  engine,
                  dialect: str  = "mssql",
                  source: str   = "SHAPEFILE",
                  dry_run: bool = False) -> dict:
    """
    Main load dispatcher — reads shapefile and routes to correct loader.
    """
    import geopandas as gpd
    gdf = gpd.read_file(file_path)
    gdf = normalize_crs(gdf)

    if feature_type == FT_WELL:
        return load_wells_to_ppdm(gdf, col_map, engine,
                                   dialect, source, dry_run)
    elif feature_type == FT_FIELD:
        return load_fields_to_ppdm(gdf, col_map, engine,
                                    dialect, source, dry_run)
    else:
        return {
            "loaded":  0,
            "skipped": len(gdf),
            "errors":  [f"No loader implemented for {feature_type} yet"]
        }


# ══════════════════════════════════════════════════════════════════════════════
# 5. Duplicate detection
# ══════════════════════════════════════════════════════════════════════════════

def detect_duplicates(files: list[dict]) -> list[dict]:
    """
    Cross-file duplicate detection.
    Flags files with overlapping spatial extents and same feature type.
    """
    flagged = []
    for i, f1 in enumerate(files):
        b1 = f1.get("bounds")
        if not b1:
            continue
        for f2 in files[i+1:]:
            b2 = f2.get("bounds")
            if not b2:
                continue
            if f1.get("feature_type") != f2.get("feature_type"):
                continue
            # Check if bounds overlap significantly
            overlap_x = (min(b1["maxx"], b2["maxx"]) -
                         max(b1["minx"], b2["minx"]))
            overlap_y = (min(b1["maxy"], b2["maxy"]) -
                         max(b1["miny"], b2["miny"]))
            if overlap_x > 0 and overlap_y > 0:
                flagged.append({
                    "file_1": f1["file_path"],
                    "file_2": f2["file_path"],
                    "type":   f1["feature_type"],
                    "overlap_x": round(overlap_x, 4),
                    "overlap_y": round(overlap_y, 4),
                })
    return flagged


# ══════════════════════════════════════════════════════════════════════════════
# 6. Summary helpers
# ══════════════════════════════════════════════════════════════════════════════

def summarize_scan(files: list[dict]) -> dict:
    """Return summary statistics from a scan result."""
    by_type = {}
    for f in files:
        ft = f.get("feature_type", FT_REVIEW)
        by_type[ft] = by_type.get(ft, 0) + 1

    total_features = sum(
        f.get("feature_count", 0)
        for f in files
        if f.get("feature_count", 0) > 0
    )

    return {
        "total_files":    len(files),
        "total_features": total_features,
        "by_type":        by_type,
        "review_needed":  by_type.get(FT_REVIEW, 0),
        "ready_to_load":  sum(
            v for k, v in by_type.items()
            if k not in (FT_REVIEW, FT_OTHER, FT_BOUNDARY)
        ),
    }

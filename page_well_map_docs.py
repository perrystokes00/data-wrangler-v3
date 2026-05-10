"""
page_well_map.py
================
DataView v3 — Map Window

A live window into what is stored in the DataView database and
registered shapefiles. Every significant spatial dataset is queryable
as a toggleable layer.

Database layers:
  Wells, Well Trajectories, Formation Tops, DST Intervals,
  Production Bubbles, Fields, Basins

Shapefile layers:
  Read from dv_spatial_layer registry (GEOJSON or SHAPEFILE source_type)

Called from app.py:
    import page_well_map
    page_well_map.run(engine)
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
import streamlit as st

try:
    import folium
    from streamlit_folium import st_folium
    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

try:
    import geopandas as gpd
    HAS_GPD = True
except ImportError:
    HAS_GPD = False

try:
    from sqlalchemy import text
except ImportError:
    pass

try:
    from modules.dv_spatial_loader import (
        list_layers, get_layer_geojson,
        LAYER_CATEGORY_DISPLAY,
    )
    HAS_SPATIAL_LOADER = True
except Exception:
    HAS_SPATIAL_LOADER = False
    def list_layers(engine): return []
    def get_layer_geojson(engine, lid): return None
    LAYER_CATEGORY_DISPLAY = {}

# =============================================================================
# CONSTANTS
# =============================================================================

STATUS_COLORS = {
    "ACTIVE":    "#1D9E75",
    "COMPLETED": "#378ADD",
    "SHUT_IN":   "#EF9F27",
    "ABANDONED": "#E24B4A",
    "DRILLING":  "#B77FDD",
    "PERMITTED": "#888780",
    "SUSPENDED": "#EF9F27",
    "MONITORING":"#378ADD",
    "UNKNOWN":   "#888780",
}

BASEMAPS = {
    "OpenStreetMap":  {
        "tiles": "OpenStreetMap",
        "attr":  "© OpenStreetMap contributors",
    },
    "Esri Satellite": {
        "tiles":    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr":     "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
        "max_zoom": 19,
    },
    "Esri Topo": {
        "tiles":    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "attr":     "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ, TomTom, Intermap, iPC, USGS, FAO, NPS, NRCAN, GeoBase, Kadaster NL, Ordnance Survey, Esri Japan, METI, Esri China (Hong Kong), and the GIS User Community",
        "max_zoom": 19,
    },
    "Esri Street": {
        "tiles":    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "attr":     "Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom, 2012",
        "max_zoom": 19,
    },
    "CartoDB Light": {
        "tiles":    "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        "attr":     "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors &copy; <a href='https://carto.com/attributions'>CARTO</a>",
        "max_zoom": 19,
    },
    "CartoDB Dark": {
        "tiles":    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        "attr":     "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors &copy; <a href='https://carto.com/attributions'>CARTO</a>",
        "max_zoom": 19,
    },
    "USGS Topo": {
        "tiles":    "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        "attr":     "Tiles courtesy of the <a href='https://usgs.gov/'>U.S. Geological Survey</a>",
        "max_zoom": 16,
    },
    "Stamen Terrain": {
        "tiles":    "https://tiles.stadiamaps.com/tiles/stamen_terrain/{z}/{x}/{y}{r}.png",
        "attr":     "&copy; <a href='https://stamen.com'>Stamen Design</a> &copy; <a href='https://stadiamaps.com/'>Stadia Maps</a> &copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a>",
        "max_zoom": 18,
    },
    "Esri Satellite + Labels": {
        "tiles":    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attr":     "Tiles &copy; Esri",
        "max_zoom": 19,
        "overlay":  "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
    },
}

DB_LAYERS = [
    {"id": "db_trajectories",   "name": "Well Trajectories",  "icon": "📐", "default": False, "order": 2},
    {"id": "db_formation_tops", "name": "Formation Tops",      "icon": "📏", "default": False, "order": 3},
    {"id": "db_dst",            "name": "DST Intervals",       "icon": "🧪", "default": False, "order": 4},
    {"id": "db_production",     "name": "Production Bubbles",  "icon": "📈", "default": False, "order": 5},
    {"id": "db_fields",         "name": "Fields",              "icon": "🌿", "default": False, "order": 6},
    {"id": "db_basins",         "name": "Basins",              "icon": "🏔", "default": False, "order": 7},
]


# =============================================================================
# DATA QUERIES
# =============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _qry_wells(_engine) -> list[dict]:
    """
    Returns wells as a list of dicts via FOR JSON PATH.
    SQL Server does the joins and JSON serialization — no pandas, no Python loops.
    """
    sql = """
        SELECT w.uwi, w.well_name, w.well_type, w.well_status,
               w.surface_latitude  AS lat,
               w.surface_longitude AS lon,
               w.county, w.province_state, w.api_num,
               CONVERT(VARCHAR(10), w.spud_date,       120) AS spud_date,
               CONVERT(VARCHAR(10), w.completion_date, 120) AS completion_date,
               w.final_td, w.depth_datum,
               w.operator_ba_id, w.field_id,
               ISNULL(ba.ba_name, 'Unknown') AS operator_name,
               ISNULL(f.field_name,  'Unknown') AS field_name
        FROM dataview.dv_well w
        LEFT JOIN dataview.dv_business_associate ba ON ba.ba_id = w.operator_ba_id
        LEFT JOIN dataview.dv_field f ON f.field_id = w.field_id
        WHERE w.surface_latitude  IS NOT NULL
          AND w.surface_longitude IS NOT NULL
        ORDER BY w.well_name
        FOR JSON PATH
    """
    try:
        with _engine.connect().execution_options(timeout=30) as con:
            # FOR JSON PATH returns multiple varchar chunks — concatenate them
            rows = con.execute(text(sql)).fetchall()
            if not rows:
                return []
            json_str = "".join(r[0] for r in rows)
            return json.loads(json_str)
    except Exception as exc:
        st.error(f"Wells query failed: {exc}")
        return []


@st.cache_data(ttl=120, show_spinner=False)
def _qry_counts(_engine) -> pd.DataFrame:
    """Sub-data counts per well — cached, with timeout."""
    try:
        with _engine.connect().execution_options(timeout=10) as con:
            return pd.read_sql(text("""
                SELECT w.uwi,
                    ISNULL(t.cnt,  0) top_count,
                    ISNULL(l.cnt,  0) log_count,
                    ISNULL(c.cnt,  0) core_count,
                    ISNULL(d.cnt,  0) dst_count,
                    ISNULL(co.cnt, 0) comp_count,
                    ISNULL(pi.cnt, 0) petro_count,
                    ISNULL(pe.cnt, 0) prod_count
                FROM dataview.dv_well w
                LEFT JOIN (SELECT uwi, COUNT(*) cnt FROM dataview.dv_well_formation_top GROUP BY uwi) t  ON t.uwi  = w.uwi
                LEFT JOIN (SELECT uwi, COUNT(*) cnt FROM dataview.dv_well_log            GROUP BY uwi) l  ON l.uwi  = w.uwi
                LEFT JOIN (SELECT uwi, COUNT(*) cnt FROM dataview.dv_well_core           GROUP BY uwi) c  ON c.uwi  = w.uwi
                LEFT JOIN (SELECT uwi, COUNT(*) cnt FROM dataview.dv_well_dst            GROUP BY uwi) d  ON d.uwi  = w.uwi
                LEFT JOIN (SELECT uwi, COUNT(*) cnt FROM dataview.dv_well_completion     GROUP BY uwi) co ON co.uwi = w.uwi
                LEFT JOIN (SELECT uwi, COUNT(*) cnt FROM dataview.dv_well_petro_interp   GROUP BY uwi) pi ON pi.uwi = w.uwi
                LEFT JOIN (SELECT uwi, COUNT(*) cnt FROM dataview.dv_prod_entity         GROUP BY uwi) pe ON pe.uwi = w.uwi
            """), con)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _qry_formation_tops(_engine) -> pd.DataFrame:
    try:
        with _engine.connect() as con:
            return pd.read_sql(text("""
                SELECT t.uwi, t.strat_unit_name formation, t.top_depth, t.base_depth,
                       t.fluid_type, t.net_thickness,
                       w.surface_latitude lat, w.surface_longitude lon, w.well_name
                FROM dataview.dv_well_formation_top t
                JOIN dataview.dv_well w ON w.uwi = t.uwi
                WHERE w.surface_latitude IS NOT NULL
                ORDER BY t.uwi, t.top_depth
            """), con)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _qry_dst(_engine) -> pd.DataFrame:
    try:
        with _engine.connect() as con:
            return pd.read_sql(text("""
                SELECT d.uwi, d.test_type, d.top_depth, d.base_depth,
                       d.test_result, d.max_oil_rate, d.max_gas_rate,
                       d.api_gravity, d.test_date,
                       w.surface_latitude lat, w.surface_longitude lon, w.well_name
                FROM dataview.dv_well_dst d
                JOIN dataview.dv_well w ON w.uwi = d.uwi
                WHERE w.surface_latitude IS NOT NULL
            """), con)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _qry_production(_engine) -> pd.DataFrame:
    try:
        with _engine.connect() as con:
            return pd.read_sql(text("""
                SELECT w.uwi, w.well_name,
                       w.surface_latitude lat, w.surface_longitude lon,
                       SUM(CASE WHEN pv.fluid_type='OIL'   THEN ISNULL(pv.volume,0) ELSE 0 END) cum_oil,
                       SUM(CASE WHEN pv.fluid_type='GAS'   THEN ISNULL(pv.volume,0) ELSE 0 END) cum_gas,
                       SUM(CASE WHEN pv.fluid_type='WATER' THEN ISNULL(pv.volume,0) ELSE 0 END) cum_water,
                       COUNT(DISTINCT pv.period_date) months
                FROM dataview.dv_well w
                JOIN dataview.dv_prod_entity pe ON pe.uwi = w.uwi
                JOIN dataview.dv_prod_volume pv ON pv.prod_entity_id = pe.prod_entity_id
                WHERE w.surface_latitude IS NOT NULL
                GROUP BY w.uwi, w.well_name, w.surface_latitude, w.surface_longitude
            """), con)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _qry_fields(_engine) -> pd.DataFrame:
    try:
        with _engine.connect() as con:
            return pd.read_sql(text("""
                SELECT field_id, field_name, field_type, country_code,
                       centroid_latitude lat, centroid_longitude lon
                FROM dataview.dv_field WHERE centroid_latitude IS NOT NULL
            """), con)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _qry_basins(_engine) -> pd.DataFrame:
    try:
        with _engine.connect() as con:
            return pd.read_sql(text("""
                SELECT basin_id, basin_name, basin_type, country_code,
                       centroid_latitude lat, centroid_longitude lon,
                       area_km2, primary_play_type
                FROM dataview.dv_basin WHERE centroid_latitude IS NOT NULL
            """), con)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _qry_trajectories(_engine) -> pd.DataFrame:
    try:
        with _engine.connect() as con:
            return pd.read_sql(text("""
                SELECT s.uwi, s.seq_num, s.md, s.tvd,
                       s.ns_offset, s.ew_offset,
                       w.surface_latitude surf_lat, w.surface_longitude surf_lon,
                       w.well_name
                FROM dataview.dv_well_dir_srvy_sta s
                JOIN dataview.dv_well w ON w.uwi = s.uwi
                WHERE w.surface_latitude IS NOT NULL
                  AND s.ns_offset IS NOT NULL AND s.ew_offset IS NOT NULL
                ORDER BY s.uwi, s.seq_num
            """), con)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def _load_shp_layers(_engine) -> list[dict]:
    try:
        return list_layers(_engine)
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def _cached_layer_geojson(_engine, layer_id: str) -> str | None:
    """Cache the GeoJSON blob — can be large, only fetch once per TTL."""
    return get_layer_geojson(_engine, layer_id)


@st.cache_data(ttl=300, show_spinner=False)
def _qry_zoom_targets(_engine) -> list[dict]:
    """
    Build a list of named locations for zoom-to selectbox.
    Includes: counties (from dv_well locations), fields, basins.
    """
    targets = [{"label": "— Zoom to location —",
                "lat": None, "lon": None, "zoom": 7}]
    try:
        with _engine.connect().execution_options(timeout=8) as con:
            # Fields with coordinates
            rows = con.execute(text("""
                SELECT field_name, surface_latitude, surface_longitude
                FROM dataview.dv_field
                WHERE surface_latitude IS NOT NULL
                ORDER BY field_name
            """)).fetchall()
            for r in rows:
                targets.append({
                    "label": f"🌿 {r[0]}",
                    "lat": float(r[1]), "lon": float(r[2]), "zoom": 9,
                })
            # Basins with coordinates
            rows = con.execute(text("""
                SELECT basin_name, centroid_latitude, centroid_longitude
                FROM dataview.dv_basin
                WHERE centroid_latitude IS NOT NULL
                ORDER BY basin_name
            """)).fetchall()
            for r in rows:
                targets.append({
                    "label": f"🏔 {r[0]}",
                    "lat": float(r[1]), "lon": float(r[2]), "zoom": 7,
                })
            # Counties — use average well location as proxy centre
            rows = con.execute(text("""
                SELECT w.county, w.province_state,
                       AVG(w.surface_latitude)  lat,
                       AVG(w.surface_longitude) lon,
                       COUNT(*) n
                FROM dataview.dv_well w
                WHERE w.surface_latitude IS NOT NULL AND w.county IS NOT NULL
                GROUP BY w.county, w.province_state
                HAVING COUNT(*) >= 1
                ORDER BY w.province_state, w.county
            """)).fetchall()
            for r in rows:
                targets.append({
                    "label": f"📍 {r[0]}, {r[1]}",
                    "lat": float(r[2]), "lon": float(r[3]), "zoom": 10,
                })
            # Individual wells omitted from dropdown — too many items causes hang
            # Use the scout ticket panel to navigate to individual wells
    except Exception:
        pass
    return targets


# Path to the catalog CSV exported from the File Catalog page.
# When present, this is the PRIMARY source for the catalog overlay.
# SQL fallback only runs if this file is missing or empty.
CATALOG_CSV_PATH = (
    r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai"
    r"\data_wrangler\data_wrangler_v3\well_header_flat_file.csv"
)


@st.cache_data(ttl=300, show_spinner=False)
def _qry_catalog_csv() -> pd.DataFrame:
    """
    Load the catalog overlay from the well-header CSV exported by the
    File Catalog page (export_well_headers). Returns lowercase-column
    DataFrame matching what _add_catalog_overlay expects:
        uwi, file_path, file_name, extension, type_group, readiness, score,
        well_name, operator, well_field, state, county,
        latitude, longitude, total_depth

    Maps common variations of header column names — handles whatever
    the export gives us (LAS mnemonics, DLIS attributes, etc.) — to the
    fixed lowercase keys the renderer needs.

    Returns empty DataFrame if the file is missing or unreadable.
    """
    p = Path(CATALOG_CSV_PATH)
    if not p.exists():
        return pd.DataFrame()
    try:
        # Try several encodings — header CSVs sometimes have non-utf8 bytes
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                df = pd.read_csv(p, encoding=enc, low_memory=False)
                break
            except UnicodeDecodeError:
                continue
        else:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

    if df.empty:
        return df

    # Normalize header columns: case-insensitive lookup with common aliases
    cols_upper = {c.upper().strip(): c for c in df.columns}

    def _pick(*candidates):
        """Return the first matching column name from the DataFrame, or None."""
        for cand in candidates:
            actual = cols_upper.get(cand.upper())
            if actual is not None:
                return actual
        return None

    # Build the normalized DataFrame
    out = pd.DataFrame()

    # UWI — try several mnemonics
    c = _pick("UWI", "API", "API_NUMBER", "API_NUM", "WELL_ID")
    out["uwi"] = df[c].astype(str).str.strip() if c else ""

    # Well name
    c = _pick("WELL_NAME", "WELL", "WELLNAME", "NAME")
    out["well_name"] = df[c].astype(str).str.strip() if c else ""

    # Operator (LAS uses COMP, DLIS varies)
    c = _pick("OPERATOR", "COMPANY", "COMP", "OPER", "OPERATOR_NAME")
    out["operator"] = df[c].astype(str).str.strip() if c else ""

    # Field
    c = _pick("WELL_FIELD", "FIELD", "FLD", "FIELD_NAME")
    out["well_field"] = df[c].astype(str).str.strip() if c else ""

    # State
    c = _pick("STATE", "STAT", "PROV", "PROVINCE")
    out["state"] = df[c].astype(str).str.strip() if c else ""

    # County
    c = _pick("COUNTY", "CNTY")
    out["county"] = df[c].astype(str).str.strip() if c else ""

    # Latitude / Longitude — try several conventions
    c = _pick("LATITUDE", "LAT", "LATI", "SLAT", "Y")
    out["latitude"] = pd.to_numeric(df[c], errors="coerce") if c else pd.NA
    c = _pick("LONGITUDE", "LON", "LONG", "SLON", "X")
    out["longitude"] = pd.to_numeric(df[c], errors="coerce") if c else pd.NA

    # File-level fields
    c = _pick("FILE_PATH", "PATH", "FILEPATH")
    out["file_path"] = df[c].astype(str).str.strip() if c else ""

    c = _pick("FILE_NAME", "FILENAME", "NAME", "FILE")
    out["file_name"] = df[c].astype(str).str.strip() if c else ""

    c = _pick("EXTENSION", "EXT", "FILE_EXT", "FILE_EXTENSION")
    out["extension"] = df[c].astype(str).str.strip() if c else ""

    c = _pick("TYPE_GROUP", "FILE_TYPE_GROUP", "FILE_TYPE", "TYPE")
    out["type_group"] = df[c].astype(str).str.strip() if c else ""

    c = _pick("READINESS", "CATALOG_STATUS", "STATUS")
    out["readiness"] = df[c].astype(str).str.strip() if c else ""

    c = _pick("SCORE", "CONFIDENCE")
    if c:
        s = pd.to_numeric(df[c], errors="coerce")
        # Normalize: confidence 0-1 → score 0-100
        if s.dropna().between(0, 1).all() and s.dropna().any():
            s = s * 100
        out["score"] = s.astype("Int64")
    else:
        out["score"] = pd.NA

    c = _pick("TOTAL_DEPTH", "TD", "STOP", "DEPTH")
    out["total_depth"] = pd.to_numeric(df[c], errors="coerce") if c else pd.NA

    # Drop rows with no parseable lat/lon
    out = out.dropna(subset=["latitude", "longitude"])
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _qry_catalog(_engine) -> pd.DataFrame:
    """
    Returns the file catalog inventory: one row per cataloged file with
    UWI, type, score, and lat/lon. Used for the catalog overlay layer.

    Handles two FILE_WELL_HEADER schemas:

      WIDE  — one row per file, columns include UWI, WELL_NAME, OPERATOR,
              LATITUDE, LONGITUDE, CONFIDENCE etc. directly.
              (Current DataView production schema.)

      EAV   — one row per (file, mnemonic) pair, with columns FILE_NAME,
              MNEMONIC, VALUE. Pivot needed.
              (Older / DataView_Test schema.)

    Detects which is in play by introspecting INFORMATION_SCHEMA, then
    runs the matching query. Joins to GLOBAL_FILE_CATALOG for the file
    path and inventory metadata.

    Returns empty DataFrame on any failure.

    Result columns (lowercase, common across both schemas):
        uwi, file_path, file_name, extension, type_group, readiness, score,
        well_name, operator, well_field, state, county,
        latitude, longitude, total_depth
    """
    # Detect which schema is in place
    try:
        cols_df = pd.read_sql(text("""
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'file_catalog'
              AND TABLE_NAME   = 'FILE_WELL_HEADER'
        """), _engine)
        cols = set(c.upper() for c in cols_df["COLUMN_NAME"].astype(str).tolist())
    except Exception:
        cols = set()

    if not cols:
        # Table doesn't exist or query failed — empty overlay
        return pd.DataFrame(columns=[
            "uwi", "file_path", "file_name", "extension", "type_group",
            "readiness", "score", "well_name", "operator", "well_field",
            "state", "county", "latitude", "longitude", "total_depth",
        ])

    # ── WIDE schema (DataView): UWI/LATITUDE/LONGITUDE etc. as columns ──
    if {"UWI", "LATITUDE", "LONGITUDE", "WELL_NAME"}.issubset(cols):
        # Pull the appropriate fields. Use COALESCE for fields whose
        # column name varies (OPERATOR vs COMPANY, WELL_FIELD vs FIELD).
        operator_col = "OPERATOR" if "OPERATOR" in cols else (
                       "COMPANY"  if "COMPANY"  in cols else "NULL")
        field_col    = "WELL_FIELD" if "WELL_FIELD" in cols else (
                       "FIELD"      if "FIELD"      in cols else "NULL")
        confidence_col = "CONFIDENCE" if "CONFIDENCE" in cols else "NULL"
        join_key = ("INVENTORY_ID" if "INVENTORY_ID" in cols
                    else "FILE_NAME")

        sql = text(f"""
            SELECT
                h.UWI                            AS uwi,
                g.FILE_PATH                      AS file_path,
                g.FILE_NAME                      AS file_name,
                g.FILE_EXT                       AS extension,
                g.FILE_TYPE_GROUP                AS type_group,
                g.CATALOG_STATUS                 AS readiness,
                CAST({confidence_col} * 100 AS INT) AS score,
                h.WELL_NAME                      AS well_name,
                {operator_col}                   AS operator,
                {field_col}                      AS well_field,
                h.STATE                          AS state,
                h.COUNTY                         AS county,
                TRY_CAST(h.LATITUDE  AS FLOAT)   AS latitude,
                TRY_CAST(h.LONGITUDE AS FLOAT)   AS longitude,
                TRY_CAST(h.TOTAL_DEPTH AS FLOAT) AS total_depth
            FROM file_catalog.FILE_WELL_HEADER h
            LEFT JOIN file_catalog.GLOBAL_FILE_CATALOG g
                   ON g.{join_key} = h.{join_key}
            WHERE TRY_CAST(h.LATITUDE  AS FLOAT) IS NOT NULL
              AND TRY_CAST(h.LONGITUDE AS FLOAT) IS NOT NULL
        """)

    # ── EAV schema (DataView_Test): pivot mnemonics ──────────────────
    elif "MNEMONIC" in cols and "VALUE" in cols and "FILE_NAME" in cols:
        sql = text("""
            ;WITH header_pivot AS (
                SELECT
                    h.FILE_NAME,
                    MAX(h.UWI)                                                          AS UWI,
                    MAX(CASE WHEN h.MNEMONIC IN ('LATI','LAT','SLAT','LATITUDE')
                             THEN h.VALUE END)                                          AS LATITUDE,
                    MAX(CASE WHEN h.MNEMONIC IN ('LONG','LON','SLON','LONGITUDE')
                             THEN h.VALUE END)                                          AS LONGITUDE,
                    MAX(CASE WHEN h.MNEMONIC IN ('WELL','WELL_NAME')
                             THEN h.VALUE END)                                          AS WELL_NAME,
                    MAX(CASE WHEN h.MNEMONIC IN ('COMP','COMPANY','OPER','OPERATOR')
                             THEN h.VALUE END)                                          AS COMPANY,
                    MAX(CASE WHEN h.MNEMONIC IN ('FLD','FIELD')
                             THEN h.VALUE END)                                          AS FIELD,
                    MAX(CASE WHEN h.MNEMONIC IN ('STAT','STATE','PROV')
                             THEN h.VALUE END)                                          AS STATE,
                    MAX(CASE WHEN h.MNEMONIC IN ('CNTY','COUNTY')
                             THEN h.VALUE END)                                          AS COUNTY,
                    MAX(CASE WHEN h.MNEMONIC IN ('STOP','TD')
                             THEN h.VALUE END)                                          AS TOTAL_DEPTH
                FROM file_catalog.FILE_WELL_HEADER h
                GROUP BY h.FILE_NAME
            )
            SELECT
                p.UWI                            AS uwi,
                g.FILE_PATH                      AS file_path,
                p.FILE_NAME                      AS file_name,
                g.FILE_EXT                       AS extension,
                g.FILE_TYPE_GROUP                AS type_group,
                g.CATALOG_STATUS                 AS readiness,
                CAST(NULL AS INT)                AS score,
                p.WELL_NAME                      AS well_name,
                p.COMPANY                        AS operator,
                p.FIELD                          AS well_field,
                p.STATE                          AS state,
                p.COUNTY                         AS county,
                TRY_CAST(p.LATITUDE  AS FLOAT)   AS latitude,
                TRY_CAST(p.LONGITUDE AS FLOAT)   AS longitude,
                TRY_CAST(p.TOTAL_DEPTH AS FLOAT) AS total_depth
            FROM header_pivot p
            LEFT JOIN file_catalog.GLOBAL_FILE_CATALOG g
                   ON g.FILE_NAME = p.FILE_NAME
            WHERE TRY_CAST(p.LATITUDE  AS FLOAT) IS NOT NULL
              AND TRY_CAST(p.LONGITUDE AS FLOAT) IS NOT NULL
        """)

    else:
        # Schema doesn't match either expected shape — give up gracefully
        return pd.DataFrame(columns=[
            "uwi", "file_path", "file_name", "extension", "type_group",
            "readiness", "score", "well_name", "operator", "well_field",
            "state", "county", "latitude", "longitude", "total_depth",
        ])

    try:
        df = pd.read_sql(sql, _engine)
    except Exception:
        return pd.DataFrame(columns=[
            "uwi", "file_path", "file_name", "extension", "type_group",
            "readiness", "score", "well_name", "operator", "well_field",
            "state", "county", "latitude", "longitude", "total_depth",
        ])

    if df.empty:
        return df

    # ── Stage 1 sanity checks ─────────────────────────────────────────
    # Filter out catalog files with low-quality or implausible coords
    # before they ever reach the map. Two checks:
    #   1. Precision: require ≥ 3 decimal places (~360 ft / section scale).
    #      Anything coarser is too imprecise to be useful for placement.
    #   2. State agreement: when the parsed state is set, drop coords that
    #      fall outside that state's rough bounding box.

    # Cast strings → floats once
    df["latitude"]  = pd.to_numeric(df["latitude"],  errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"])

    # ── Check 1: precision ≥ 3 decimal places ─────────────────────
    # Counts the digits after the decimal in the original string form.
    # Coords like "29.32" (2 decimals) get dropped; "29.322" (3) and
    # finer pass through.
    def _decimal_places(v) -> int:
        s = f"{v:.10f}".rstrip("0").rstrip(".")
        if "." not in s:
            return 0
        return len(s.split(".")[1])

    df["_lat_decimals"] = df["latitude"].map(_decimal_places)
    df["_lon_decimals"] = df["longitude"].map(_decimal_places)
    df = df[(df["_lat_decimals"] >= 3) & (df["_lon_decimals"] >= 3)]
    df = df.drop(columns=["_lat_decimals", "_lon_decimals"])

    if df.empty:
        return df

    # ── Check 2: state-coord sanity ───────────────────────────────
    # Rough bounding boxes for US states & a few CA provinces. Used only
    # to detect gross mismatches (e.g., LAS says STATE=TX but lon = -90,
    # which is Mississippi). Boxes are intentionally generous — better to
    # let a borderline file through than to falsely reject it.
    # Format: STATE_CODE → (min_lat, max_lat, min_lon, max_lon)
    STATE_BBOX = {
        # USA — lower 48 + AK + HI; common 2-letter codes
        "AL": (30.2, 35.0, -88.5, -84.9),  "AK": (54.0, 71.5, -179.2,-129.9),
        "AZ": (31.3, 37.0, -114.9,-109.0), "AR": (33.0, 36.5, -94.7, -89.6),
        "CA": (32.5, 42.0, -124.5,-114.1), "CO": (37.0, 41.0, -109.1,-102.0),
        "CT": (40.9, 42.1, -73.8, -71.7),  "DE": (38.4, 39.9, -75.8, -75.0),
        "FL": (24.5, 31.0, -87.7, -80.0),  "GA": (30.4, 35.0, -85.7, -80.8),
        "HI": (18.9, 22.3, -160.3,-154.7), "ID": (42.0, 49.0, -117.3,-111.0),
        "IL": (37.0, 42.6, -91.6, -87.5),  "IN": (37.7, 41.8, -88.1, -84.7),
        "IA": (40.3, 43.6, -96.7, -90.1),  "KS": (36.9, 40.1, -102.1,-94.6),
        "KY": (36.4, 39.2, -89.7, -81.9),  "LA": (28.9, 33.1, -94.1, -88.7),
        "ME": (43.0, 47.5, -71.1, -66.9),  "MD": (37.8, 39.8, -79.5, -75.0),
        "MA": (41.2, 42.9, -73.5, -69.9),  "MI": (41.6, 48.3, -90.5, -82.4),
        "MN": (43.4, 49.4, -97.3, -89.4),  "MS": (30.1, 35.0, -91.7, -88.0),
        "MO": (35.9, 40.7, -95.9, -89.0),  "MT": (44.3, 49.1, -116.1,-104.0),
        "NE": (39.9, 43.1, -104.1,-95.3),  "NV": (35.0, 42.0, -120.0,-114.0),
        "NH": (42.6, 45.4, -72.6, -70.6),  "NJ": (38.8, 41.4, -75.7, -73.9),
        "NM": (31.2, 37.1, -109.1,-103.0), "NY": (40.4, 45.1, -79.8, -71.8),
        "NC": (33.7, 36.7, -84.4, -75.4),  "ND": (45.9, 49.1, -104.1,-96.5),
        "OH": (38.3, 42.0, -84.9, -80.5),  "OK": (33.6, 37.1, -103.0,-94.4),
        "OR": (41.9, 46.3, -124.6,-116.4), "PA": (39.7, 42.3, -80.6, -74.6),
        "RI": (41.1, 42.1, -71.9, -71.1),  "SC": (32.0, 35.3, -83.4, -78.5),
        "SD": (42.4, 46.0, -104.1,-96.4),  "TN": (34.9, 36.7, -90.4, -81.6),
        "TX": (25.8, 36.6, -106.7,-93.5),  "UT": (37.0, 42.0, -114.1,-109.0),
        "VT": (42.7, 45.1, -73.5, -71.4),  "VA": (36.5, 39.5, -83.7, -75.2),
        "WA": (45.5, 49.1, -124.8,-116.9), "WV": (37.2, 40.7, -82.7, -77.7),
        "WI": (42.4, 47.1, -92.9, -86.2),  "WY": (40.9, 45.1, -111.1,-104.0),
        # Canada — a few common O&G provinces
        "AB": (49.0, 60.0, -120.0,-110.0), "BC": (48.3, 60.0, -139.1,-114.0),
        "SK": (49.0, 60.0, -110.0,-101.4), "MB": (49.0, 60.0, -102.0, -89.0),
    }

    def _state_code(s) -> str | None:
        """Normalize state values to a 2-letter code if recognizable."""
        if s is None:
            return None
        s = str(s).strip().upper()
        if not s:
            return None
        # Already a 2-letter code we know
        if len(s) == 2 and s in STATE_BBOX:
            return s
        # Common full-name → code mapping
        FULL = {
            "TEXAS":"TX","NEW MEXICO":"NM","OKLAHOMA":"OK","KANSAS":"KS",
            "NORTH DAKOTA":"ND","SOUTH DAKOTA":"SD","MONTANA":"MT",
            "COLORADO":"CO","WYOMING":"WY","CALIFORNIA":"CA","ALASKA":"AK",
            "PENNSYLVANIA":"PA","WEST VIRGINIA":"WV","OHIO":"OH",
            "ARKANSAS":"AR","LOUISIANA":"LA","MISSISSIPPI":"MS","ALABAMA":"AL",
            "ILLINOIS":"IL","INDIANA":"IN","NEBRASKA":"NE","MICHIGAN":"MI",
            "ALBERTA":"AB","BRITISH COLUMBIA":"BC","SASKATCHEWAN":"SK",
            "MANITOBA":"MB",
        }
        return FULL.get(s)

    def _coord_in_state(row) -> bool:
        """True if the coord is plausibly inside the parsed state's bbox.
        Returns True when state is unknown (don't penalize blank states).
        """
        code = _state_code(row.get("state"))
        if code is None:
            return True  # unknown state → don't filter
        bbox = STATE_BBOX.get(code)
        if bbox is None:
            return True  # state we don't have a bbox for → don't filter
        min_lat, max_lat, min_lon, max_lon = bbox
        lat = row["latitude"]; lon = row["longitude"]
        return (min_lat <= lat <= max_lat) and (min_lon <= lon <= max_lon)

    df = df[df.apply(_coord_in_state, axis=1)]
    return df


def _add_catalog_overlay(m, catalog_df: pd.DataFrame) -> int:
    """
    Render the file catalog as a separate overlay layer.

    Strategy:
    - Group by UWI — one marker per UWI even if multiple files exist
    - Marker style: purple square (svg DivIcon) — visually distinct from
      cluster bubbles (round) and viewport markers (yellow-ringed round)
    - Popup: lists all files for the UWI, with file_path, type_group,
      readiness, score, file_name. Flags coordinate inconsistencies.
    - Click handler: data-catalog-uwi attribute embedded in popup, wired
      to set st.session_state.catalog_uwi for later File Catalog navigation

    Args:
        m: folium.Map
        catalog_df: DataFrame from _qry_catalog

    Returns:
        Number of UWIs rendered (0 if empty)
    """
    if catalog_df is None or catalog_df.empty:
        return 0

    # Coerce numerics for safety
    df = catalog_df.copy()
    df["latitude"]  = pd.to_numeric(df["latitude"],  errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"])
    if df.empty:
        return 0

    # Group key: prefer UWI when present, fall back to FILE_NAME for files
    # that were cataloged with coords but no UWI (PDFs, surveys, scout tickets,
    # anything where the parser found coords but no well identifier).
    df["_group_key"] = df["uwi"].fillna("").astype(str)
    no_uwi_mask = df["_group_key"].str.strip() == ""
    df.loc[no_uwi_mask, "_group_key"] = "📄 " + df.loc[no_uwi_mask, "file_name"].astype(str)

    groups = df.groupby("_group_key", sort=False)
    n_groups = len(groups)
    n = 0
    fg = folium.FeatureGroup(name=f"📁 File Catalog ({n_groups} locations)", show=True)

    for group_key, sub in groups:
        # Representative coords (first row)
        lat = float(sub["latitude"].iloc[0])
        lon = float(sub["longitude"].iloc[0])

        # Detect coord inconsistency across this group's files
        # (only meaningful when grouped by UWI — multi-file groups can have
        # the same UWI but different parsed coords from different extraction
        # passes. Single-file groups have nothing to compare.)
        unique_coords = set(zip(
            sub["latitude"].round(3).tolist(),
            sub["longitude"].round(3).tolist(),
        ))
        coord_warning = ""
        if len(unique_coords) > 1:
            coord_warning = (
                f'<div style="margin:4px 0;padding:4px 6px;background:#fef3c7;'
                f'border-left:3px solid #f59e0b;font-size:10px;color:#92400e">'
                f'⚠ {len(unique_coords)} different coordinates across files '
                f'for this group — file paths may be from different extraction '
                f'passes.</div>'
            )

        # Was this group keyed by UWI or by FILE_NAME (UWI-less)?
        first_uwi = sub["uwi"].iloc[0]
        has_uwi = pd.notna(first_uwi) and str(first_uwi).strip() != ""
        uwi = str(first_uwi).strip() if has_uwi else ""

        # Build per-file rows in the popup
        file_rows = []
        for _, r in sub.iterrows():
            fname = str(r.get("file_name") or "")
            fpath = str(r.get("file_path") or "")
            tgrp  = str(r.get("type_group") or "—")
            ready = str(r.get("readiness")  or "—")
            score = r.get("score")
            score_s = f"{int(score)}" if pd.notna(score) else "—"
            ext   = str(r.get("extension")  or "").lstrip(".")

            # Color the readiness badge
            ready_color = {
                "READY":   "#10b981",
                "REVIEW":  "#f59e0b",
                "PENDING": "#6b7280",
                "REJECTED":"#ef4444",
            }.get(ready.upper(), "#6b7280")

            # Build the download link: ?open_file=<urlencoded path>
            # The popup runs inside streamlit-folium's iframe. Plain href
            # with target="_top" gets blocked by browser sandbox because
            # the iframe is treated as a different origin. Use an onclick
            # handler that explicitly navigates window.top, which IS allowed
            # for same-origin iframes (which streamlit-folium is, even
            # though browsers initially treat it as cross-origin).
            from urllib.parse import quote as _urlquote
            dl_url = f"?open_file={_urlquote(fpath)}" if fpath else ""
            if dl_url:
                # Escape the URL for inclusion in an onclick attribute
                dl_url_js = dl_url.replace("'", "\\'")
                fname_html = (
                    f"<a href=\"#\" "
                    f"onclick=\"event.preventDefault(); "
                    f"try {{ window.top.location.search = '{dl_url_js}'; }} "
                    f"catch(e) {{ window.parent.location.search = '{dl_url_js}'; }} "
                    f"return false;\" "
                    f'style="color:#1a73e8;text-decoration:none;font-weight:600;cursor:pointer">'
                    f'📥 {fname}</a>'
                )
            else:
                fname_html = f'<b>{fname}</b>'

            file_rows.append(
                f'<tr>'
                f'<td style="padding:3px 6px;font-size:10px;color:#475569;'
                f'  font-family:monospace;border-bottom:1px solid #e5e7eb">'
                f'  {ext.upper()}'
                f'</td>'
                f'<td style="padding:3px 6px;font-size:10px;'
                f'  border-bottom:1px solid #e5e7eb">'
                f'  {fname_html}<br>'
                f'  <span style="color:#94a3b8;font-size:9px;'
                f'    word-break:break-all">{fpath}</span>'
                f'</td>'
                f'<td style="padding:3px 6px;font-size:10px;'
                f'  border-bottom:1px solid #e5e7eb;text-align:right">'
                f'  <span style="background:{ready_color};color:#fff;'
                f'    padding:1px 5px;border-radius:3px;font-size:9px;'
                f'    font-weight:600">{ready}</span>'
                f'  <br><span style="color:#64748b">'
                f'  {tgrp} · {score_s}</span>'
                f'</td>'
                f'</tr>'
            )

        # Header info from first row
        well_name = str(sub["well_name"].iloc[0] or "")
        operator  = str(sub["operator"].iloc[0]  or "—")
        field     = str(sub["well_field"].iloc[0] or "—")
        state     = str(sub["state"].iloc[0]      or "")
        county    = str(sub["county"].iloc[0]     or "")
        n_files   = len(sub)

        # Title: well_name if known, otherwise the file name (UWI-less files)
        if well_name:
            title = well_name
        elif has_uwi:
            title = "(unnamed well)"
        else:
            # Use the file name as title for orphan files
            title = str(sub["file_name"].iloc[0] or "(file with no UWI)")

        # UWI line: omit the empty monospace block when there's no UWI
        uwi_line = (
            f'<span style="font-family:monospace;font-size:10px;color:#888">'
            f'{uwi}</span>'
            if has_uwi else
            f'<span style="font-size:10px;color:#94a3b8;font-style:italic">'
            f'No UWI · catalog location only</span>'
        )

        # data-catalog="1" is always present on a catalog marker popup
        # (used by the click handler to detect catalog clicks).
        # data-catalog-uwi is only added when there's a UWI to forward to
        # the File Catalog page.
        catalog_attrs = (
            f'data-catalog="1" data-catalog-uwi="{uwi}"'
            if has_uwi else
            'data-catalog="1"'
        )
        popup_html = (
            f'<div {catalog_attrs} style="min-width:340px;max-width:420px">'
            f'<b style="font-size:13px">{title}</b><br>'
            f'{uwi_line}'
            f'<hr style="margin:4px 0">'
            f'<div style="font-size:11px;color:#475569">'
            f'{operator} &middot; {field}'
            f'<br>{state}{(" · "+county) if county else ""}'
            f'</div>'
            f'{coord_warning}'
            f'<div style="margin:6px 0 2px 0;font-size:11px;color:#0f172a">'
            f'<b>📁 {n_files} cataloged file(s)</b></div>'
            f'<table style="width:100%;border-collapse:collapse;margin-bottom:4px">'
            f'<thead>'
            f'<tr style="background:#f1f5f9;color:#475569;font-size:9px">'
            f'  <th style="padding:3px 6px;text-align:left">Type</th>'
            f'  <th style="padding:3px 6px;text-align:left">Name &amp; Path</th>'
            f'  <th style="padding:3px 6px;text-align:right">Status</th>'
            f'</tr>'
            f'</thead>'
            f'<tbody>{"".join(file_rows)}</tbody>'
            f'</table>'
            f'<hr style="margin:4px 0">'
            f'<span style="font-size:11px;color:#7c3aed;font-weight:600">'
            f'🗂 Click to view in File Catalog'
            f'</span>'
            f'</div>'
        )

        # Purple square marker via DivIcon — visually distinct from
        # the round cluster bubbles and yellow-ringed viewport dots
        icon_html = (
            '<div style="width:14px;height:14px;background:#7c3aed;'
            'border:2px solid #fff;box-shadow:0 0 0 1px #7c3aed,'
            '0 1px 3px rgba(0,0,0,0.4);transform:rotate(45deg);'
            'cursor:crosshair"></div>'
        )
        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(
                icon_size=(18, 18),
                icon_anchor=(9, 9),
                html=icon_html,
            ),
            popup=folium.Popup(popup_html, max_width=440),
            tooltip=f"📁 {n_files} file(s) · {title}",
        ).add_to(fg)
        n += 1

    fg.add_to(m)
    return n



    rows = "".join(
        f"<tr><td style='color:#666;padding:2px 6px 2px 0;font-size:11px'>{k}</td>"
        f"<td style='font-size:11px'>{v}</td></tr>"
        for k, v in fields.items()
        if v is not None and str(v).strip() not in ("", "None", "nan")
    )
    return f"<table style='border-collapse:collapse'>{rows}</table>"


def _offset_to_latlon(surf_lat, surf_lon, ns_ft, ew_ft):
    deg_lat = 364000.0
    deg_lon = 364000.0 * math.cos(math.radians(surf_lat))
    return surf_lat + ns_ft / deg_lat, surf_lon + ew_ft / deg_lon


def _trajectory_geojson(df: pd.DataFrame) -> dict:
    features = []
    for uwi, grp in df.groupby("uwi"):
        grp = grp.sort_values("seq_num")
        slat = grp["surf_lat"].iloc[0]
        slon = grp["surf_lon"].iloc[0]
        coords = [list(_offset_to_latlon(slat, slon,
                    float(r["ns_offset"] or 0),
                    float(r["ew_offset"] or 0)))[::-1]
                  for _, r in grp.iterrows()]
        if len(coords) >= 2:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "well_name": grp["well_name"].iloc[0],
                    "uwi": uwi,
                    "stations": len(coords),
                    "td_ft": float(grp["md"].max()),
                },
            })
    return {"type": "FeatureCollection", "features": features}


# =============================================================================
# LAYER RENDERERS
# =============================================================================

def _add_wells(m, df, exclude_uwis=None):
    """
    Clustered well markers via FastMarkerCluster.

    Behavior:
    - Cluster bubbles show density of all wells in df (minus exclude_uwis)
    - Cluster click zooms to bounds (Leaflet.markercluster default)
    - Clusters NEVER break into individual markers on zoom alone
    - Individual markers come from the user drawing a rectangle viewport,
      which is rendered separately by _add_viewport_wells

    Args:
        m: folium.Map
        df: full wells DataFrame (filtered by current top-level filters)
        exclude_uwis: iterable of UWI strings to skip (typically the current
            viewport selection, since those render as individual markers)
    """
    if df.empty:
        return

    df = df.reset_index(drop=True)
    if exclude_uwis:
        excl = set(map(str, exclude_uwis))
        df = df[~df["uwi"].astype(str).isin(excl)].reset_index(drop=True)
        if df.empty:
            return

    sc = df["well_status"].astype(str).str.upper().fillna("UNKNOWN")

    # Vectorized prep — every column to a flat list, no iterrows()
    colors = sc.map(STATUS_COLORS).fillna("#888780").tolist()
    statuses = sc.tolist()
    lats     = pd.to_numeric(df["lat"], errors="coerce").tolist()
    lons     = pd.to_numeric(df["lon"], errors="coerce").tolist()
    uwis     = df["uwi"].astype(str).tolist()
    names    = df["well_name"].fillna("").astype(str).tolist()
    ops      = df["operator_name"].fillna("—").astype(str).tolist()
    fields   = df["field_name"].fillna("—").astype(str).tolist()
    spuds    = df["spud_date"].fillna("—").astype(str).str[:10].tolist()
    tds      = df["final_td"].apply(
        lambda v: f"{float(v):,.0f} ft" if pd.notna(v) else "—").tolist()

    # Flat per-well data array — passed to JS as a single JSON payload
    data = []
    for i in range(len(df)):
        if lats[i] is None or lons[i] is None:
            continue
        try:
            if pd.isna(lats[i]) or pd.isna(lons[i]):
                continue
        except (TypeError, ValueError):
            continue
        data.append([
            float(lats[i]), float(lons[i]),
            colors[i], uwis[i], names[i], statuses[i],
            ops[i], fields[i], spuds[i], tds[i]
        ])

    if not data:
        return

    # JS callback — one function per well at marker construction time.
    # Builds the popup HTML on the JS side from the flat data array, embedding
    # data-uwi for the Python click parser.
    callback = """
        function(row) {
            var lat=row[0], lon=row[1], color=row[2], uwi=row[3],
                name=row[4], status=row[5], op=row[6],
                field=row[7], spud=row[8], td=row[9];
            var popup = '<div data-uwi="' + uwi + '">'
                + '<b style="font-size:13px">' + name + '</b><br>'
                + '<span style="font-family:monospace;font-size:10px;color:#888">' + uwi + '</span>'
                + '<hr style="margin:4px 0">'
                + '<small>'
                + op + ' &middot; ' + field + '<br>'
                + '<b style="color:' + color + '">' + status + '</b>'
                + ' &middot; Spud ' + spud + ' &middot; TD ' + td
                + '</small>'
                + '<hr style="margin:4px 0">'
                + '<span style="font-size:12px;color:#1a73e8;font-weight:600">'
                + '📋 Open Scout Ticket &amp; Add to Tray'
                + '</span>'
                + '</div>';
            var marker = L.circleMarker(
                new L.LatLng(lat, lon),
                {radius:5, fillColor:color, color:'#ffffff',
                 weight:1, opacity:1, fillOpacity:0.88}
            );
            marker.bindPopup(popup, {maxWidth:300});
            marker.bindTooltip(name || uwi, {sticky:true});
            return marker;
        }
    """

    try:
        from folium.plugins import FastMarkerCluster
        FastMarkerCluster(
            data,
            callback=callback,
            name="🛢 Wells (clusters)",
            options={
                # Permanent-cluster config: clusters NEVER break into individual
                # markers on zoom alone. Individual markers come from the user
                # drawing a rectangle viewport (handled in Python below).
                "maxClusterRadius":          60,    # cluster nearby wells (px)
                "disableClusteringAtZoom":   20,    # never break apart in practice
                "spiderfyOnMaxZoom":         False, # no spiderfy — clusters always cluster
                "showCoverageOnHover":       False, # no hover-bounds polygon
                "zoomToBoundsOnClick":       True,  # cluster click → zoom to bounds
                "chunkedLoading":            True,  # render incrementally
                # FUTURE: experiment with DB-side hex-grid aggregation here.
                # Pre-aggregate ~500 grid points server-side and feed them as
                # weighted markers rather than 50K full lat/lon pairs.
            },
        ).add_to(m)
    except ImportError:
        # Graceful fallback if folium.plugins unavailable — uncluster everything
        st.warning("FastMarkerCluster unavailable; falling back to individual markers.")
        fg = folium.FeatureGroup(name="🛢 Wells", show=True)
        for r in data:
            lat, lon, color, uwi, name, status, op, field, spud, td = r
            popup_html = (
                f'<div data-uwi="{uwi}"><b>{name}</b><br>'
                f'<span style="font-family:monospace;font-size:10px;color:#888">{uwi}</span>'
                f'<hr style="margin:4px 0"><small>{op} &middot; {field}<br>'
                f'<b style="color:{color}">{status}</b> &middot; Spud {spud} &middot; TD {td}</small>'
                f'<hr style="margin:4px 0">'
                f'<span style="font-size:12px;color:#1a73e8;font-weight:600">'
                f'📋 Open Scout Ticket &amp; Add to Tray</span></div>'
            )
            folium.CircleMarker(
                location=[lat, lon], radius=5, color="#ffffff", weight=1,
                fill=True, fill_color=color, fill_opacity=0.88, opacity=1,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=name or uwi,
            ).add_to(fg)
        fg.add_to(m)


VIEWPORT_PYTHON_LIMIT = 1000  # ≤ this → slow Python path with yellow rings;
                              # > this → fast JS path via FastMarkerCluster.
                              # Total hard cap for any viewport selection:
VIEWPORT_HARD_CAP      = 25000


def _add_viewport_wells(m, df, viewport_uwis, label_field="None"):
    """
    Render INDIVIDUAL clickable markers for wells inside a user-drawn viewport,
    on top of the existing cluster layer.

    Routes to one of two render paths based on size:
    - ≤ VIEWPORT_PYTHON_LIMIT (1000): Python folium.CircleMarker loop. Each
      well gets a dual-marker pattern: an invisible 14px hit target (catches
      clicks/hovers) plus a visible 5px colored dot.
    - > VIEWPORT_PYTHON_LIMIT: FastMarkerCluster JS path with single 6px
      yellow-ringed markers (no dual pattern; would double the JS payload).
    - > VIEWPORT_HARD_CAP (25000): refuse to render markers, return 0;
      caller surfaces a message to the user.

    Labels:
    - label_field selects which attribute appears next to each marker
      (None / Well name / UWI / Operator).
    - Labels are permanent tooltips, but CSS hides them when the map zoom is
      below 11 (county/township threshold). The CSS rule lives in the map's
      style block — see `<style>` injected near st_folium call.

    Args:
        m: folium.Map
        df: full wells DataFrame (filtered by current top-level filters)
        viewport_uwis: list of UWI strings to render as individual markers
        label_field: str, one of "None"/"Well name"/"UWI"/"Operator"

    Returns:
        Number of markers actually rendered (0 if hard cap exceeded)
    """
    if df.empty or not viewport_uwis:
        return 0

    vp_set = set(map(str, viewport_uwis))
    sub = df[df["uwi"].astype(str).isin(vp_set)].reset_index(drop=True)
    if sub.empty:
        return 0
    n = len(sub)

    if n > VIEWPORT_HARD_CAP:
        # Too many — caller handles the user-facing warning
        return 0

    # ── Common data prep ──────────────────────────────────────────────
    sc       = sub["well_status"].astype(str).str.upper().fillna("UNKNOWN")
    colors   = sc.map(STATUS_COLORS).fillna("#888780").tolist()
    statuses = sc.tolist()
    lats     = pd.to_numeric(sub["lat"], errors="coerce").tolist()
    lons     = pd.to_numeric(sub["lon"], errors="coerce").tolist()
    uwis     = sub["uwi"].astype(str).tolist()
    names    = sub["well_name"].fillna("").astype(str).tolist()
    ops      = sub["operator_name"].fillna("—").astype(str).tolist()
    fields   = sub["field_name"].fillna("—").astype(str).tolist()
    spuds    = sub["spud_date"].fillna("—").astype(str).str[:10].tolist()
    tds      = sub["final_td"].apply(
        lambda v: f"{float(v):,.0f} ft" if pd.notna(v) else "—").tolist()

    # Pick the per-well label text based on label_field
    def _label_for(i):
        if label_field == "Well name":
            return names[i] or uwis[i]
        if label_field == "UWI":
            return uwis[i]
        if label_field == "Operator":
            return ops[i]
        return None  # "None" → no label

    # ── SMALL: Python CircleMarker loop with dual markers + labels ────
    if n <= VIEWPORT_PYTHON_LIMIT:
        fg = folium.FeatureGroup(name=f"📍 Viewport selection ({n})", show=True)
        for i in range(n):
            lat = lats[i]; lon = lons[i]
            if lat is None or lon is None:
                continue
            try:
                if pd.isna(lat) or pd.isna(lon):
                    continue
            except (TypeError, ValueError):
                continue
            uwi    = uwis[i]
            name   = names[i]
            status = statuses[i]
            color  = colors[i]
            popup_html = (
                f'<div data-uwi="{uwi}">'
                f'<b style="font-size:13px">{name}</b><br>'
                f'<span style="font-family:monospace;font-size:10px;color:#888">{uwi}</span>'
                f'<hr style="margin:4px 0">'
                f'<small>{ops[i]} &middot; {fields[i]}<br>'
                f'<b style="color:{color}">{status}</b>'
                f' &middot; Spud {spuds[i]} &middot; TD {tds[i]}</small>'
                f'<hr style="margin:4px 0">'
                f'<span style="font-size:12px;color:#1a73e8;font-weight:600">'
                f'📋 Open Scout Ticket &amp; Add to Tray</span>'
                f'</div>'
            )

            # INVISIBLE hit target — radius 14px, fully transparent.
            # Carries the popup and tooltip (label) so clicks within ~14px of
            # the well center reliably trigger.
            label_text = _label_for(i)
            hit = folium.CircleMarker(
                location=[float(lat), float(lon)],
                radius=14,
                color="#000000",
                weight=0,
                stroke=False,
                fill=True,
                fill_color="#000000",
                fill_opacity=0.0,    # fully transparent
                opacity=0.0,
                popup=folium.Popup(popup_html, max_width=300),
            )
            # Permanent tooltip = the visible label
            if label_text:
                hit.add_child(folium.Tooltip(
                    label_text,
                    permanent=True,
                    direction="right",
                    offset=(8, 0),
                    class_name="dv-vp-label"  # CSS hides these when zoom < 11
                ))
            else:
                # No label → use a non-permanent tooltip with the well name
                # for hover feedback only
                hit.add_child(folium.Tooltip(name or uwi, sticky=True))
            hit.add_to(fg)

            # VISIBLE marker — small yellow-ringed dot on top of the hit target
            folium.CircleMarker(
                location=[float(lat), float(lon)],
                radius=6,
                color="#ffeb3b",   # yellow ring distinguishes from cluster bubbles
                weight=2,
                fill=True,
                fill_color=color,
                fill_opacity=0.95,
                opacity=1,
            ).add_to(fg)
        fg.add_to(m)
        return n

    # ── LARGE: JS path via FastMarkerCluster (disableClusteringAtZoom:0)
    # Markers render individually from zoom 0; the cluster engine is just
    # acting as a fast batch renderer. ~10K markers in 1-2 seconds vs
    # 90+ seconds for the Python loop.
    # Note: dual-marker pattern omitted in JS path to keep payload small.
    # Hit area is single 6px radius — slightly less generous than Python path.
    data = []
    for i in range(n):
        lat = lats[i]; lon = lons[i]
        if lat is None or lon is None:
            continue
        try:
            if pd.isna(lat) or pd.isna(lon):
                continue
        except (TypeError, ValueError):
            continue
        data.append([
            float(lat), float(lon),
            colors[i], uwis[i], names[i], statuses[i],
            ops[i], fields[i], spuds[i], tds[i],
            _label_for(i) or ""   # 11th column: label text (empty = no label)
        ])
    if not data:
        return 0

    callback = """
        function(row) {
            var lat=row[0], lon=row[1], color=row[2], uwi=row[3],
                name=row[4], status=row[5], op=row[6],
                field=row[7], spud=row[8], td=row[9], lbl=row[10];
            var popup = '<div data-uwi="' + uwi + '">'
                + '<b style="font-size:13px">' + name + '</b><br>'
                + '<span style="font-family:monospace;font-size:10px;color:#888">' + uwi + '</span>'
                + '<hr style="margin:4px 0">'
                + '<small>'
                + op + ' &middot; ' + field + '<br>'
                + '<b style="color:' + color + '">' + status + '</b>'
                + ' &middot; Spud ' + spud + ' &middot; TD ' + td
                + '</small>'
                + '<hr style="margin:4px 0">'
                + '<span style="font-size:12px;color:#1a73e8;font-weight:600">'
                + '📋 Open Scout Ticket &amp; Add to Tray'
                + '</span>'
                + '</div>';
            var marker = L.circleMarker(
                new L.LatLng(lat, lon),
                {radius:6, fillColor:color, color:'#ffeb3b',
                 weight:2, opacity:1, fillOpacity:0.95}
            );
            marker.bindPopup(popup, {maxWidth:300});
            if (lbl && lbl.length > 0) {
                // Permanent label — CSS hides at zoom < 11
                marker.bindTooltip(lbl, {
                    permanent: true,
                    direction: 'right',
                    offset: [8, 0],
                    className: 'dv-vp-label'
                });
            } else {
                marker.bindTooltip(name || uwi, {sticky: true});
            }
            return marker;
        }
    """

    try:
        from folium.plugins import FastMarkerCluster
        FastMarkerCluster(
            data,
            callback=callback,
            name=f"📍 Viewport selection ({n})",
            options={
                "maxClusterRadius":          1,    # effectively no clustering
                "disableClusteringAtZoom":   0,    # never cluster, render individuals
                "spiderfyOnMaxZoom":         False,
                "showCoverageOnHover":       False,
                "zoomToBoundsOnClick":       False,
                "chunkedLoading":            True, # render incrementally
            },
        ).add_to(m)
    except ImportError:
        # If FastMarkerCluster unavailable, fall back to slow Python path
        # with a warning (this should be rare — folium.plugins ships with folium)
        st.warning("FastMarkerCluster unavailable — viewport may render slowly.")
        # Recursive call using the small path won't work because n > limit, so
        # build a plain FeatureGroup manually
        fg = folium.FeatureGroup(name=f"📍 Viewport selection ({n})", show=True)
        for r in data:
            lat, lon, color, uwi, name, status, op, field, spud, td, lbl = r
            popup_html = (
                f'<div data-uwi="{uwi}"><b>{name}</b><br>'
                f'<span style="font-family:monospace;font-size:10px;color:#888">{uwi}</span>'
                f'<hr style="margin:4px 0"><small>{op} &middot; {field}<br>'
                f'<b style="color:{color}">{status}</b> &middot; Spud {spud} &middot; TD {td}</small>'
                f'<hr style="margin:4px 0">'
                f'<span style="font-size:12px;color:#1a73e8;font-weight:600">'
                f'📋 Open Scout Ticket &amp; Add to Tray</span></div>'
            )
            cm = folium.CircleMarker(
                location=[lat, lon], radius=6, color="#ffeb3b", weight=2,
                fill=True, fill_color=color, fill_opacity=0.95, opacity=1,
                popup=folium.Popup(popup_html, max_width=300),
            )
            if lbl:
                cm.add_child(folium.Tooltip(
                    lbl, permanent=True, direction="right",
                    offset=(8, 0), class_name="dv-vp-label"))
            else:
                cm.add_child(folium.Tooltip(name or uwi, sticky=True))
            cm.add_to(fg)
        fg.add_to(m)
    return n



    if df.empty:
        return
    gj = _trajectory_geojson(df)
    if not gj["features"]:
        return
    folium.GeoJson(
        gj, name="📐 Well Trajectories",
        style_function=lambda _: {"color":"#00BCD4","weight":2,"opacity":0.8},
        tooltip=folium.GeoJsonTooltip(
            fields=["well_name","stations","td_ft"],
            aliases=["Well","Stations","TD (ft)"], sticky=True),
        popup=folium.GeoJsonPopup(
            fields=["well_name","uwi","stations","td_ft"],
            aliases=["Well","UWI","Stations","TD MD (ft)"], max_width=280),
    ).add_to(m)


def _add_formation_tops(m, df):
    if df.empty:
        return
    fg = folium.FeatureGroup(name="📏 Formation Tops", show=False)
    for _, row in df.iterrows():
        fluid = str(row.get("fluid_type") or "").upper()
        color = {"OIL":"#4CAF50","GAS":"#FF9800","OIL/GAS":"#CDDC39",
                 "WATER":"#2196F3"}.get(fluid, "#9C27B0")
        depth = row.get("top_depth")
        depth_str = f"{depth:,.0f} ft" if pd.notna(depth) else "—"
        net = row.get("net_thickness")
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=5, color=color, weight=1,
            fill=True, fill_color=color, fill_opacity=0.7,
            popup=folium.Popup(
                f"<b>{row.get('formation','—')}</b><br>"
                + _popup_table({
                    "Well":    row.get("well_name","—"),
                    "Top MD":  depth_str,
                    "Net Pay": f"{net:,.1f} ft" if pd.notna(net) else "—",
                    "Fluid":   fluid or "—",
                }), max_width=220),
            tooltip=f"{row.get('formation','?')} @ {depth_str}",
        ).add_to(fg)
    fg.add_to(m)


def _add_dst(m, df):
    if df.empty:
        return
    fg = folium.FeatureGroup(name="🧪 DST Intervals", show=False)
    for _, row in df.iterrows():
        result = str(row.get("test_result") or "").upper()
        color  = {"PRODUCTIVE":"#4CAF50","NON-PRODUCTIVE":"#E24B4A",
                  "GAS":"#FF9800","SHOWS":"#CDDC39"}.get(result, "#9C27B0")
        oil = row.get("max_oil_rate")
        gas = row.get("max_gas_rate")
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=8, color=color, weight=2,
            fill=True, fill_color=color, fill_opacity=0.6,
            popup=folium.Popup(
                f"<b>DST — {row.get('well_name','—')}</b><br>"
                + _popup_table({
                    "Type":     row.get("test_type","—"),
                    "Interval": f"{row.get('top_depth','?')} – {row.get('base_depth','?')} ft",
                    "Result":   result or "—",
                    "Oil":      f"{oil:,.0f} BOPD" if pd.notna(oil) and oil else "—",
                    "Gas":      f"{gas:,.0f} Mcf/d" if pd.notna(gas) and gas else "—",
                    "Date":     str(row.get("test_date",""))[:10],
                }), max_width=260),
            tooltip=f"DST: {result or '?'}",
        ).add_to(fg)
    fg.add_to(m)


def _add_production_bubbles(m, df):
    if df.empty:
        return
    fg = folium.FeatureGroup(name="📈 Production Bubbles", show=False)
    import math
    max_oil = float(df["cum_oil"].max() or 1)
    min_oil = float(df["cum_oil"].min() or 0)
    for _, row in df.iterrows():
        cum_oil = float(row.get("cum_oil") or 0)
        # Square root scaling gives better visual spread for narrow ranges
        if max_oil > min_oil:
            norm   = (cum_oil - min_oil) / (max_oil - min_oil)
        else:
            norm   = 0.5
        radius = 6 + math.sqrt(norm) * 24  # range: 6-30px
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius, color="#1B5E20", weight=1,
            fill=True, fill_color="#4CAF50", fill_opacity=0.55,
            popup=folium.Popup(
                f"<b>{row.get('well_name','—')}</b><br>"
                + _popup_table({
                    "Cum Oil":   f"{cum_oil:,.0f} bbl",
                    "Cum Gas":   f"{float(row.get('cum_gas') or 0):,.0f} Mcf",
                    "Cum Water": f"{float(row.get('cum_water') or 0):,.0f} bbl",
                    "Months":    str(int(row.get("months") or 0)),
                }), max_width=220),
            tooltip=f"Cum oil: {cum_oil:,.0f} bbl",
        ).add_to(fg)
    fg.add_to(m)


def _add_fields(m, df):
    if df.empty:
        return
    fg = folium.FeatureGroup(name="🌿 Fields", show=False)
    for _, row in df.iterrows():
        folium.Marker(
            location=[row["lat"], row["lon"]],
            icon=folium.Icon(color="green", icon="leaf", prefix="fa"),
            popup=folium.Popup(
                f"<b>{row.get('field_name','—')}</b><br>"
                + _popup_table({"Type": row.get("field_type","—"),
                                "Country": row.get("country_code","—")}),
                max_width=200),
            tooltip=row.get("field_name","—"),
        ).add_to(fg)
    fg.add_to(m)


def _add_basins(m, df):
    if df.empty:
        return
    fg = folium.FeatureGroup(name="🏔 Basins", show=False)
    for _, row in df.iterrows():
        area = row.get("area_km2")
        folium.Marker(
            location=[row["lat"], row["lon"]],
            icon=folium.Icon(color="orange", icon="globe", prefix="fa"),
            popup=folium.Popup(
                f"<b>{row.get('basin_name','—')}</b><br>"
                + _popup_table({
                    "Type":    row.get("basin_type","—"),
                    "Country": row.get("country_code","—"),
                    "Area":    f"{area:,.0f} km²" if pd.notna(area) else "—",
                    "Play":    row.get("primary_play_type","—"),
                }), max_width=240),
            tooltip=row.get("basin_name","—"),
        ).add_to(fg)
    fg.add_to(m)


def _add_shapefile_layer(m, engine, layer):
    source_type  = layer.get("source_type","GEOJSON")
    layer_name   = layer.get("layer_name","Layer")
    color        = layer.get("style_color")        or "#888888"
    weight       = float(layer.get("style_weight")      or 1.5)
    opacity      = float(layer.get("style_opacity")     or 0.8)
    fill_color   = layer.get("style_fill_color")   or color
    fill_opacity = float(layer.get("style_fill_opacity") or 0.0)
    dash         = layer.get("style_dash")
    tt_fields    = [f.strip() for f in
                    (layer.get("tooltip_fields") or "").split(",") if f.strip()]

    gj = None
    if source_type == "SHAPEFILE":
        fpath = layer.get("file_path","")
        if fpath and os.path.exists(fpath) and HAS_GPD:
            try:
                gdf = gpd.read_file(fpath).to_crs("EPSG:4326")
                gj  = json.loads(gdf.to_json())
            except Exception:
                return
        else:
            return
    else:
        gj_str = _cached_layer_geojson(engine, layer["layer_id"])
        if not gj_str:
            return
        try:
            gj = json.loads(gj_str)
        except Exception:
            return

    if not gj:
        return

    icon_ch = LAYER_CATEGORY_DISPLAY.get(layer.get("layer_category",""), "📁").split()[0]

    def _style(_, c=color, w=weight, o=opacity,
               fc=fill_color, fo=fill_opacity, d=dash):
        s = {"color":c,"weight":w,"opacity":o,"fillColor":fc,"fillOpacity":fo}
        if d:
            s["dashArray"] = d
        return s

    kw = {"name": f"{icon_ch} {layer_name}", "style_function": _style}
    if tt_fields:
        sample = (gj.get("features") or [{}])[0].get("properties",{})
        valid  = [f for f in tt_fields if f in sample]
        if valid:
            kw["tooltip"] = folium.GeoJsonTooltip(fields=valid, sticky=True)
            kw["popup"]   = folium.GeoJsonPopup(fields=valid, max_width=300)
    folium.GeoJson(gj, **kw).add_to(m)


# =============================================================================
# WELL DETAIL PANEL
# =============================================================================

def _fluid_color(fluid):
    f = str(fluid or "").upper()
    c = {"OIL":"#1b5e20","GAS":"#e65100","WATER":"#0d47a1"}.get(f,"#555")
    return f"<span style='color:{c};font-weight:600'>{fluid or chr(8212)}</span>"


def _fmt(v, fmt=",", suffix=""):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return chr(8212)
    try:
        if fmt == ",":   return f"{float(v):,.0f}{suffix}"
        if fmt == ",.1": return f"{float(v):,.1f}{suffix}"
        if fmt == ",.2": return f"{float(v):,.2f}{suffix}"
        return str(v)
    except Exception:
        return str(v)


def _th(cells, bg="#475569"):
    """Column header row — slate-600 by default."""
    tds = "".join(
        f"<th style='background:{bg};color:#ffffff;padding:8px 12px;"
        f"font-size:12px;font-weight:700;text-align:left;letter-spacing:0.3px;"
        f"border-right:1px solid #64748b;border-bottom:1px solid #1e293b'>{c}</th>"
        for c in cells
    )
    return f"<tr>{tds}</tr>"


def _td(cells, alt=False):
    """Body cell row — white or slate-100 alt, near-black text."""
    bg = "#f1f5f9" if alt else "#ffffff"
    tds = "".join(
        f"<td style='background:{bg};color:#1e293b;padding:7px 12px;"
        f"font-size:13px;border-bottom:1px solid #cbd5e1;"
        f"border-right:1px solid #cbd5e1;white-space:nowrap'>{c}</td>"
        for c in cells
    )
    return f"<tr>{tds}</tr>"


def _section(title):
    """Section divider bar — slate-700, white text."""
    return (f"<div style='background:#334155;color:#ffffff;padding:8px 14px;"
            f"font-size:13px;font-weight:700;margin-top:10px;letter-spacing:0.3px;"
            f"border-radius:3px 3px 0 0'>{title}</div>")


def _tbl(rows):
    """Table wrapper — soft slate border."""
    return (f"<table style='width:100%;border-collapse:collapse;"
            f"border:1px solid #cbd5e1;margin-bottom:0;background:#ffffff'>{rows}</table>")


def _full_html_doc(html_body: str, title: str = "Scout Tickets") -> str:
    """Wrap scout ticket HTML in a full printable document with print/save buttons."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="color-scheme" content="light">
<title>{title}</title>
<style>
@page {{size:A4;margin:15mm 12mm;}}
html, body {{background:#ffffff;color:#1e293b;color-scheme:light;}}
body {{font-family:Arial,Helvetica,sans-serif;font-size:10px;margin:0;padding:0;}}
table {{width:100%;border-collapse:collapse;background:#ffffff;}}
th {{background:#475569;color:#ffffff;padding:8px 12px;font-size:11px;font-weight:700;
     text-align:left;letter-spacing:0.3px;border-right:1px solid #64748b;}}
td {{padding:6px 12px;font-size:11px;background:#ffffff;color:#1e293b;
     border-bottom:1px solid #cbd5e1;border-right:1px solid #cbd5e1;}}
tr:nth-child(even) td {{background:#f1f5f9;}}
.sh {{background:#334155;color:#ffffff;padding:8px 14px;font-size:12px;
      font-weight:700;margin-top:10px;letter-spacing:0.3px;}}
.no-print {{
    position:fixed;top:12px;right:16px;z-index:9999;
    display:flex;gap:8px;
}}
.no-print button {{
    background:#334155;color:#fff;border:none;border-radius:6px;
    padding:8px 18px;font-size:13px;font-weight:600;cursor:pointer;
    box-shadow:0 2px 4px rgba(0,0,0,0.15);
}}
.no-print button:hover {{background:#1e293b;}}
@media print {{.no-print{{display:none;}}}}
</style>
</head>
<body>
<div class="no-print">
  <button onclick="window.print()">🖨 Print</button>
  <button onclick="window.close()">✕ Close</button>
</div>
{html_body}
</body></html>"""


def _scout_ticket_pdf(html_body, well_name):
    try:
        from weasyprint import HTML
        return HTML(string=_full_html_doc(html_body, well_name)).write_pdf()
    except Exception:
        return None


def _show_detail(uwi, well_row, counts_df, engine=None):
    st.markdown('<hr style="margin:4px 0 8px 0;border-top:1px solid #ccc">',
                unsafe_allow_html=True)
    html = _build_scout_ticket_html(uwi, well_row, engine)
    st.markdown(html, unsafe_allow_html=True)
    # PDF download
    dl_col, _ = st.columns([1, 4])
    with dl_col:
        if st.button("⬇ Download PDF", key=f"pdf_btn_{uwi}",
                     type="primary", use_container_width=True):
            with st.spinner("Generating PDF..."):
                pdf = _scout_ticket_pdf(html, well_row.get("well_name", uwi))
            if pdf:
                st.download_button("📄 Save PDF", data=pdf,
                    file_name=f"Scout_{well_row.get('well_name',uwi).replace(' ','_')}.pdf",
                    mime="application/pdf",
                    key=f"pdf_dl_{uwi}", use_container_width=True)
            else:
                st.error("PDF generation failed — pip install weasyprint")

def _dst_result_color(result):
    r = str(result or "").upper()
    c = {"SHOW":"#1b5e20","MISS":"#c62828","INC":"#e65100","TRACE":"#e65100"}.get(r,"#555")
    return f"<b style='color:{c}'>{result or chr(8212)}</b>"


def _photo_to_b64(file_path: str) -> str:
    import base64
    from pathlib import Path
    try:
        p = Path(file_path)
        if p.exists():
            return base64.b64encode(p.read_bytes()).decode()
    except Exception:
        pass
    return ""


def _photos_html(photos_df) -> str:
    if photos_df.empty:
        return "<div style='padding:6px 12px;font-size:12px;color:#999;background:#fff'>No photos registered</div>"
    cards = []
    for _, r in photos_df.iterrows():
        b64 = _photo_to_b64(r.get("file_path",""))
        if not b64:
            continue
        ext  = str(r.get("file_path","")).split(".")[-1].lower()
        mime = "image/jpeg" if ext in ("jpg","jpeg") else f"image/{ext}"
        td   = r.get("top_depth"); bd = r.get("base_depth")
        dep  = (f"{td:.0f}–{bd:.0f} ft" if pd.notna(td) and td and pd.notna(bd) and bd
                else f"{td:.0f} ft" if pd.notna(td) and td else "")
        lbl  = f"{r.get('photo_type','')} · {r.get('lighting','')} · {dep}"
        cards.append(
            f"<div style='display:inline-block;margin:4px;vertical-align:top;text-align:center'>"
            f"<img src='data:{mime};base64,{b64}' "
            f"style='max-width:320px;max-height:160px;border:1px solid #dde;"
            f"border-radius:4px;display:block'/>"
            f"<div style='font-size:10px;color:#666;margin-top:2px'>{lbl}</div>"
            f"</div>"
        )
    if not cards:
        return "<div style='padding:6px 12px;font-size:12px;color:#999;background:#fff'>Photos on file but not found on disk</div>"
    return ("<div style='background:#fff;padding:8px;overflow-x:auto;white-space:nowrap'>"
            + "".join(cards) + "</div>")


def _build_scout_ticket_html(uwi, well_row, engine=None):
    """Build scout ticket HTML for one well."""
    tops_df = srvy_df = comp_df = prod_df = pd.DataFrame()
    dst_df  = core_df = core_sample_df = photos_df = pd.DataFrame()

    if engine is not None:
        def _q(sql, params):
            try:
                with engine.connect() as con:
                    return pd.read_sql(text(sql), con, params=params)
            except Exception:
                return pd.DataFrame()

        tops_df = _q("SELECT strat_unit_name, top_depth, base_depth, fluid_type, net_thickness FROM dataview.dv_well_formation_top WHERE uwi=:u ORDER BY top_depth", {"u": uwi})
        srvy_df = _q("SELECT TOP 15 s.md, s.incl, s.azim, s.tvd, s.ns_offset, s.ew_offset, s.dls FROM dataview.dv_well_dir_srvy_sta s WHERE s.uwi=:u ORDER BY s.md", {"u": uwi})
        comp_df = _q("""SELECT c.completion_date, c.lateral_length, s.num_stages,
                   s.total_fluid_bbl, s.total_proppant_lbs,
                   s.cluster_spacing_ft, s.max_treatment_pressure_psi
            FROM dataview.dv_well_completion c
            LEFT JOIN dataview.dv_well_stimulation s
              ON s.uwi=c.uwi AND s.completion_id=c.completion_id
            WHERE c.uwi=:u ORDER BY c.completion_date DESC""", {"u": uwi})
        dst_df  = _q("""SELECT test_date, test_type, top_depth, base_depth,
                   test_result, max_oil_rate, max_gas_rate, api_gravity
            FROM dataview.dv_well_dst WHERE uwi=:u ORDER BY test_date""", {"u": uwi})
        core_df = _q("""SELECT core_num, core_type, core_show, strat_unit_name,
                   top_depth, base_depth, core_length, recovery_length,
                   recovery_pct, core_date, photo_count
            FROM dataview.dv_well_core WHERE uwi=:u ORDER BY top_depth""", {"u": uwi})
        core_sample_df = _q("""SELECT sample_id, sample_type, sample_depth,
                   lithology, hydrocarbon_show,
                   porosity_frac  * 100.0        porosity_pct,
                   permeability_air_md            permeability_md,
                   bulk_density_g_cc              bulk_density,
                   water_saturation_frac * 100.0  water_saturation,
                   oil_saturation_frac  * 100.0   oil_saturation
            FROM dataview.dv_well_core_sample
            WHERE uwi=:u ORDER BY sample_depth""", {"u": uwi})
        photos_df = _q("""SELECT photo_type, lighting, file_path, file_name,
                   top_depth, base_depth, tray_num
            FROM dataview.dv_well_core_photo
            WHERE uwi=:u AND active_ind='Y'
            ORDER BY tray_num, photo_type""", {"u": uwi})
        prod_df = _q("""
            SELECT pv.period_date prod_date,
                   SUM(CASE WHEN pv.fluid_type='OIL'   THEN ISNULL(pv.volume,0) ELSE 0 END) oil_vol,
                   SUM(CASE WHEN pv.fluid_type='GAS'   THEN ISNULL(pv.volume,0) ELSE 0 END) gas_vol,
                   SUM(CASE WHEN pv.fluid_type='WATER' THEN ISNULL(pv.volume,0) ELSE 0 END) water_vol,
                   MAX(pv.avg_daily_rate) avg_rate
            FROM dataview.dv_prod_volume pv
            JOIN dataview.dv_prod_entity pe ON pe.prod_entity_id=pv.prod_entity_id
            WHERE pe.uwi=:u
            GROUP BY pv.period_date ORDER BY pv.period_date""", {"u": uwi})

    status       = well_row.get("well_status","")
    status_color = STATUS_COLORS.get(str(status).upper(), "#888")
    td  = well_row.get("final_td")
    lat = well_row.get("lat"); lon = well_row.get("lon")
    loc = (f"{lat:.6f}N  {abs(lon):.6f}W"
           if pd.notna(lat) and lat else chr(8212))

    html = f"""
    <div style='font-family:Arial,Helvetica,sans-serif;border:2px solid #334155;
                border-radius:8px;overflow:hidden;margin-bottom:8px;
                background:#ffffff;color:#1e293b'>
      <div style='background:#334155;color:#ffffff;padding:14px 18px;
                  border-bottom:4px solid {status_color};
                  display:flex;justify-content:space-between;align-items:center'>
        <div>
          <div style='font-size:17px;font-weight:700;letter-spacing:1.5px;color:#ffffff'>WELL SCOUT TICKET</div>
          <div style='font-size:12px;color:#cbd5e1;margin-top:2px'>DataView &nbsp;·&nbsp; {well_row.get("operator_name","")}</div>
        </div>
        <span style='background:{status_color};color:#ffffff;padding:4px 14px;
              border-radius:12px;font-size:12px;font-weight:700;letter-spacing:0.5px;
              border:1px solid rgba(255,255,255,0.25)'>{status}</span>
      </div>

      {_section("Well Header")}
      {_tbl(
        _th(["API","Well Name","Well Type","Status"]) +
        _td([well_row.get("api_num",chr(8212)),
             f"<b>{well_row.get('well_name', uwi)}</b>",
             well_row.get("well_type",chr(8212)),
             f"<span style='color:{status_color};font-weight:600'>{status}</span>"]) +
        _th(["Operator","Field","County","State"]) +
        _td([well_row.get("operator_name",chr(8212)), well_row.get("field_name",chr(8212)),
             well_row.get("county",chr(8212)), well_row.get("province_state",chr(8212))], alt=True) +
        _th(["Spud Date","Completion Date","Total Depth MD","Surface Location"]) +
        _td([str(well_row.get("spud_date",""))[:10] or chr(8212),
             str(well_row.get("completion_date",""))[:10] or chr(8212),
             f"{_fmt(td)} ft", loc]) +
        _th(["UWI","KB Elevation","Depth Datum",""]) +
        _td([f"<span style='font-family:monospace'>{uwi}</span>",
             f"{_fmt(well_row.get('kb_elevation'))} ft",
             well_row.get("depth_datum","KB"), ""], alt=True)
      )}

      {_section("Stratigraphy — Formation Tops")}
      {_tbl(_th(["Formation","Top MD (ft)","Base MD (ft)","Net Pay (ft)","Fluid"]) +
        ("".join(_td([f"<b>{r.get('strat_unit_name',chr(8212))}</b>",
                      _fmt(r.get("top_depth")), _fmt(r.get("base_depth")),
                      _fmt(r.get("net_thickness")), _fluid_color(r.get("fluid_type"))],
                     alt=i%2==0) for i, r in tops_df.iterrows())
         if not tops_df.empty else _td(["No formation tops loaded","","","",""]))
      )}

      {_section("Directional Survey" + (f" — first {len(srvy_df)} stations" if not srvy_df.empty else ""))}
      {_tbl(_th(["MD (ft)","Inc","Azi","TVD (ft)","N/S (ft)","E/W (ft)","DLS"]) +
        ("".join(_td([_fmt(r.get("md")), _fmt(r.get("incl"),",.2"),
                      _fmt(r.get("azim"),",.2"), _fmt(r.get("tvd")),
                      _fmt(r.get("ns_offset")), _fmt(r.get("ew_offset")),
                      _fmt(r.get("dls"),",.2")], alt=i%2==0)
                 for i, r in srvy_df.iterrows())
         if not srvy_df.empty else _td(["No survey data","","","","","",""]))
      )}

      {_section("DST — Drill Stem Tests")}
      {_tbl(_th(["Test Date","Type","Top MD (ft)","Base MD (ft)",
                  "Result","Max Oil (bbl/d)","Max Gas (Mcf/d)","API Gravity"]) +
        ("".join(_td([str(r.get("test_date",""))[:10], r.get("test_type","—"),
                      _fmt(r.get("top_depth")), _fmt(r.get("base_depth")),
                      _dst_result_color(r.get("test_result")),
                      _fmt(r.get("max_oil_rate")), _fmt(r.get("max_gas_rate")),
                      _fmt(r.get("api_gravity"),",.1")], alt=i%2==0)
                 for i, r in dst_df.iterrows())
         if not dst_df.empty else _td(["No DST data","","","","","","",""]))
      )}

      {_section("Core Runs")}
      {_tbl(_th(["#","Type","Formation","Show","Top MD (ft)","Base MD (ft)",
                  "Length (ft)","Recovery (%)","Date","Photos"]) +
        ("".join(_td([str(r.get("core_num","—")), r.get("core_type","—"),
                      r.get("strat_unit_name","—"), r.get("core_show","—"),
                      _fmt(r.get("top_depth")), _fmt(r.get("base_depth")),
                      _fmt(r.get("core_length"),",.1"),
                      _fmt(r.get("recovery_pct"),",.1"),
                      str(r.get("core_date",""))[:10],
                      str(int(r.get("photo_count") or 0))], alt=i%2==0)
                 for i, r in core_df.iterrows())
         if not core_df.empty else _td(["No core data","","","","","","","","",""]))
      )}

      {_section("Core Sample Analysis")}
      {_tbl(_th(["Sample","Depth (ft)","Type","Por (%)","Perm (mD)",
                  "Bulk Den.","Sw (%)","So (%)","Lithology","Show"]) +
        ("".join(_td([str(r.get("sample_id","—")),
                      _fmt(r.get("sample_depth"),",.1"),
                      r.get("sample_type","—"),
                      _fmt(r.get("porosity_pct"),",.2"),
                      _fmt(r.get("permeability_md"),",.4"),
                      _fmt(r.get("bulk_density"),",.3"),
                      _fmt(r.get("water_saturation"),",.1"),
                      _fmt(r.get("oil_saturation"),",.1"),
                      r.get("lithology","—"),
                      r.get("hydrocarbon_show","—")], alt=i%2==0)
                 for i, r in core_sample_df.iterrows())
         if not core_sample_df.empty else _td(["No sample data","","","","","","","","",""]))
      )}

      {_section("Core Photographs")}
      {_photos_html(photos_df)}

      {_section("Completion Summary")}
      {_tbl(_th(["Completion Date","Lateral (ft)","Stages","Fluid (bbl)",
                  "Proppant (lbs)","Cluster Spacing (ft)","Max Pressure (psi)"]) +
        (_td([str(comp_df.iloc[0].get("completion_date",""))[:10],
              _fmt(comp_df.iloc[0].get("lateral_length")),
              _fmt(comp_df.iloc[0].get("num_stages")),
              _fmt(comp_df.iloc[0].get("total_fluid_bbl")),
              _fmt(comp_df.iloc[0].get("total_proppant_lbs")),
              _fmt(comp_df.iloc[0].get("cluster_spacing_ft")),
              _fmt(comp_df.iloc[0].get("max_treatment_pressure_psi"))])
         if not comp_df.empty else _td(["No completion data","","","","","",""]))
      )}

      {_section("Production Summary")}
      {_tbl(_th(["Date","Oil (bbl)","Gas (Mcf)","Water (bbl)","Avg Rate"]) +
        ("".join(_td([str(r.get("prod_date",""))[:10],
                      _fmt(r.get("oil_vol")), _fmt(r.get("gas_vol")),
                      _fmt(r.get("water_vol")), _fmt(r.get("avg_rate"))],
                     alt=i%2==0) for i, r in prod_df.iterrows()) +
         _td([f"<b>CUMULATIVE ({len(prod_df)} months)</b>",
              f"<b>{_fmt(prod_df['oil_vol'].sum())}</b>",
              f"<b>{_fmt(prod_df['gas_vol'].sum())}</b>",
              f"<b>{_fmt(prod_df['water_vol'].sum())}</b>",""])
         if not prod_df.empty else _td(["No production data","","","",""]))
      )}

      <div style='background:#334155;color:#cbd5e1;font-size:10px;
                  padding:6px 14px;text-align:center;letter-spacing:0.5px'>
        CONFIDENTIAL &nbsp;|&nbsp; {well_row.get("operator_name","")}
        &nbsp;|&nbsp; {well_row.get("well_name", uwi)}
        &nbsp;|&nbsp; DataView Scout Ticket
      </div>
    </div>"""
    return html


def _build_batch_pdf(selected_uwis, wells_df, engine):
    """Generate a multi-well PDF with one scout ticket per well."""
    all_html = ""
    for uwi in selected_uwis:
        rows = wells_df[wells_df["uwi"] == uwi]
        if rows.empty:
            continue
        all_html += _build_scout_ticket_html(uwi, rows.iloc[0], engine)
    return _scout_ticket_pdf(all_html, f"{len(selected_uwis)} wells")


def _build_export_excel(selected_uwis, wells_df, engine):
    """Build a multi-sheet Excel workbook matching the scout ticket sections."""
    import io
    buf  = io.BytesIO()
    w_df = wells_df[wells_df["uwi"].isin(selected_uwis)].copy()
    w_df = w_df.drop(columns=["lat","lon"], errors="ignore")
    tops_df = srvy_df = comp_df = stim_df = prod_df = pd.DataFrame()
    if engine is not None and selected_uwis:
        ph     = ",".join([f":u{i}" for i in range(len(selected_uwis))])
        params = {f"u{i}": u for i, u in enumerate(selected_uwis)}
        def _q(sql):
            try:
                with engine.connect() as con:
                    return pd.read_sql(text(sql), con, params=params)
            except Exception:
                return pd.DataFrame()
        tops_df = _q(f"SELECT uwi, strat_unit_name formation, top_depth, base_depth, net_thickness, fluid_type FROM dataview.dv_well_formation_top WHERE uwi IN ({ph}) ORDER BY uwi, top_depth")
        srvy_df = _q(f"SELECT s.uwi, s.md, s.incl, s.azim, s.tvd, s.ns_offset, s.ew_offset, s.dls FROM dataview.dv_well_dir_srvy_sta s WHERE s.uwi IN ({ph}) ORDER BY s.uwi, s.md")
        comp_df = _q(f"""SELECT c.uwi, c.completion_date, c.lateral_length,
                   s.num_stages, s.total_fluid_bbl, s.total_proppant_lbs,
                   s.cluster_spacing_ft, s.max_treatment_pressure_psi
            FROM dataview.dv_well_completion c
            LEFT JOIN dataview.dv_well_stimulation s ON s.uwi=c.uwi AND s.completion_id=c.completion_id
            WHERE c.uwi IN ({ph}) ORDER BY c.uwi""")
        prod_df = _q(f"""SELECT pe.uwi, pv.period_date prod_date,
                   SUM(CASE WHEN pv.fluid_type='OIL'   THEN ISNULL(pv.volume,0) ELSE 0 END) oil_vol,
                   SUM(CASE WHEN pv.fluid_type='GAS'   THEN ISNULL(pv.volume,0) ELSE 0 END) gas_vol,
                   SUM(CASE WHEN pv.fluid_type='WATER' THEN ISNULL(pv.volume,0) ELSE 0 END) water_vol
            FROM dataview.dv_prod_volume pv
            JOIN dataview.dv_prod_entity pe ON pe.prod_entity_id=pv.prod_entity_id
            WHERE pe.uwi IN ({ph})
            GROUP BY pe.uwi, pv.period_date ORDER BY pe.uwi, pv.period_date""")
    try:
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            def _write(df, sheet):
                if df.empty:
                    pd.DataFrame({"Note":["No data"]}).to_excel(writer, sheet_name=sheet, index=False)
                else:
                    df.to_excel(writer, sheet_name=sheet, index=False)
                    ws = writer.sheets[sheet]
                    ws.freeze_panes = "A2"
                    for col in ws.columns:
                        w = max((len(str(c.value)) for c in col if c.value), default=8)
                        ws.column_dimensions[col[0].column_letter].width = min(w+2, 40)
            _write(w_df,    "Well Header")
            _write(tops_df, "Formation Tops")
            _write(srvy_df, "Directional Survey")
            _write(comp_df, "Completion Summary")
            _write(prod_df, "Production Summary")
    except Exception:
        return b""
    buf.seek(0)
    return buf.read()




# =============================================================================
# AI NATURAL LANGUAGE FILTER
# =============================================================================

def _ai_filter_wells(question: str, sample_wells: list[dict]) -> tuple[dict | None, str]:
    """
    Send a natural language question to Claude via anthropic SDK.
    Returns (filter_spec, error_message).
    """
    try:
        import anthropic

        # Build column summary from sample
        cols = {}
        for w in sample_wells[:20]:
            for k, v in w.items():
                if k not in cols:
                    cols[k] = type(v).__name__
        col_summary = ", ".join(f"{k} ({t})" for k, t in cols.items())

        statuses  = sorted({w.get("well_status","") for w in sample_wells if w.get("well_status")})
        wtypes    = sorted({w.get("well_type","")   for w in sample_wells if w.get("well_type")})
        operators = sorted({w.get("operator_name","") for w in sample_wells if w.get("operator_name")})[:10]
        counties  = sorted({w.get("county","")      for w in sample_wells if w.get("county")})[:15]

        system = (
            "You are a petroleum data filter assistant.\n"
            "Convert natural language questions into a JSON filter spec for well data.\n"
            "Return ONLY valid JSON — no explanation, no markdown, no backticks.\n\n"
            f"Available columns: {col_summary}\n\n"
            f"Sample values:\n"
            f"  well_status: {statuses}\n"
            f"  well_type: {wtypes}\n"
            f"  operator_name (sample): {operators}\n"
            f"  county (sample): {counties}\n\n"
            'Return this exact JSON structure:\n'
            '{\n'
            '  "filters": [\n'
            '    {"field": "<column_name>", "op": "<eq|ne|gt|gte|lt|lte|contains|in>", "value": <value>}\n'
            '  ],\n'
            '  "description": "<short human description of the filter>"\n'
            '}\n\n'
            "Rules:\n"
            "- Use exact column names from the available columns list\n"
            "- For text comparisons use uppercase values to match the data\n"
            "- contains is case-insensitive substring match\n"
            "- in value must be a list\n"
            "- final_td, lat, lon are numeric (float)\n"
            '- If the question cannot be answered, return {"filters": [], "description": "Could not interpret query"}'
        )

        import os
        from pathlib import Path
        # Try dotenv first
        try:
            from dotenv import load_dotenv
            # Explicitly find .env relative to this file
            _env = Path(__file__).parent / ".env"
            load_dotenv(_env if _env.exists() else None)
        except ImportError:
            pass
        # Manual fallback — read .env directly
        _api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not _api_key:
            _env_path = Path(__file__).parent / ".env"
            if _env_path.exists():
                for line in _env_path.read_text().splitlines():
                    if line.startswith("ANTHROPIC_API_KEY"):
                        _api_key = line.split("=", 1)[-1].strip().strip('"').strip("'")
                        break
        if not _api_key:
            return None, "ANTHROPIC_API_KEY not found in .env file"
        client = anthropic.Anthropic(api_key=_api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": question}],
        )
        text = msg.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        return json.loads(text), ""
    except Exception as e:
        return None, str(e)


def _apply_ai_filter(wells: list[dict], filter_spec: dict) -> list[dict]:
    """Apply filter spec returned by Claude to wells list."""
    filters = filter_spec.get("filters", [])
    if not filters:
        return wells

    result = []
    for w in wells:
        match = True
        for f in filters:
            field = f.get("field", "")
            op    = f.get("op", "eq")
            val   = f.get("value")
            wval  = w.get(field)

            # Numeric ops
            try:
                if op == "gt":  match = match and float(wval or 0) > float(val)
                elif op == "gte": match = match and float(wval or 0) >= float(val)
                elif op == "lt":  match = match and float(wval or 0) < float(val)
                elif op == "lte": match = match and float(wval or 0) <= float(val)
                elif op == "eq":
                    match = match and str(wval or "").upper() == str(val).upper()
                elif op == "ne":
                    match = match and str(wval or "").upper() != str(val).upper()
                elif op == "contains":
                    match = match and str(val).upper() in str(wval or "").upper()
                elif op == "in":
                    match = match and str(wval or "").upper() in [str(v).upper() for v in (val or [])]
            except Exception:
                pass
            if not match:
                break
        if match:
            result.append(w)
    return result

def _handle_catalog_file_download():
    """
    If the URL has ?open_file=<encoded_path>, serve that file as an
    auto-triggered download and redirect back to the map. The user sees
    a brief "Downloading..." flash then returns to the map; the file
    lands in their browser's Downloads folder.

    Security: only files that appear in the current catalog are allowed.
    Returns True if a download was served, False otherwise.
    """
    qp = st.query_params
    requested = qp.get("open_file")
    if not requested:
        return False

    try:
        from urllib.parse import unquote
        requested_path = unquote(str(requested)).strip()
    except Exception:
        return False

    if not requested_path:
        return False

    # Build the allowed-paths set from the catalog
    allowed = set()
    try:
        df_csv = _qry_catalog_csv()
        if df_csv is not None and not df_csv.empty:
            allowed.update(
                p.strip() for p in df_csv["file_path"].dropna().astype(str)
                if p.strip()
            )
    except Exception:
        pass

    def _norm(p: str) -> str:
        try:
            return str(Path(p).resolve()).lower()
        except Exception:
            return p.lower()

    requested_norm = _norm(requested_path)
    allowed_norm = {_norm(p) for p in allowed}

    if requested_norm not in allowed_norm:
        st.error(
            f"🚫 File access denied. The requested path is not in the "
            f"catalog and cannot be served.\n\n`{requested_path}`"
        )
        if st.button("← Back to map", key="dl_back_denied"):
            st.query_params.clear()
            st.rerun()
        st.stop()

    p = Path(requested_path)
    if not p.exists():
        st.error(
            f"📁 File not found at the catalog's recorded path:\n\n"
            f"`{requested_path}`\n\n"
            f"The file may have been moved or deleted since the catalog "
            f"was last refreshed."
        )
        if st.button("← Back to map", key="dl_back_missing"):
            st.query_params.clear()
            st.rerun()
        st.stop()

    # Read and serve. Plain Streamlit download_button — user clicks it
    # to send the file to their browser's Downloads folder. Browser
    # back-button returns them to the map (state is preserved).
    try:
        with open(p, "rb") as fh:
            data = fh.read()

        ext = p.suffix.lower()
        mime = {
            ".pdf":  "application/pdf",
            ".csv":  "text/csv",
            ".txt":  "text/plain",
            ".xls":  "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".doc":  "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".zip":  "application/zip",
        }.get(ext, "application/octet-stream")

        size_mb = p.stat().st_size / 1_048_576
        st.markdown(f"## 📥 `{p.name}`")
        st.caption(
            f"Path: `{p}`  ·  Size: {size_mb:,.2f} MB  ·  "
            f"Type: {p.suffix or '(no extension)'}"
        )

        st.download_button(
            label=f"⬇ Download {p.name}",
            data=data,
            file_name=p.name,
            mime=mime,
            key="dl_catalog_file",
            use_container_width=True,
            type="primary",
        )

        st.divider()
        st.caption("Use your browser's back button to return to the map.")
        if st.button("← Back to map", key="dl_back"):
            st.query_params.clear()
            st.rerun()
        st.stop()

    except Exception as e:
        st.error(f"Error serving file: {e}")
        if st.button("← Back to map", key="dl_back_err"):
            st.query_params.clear()
            st.rerun()
        st.stop()
    return True


def run(engine=None):
    if not HAS_FOLIUM:
        st.error("pip install folium streamlit-folium")
        return

    # If URL has ?open_file=<path>, serve the file and stop. This is the
    # back-end half of the catalog popup's "📥 Download" links.
    _handle_catalog_file_download()

    if engine is None:
        st.info("Connect to the DataView database first.")
        return

    _status = st.empty()

    _status.info("⏳ Querying wells from DataView…")
    _wells_raw = _qry_wells(engine)
    _status.info("⏳ Loading spatial layers…")
    shp_layers = _load_shp_layers(engine)
    _status.empty()
    # counts_df loaded lazily below — only when a "Has X" filter is active

    if not _wells_raw:
        st.warning("No wells found with valid coordinates.")
        return

    # Apply AI filter if active
    _ai_spec = st.session_state.get("ai_filter_spec")
    _display_wells = _apply_ai_filter(_wells_raw, _ai_spec) if _ai_spec else _wells_raw

    # Convert list-of-dicts to DataFrame once — all downstream code unchanged
    wells_df  = pd.DataFrame(_display_wells)
    uwi_index = {w["uwi"]: w for w in _wells_raw}  # full index for scout tickets

    # ── Top bar above map: Background | Zoom | Query | Labels ──────
    top1, top2, top3, top4 = st.columns([1, 1, 2, 1])
    with top1:
        basemap = st.selectbox("🖼 Background", list(BASEMAPS.keys()),
                               index=0, key="wm_basemap")
    with top2:
        try:
            zoom_targets = _qry_zoom_targets(engine)
        except Exception:
            zoom_targets = [{"label":"— Zoom to location —",
                             "lat":None,"lon":None,"zoom":7}]
        zoom_sel    = st.selectbox("🔍 Zoom to",
                                   [t["label"] for t in zoom_targets],
                                   index=0, key="wm_zoom_target")
        zoom_target = next((t for t in zoom_targets
                            if t["label"]==zoom_sel), None)
    with top3:
        QUERIES = {
            "All wells":None,"By operator":"operator","By field":"field",
            "By county":"county","By well type":"well_type",
            "Has formation tops":"has_tops","Has production data":"has_prod",
            "Has DST":"has_dst","Has directional survey":"has_survey",
            "Has core data":"has_core","Has petro interpretation":"has_petro",
        }
        qsel   = st.selectbox("📋 Query", list(QUERIES.keys()),
                              key="wm_query_sel")
        qtype  = QUERIES[qsel]
        qvalue = None
        if qtype == "operator":
            qvalue = st.selectbox("Operator",
                sorted(wells_df["operator_name"].dropna().unique()),
                key="wm_q_op", label_visibility="collapsed")
        elif qtype == "field":
            qvalue = st.selectbox("Field",
                sorted(wells_df["field_name"].dropna().unique()),
                key="wm_q_field", label_visibility="collapsed")
        elif qtype == "county":
            qvalue = st.selectbox("County",
                sorted(wells_df["county"].dropna().unique()),
                key="wm_q_county", label_visibility="collapsed")
        elif qtype == "well_type":
            qvalue = st.selectbox("Well Type",
                sorted(wells_df["well_type"].dropna().unique()),
                key="wm_q_wtype", label_visibility="collapsed")
    with top4:
        # Labels appear only on viewport-rendered wells (yellow-ringed markers)
        # and only when zoomed to >= 11 (county/township scale). Otherwise hidden.
        label_field = st.selectbox(
            "🏷 Label by",
            ["None", "Well name", "UWI", "Operator"],
            index=0, key="wm_label_field",
            help="Labels appear on viewport markers when zoomed in (zoom ≥ 11)."
        )

    # ── Left panel + map ─────────────────────────────────────────────
    ctrl, mapcol = st.columns([1, 3], gap="small")

    with ctrl:
        # ── AI Query ──────────────────────────────────────────────────
        _ai_open = bool(
            st.session_state.get("ai_filter_spec") or
            st.session_state.get("ai_filter_error") or
            st.session_state.get("ai_filter_desc")
        )
        with st.expander("🤖 AI Well Filter", expanded=_ai_open):
            st.caption("Ask anything about the wells — natural language.")
            _ai_q = st.text_area(
                "Question",
                key="wm_ai_question",
                label_visibility="collapsed",
                placeholder='e.g. "horizontal wells deeper than 10,000 ft in Loving County"',
                height=80,
            )
            _ai_col1, _ai_col2 = st.columns(2)
            if _ai_col1.button("🔍 Filter", key="wm_ai_run",
                               use_container_width=True, type="primary",
                               disabled=not _ai_q.strip()):
                st.session_state.pop("ai_filter_error", None)
                with st.spinner("Asking Claude…"):
                    _spec, _err = _ai_filter_wells(_ai_q.strip(), _wells_raw)
                if _spec is not None:
                    st.session_state["ai_filter_spec"] = _spec
                    st.session_state["ai_filter_desc"] = _spec.get("description", "")
                    st.session_state.pop("ai_filter_error", None)
                    st.rerun()
                else:
                    # Store error — don't rerun so user can read it
                    st.session_state["ai_filter_error"] = _err
            if _ai_col2.button("✕ Clear", key="wm_ai_clear",
                               use_container_width=True,
                               disabled="ai_filter_spec" not in st.session_state):
                st.session_state.pop("ai_filter_spec", None)
                st.session_state.pop("ai_filter_desc", None)
                st.session_state.pop("ai_filter_error", None)
                st.rerun()
            if st.session_state.get("ai_filter_error"):
                st.error(f"❌ {st.session_state['ai_filter_error']}")
            elif st.session_state.get("ai_filter_desc"):
                st.success(f"✅ {st.session_state['ai_filter_desc']}")

        # Status
        all_statuses = sorted(wells_df["well_status"].dropna().unique())
        for o in all_statuses:
            if f"wm_status_{o}" not in st.session_state:
                st.session_state[f"wm_status_{o}"] = True
        n_s = sum(1 for o in all_statuses
                  if st.session_state.get(f"wm_status_{o}", True))
        st.caption(f"🚦 Status ({n_s}/{len(all_statuses)})")
        sa, sb = st.columns(2)
        if sa.button("All",   key="wm_status_all",   use_container_width=True):
            for o in all_statuses: st.session_state[f"wm_status_{o}"] = True
            st.rerun()
        if sb.button("Clear", key="wm_status_clear", use_container_width=True):
            for o in all_statuses: st.session_state[f"wm_status_{o}"] = False
            st.rerun()
        sel_statuses = []
        for o in all_statuses:
            if st.checkbox(f"● {o}", key=f"wm_status_{o}"):
                sel_statuses.append(o)

        # ── Well picker — multiselect from filtered list ──────────────
        with st.expander("🔎 Add Wells to Tray", expanded=False):
            st.caption("Pick from filtered wells or draw a box on the map")
            _pick_opts = {
                f"{w.get('well_name','?')} — {w.get('operator_name','')}": w["uwi"]
                for w in _display_wells
            }
            _picked_labels = st.multiselect(
                "Select wells",
                options=list(_pick_opts.keys()),
                default=[],
                key="wm_well_picker",
                label_visibility="collapsed",
                placeholder="Search by well name or operator…",
            )
            if _picked_labels:
                if st.button("➕ Add to Tray", key="add_picked",
                             use_container_width=True, type="primary"):
                    for lbl in _picked_labels:
                        uwi = _pick_opts[lbl]
                        if uwi not in st.session_state.clicked_uwis:
                            st.session_state.clicked_uwis.append(uwi)
                    st.rerun()

        # Overlays
        active_db = set()
        with st.expander("💾 Overlays", expanded=False):
            if st.checkbox("📐 Trajectories",    key="wm_db_traj"):
                active_db.add("db_trajectories")
            if st.checkbox("📈 Prod Bubbles",    key="wm_db_prod"):
                active_db.add("db_production")
            if st.checkbox("🧪 DST Intervals",   key="wm_db_dst"):
                active_db.add("db_dst")
            if st.checkbox("📏 Formation Tops",  key="wm_db_tops"):
                active_db.add("db_formation_tops")
            if st.checkbox("📁 File Catalog",    key="wm_db_catalog",
                           help="Cataloged files (LAS, PDFs, etc.) as purple "
                                "square markers. Click for file list per UWI."):
                active_db.add("db_catalog")
            # Tiny refresh button for the catalog cache — useful after a
            # fresh File Catalog scan if you don't want to wait for the
            # 1-hour TTL to expire.
            if st.button("🔄 Refresh catalog cache", key="wm_refresh_catalog",
                         help="Re-read the catalog CSV / SQL now (overrides "
                              "the cache)."):
                _qry_catalog.clear()
                _qry_catalog_csv.clear()
                st.rerun()

        # Registered layers
        active_shp = []
        with st.expander("🗂 Registered Layers", expanded=True):
            if shp_layers:
                by_cat = defaultdict(list)
                for lay in shp_layers:
                    by_cat[lay["layer_category"]].append(lay)
                for cat, layers in sorted(by_cat.items()):
                    cat_label = LAYER_CATEGORY_DISPLAY.get(
                        cat, f"📁 {cat.title()}")
                    st.caption(cat_label)
                    for lay in layers:
                        stype    = lay.get("source_type","GEOJSON")
                        src_icon = "💾" if stype=="GEOJSON" else "📂"
                        n        = lay.get("feature_count") or "?"
                        if st.checkbox(
                            f"{src_icon} {lay['layer_name']} ({n})",
                            value=False,
                            key=f"wm_shp_{lay['layer_id']}",
                            help=stype,
                        ):
                            active_shp.append(lay)
            else:
                st.caption("No layers registered yet.")
            st.divider()
            st.caption("**Register a shapefile**")
            reg_path = st.text_input("Path", key="wm_reg_path",
                                     placeholder=r"C:\Bulk\spatialile.shp",
                                     label_visibility="collapsed")
            reg_name = st.text_input("Layer name", key="wm_reg_name",
                                     placeholder="e.g. Active Leases TX")
            reg_cat  = st.selectbox("Category",
                ["SEISMIC_2D","SEISMIC_3D","WELL","LEASE","FIELD",
                 "PIPELINE","BOUNDARY","BASIN","OTHER"],
                key="wm_reg_cat")
            reg_mode = st.radio("Import mode",
                ["📂 Register path","💾 Import into DB"],
                key="wm_reg_mode", horizontal=True)
            if st.button("➕ Add Layer", key="wm_reg_btn",
                         use_container_width=True,
                         disabled=not reg_path):
                try:
                    from modules.dv_spatial_loader import (
                        import_shapefile, register_shapefile, import_geojson)
                    from pathlib import Path as _P
                    p    = _P(reg_path)
                    name = reg_name or p.stem.replace("_"," ")
                    if not p.exists():
                        st.error(f"File not found: {reg_path}")
                    else:
                        ext = p.suffix.lower()
                        if "Register" in reg_mode:
                            fn = import_geojson if ext in (".geojson",".json")                                  else register_shapefile
                        else:
                            fn = import_shapefile if ext==".shp"                                  else import_geojson
                        result = fn(engine, reg_path,
                                    layer_name=name, layer_category=reg_cat)
                        if result.get("errors"):
                            st.error(result["errors"][0])
                        else:
                            st.success(
                                f"✅ {name} ({result.get('loaded',0)} features)")
                            st.cache_data.clear()
                            st.rerun()
                except Exception as exc:
                    st.error(str(exc))


    with mapcol:
        # Safe filter — if nothing selected fall back to show all
        _ss  = sel_statuses or list(all_statuses)
        mask = wells_df["well_status"].isin(_ss)
        counts_df = pd.DataFrame()  # populated lazily if a has_X filter is used
        if qtype == "operator" and qvalue:
            mask &= wells_df["operator_name"] == qvalue
        elif qtype == "field" and qvalue:
            mask &= wells_df["field_name"] == qvalue
        elif qtype == "county" and qvalue:
            mask &= wells_df["county"] == qvalue
        elif qtype == "well_type" and qvalue:
            mask &= wells_df["well_type"] == qvalue
        elif qtype in ("has_tops","has_prod","has_dst",
                       "has_survey","has_core","has_petro"):
            if "counts_df" not in st.session_state or st.session_state.counts_df is None:
                with st.spinner("Loading sub-data counts..."):
                    st.session_state.counts_df = _qry_counts(engine)
            counts_df = st.session_state.get("counts_df", pd.DataFrame())
        if qtype in ("has_tops","has_prod","has_dst",
                       "has_survey","has_core","has_petro") and not counts_df.empty:
            col = {"has_tops":"top_count","has_prod":"prod_count",
                   "has_dst":"dst_count","has_survey":"top_count",
                   "has_core":"core_count","has_petro":"petro_count"}[qtype]
            mask &= wells_df["uwi"].isin(
                counts_df[counts_df[col] > 0]["uwi"].tolist())
        dff = wells_df[mask].copy()

        st.caption(
            f"**{len(dff)}** of **{len(wells_df)}** wells"
            + (f" · {len(active_db)} DB layer(s)" if active_db else "")
            + (f" · {len(active_shp)} shapefile(s)" if active_shp else "")
        )

        # Build map — always show basemap even if no wells
        bm   = BASEMAPS.get(basemap, BASEMAPS["OpenStreetMap"])

        # Center priority:
        #   1. Active viewport (last drawn rectangle) — fit map to its bounds
        #   2. Explicit zoom target from dropdown
        #   3. Default: centroid of full filtered dataset
        _viewport_uwis_for_center = st.session_state.get("viewport_uwis", [])
        _viewport_bounds = None  # set below if we have a viewport
        if _viewport_uwis_for_center and not dff.empty:
            _vp_set  = set(_viewport_uwis_for_center)
            _vp_subset = dff[dff["uwi"].astype(str).isin(_vp_set)]
            if not _vp_subset.empty:
                _vp_lats = _vp_subset["lat"].astype(float)
                _vp_lons = _vp_subset["lon"].astype(float)
                _vp_min_lat, _vp_max_lat = float(_vp_lats.min()), float(_vp_lats.max())
                _vp_min_lon, _vp_max_lon = float(_vp_lons.min()), float(_vp_lons.max())
                # Pad bounds 30% so zoom is comfortable, not crowded.
                # Increase if you want to see more surrounding context;
                # decrease if you want a tighter zoom on the selection.
                _pad_lat = max(0.005, (_vp_max_lat - _vp_min_lat) * 0.3)
                _pad_lon = max(0.005, (_vp_max_lon - _vp_min_lon) * 0.3)
                _viewport_bounds = [
                    [_vp_min_lat - _pad_lat, _vp_min_lon - _pad_lon],
                    [_vp_max_lat + _pad_lat, _vp_max_lon + _pad_lon],
                ]
                lat0 = (_vp_min_lat + _vp_max_lat) / 2
                lon0 = (_vp_min_lon + _vp_max_lon) / 2
                zoom0 = 11  # initial guess, fit_bounds will adjust precisely

        if _viewport_bounds is None:
            # No viewport — use zoom_target or full-dataset centroid
            if zoom_target and zoom_target.get("lat"):
                lat0  = zoom_target["lat"]
                lon0  = zoom_target["lon"]
                zoom0 = zoom_target["zoom"]
            else:
                lat0  = dff["lat"].mean() if not dff.empty else 31.5
                lon0  = dff["lon"].mean() if not dff.empty else -102.5
                zoom0 = 7

        # Build map — show progress so user knows it's working
        _msg = st.empty()
        _msg.info(f"🗺 Building map for {len(dff):,} wells…")

        # NOTE: prefer_canvas removed — Leaflet.markercluster needs SVG children
        # to render its cluster bubbles correctly. With clustering on, marker
        # count is always low (~50-100 cluster bubbles + viewport markers) so
        # SVG performance is fine.
        m = folium.Map(location=[lat0, lon0], zoom_start=zoom0,
                       tiles=bm["tiles"], attr=bm["attr"],
                       max_zoom=bm.get("max_zoom", 19))

        # If we have a viewport, fit the map exactly to its bounds (overrides
        # the initial location/zoom_start with proper bbox-based zoom).
        if _viewport_bounds is not None:
            m.fit_bounds(_viewport_bounds)

        if bm.get("overlay"):
            folium.TileLayer(
                tiles=bm["overlay"], attr=bm["attr"],
                name="Labels", overlay=True,
                control=False, opacity=1.0,
            ).add_to(m)

        if not dff.empty:
            _msg.info(f"📍 Placing {len(dff):,} wells…")
            # Cluster layer EXCLUDES viewport wells — those render as individual
            # markers via _add_viewport_wells below, so we don't want duplicate
            # bubbles underneath them.
            _viewport_uwis = st.session_state.get("viewport_uwis", [])
            _add_wells(m, dff, exclude_uwis=_viewport_uwis)

            # Viewport wells — individual markers for the user's last-drawn
            # rectangle. Rendered ON TOP of the cluster layer. Wrapped in
            # try/except so a viewport-render bug doesn't break the whole map.
            if _viewport_uwis:
                try:
                    _vp_count = _add_viewport_wells(
                        m, dff, _viewport_uwis, label_field=label_field)
                    if _vp_count:
                        _msg.info(f"📍 Viewport: {_vp_count:,} individual markers")
                except Exception as _e:
                    st.warning(f"Viewport render skipped: {_e}")
                    st.session_state["viewport_uwis"] = []

        if "db_trajectories" in active_db:
            _msg.info("📐 Loading trajectories…")
            _add_trajectories(m, _qry_trajectories(engine))
        if "db_formation_tops" in active_db:
            _msg.info("📏 Loading formation tops…")
            _add_formation_tops(m, _qry_formation_tops(engine))
        if "db_dst" in active_db:
            _msg.info("🧪 Loading DST intervals…")
            _add_dst(m, _qry_dst(engine))
        if "db_production" in active_db:
            _msg.info("📈 Loading production…")
            _add_production_bubbles(m, _qry_production(engine))
        if "db_catalog" in active_db:
            _msg.info("📁 Loading file catalog…")
            try:
                # CSV first (faster, file-based, easier to refresh).
                # Fall back to SQL only if CSV is missing or empty.
                _cat_df = _qry_catalog_csv()
                _src = "CSV"
                if _cat_df is None or _cat_df.empty:
                    _cat_df = _qry_catalog(engine)
                    _src = "SQL"
                _cat_n = _add_catalog_overlay(m, _cat_df)
                if _cat_n:
                    _msg.info(f"📁 Catalog ({_src}): {_cat_n:,} locations")
                else:
                    if _cat_df is None or _cat_df.empty:
                        st.info(
                            f"📁 File Catalog overlay: no rows found. "
                            f"Tried CSV at `{CATALOG_CSV_PATH}` (missing or empty), "
                            f"then SQL (returned no rows). Run a catalog scan or "
                            f"export the well-header CSV from the File Catalog page."
                        )
                    else:
                        st.info(
                            f"📁 File Catalog overlay: source returned "
                            f"{len(_cat_df):,} rows but none survived rendering "
                            f"(precision/state filters or grouping)."
                        )
            except Exception as _e:
                st.warning(f"Catalog overlay failed: {_e}")
        if "db_fields" in active_db:
            _add_fields(m, _qry_fields(engine))
        if "db_basins" in active_db:
            _add_basins(m, _qry_basins(engine))

        for lay in active_shp:
            _msg.info(f"🗂 Loading {lay.get('layer_name','layer')}…")
            _add_shapefile_layer(m, engine, lay)

        folium.LayerControl(collapsed=False).add_to(m)

        # Draw toolbar — both rectangle (drag-release, native Leaflet.draw) AND
        # our custom click-click rectangle (added below as ▭ button) are available.
        # If one acts up, use the other.
        from folium.plugins import Draw
        Draw(
            export=False,
            position="topleft",
            draw_options={
                "rectangle":    {
                    "shapeOptions": {"color": "#1a73e8", "weight": 2},
                    "metric":       False,
                    "showArea":     False,
                    "repeatMode":   False,
                },
                "polygon":      {
                    "shapeOptions": {"color": "#1a73e8", "weight": 2},
                    "allowIntersection": False,
                    "showArea":     False,
                    "repeatMode":   False,
                },
                "circle":       False,
                "marker":       False,
                "circlemarker": False,
                "polyline":     False,
            },
            edit_options={"edit": False, "remove": True},
        ).add_to(m)

        # Patch Leaflet.draw's existing Rectangle tool to use click-click instead
        # of click-drag-release. The rectangle button already in the left toolbar
        # gets the new behavior — no new button needed. Solves the "stuck still
        # drawing after release" bug because there's no drag/release cycle.
        from branca.element import MacroElement
        from jinja2 import Template
        rect_picker = MacroElement()
        rect_picker._name = "dv_rect_clickclick"
        rect_picker._template = Template(u"""
            {% macro script(this, kwargs) %}
            (function() {
                function patch() {
                    if (typeof L === 'undefined' || !L.Draw || !L.Draw.Rectangle ||
                        !L.Draw.Feature || !L.Draw.Feature.prototype) {
                        setTimeout(patch, 200);
                        return;
                    }
                    if (window.L_DRAW_RECT_PATCHED) return;
                    window.L_DRAW_RECT_PATCHED = true;

                    L.Draw.Rectangle.prototype.addHooks = function() {
                        L.Draw.Feature.prototype.addHooks.call(this);
                        if (!this._map) return;
                        this._map.dragging.disable();
                        this._map.getContainer().style.cursor = 'crosshair';
                        this._ccDrawing     = true;
                        this._ccFirstCorner = null;
                        this._ccPreview     = null;

                        var h = L.DomUtil.create('div', 'dv-rect-hint',
                                                 this._map.getContainer());
                        h.style.cssText =
                            'position:absolute;top:10px;left:50%;transform:translateX(-50%);' +
                            'background:rgba(26,115,232,0.95);color:#fff;padding:6px 14px;' +
                            'border-radius:4px;font-size:13px;font-family:Arial,sans-serif;' +
                            'z-index:9999;box-shadow:0 2px 8px rgba(0,0,0,0.3);' +
                            'pointer-events:none';
                        h.textContent =
                            '📐 Click first corner, then click second corner. Esc to cancel.';
                        this._ccHint = h;

                        this._map.on('click',     this._ccOnClick, this);
                        this._map.on('mousemove', this._ccOnMove,  this);
                        var self = this;
                        this._ccOnKey = function(ev) {
                            if (ev.key === 'Escape') self.disable();
                        };
                        document.addEventListener('keydown', this._ccOnKey);
                    };

                    L.Draw.Rectangle.prototype.removeHooks = function() {
                        L.Draw.Feature.prototype.removeHooks.call(this);
                        if (this._map) {
                            this._map.dragging.enable();
                            this._map.getContainer().style.cursor = '';
                            this._map.off('click',     this._ccOnClick, this);
                            this._map.off('mousemove', this._ccOnMove,  this);
                        }
                        if (this._ccOnKey) {
                            document.removeEventListener('keydown', this._ccOnKey);
                            this._ccOnKey = null;
                        }
                        if (this._ccPreview) {
                            try { this._map.removeLayer(this._ccPreview); } catch(e) {}
                            this._ccPreview = null;
                        }
                        if (this._ccHint && this._ccHint.parentNode) {
                            this._ccHint.parentNode.removeChild(this._ccHint);
                            this._ccHint = null;
                        }
                        this._ccFirstCorner = null;
                        this._ccDrawing     = false;
                    };

                    L.Draw.Rectangle.prototype._ccOnClick = function(e) {
                        if (!this._ccDrawing) return;
                        if (this._ccFirstCorner === null) {
                            this._ccFirstCorner = e.latlng;
                            this._ccPreview = L.rectangle(
                                [e.latlng, e.latlng],
                                {color:'#1a73e8', weight:2, dashArray:'5,5',
                                 fillOpacity:0.1}
                            ).addTo(this._map);
                            if (this._ccHint) {
                                this._ccHint.textContent =
                                    '📐 Move mouse, then click second corner. Esc to cancel.';
                            }
                        } else {
                            var bounds = L.latLngBounds(this._ccFirstCorner, e.latlng);
                            if (this._ccPreview) {
                                try { this._map.removeLayer(this._ccPreview); } catch(err) {}
                                this._ccPreview = null;
                            }
                            this._shape = L.rectangle(bounds,
                                this.options.shapeOptions ||
                                {color:'#1a73e8', weight:2});
                            this._fireCreatedEvent();
                            this.disable();
                        }
                    };

                    L.Draw.Rectangle.prototype._ccOnMove = function(e) {
                        if (this._ccDrawing && this._ccFirstCorner !== null &&
                            this._ccPreview) {
                            this._ccPreview.setBounds(
                                L.latLngBounds(this._ccFirstCorner, e.latlng));
                        }
                    };

                    console.log('dv-rect: Rectangle prototype patched to click-click');
                }
                patch();
            })();
            {% endmacro %}
        """)
        rect_picker._parent = m
        m.add_child(rect_picker)

        # Crosshair cursor everywhere on the map — including over markers.
        # Plus: hide viewport labels (.dv-vp-label tooltips) when zoom < 11.
        # Uses !important to win against Leaflet's defaults that set the hand
        # (pointer) cursor on .leaflet-interactive elements.
        folium.Element("""
            <style>
            .leaflet-container,
            .leaflet-container .leaflet-overlay-pane,
            .leaflet-container .leaflet-tile-pane,
            .leaflet-container .leaflet-marker-pane,
            .leaflet-interactive,
            .leaflet-overlay-pane svg path,
            .leaflet-overlay-pane svg circle {
                cursor: crosshair !important;
            }

            /* ── Viewport label visibility ─────────────────────────
             * Labels (.dv-vp-label tooltips) are permanent, but we hide them
             * at low zoom to avoid a wall of overlapping text. They reappear
             * when the user zooms in past zoom 11 (county/township scale).
             *
             * Leaflet does NOT add zoom level as a CSS class on the container.
             * So we use a different mechanism: a JS hook that watches zoom
             * change events and toggles a class on the map container. The
             * CSS below keys off that class.
             */
            .leaflet-container:not(.dv-zoom-labeled) .dv-vp-label {
                display: none !important;
            }
            /* Style the visible labels when shown */
            .leaflet-tooltip.dv-vp-label {
                background: rgba(255, 255, 255, 0.92);
                color: #1a202c;
                border: 1px solid #ffeb3b;
                border-radius: 3px;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 6px;
                box-shadow: 0 1px 2px rgba(0,0,0,0.15);
                white-space: nowrap;
            }
            .leaflet-tooltip.dv-vp-label:before {
                display: none; /* no arrow tick */
            }
            </style>

            <script>
            // Toggle .dv-zoom-labeled class on the map container based on
            // current zoom. Threshold: 11 (labels visible at zoom >= 11).
            (function() {
                function attachZoomLabelToggle() {
                    if (typeof L === 'undefined') {
                        setTimeout(attachZoomLabelToggle, 200);
                        return;
                    }
                    // Find the Leaflet map instance
                    var map = null;
                    for (var k in window) {
                        if (k.indexOf('map_') === 0 && window[k] &&
                            window[k]._container && window[k].on) {
                            map = window[k];
                            break;
                        }
                    }
                    if (!map) {
                        setTimeout(attachZoomLabelToggle, 200);
                        return;
                    }
                    var THRESHOLD = 11;
                    function syncLabels() {
                        var z = map.getZoom();
                        if (z >= THRESHOLD) {
                            map._container.classList.add('dv-zoom-labeled');
                        } else {
                            map._container.classList.remove('dv-zoom-labeled');
                        }
                    }
                    map.on('zoomend', syncLabels);
                    map.on('load', syncLabels);
                    syncLabels();  // initial state
                }
                attachZoomLabelToggle();
            })();
            </script>
        """).add_to(m.get_root().html)

        # st_folium with width="100%" reserves more vertical space than the map
        # actually uses — the iframe wrapper grows tall while the map stays 500px.
        # Cap the wrapper to exactly the map height to stop the column-stretching bug.
        st.markdown("""
            <style>
            iframe { display:block !important; margin:0 !important; padding:0 !important; }
            /* Hard-cap st_folium iframe wrapper to its requested height */
            iframe[title="streamlit_folium.st_folium"],
            iframe[srcdoc] {
                height: 500px !important;
                max-height: 500px !important;
                vertical-align: bottom !important;
            }
            div:has(> iframe[title="streamlit_folium.st_folium"]),
            div:has(> iframe[srcdoc]) {
                height: 500px !important;
                max-height: 500px !important;
                margin: 0 !important;
                padding: 0 !important;
                line-height: 0 !important;
            }
            div[data-testid="element-container"]:has(iframe) {
                margin-bottom: 0 !important;
                padding-bottom: 0 !important;
            }
            /* Hide empty divs Streamlit injects */
            div[data-testid="stVerticalBlock"] > div:empty { display:none !important; }
            </style>
        """, unsafe_allow_html=True)

        _msg.info("🌐 Rendering map in browser…")
        # Try use_container_width if available (streamlit-folium >= 0.18),
        # else fall back to width=None which lets st_folium auto-size.
        try:
            map_data = st_folium(
                m, height=500, use_container_width=True,
                returned_objects=["last_object_clicked_popup", "all_drawings"],
                key="well_map_folium",
            )
        except TypeError:
            # Older streamlit-folium that doesn't support use_container_width
            map_data = st_folium(
                m, width=None, height=500,
                returned_objects=["last_object_clicked_popup", "all_drawings"],
                key="well_map_folium",
            )
        _msg.empty()

        # Instructional hint for the spatial select tools
        st.caption(
            "💡 **Map:** Cluster bubbles show all 50K wells (click a cluster to "
            "zoom in). To select a region: click the **rectangle** icon (left "
            "toolbar), click two corners on the map — wells inside the box render "
            "as individual yellow-ringed markers and are added to the tray. "
            "Click any individual marker for its scout ticket. **Esc** cancels."
        )

        # ── Session state init ────────────────────────────────────────
        if "clicked_uwis" not in st.session_state:
            st.session_state.clicked_uwis = []
        if "scout_uwi" not in st.session_state:
            st.session_state.scout_uwi = None

        # ── Spatial select — rectangle/polygon drawn on map ─────────
        # On rectangle release: (1) save UWIs as a "viewport" — these wells
        # render as individual interactive markers on the next rerun, on top
        # of the underlying cluster layer; (2) add the same UWIs to the tray
        # for batch reporting/export.
        _raw_drawings = map_data.get("all_drawings") if map_data else None
        drawings = []
        if isinstance(_raw_drawings, list):
            # list of GeoJSON feature dicts
            drawings = _raw_drawings
        elif isinstance(_raw_drawings, dict):
            drawings = _raw_drawings.get("features", [])

        # Track which drawings we've already processed so we don't re-trigger
        # the viewport load on every Streamlit rerun (st_folium keeps returning
        # the same drawings list until the user clears them).
        if "processed_drawings" not in st.session_state:
            st.session_state.processed_drawings = set()

        if drawings:
            for drawing in drawings:
                geom = drawing.get("geometry", {})
                gtype = geom.get("type", "")
                coords = geom.get("coordinates", [])

                # Hash the geometry so we only process each shape once
                _geom_hash = hash(json.dumps(geom, sort_keys=True))
                if _geom_hash in st.session_state.processed_drawings:
                    continue

                try:
                    if gtype == "Polygon" and coords:
                        ring = coords[0]
                        lons = [c[0] for c in ring]
                        lats = [c[1] for c in ring]
                        min_lat, max_lat = min(lats), max(lats)
                        min_lon, max_lon = min(lons), max(lons)

                        # Find all wells in the bounding box (with point-in-polygon
                        # for non-rectangular shapes)
                        def _point_in_polygon(lat, lon, ring):
                            """Ray casting — works for rectangles and polygons."""
                            inside = False
                            n = len(ring)
                            j = n - 1
                            for i in range(n):
                                xi, yi = ring[i][0], ring[i][1]
                                xj, yj = ring[j][0], ring[j][1]
                                if ((yi > lat) != (yj > lat) and
                                        lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-10) + xi):
                                    inside = not inside
                                j = i
                            return inside

                        selected = [
                            w["uwi"] for w in _display_wells
                            if (min_lat <= (w.get("lat") or 0) <= max_lat and
                                min_lon <= (w.get("lon") or 0) <= max_lon and
                                _point_in_polygon(w.get("lat", 0), w.get("lon", 0), ring))
                        ]

                        # Mark this drawing processed regardless of whether wells found
                        st.session_state.processed_drawings.add(_geom_hash)

                        if selected:
                            n_sel = len(selected)
                            # Tray always gets all selected wells regardless of
                            # whether we render markers — tray works on UWIs,
                            # not visual elements.
                            new_uwis = [u for u in selected
                                        if u not in st.session_state.clicked_uwis]
                            if new_uwis:
                                st.session_state.clicked_uwis.extend(new_uwis)

                            if n_sel > VIEWPORT_HARD_CAP:
                                # Too many to render markers — tray-only mode
                                st.session_state.viewport_uwis = []  # no markers
                                st.warning(
                                    f"📐 {n_sel:,} wells in box — too many to render as "
                                    f"markers (cap: {VIEWPORT_HARD_CAP:,}). "
                                    f"All {n_sel:,} are in the tray for batch operations. "
                                    f"Draw a smaller box to see individual markers."
                                )
                            elif n_sel > VIEWPORT_PYTHON_LIMIT:
                                # Large but renderable via JS path
                                st.session_state.viewport_uwis = selected
                                st.success(
                                    f"📐 Viewport: {n_sel:,} wells (JS render) · "
                                    f"{len(new_uwis):,} new in tray"
                                )
                            else:
                                # Small — Python yellow-ring path
                                st.session_state.viewport_uwis = selected
                                st.success(
                                    f"📐 Viewport: {n_sel:,} wells · "
                                    f"{len(new_uwis):,} new in tray"
                                )
                            # NOTE: removed explicit st.rerun() that used to be here.
                            # st_folium triggers an automatic rerun when the map state
                            # settles after the drawing event. Calling st.rerun() on top
                            # of that produced a second grey-out flash unnecessarily.
                            # Trade-off: viewport markers won't appear until that automatic
                            # settle rerun happens (typically immediate when the user
                            # finishes clicking the second corner of the rectangle).
                        else:
                            st.info("No wells found in drawn area")
                except Exception as _e:
                    st.warning(f"Spatial select failed: {_e}")

        # ── Parse clicked popup — data-uwi is the reliable source ────
        clicked = map_data.get("last_object_clicked_popup") if map_data else None
        if clicked:
            _uwi = None
            _catalog_click = False
            # Catalog popup takes priority: data-catalog="1" attribute means
            # the user clicked a File Catalog marker (purple square), not a
            # well marker. data-catalog-uwi is optional — present only for
            # catalog files that had a UWI; orphan files (PDFs etc.) just
            # have data-catalog="1" with no UWI to forward.
            if re.search(r'data-catalog="1"', str(clicked)):
                _catalog_click = True
                mc = re.search(r'data-catalog-uwi="([^"]+)"', str(clicked))
                if mc:
                    _uwi = mc.group(1).strip()
            if not _catalog_click:
                # Primary: data-uwi attribute embedded by JS callback
                m2 = re.search(r'data-uwi="([^"]+)"', str(clicked))
                if m2:
                    _uwi = m2.group(1).strip()
                else:
                    # Fallbacks for other layer popups
                    for pat in [
                        r"font-family:monospace[^>]*>([^<]+)<",
                        r"(US[0-9]{14})",
                    ]:
                        m2 = re.search(pat, str(clicked))
                        if m2:
                            _uwi = m2.group(1).strip()
                            break

            if _catalog_click:
                # Catalog click: stash UWI for the File Catalog page to pick
                # up when user navigates there. Flash a message either way.
                if _uwi:
                    st.session_state["catalog_filter_uwi"] = _uwi
                    st.session_state["catalog_filter_set_at"] = pd.Timestamp.utcnow().isoformat()
                    st.success(
                        f"📁 UWI **{_uwi}** stored for File Catalog. "
                        f"Open the File Catalog page to view its files."
                    )
                else:
                    # Orphan catalog file (no UWI). Don't set the filter, but
                    # acknowledge the click.
                    st.info(
                        "📁 Catalog file selected (no UWI for this file — "
                        "it was cataloged by location only)."
                    )
            elif _uwi:
                # Standard well click: add to tray + open scout ticket
                if _uwi not in st.session_state.clicked_uwis:
                    st.session_state.clicked_uwis.append(_uwi)
                # Open scout ticket for this well — auto-render below map
                st.session_state.scout_uwi = _uwi
                st.session_state["show_summary"] = True
                st.session_state["_summary_uwis"] = [_uwi]

        # ── clicked well → add to tray only, no ticket panel ────────────
        scout_uwi = st.session_state.scout_uwi
        if scout_uwi and scout_uwi not in st.session_state.clicked_uwis:
            st.session_state.clicked_uwis.append(scout_uwi)
            st.session_state.scout_uwi = None

        # ── Scout Ticket panel — renders immediately below map ──────────
        _summary_uwis = st.session_state.get("_summary_uwis", [])
        if st.session_state.get("show_summary") and _summary_uwis:
            # Cache HTML — only rebuild when selection changes
            cache_key = tuple(_summary_uwis)
            if st.session_state.get("_summary_cache_key") != cache_key:
                _html = ""
                for uwi in _summary_uwis:
                    well_row = uwi_index.get(uwi)
                    if well_row:
                        _html += _build_scout_ticket_html(uwi, well_row, engine)
                        _html += "<div style='page-break-after:always'></div>"
                st.session_state["_summary_html"]      = _html
                st.session_state["_summary_cache_key"] = cache_key

            all_html = st.session_state.get("_summary_html", "")
            full_doc = _full_html_doc(all_html, f"Scout Tickets — {len(_summary_uwis)} wells")
            fn       = f"Scout_Tickets_{len(_summary_uwis)}_wells.html"

            _hdr = ("Scout Ticket" if len(_summary_uwis) == 1
                    else f"Scout Tickets — {len(_summary_uwis)} wells")
            st.markdown(f"#### 📋 {_hdr}")
            b1, b2, _ = st.columns([1, 1, 4])
            b1.download_button(
                "⬇ Save Report", data=full_doc.encode(),
                file_name=fn, mime="text/html",
                key="save_report_dl", use_container_width=True)
            if b2.button("✕ Close", key="close_summary", use_container_width=True):
                st.session_state["show_summary"] = False
                st.session_state["_summary_uwis"] = []
                st.rerun()

            st.markdown(all_html, unsafe_allow_html=True)
            st.markdown("---")

        # ── Object Tray — compact bar, always visible ────────────────────
        clicked_uwis = st.session_state.clicked_uwis
        _n = len(clicked_uwis)
        tray_label = f"📋 Object Tray — {_n} item(s)" if clicked_uwis else "📋 Object Tray"
        with st.expander(tray_label, expanded=True):
            if not clicked_uwis:
                # Show a sample placeholder so tray fills the space
                st.markdown(
                    "<div style='padding:6px 0'>"
                    "<span style='color:#aaa;font-size:12px'>— Sample Item —&nbsp;&nbsp;"
                    "Click a well on the map, draw a selection box, or use the well picker "
                    "to add items to the tray.</span></div>",
                    unsafe_allow_html=True)
            else:
                # Checkbox list — uncheck to exclude from reports/export
                selected_in_tray = []
                for cu in list(clicked_uwis):
                    well = uwi_index.get(cu, {})
                    wn   = well.get("well_name", cu)
                    op   = well.get("operator_name", "")
                    checked = st.checkbox(
                        f"🛢 **{wn}** — {op}",
                        value=True,
                        key=f"tray_chk_{cu}")
                    if checked:
                        selected_in_tray.append(cu)

                # Instruction message
                st.markdown(
                    "<div style='font-size:11px;color:#555;padding:4px 0 6px 0'>"
                    "Uncheck wells to exclude from reports. "
                    "Click <b>Reports</b> for Scout Tickets. "
                    "<b>Export Excel</b> exports checked wells only."
                    "</div>",
                    unsafe_allow_html=True)

                # Action row — operates on checked wells only
                p1, p2, p3 = st.columns(3)
                with p1:
                    if st.button("📋 Reports",
                                 key="view_summary",
                                 use_container_width=True, type="primary",
                                 disabled=not selected_in_tray):
                        st.session_state["show_summary"] = True
                        st.session_state["_summary_uwis"] = selected_in_tray
                        st.rerun()
                with p2:
                    if st.button("📊 Export Excel", key="export_xlsx_btn",
                                 use_container_width=True,
                                 disabled=not selected_in_tray):
                        with st.spinner("Building Excel..."):
                            xlsx = _build_export_excel(selected_in_tray, wells_df, engine)
                        if xlsx:
                            st.download_button(
                                "⬇ Download Excel", data=xlsx,
                                file_name=f"Wells_{len(selected_in_tray)}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key="export_xlsx_dl", use_container_width=True)
                        else:
                            st.error("Excel failed — pip install openpyxl")
                with p3:
                    if st.button("🗑 Clear Tray", key="clear_tray",
                                 use_container_width=True):
                        st.session_state.clicked_uwis = []
                        st.session_state.scout_uwi    = None
                        st.session_state["show_summary"] = False
                        st.session_state["_summary_uwis"] = []
                        # Also clear viewport markers and the drawing dedupe set
                        st.session_state["viewport_uwis"] = []
                        st.session_state["processed_drawings"] = set()
                        st.rerun()





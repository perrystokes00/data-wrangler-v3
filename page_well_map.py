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

# BOEM OCS area-code → friendly-name lookup for the GOM Zoom-To dropdown.
# Falls back to a passthrough if the module isn't present, so the page
# still works (just shows bare codes) if boem_area_codes.py is missing.
try:
    from boem_area_codes import area_name as _boem_area_name
except ImportError:
    def _boem_area_name(code):
        return str(code).strip().upper() if code else ""

# BOEM well status_code → friendly-label lookup for the GOM status
# filter checkboxes. Same passthrough-fallback pattern: if the module
# is missing, checkboxes just show raw codes. status_color gives each
# status a fixed marker color; falls back to neutral slate if missing.
try:
    from boem_status_codes import (
        status_label as _boem_status_label,
        status_color as _boem_status_color,
    )
except ImportError:
    def _boem_status_label(code):
        return str(code).strip().upper() if code else ""
    def _boem_status_color(code):
        return "#94a3b8"

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
    {"id": "db_seismic_3d",     "name": "Seismic 3D Surveys",  "icon": "🟦", "default": False, "order": 8},
    {"id": "db_wells_gom",      "name": "GOM Wells",           "icon": "🛢", "default": True,  "order": 9},
]


# ── Area registry ────────────────────────────────────────────────────────────
# Defines which producing-area selectors appear in the top-bar Area dropdown.
# Each entry binds a label to:
#   id          — internal area identifier used in render dispatching
#   sources     — which well-grid query to render for this area. "main"
#                 means the existing _qry_well_grid (reads dataview.dv_well);
#                 "gom" means _qry_gom_well_grid (reads dataview_gom.well).
#                 "all" means both — dispatched separately at render time.
#   center      — (lat, lon, zoom) used to auto-fit the map when the user
#                 selects this area. The pan-persistence JS yields to
#                 _drawn_bounds, so we set _drawn_bounds on area change to
#                 force the auto-zoom.
#   enabled     — False for placeholders (regions where data isn't loaded
#                 yet). Disabled entries still appear in the dropdown so
#                 the user sees what's coming, but selecting them does
#                 nothing beyond rendering "All regions" fallback.
#   queries     — which Query-dropdown options are valid for this area's
#                 schema. The keys correspond to QUERIES values. dv_well
#                 (main) supports the full set; dataview_gom.well only has
#                 the columns for a subset, so GOM gets a shorter list.
#                 Keeping a broken option OUT of the dropdown is clearer
#                 than showing it and silently returning nothing.
#
# Future: replace the hardcoded list with a dynamic discovery query that
# enumerates dataview_<region> schemas. For tonight, hardcoded is fine.
AREAS = [
    # Default selection — renders nothing. Page opens with just the basemap;
    # user must explicitly pick a region to load wells. This prevents the
    # grey-out + spinner on first page open from auto-firing the grid
    # aggregation queries.
    {"label": "— Select area —",    "id": "none",       "sources": [],
     "center": (39.0, -98.0, 3),   "enabled": True,
     "queries": ["all"]},
    {"label": "🌎 All regions",     "id": "all",        "sources": ["main", "gom"],
     "center": (39.0, -98.0, 3),   "enabled": True,
     "queries": ["all", "operator", "field", "county", "well_type", "source", "area",
                 "has_tops", "has_prod", "has_dst", "has_survey",
                 "has_core", "has_petro"]},
    {"label": "🌊 Gulf of America", "id": "gom",        "sources": ["gom"],
     "center": (27.5, -90.0, 6),   "enabled": True,
     # GOM (dataview_gom.well) has operator (company_name) and well type
     # (type_code) columns. It does NOT have field/county or the
     # aux-table joins (formation tops, production, DST, etc.) that the
     # "has_*" queries depend on — those tables don't exist for GOM yet.
     "queries": ["all", "operator", "well_type"]},
    # West Texas — currently held in dataview.dv_well. The "main" source
    # tag means this area renders via the existing _qry_well_grid path.
    # When we migrate dv_well to its own per-region schema later, switch
    # the source tag to that schema's identifier.
    {"label": "🏜 West Texas",      "id": "west_texas", "sources": ["main"],
     "center": (32.0, -102.5, 6),  "enabled": True,
     "queries": ["all", "operator", "field", "county", "well_type", "source", "area",
                 "has_tops", "has_prod", "has_dst", "has_survey",
                 "has_core", "has_petro"]},
    # Disabled placeholders — visible in dropdown but no data yet
    {"label": "🌾 Kansas",          "id": "kansas",     "sources": [],
     "center": (38.5, -98.0, 7),   "enabled": False,
     "queries": ["all"]},
    {"label": "🌲 Bakken",          "id": "bakken",     "sources": [],
     "center": (48.0, -103.0, 7),  "enabled": False,
     "queries": ["all"]},
]


# Module-level flag tracking whether run() has been called in this Streamlit
# process. Set to True on first entry, stays True until the process restarts.
# Used to force-reset the Area selector widget to "— Select area —" on every
# fresh Streamlit start, even if browser session state somehow persists the
# previous selection. Streamlit's session_state can survive browser
# close/reopen in some configurations, so we need a marker that ONLY
# survives within a single Python process lifetime — and module-level
# globals are exactly that.
_PROCESS_FIRST_RUN_DONE = False


# =============================================================================
# DATA QUERIES
# =============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def _qry_wells(_engine, _v=3) -> list[dict]:  # bump _v to bust cache
    """
    Returns wells as a list of dicts via FOR JSON PATH.
    SQL Server does the joins and JSON serialization — no pandas, no Python loops.

    This is the dv_well (main / West Texas) variant. For GOM, see
    _qry_gom_wells — the Wells-mode loader dispatches on active_area.
    """
    sql = """
        SELECT w.uwi, w.well_name, w.well_type, w.well_status,
               w.surface_latitude  AS lat,
               w.surface_longitude AS lon,
               w.county, w.province_state, w.country, w.api_num,
               w.source,
               CONVERT(VARCHAR(10), w.spud_date,       120) AS spud_date,
               CONVERT(VARCHAR(10), w.completion_date, 120) AS completion_date,
               w.final_td, w.depth_datum,
               w.operator_ba_id, w.field_id,
               ISNULL(ba.ba_name, 'Unknown') AS operator_name,
               ISNULL(f.field_name,  'Unknown') AS field_name,
               ISNULL(f.basin_name,  'Unknown') AS basin_name,
               w.area
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


def _qry_gom_wells(_engine) -> list[dict]:
    """
    GOM (dataview_gom.well) variant of _qry_wells.

    Returns the same dict shape as _qry_wells so all downstream code —
    the wells_df DataFrame, the operator/well_type filter dropdowns,
    the map markers — works unchanged. GOM columns are aliased to the
    dv_well names the rest of the page expects:

        well_id          → uwi          (GOM PK, a uniqueidentifier)
        company_name     → operator_name
        type_code        → well_type
        status_code      → well_status
        bh_total_md_ft   → final_td
        api_well_number  → api_num

    GOM has no field/county, so field_name is set to the area code as a
    reasonable stand-in and county/province_state come back blank. The
    "By field"/"By county" query options are not whitelisted for GOM
    anyway (see AREAS), so nothing downstream tries to filter on them.
    """
    sql = """
        SELECT CONVERT(VARCHAR(36), w.well_id) AS uwi,
               w.well_name,
               ISNULL(w.type_code,   'Unknown') AS well_type,
               ISNULL(w.status_code, 'Unknown') AS well_status,
               w.surface_latitude  AS lat,
               w.surface_longitude AS lon,
               CAST('' AS NVARCHAR(40))  AS county,
               w.region                 AS province_state,
               w.api_well_number         AS api_num,
               CONVERT(VARCHAR(10), w.spud_date,        120) AS spud_date,
               CONVERT(VARCHAR(10), w.total_depth_date, 120) AS completion_date,
               w.bh_total_md_ft          AS final_td,
               w.rkb_ft                  AS depth_datum,
               CAST(NULL AS INT)         AS operator_ba_id,
               CAST(NULL AS INT)         AS field_id,
               ISNULL(w.company_name, 'Unknown')      AS operator_name,
               ISNULL(w.bottom_area_code, 'Unknown')  AS field_name
        FROM dataview_gom.well w
        WHERE w.surface_latitude  IS NOT NULL
          AND w.surface_longitude IS NOT NULL
        ORDER BY w.well_name
        FOR JSON PATH
    """
    try:
        with _engine.connect().execution_options(timeout=30) as con:
            rows = con.execute(text(sql)).fetchall()
            if not rows:
                return []
            json_str = "".join(r[0] for r in rows)
            return json.loads(json_str)
    except Exception as exc:
        st.error(f"GOM wells query failed: {exc}")
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def _qry_gom_status_codes(_engine) -> list[str]:
    """
    Distinct status_code values present in dataview_gom.well, ordered by
    well count descending. Cheap — it's a GROUP BY on one indexed column,
    no row payload — so the status sidebar can populate from the real
    schema without paying the cost of loading the full wells list.

    Returns a list of raw BOEM status codes, e.g. ["PA","ST","COM",...].
    Falls back to an empty list on error; the caller handles that.
    """
    try:
        with _engine.connect().execution_options(timeout=8) as con:
            rows = con.execute(text("""
                SELECT status_code, COUNT(*) AS n
                FROM dataview_gom.well
                WHERE status_code IS NOT NULL
                  AND LTRIM(RTRIM(status_code)) <> ''
                GROUP BY status_code
                ORDER BY COUNT(*) DESC
            """)).fetchall()
            return [str(r[0]).strip() for r in rows]
    except Exception:
        return []


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


@st.cache_data(ttl=600, show_spinner=False)
def _qry_seismic_3d(_engine) -> pd.DataFrame:
    """3D seismic surveys with valid bbox geometry, joined to file path.

    Returns one row per 3D survey footprint. We pull from FILE_SEIS_HEADER
    where the bbox columns are populated AND the lat values fall in a
    sane range (sometimes segyio misreads CDP scalars and yields huge
    out-of-range numbers; those got filtered to NULL at write time by
    _safe_coord, but old rows from before that fix may still have garbage).

    Joins to GLOBAL_FILE_CATALOG to surface the filename for the popup.
    """
    try:
        with _engine.connect() as con:
            return pd.read_sql(text("""
                SELECT
                    sh.SEIS_HEADER_ID                AS id,
                    sh.SURVEY_NAME                   AS survey_name,
                    sh.LINE_NAME                     AS line_name,
                    sh.CONTRACTOR                    AS contractor,
                    sh.SURVEY_DATE                   AS survey_date,
                    sh.TRACE_COUNT                   AS trace_count,
                    sh.SAMPLE_INTERVAL               AS sample_interval,
                    sh.EPSG_CODE                     AS epsg_code,
                    CAST(sh.BBOX_MIN_LAT AS FLOAT)   AS min_lat,
                    CAST(sh.BBOX_MAX_LAT AS FLOAT)   AS max_lat,
                    CAST(sh.BBOX_MIN_LON AS FLOAT)   AS min_lon,
                    CAST(sh.BBOX_MAX_LON AS FLOAT)   AS max_lon,
                    fc.FILE_NAME                     AS file_name
                FROM file_catalog.FILE_SEIS_HEADER sh
                LEFT JOIN file_catalog.GLOBAL_FILE_CATALOG fc
                    ON fc.INVENTORY_ID = sh.INVENTORY_ID
                WHERE sh.SEIS_SET_TYPE = '3D'
                  AND sh.BBOX_MIN_LAT IS NOT NULL
                  AND sh.BBOX_MAX_LAT IS NOT NULL
                  AND sh.BBOX_MIN_LON IS NOT NULL
                  AND sh.BBOX_MAX_LON IS NOT NULL
                  AND TRY_CAST(sh.BBOX_MIN_LAT AS FLOAT) BETWEEN -90 AND 90
                  AND TRY_CAST(sh.BBOX_MAX_LAT AS FLOAT) BETWEEN -90 AND 90
                  AND TRY_CAST(sh.BBOX_MIN_LON AS FLOAT) BETWEEN -180 AND 180
                  AND TRY_CAST(sh.BBOX_MAX_LON AS FLOAT) BETWEEN -180 AND 180
            """), con)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=None, show_spinner=False)
def _qry_gom_well_grid(_engine, step: float = 0.36) -> pd.DataFrame:
    """
    Server-side spatial aggregation for the GOM wells overview layer.

    Bins GOM wells (from dataview_gom.well) into square cells of `step`
    degrees. Default 0.36° is roughly 25 miles N/S at Gulf latitudes
    (and ~22 miles E/W since longitude shrinks toward the equator).
    A coarser step than the offshore lease block density would suggest,
    chosen for visual readability at the zoom levels where users actually
    look at the whole Gulf.

    Mirrors _qry_well_grid's structure but reads from dataview_gom.well,
    which has surface_latitude and surface_longitude already as DECIMAL
    (no CAST needed). The schema separation is what makes this clean:
    we don't need a UNION across regions, just a focused query against
    one source-shaped table.

    Cache TTL is None because the GOM well set only changes when the
    loader runs. After loading, the user may need to clear the cache to
    see new wells — same caveat as the main dv_well grid.

    Columns returned:
        lat_bin    — south edge of the cell (degrees)
        lon_bin    — west edge of the cell (degrees)
        well_count — wells inside the cell
        center_lat — centroid of those wells
        center_lon — centroid of those wells
    """
    sql = """
        DECLARE @step FLOAT = :step;
        SELECT
            FLOOR(w.surface_latitude  / @step) * @step AS lat_bin,
            FLOOR(w.surface_longitude / @step) * @step AS lon_bin,
            COUNT(*) AS well_count,
            AVG(CAST(w.surface_latitude  AS FLOAT)) AS center_lat,
            AVG(CAST(w.surface_longitude AS FLOAT)) AS center_lon
        FROM dataview_gom.well w
        WHERE w.surface_latitude  IS NOT NULL
          AND w.surface_longitude IS NOT NULL
        GROUP BY FLOOR(w.surface_latitude  / @step),
                 FLOOR(w.surface_longitude / @step)
    """
    try:
        with _engine.connect() as con:
            return pd.read_sql(text(sql), con, params={"step": step})
    except Exception as exc:
        st.error(f"GOM well grid query failed: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=None, show_spinner=False)
def _qry_well_grid(_engine, step: float = 0.035) -> pd.DataFrame:
    """
    Server-side spatial aggregation for the hex/grid overview layer.

    Bins wells into square cells of `step` degrees (default 0.1° ~= 7 miles).
    Returns one row per non-empty cell with the well count and the centroid
    of wells inside it.

    This replaces the 50K-marker payload with ~100-500 polygons. Massive
    serialization win on every Streamlit rerun.

    Columns returned:
        lat_bin    — south edge of the cell (degrees)
        lon_bin    — west edge of the cell (degrees)
        well_count — wells inside the cell
        center_lat — centroid of those wells (for tooltip placement)
        center_lon — centroid of those wells

    Cache TTL is None — the grid only changes when wells are loaded/deleted,
    so we hold it for the whole session.
    """
    sql = """
        DECLARE @step FLOAT = :step;
        SELECT
            FLOOR(w.surface_latitude  / @step) * @step AS lat_bin,
            FLOOR(w.surface_longitude / @step) * @step AS lon_bin,
            COUNT(*) AS well_count,
            AVG(w.surface_latitude)  AS center_lat,
            AVG(w.surface_longitude) AS center_lon
        FROM dataview.dv_well w
        WHERE w.surface_latitude  IS NOT NULL
          AND w.surface_longitude IS NOT NULL
        GROUP BY FLOOR(w.surface_latitude  / @step),
                 FLOOR(w.surface_longitude / @step)
    """
    try:
        with _engine.connect() as con:
            return pd.read_sql(text(sql), con, params={"step": step})
    except Exception as exc:
        st.error(f"Well grid query failed: {exc}")
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def _qry_wells_in_bbox(
    _engine,
    min_lat: float, max_lat: float,
    min_lon: float, max_lon: float,
    limit: int = 1000,
) -> tuple[list[dict], int]:
    """
    Rectangle drill-down query: wells inside the given bounding box.

    Returns a tuple of (wells, total_count):
      wells       — list of well dicts, capped at `limit`
      total_count — true count of wells in the bbox (may exceed len(wells))

    The total_count tells the UI whether to warn about the cap being hit.
    The IX_dv_well_lat_lon composite index makes this query fast (sub-second
    for any reasonable bbox even at 4M scale).

    Cache TTL is 300s — bbox queries are user-driven by rectangle drawing,
    so we don't need session-long persistence but want to avoid re-firing
    if the same rectangle is drawn twice in quick succession.
    """
    # COUNT first — cheap with the index, tells us whether to return rows
    count_sql = """
        SELECT COUNT(*) AS n
        FROM dataview.dv_well w
        WHERE w.surface_latitude  BETWEEN :min_lat AND :max_lat
          AND w.surface_longitude BETWEEN :min_lon AND :max_lon
    """
    rows_sql = """
        SELECT TOP (:limit)
               w.uwi, w.well_name, w.well_type, w.well_status,
               w.surface_latitude  AS lat,
               w.surface_longitude AS lon,
               w.county, w.province_state, w.api_num,
               CONVERT(VARCHAR(10), w.spud_date,       120) AS spud_date,
               CONVERT(VARCHAR(10), w.completion_date, 120) AS completion_date,
               w.final_td, w.depth_datum,
               w.operator_ba_id, w.field_id,
               ISNULL(ba.ba_name,   'Unknown') AS operator_name,
               ISNULL(f.field_name, 'Unknown') AS field_name
        FROM dataview.dv_well w
        LEFT JOIN dataview.dv_business_associate ba ON ba.ba_id = w.operator_ba_id
        LEFT JOIN dataview.dv_field f ON f.field_id = w.field_id
        WHERE w.surface_latitude  BETWEEN :min_lat AND :max_lat
          AND w.surface_longitude BETWEEN :min_lon AND :max_lon
        ORDER BY w.well_name
        FOR JSON PATH
    """
    params = {
        "min_lat": float(min_lat), "max_lat": float(max_lat),
        "min_lon": float(min_lon), "max_lon": float(max_lon),
        "limit": int(limit),
    }
    try:
        with _engine.connect().execution_options(timeout=30) as con:
            total = con.execute(text(count_sql), params).scalar() or 0
            if total == 0:
                return [], 0

            # FOR JSON PATH returns multi-row varchar chunks — concat them
            json_rows = con.execute(text(rows_sql), params).fetchall()
            if not json_rows:
                return [], total
            json_str = "".join(r[0] for r in json_rows)
            wells = json.loads(json_str)
            return wells, int(total)
    except Exception as exc:
        st.error(f"Bbox query failed: {exc}")
        return [], 0


@st.cache_data(ttl=300, show_spinner=False)
def _qry_wells_in_circle(
    _engine,
    center_lat: float,
    center_lon: float,
    radius_m: float,
    limit: int = 5000,
) -> tuple[list[dict], int]:
    """
    Haversine wells-in-radius query.

    Returns (wells, total_count) — wells capped at `limit`, total_count is
    the true population inside the circle (may exceed len(wells)).

    Two-stage filter:
      1. bbox prefilter using IX_dv_well_lat_lon (cheap index range scan)
      2. Haversine distance check on the prefilter result (Python-side
         dataframe filter, cheap on ~hundreds of candidates)

    Validated against SSMS — same query pattern, sub-second at current scale,
    scales to 4M wells with the index in place.
    """
    import math as _m

    # bbox prefilter expansion in degrees (rough but generous — we filter
    # exactly with Haversine afterward)
    _dlat = radius_m / 111000.0
    _dlon = radius_m / (
        111000.0 * max(_m.cos(_m.radians(center_lat)), 0.01)
    )
    _min_lat = center_lat - _dlat
    _max_lat = center_lat + _dlat
    _min_lon = center_lon - _dlon
    _max_lon = center_lon + _dlon

    # Two queries: COUNT (with Haversine) then TOP rows (with Haversine).
    # We can't combine because the COUNT needs the full result, not TOP.
    # Both queries are fast because of the bbox prefilter on the indexed
    # columns — Haversine runs only on the candidates inside the bbox.
    count_sql = """
        WITH InBox AS (
            SELECT surface_latitude AS lat, surface_longitude AS lon
            FROM dataview.dv_well
            WHERE surface_latitude  BETWEEN :min_lat AND :max_lat
              AND surface_longitude BETWEEN :min_lon AND :max_lon
        )
        SELECT COUNT(*) AS n
        FROM InBox
        WHERE 6371000 * 2 * ASIN(SQRT(
                POWER(SIN(RADIANS(lat - :center_lat) / 2), 2) +
                COS(RADIANS(:center_lat)) * COS(RADIANS(lat)) *
                POWER(SIN(RADIANS(lon - :center_lon) / 2), 2)
            )) <= :radius_m
    """
    rows_sql = """
        WITH InBox AS (
            SELECT w.uwi, w.well_name, w.well_type, w.well_status,
                   w.surface_latitude  AS lat,
                   w.surface_longitude AS lon,
                   w.county, w.province_state, w.api_num,
                   CONVERT(VARCHAR(10), w.spud_date,       120) AS spud_date,
                   CONVERT(VARCHAR(10), w.completion_date, 120) AS completion_date,
                   w.final_td, w.depth_datum,
                   w.operator_ba_id, w.field_id,
                   ISNULL(ba.ba_name,   'Unknown') AS operator_name,
                   ISNULL(f.field_name, 'Unknown') AS field_name
            FROM dataview.dv_well w
            LEFT JOIN dataview.dv_business_associate ba ON ba.ba_id = w.operator_ba_id
            LEFT JOIN dataview.dv_field f               ON f.field_id      = w.field_id
            WHERE w.surface_latitude  BETWEEN :min_lat AND :max_lat
              AND w.surface_longitude BETWEEN :min_lon AND :max_lon
        )
        SELECT TOP (:limit) *,
            6371000 * 2 * ASIN(SQRT(
                POWER(SIN(RADIANS(lat - :center_lat) / 2), 2) +
                COS(RADIANS(:center_lat)) * COS(RADIANS(lat)) *
                POWER(SIN(RADIANS(lon - :center_lon) / 2), 2)
            )) AS distance_m
        FROM InBox
        WHERE 6371000 * 2 * ASIN(SQRT(
                POWER(SIN(RADIANS(lat - :center_lat) / 2), 2) +
                COS(RADIANS(:center_lat)) * COS(RADIANS(lat)) *
                POWER(SIN(RADIANS(lon - :center_lon) / 2), 2)
            )) <= :radius_m
        ORDER BY distance_m
        FOR JSON PATH
    """
    params = {
        "min_lat":    float(_min_lat),
        "max_lat":    float(_max_lat),
        "min_lon":    float(_min_lon),
        "max_lon":    float(_max_lon),
        "center_lat": float(center_lat),
        "center_lon": float(center_lon),
        "radius_m":   float(radius_m),
        "limit":      int(limit),
    }
    try:
        with _engine.connect().execution_options(timeout=30) as con:
            total = con.execute(text(count_sql), params).scalar() or 0
            if total == 0:
                return [], 0

            json_rows = con.execute(text(rows_sql), params).fetchall()
            if not json_rows:
                return [], total
            json_str = "".join(r[0] for r in json_rows)
            wells = json.loads(json_str)
            return wells, int(total)
    except Exception as exc:
        st.error(f"Circle query failed: {exc}")
        return [], 0


# ── GOM well drill queries ──────────────────────────────────────────────────
# REFACTOR: These mirror _qry_wells_in_bbox and _qry_wells_in_circle but
# read from dataview_gom.well and return GOM-shaped rows (no operator FK,
# no field FK, has BOEM-specific fields like bottom_area_code).
# When the second region (Permian, etc.) lands, these should consolidate
# with the dv_well versions into a single generic dispatcher.

@st.cache_data(ttl=300, show_spinner=False)
def _qry_gom_wells_in_bbox(
    _engine,
    min_lat: float, max_lat: float,
    min_lon: float, max_lon: float,
    limit: int = 1000,
) -> tuple[list[dict], int]:
    """
    Rectangle drill-down query for GOM wells inside a bounding box.

    Mirrors _qry_wells_in_bbox structure but reads from dataview_gom.well.
    Returns GOM-shaped well dicts with BOEM-native fields (api_well_number,
    company_name, lease, area/block, water depth, etc.).

    The well_id (UUID) is returned alongside the BOEM API so the popup can
    show the user-readable identifier while the system tracks the internal
    one. Indexes ix_dv_well_gom_surface_coords makes this query fast.
    """
    count_sql = """
        SELECT COUNT(*) AS n
        FROM dataview_gom.well w
        WHERE w.surface_latitude  BETWEEN :min_lat AND :max_lat
          AND w.surface_longitude BETWEEN :min_lon AND :max_lon
    """
    rows_sql = """
        SELECT TOP (:limit)
               CAST(w.well_id AS NVARCHAR(40)) AS well_id,
               w.api_well_number,
               w.well_name,
               w.well_name_suffix,
               w.company_name,
               w.surface_lease_number,
               w.bottom_lease_number,
               w.bottom_area_code,
               w.bottom_block_number,
               w.region,
               CONVERT(VARCHAR(10), w.spud_date,        120) AS spud_date,
               CONVERT(VARCHAR(10), w.total_depth_date, 120) AS total_depth_date,
               CONVERT(VARCHAR(10), w.status_date,      120) AS status_date,
               w.type_code,
               w.status_code,
               CAST(w.surface_latitude  AS FLOAT) AS lat,
               CAST(w.surface_longitude AS FLOAT) AS lon,
               CAST(w.bottom_latitude   AS FLOAT) AS bottom_lat,
               CAST(w.bottom_longitude  AS FLOAT) AS bottom_lon,
               CAST(w.bh_total_md_ft         AS FLOAT) AS bh_total_md_ft,
               CAST(w.true_vertical_depth_ft AS FLOAT) AS tvd_ft,
               CAST(w.water_depth_ft         AS FLOAT) AS water_depth_ft
        FROM dataview_gom.well w
        WHERE w.surface_latitude  BETWEEN :min_lat AND :max_lat
          AND w.surface_longitude BETWEEN :min_lon AND :max_lon
        ORDER BY w.well_name
        FOR JSON PATH
    """
    params = {
        "min_lat": float(min_lat), "max_lat": float(max_lat),
        "min_lon": float(min_lon), "max_lon": float(max_lon),
        "limit": int(limit),
    }
    try:
        with _engine.connect().execution_options(timeout=30) as con:
            total = con.execute(text(count_sql), params).scalar() or 0
            if total == 0:
                return [], 0
            json_rows = con.execute(text(rows_sql), params).fetchall()
            if not json_rows:
                return [], total
            json_str = "".join(r[0] for r in json_rows)
            wells = json.loads(json_str)
            return wells, int(total)
    except Exception as exc:
        st.error(f"GOM bbox query failed: {exc}")
        return [], 0


@st.cache_data(ttl=300, show_spinner=False)
def _qry_gom_wells_in_circle(
    _engine,
    center_lat: float,
    center_lon: float,
    radius_m: float,
    limit: int = 5000,
) -> tuple[list[dict], int]:
    """
    Haversine drill-down query for GOM wells inside a radius.

    Mirrors _qry_wells_in_circle structure (bbox prefilter + Haversine
    refinement) but reads from dataview_gom.well. Returns GOM-shaped
    well dicts ordered by distance from circle center.

    The bbox prefilter uses ix_dv_well_gom_surface_coords; the Haversine
    distance check then refines to the exact circle. Two queries (COUNT
    then TOP rows) — same pattern as the dv_well version.
    """
    import math as _m

    _dlat = radius_m / 111000.0
    _dlon = radius_m / (
        111000.0 * max(_m.cos(_m.radians(center_lat)), 0.01)
    )
    _min_lat = center_lat - _dlat
    _max_lat = center_lat + _dlat
    _min_lon = center_lon - _dlon
    _max_lon = center_lon + _dlon

    count_sql = """
        WITH InBox AS (
            SELECT CAST(surface_latitude  AS FLOAT) AS lat,
                   CAST(surface_longitude AS FLOAT) AS lon
            FROM dataview_gom.well
            WHERE surface_latitude  BETWEEN :min_lat AND :max_lat
              AND surface_longitude BETWEEN :min_lon AND :max_lon
        )
        SELECT COUNT(*) AS n
        FROM InBox
        WHERE 6371000 * 2 * ASIN(SQRT(
                POWER(SIN(RADIANS(lat - :center_lat) / 2), 2) +
                COS(RADIANS(:center_lat)) * COS(RADIANS(lat)) *
                POWER(SIN(RADIANS(lon - :center_lon) / 2), 2)
            )) <= :radius_m
    """
    rows_sql = """
        WITH InBox AS (
            SELECT CAST(w.well_id AS NVARCHAR(40)) AS well_id,
                   w.api_well_number, w.well_name, w.well_name_suffix,
                   w.company_name, w.surface_lease_number, w.bottom_lease_number,
                   w.bottom_area_code, w.bottom_block_number, w.region,
                   CONVERT(VARCHAR(10), w.spud_date,        120) AS spud_date,
                   CONVERT(VARCHAR(10), w.total_depth_date, 120) AS total_depth_date,
                   CONVERT(VARCHAR(10), w.status_date,      120) AS status_date,
                   w.type_code, w.status_code,
                   CAST(w.surface_latitude  AS FLOAT) AS lat,
                   CAST(w.surface_longitude AS FLOAT) AS lon,
                   CAST(w.bottom_latitude   AS FLOAT) AS bottom_lat,
                   CAST(w.bottom_longitude  AS FLOAT) AS bottom_lon,
                   CAST(w.bh_total_md_ft         AS FLOAT) AS bh_total_md_ft,
                   CAST(w.true_vertical_depth_ft AS FLOAT) AS tvd_ft,
                   CAST(w.water_depth_ft         AS FLOAT) AS water_depth_ft
            FROM dataview_gom.well w
            WHERE w.surface_latitude  BETWEEN :min_lat AND :max_lat
              AND w.surface_longitude BETWEEN :min_lon AND :max_lon
        )
        SELECT TOP (:limit) *,
            6371000 * 2 * ASIN(SQRT(
                POWER(SIN(RADIANS(lat - :center_lat) / 2), 2) +
                COS(RADIANS(:center_lat)) * COS(RADIANS(lat)) *
                POWER(SIN(RADIANS(lon - :center_lon) / 2), 2)
            )) AS distance_m
        FROM InBox
        WHERE 6371000 * 2 * ASIN(SQRT(
                POWER(SIN(RADIANS(lat - :center_lat) / 2), 2) +
                COS(RADIANS(:center_lat)) * COS(RADIANS(lat)) *
                POWER(SIN(RADIANS(lon - :center_lon) / 2), 2)
            )) <= :radius_m
        ORDER BY distance_m
        FOR JSON PATH
    """
    params = {
        "min_lat":    float(_min_lat),
        "max_lat":    float(_max_lat),
        "min_lon":    float(_min_lon),
        "max_lon":    float(_max_lon),
        "center_lat": float(center_lat),
        "center_lon": float(center_lon),
        "radius_m":   float(radius_m),
        "limit":      int(limit),
    }
    try:
        with _engine.connect().execution_options(timeout=30) as con:
            total = con.execute(text(count_sql), params).scalar() or 0
            if total == 0:
                return [], 0
            json_rows = con.execute(text(rows_sql), params).fetchall()
            if not json_rows:
                return [], total
            json_str = "".join(r[0] for r in json_rows)
            wells = json.loads(json_str)
            return wells, int(total)
    except Exception as exc:
        st.error(f"GOM circle query failed: {exc}")
        return [], 0


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

    This is the dv_well / main-source variant. For GOM, see
    _qry_gom_zoom_targets — the Zoom-To widget dispatches on the
    active Area.
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


def _qry_gom_zoom_targets(_engine) -> list[dict]:
    """
    Build the Zoom-To list for the Gulf of America area.

    GOM has no fields/basins/counties in the dv_well sense. The natural
    navigation unit offshore is the BOEM OCS protraction area
    (Mississippi Canyon, Green Canyon, etc.), identified by
    bottom_area_code in dataview_gom.well. Each entry's centroid is the
    average surface coordinate of all wells in that area code.

    Ordered by well count descending so the most-drilled areas are at
    the top of the dropdown — that's where the user most likely wants
    to go.
    """
    targets = [{"label": "— Zoom to location —",
                "lat": None, "lon": None, "zoom": 6}]
    try:
        with _engine.connect().execution_options(timeout=8) as con:
            rows = con.execute(text("""
                SELECT bottom_area_code,
                       AVG(surface_latitude)  AS lat,
                       AVG(surface_longitude) AS lon,
                       COUNT(*)               AS n
                FROM dataview_gom.well
                WHERE surface_latitude IS NOT NULL
                  AND surface_longitude IS NOT NULL
                  AND bottom_area_code IS NOT NULL
                  AND LTRIM(RTRIM(bottom_area_code)) <> ''
                GROUP BY bottom_area_code
                ORDER BY COUNT(*) DESC
            """)).fetchall()
            for r in rows:
                _code = str(r[0]).strip()
                _n    = int(r[3])
                _name = _boem_area_name(_code)
                # Show "Garden Banks (GB)" when we have a friendly name,
                # or just the code if the lookup doesn't cover it.
                _disp = f"{_name} ({_code})" if _name != _code else _code
                targets.append({
                    "label": f"🌊 {_disp} · {_n:,} wells",
                    "lat": float(r[1]), "lon": float(r[2]),
                    # Area codes cover a roughly consistent-size region;
                    # zoom 9 frames one comfortably without losing context.
                    "zoom": 9,
                })
    except Exception:
        pass
    return targets


# =============================================================================
# HELPERS
# =============================================================================

def _popup_table(fields: dict) -> str:
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

def _add_well_grid(
    m,
    df: pd.DataFrame,
    step: float = 0.035,
    selected_set: set | None = None,
    interactive: bool = True,
) -> int:
    """
    Renders the grid-density overview layer.

    Each non-empty cell becomes a square polygon, fill-colored by log-scaled
    well count (light yellow → dark red). Tooltip shows the count.

    This is the low-load alternative to FastMarkerCluster. Use when the user
    wants a fast overview of where the wells are, without paying the cost of
    serializing 50K individual markers.

    Cells in `selected_set` (a set of "lat_bin|lon_bin" string keys) are
    rendered with a bold blue outline so the user can see what's queued
    for the multi-select Commit action.

    Args:
        m: folium.Map
        df: result of _qry_well_grid — columns lat_bin, lon_bin, well_count,
            center_lat, center_lon
        step: cell size in degrees (must match what was used to bin)
        selected_set: optional set of "lat_bin|lon_bin" keys identifying
            cells the user has multi-selected for drill

    Returns:
        number of cells rendered (for status caption)
    """
    if df is None or df.empty:
        return 0

    import math

    # Log scale because counts span 4 orders of magnitude (1 to 3,400+).
    # Linear scaling makes most cells indistinguishable pale.
    max_count = max(int(df["well_count"].max()), 1)
    log_max = math.log10(max_count + 1) or 1.0

    # Sequential colormap: pale yellow (few wells) → deep red (many wells).
    # 6 stops gives smooth visual gradation without rendering noise.
    palette = [
        "#fff5b1",  # 0.0 — very pale yellow
        "#fed976",  # 0.2
        "#feb24c",  # 0.4
        "#fd8d3c",  # 0.6
        "#fc4e2a",  # 0.8
        "#b10026",  # 1.0 — deep red
    ]

    def _color_for(count: int) -> str:
        # Normalize log-count to 0..1, then pick palette bin
        if count <= 0:
            return palette[0]
        t = math.log10(count + 1) / log_max
        idx = min(int(t * len(palette)), len(palette) - 1)
        return palette[idx]

    if selected_set is None:
        selected_set = set()

    grid_group = folium.FeatureGroup(name="Wells (grid)", show=True)

    for row in df.itertuples(index=False):
        try:
            lat_bin = float(row.lat_bin)
            lon_bin = float(row.lon_bin)
            count = int(row.well_count)
        except (TypeError, ValueError):
            continue

        color = _color_for(count)
        bounds = [
            [lat_bin, lon_bin],                  # SW corner
            [lat_bin + step, lon_bin + step],    # NE corner
        ]

        # Is this cell currently selected for the multi-select Commit?
        # Use lat_bin|lon_bin string as the dictionary key — matches how
        # the click handler stores selections.
        _cell_key = f"{lat_bin:.4f}|{lon_bin:.4f}"
        _is_selected = _cell_key in selected_set

        # Selected cells get a bold blue outline. Density color (fill)
        # stays the same so the user can still read "I selected dense vs
        # sparse cells." Unselected get the default dark-red thin border.
        if _is_selected:
            border_color  = "#1d4ed8"   # bold blue
            border_weight = 4
            tooltip_html  = f"<b>{count:,}</b> wells — ✓ selected (click again to deselect)"
        else:
            border_color  = "#7f1d1d"   # dark red
            border_weight = 0.5
            tooltip_html  = f"<b>{count:,}</b> wells — click to select"

        # Render as a Rectangle with a count tooltip. NO popup — popups
        # trigger streamlit-folium reruns when they auto-close (after the
        # user pans, hovers, or just waits a moment), and those reruns
        # rebuild the entire map. Instead, the click handler reads the
        # click's lat/lon from streamlit-folium's last_object_clicked and
        # uses floor-division by step to derive which cell was clicked.
        # The cell coordinates are implicit in the click coordinate.
        # When `interactive` is False (Circle selection mode), the cell
        # polygons are rendered inert — they still draw the heatmap fill
        # but do NOT intercept pointer events. This lets a press-drag that
        # starts on top of a cell pass straight through to Leaflet.draw so
        # the circle gesture begins cleanly. In Cells mode they stay
        # interactive so last_object_clicked fires for cell selection.
        #
        # NOTE: folium 0.20's Rectangle constructor silently DROPS an
        # `interactive=` kwarg — it never reaches the serialized Leaflet
        # options. The reliable path is to set it on `.options` after
        # construction, which IS serialized into the rendered JS as
        # "interactive": false. Verified against folium 0.20.0.
        _rect = folium.Rectangle(
            bounds=bounds,
            color=border_color,
            weight=border_weight,
            fill=True,
            fill_color=color,
            fill_opacity=0.55,
            tooltip=(folium.Tooltip(tooltip_html, sticky=True)
                     if interactive else None),
        )
        _rect.options["interactive"] = interactive
        _rect.add_to(grid_group)

    grid_group.add_to(m)
    return len(df)



# ══════════════════════════════════════════════════════════════════════════════
# GeoJSON mode — GeoJSON layer built from dv_well
# ══════════════════════════════════════════════════════════════════════════════

def _load_well_geojson(geojson_path: str = "wells.geojson") -> dict:
    """Load the pre-built wells.geojson file into session state.

    Called once on first render. The file is generated by
    build_well_geojson.py (run nightly or on-demand).
    Returns the full GeoJSON dict, or an empty FeatureCollection
    if the file doesn't exist.
    """
    _key = "_well_geojson_data"
    if _key in st.session_state:
        return st.session_state[_key]

    from pathlib import Path
    import json

    p = Path(geojson_path)
    if not p.exists():
        # Try relative to the app directory
        app_dir = Path(__file__).parent
        p = app_dir / geojson_path
    if not p.exists():
        st.session_state[_key] = {
            "type": "FeatureCollection", "features": [],
            "metadata": {"total_wells": 0},
        }
        return st.session_state[_key]

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

    st.session_state[_key] = data
    return data


def _filter_geojson(geojson: dict, schema: str = "all",
                    area: str = "", source: str = "") -> dict:
    """Filter a GeoJSON FeatureCollection by schema, area, source.

    Returns a new FeatureCollection with only matching features.
    Operates entirely in memory — no DB query.
    """
    features = geojson.get("features", [])
    if not features:
        return geojson

    filtered = []
    for f in features:
        props = f.get("properties", {})

        if schema != "all" and props.get("schema", "") != schema:
            continue
        if area and props.get("area", "") != area:
            continue
        if source and props.get("source", "") != source:
            continue

        filtered.append(f)

    return {"type": "FeatureCollection", "features": filtered}




def _add_geojson_wells(m, geojson: dict):
    """Add the well GeoJSON layer to a Folium map.

    Uses folium.GeoJson with CircleMarker rendering — the browser
    handles all 30K+ points as one JavaScript layer. Each point has
    a popup with the UWI for click → scout ticket.
    """
    import folium

    if not geojson.get("features"):
        return

    # Lightweight popup — just UWI + name. The full scout ticket
    # is fetched on click via _qry_well_detail.
    layer = folium.GeoJson(
        geojson,
        name="Wells",
        marker=folium.CircleMarker(
            radius=3,
            fill=True,
            fill_color="#1D9E75",
            fill_opacity=0.7,
            color="#0A5C45",
            weight=1,
        ),
        popup=folium.GeoJsonPopup(
            fields=["uwi", "name", "operator", "field"],
            aliases=["UWI", "Well", "Operator", "Field"],
            localize=True,
            max_width=300,
        ),
        tooltip=folium.GeoJsonTooltip(
            fields=["uwi", "name"],
            aliases=["UWI", "Well"],
            sticky=False,
        ),
    )
    layer.add_to(m)


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
            var popup = '<div data-uwi="' + uwi + '" '
                + 'style="font-size:11px;line-height:1.4;padding:0">'
                + '<b style="font-size:12px;color:#0f172a">' + name + '</b><br>'
                + '<span style="font-family:monospace;font-size:10px;color:#888">'
                + uwi + '</span><br>'
                + '<span style="color:#475569;font-size:10px">' + op + '</span><br>'
                + '<span style="color:#475569;font-size:10px">' + field + '</span><br>'
                + '<b style="color:' + color + ';font-size:10px">' + status + '</b><br>'
                + '<span style="font-size:10px;color:#475569">Spud ' + spud + '</span><br>'
                + '<span style="font-size:10px;color:#475569">TD ' + td + '</span><br>'
                + '<span style="font-size:10px;color:#1a73e8;font-weight:600">'
                + '📋 Open the tray for Scout Tickets<br>'
                + 'and to export data'
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
                f'<div data-uwi="{uwi}" '
                f'style="font-size:11px;line-height:1.4;padding:0">'
                f'<b style="font-size:12px;color:#0f172a">{name}</b><br>'
                f'<span style="font-family:monospace;font-size:10px;color:#888">'
                f'{uwi}</span><br>'
                f'<span style="color:#475569;font-size:10px">{op}</span><br>'
                f'<span style="color:#475569;font-size:10px">{field}</span><br>'
                f'<b style="color:{color};font-size:10px">{status}</b><br>'
                f'<span style="font-size:10px;color:#475569">Spud {spud}</span><br>'
                f'<span style="font-size:10px;color:#475569">TD {td}</span><br>'
                f'<span style="font-size:10px;color:#1a73e8;font-weight:600">'
                f'📋 Open the tray for Scout Tickets<br>'
                f'and to export data</span>'
                f'</div>'
            )
            folium.CircleMarker(
                location=[lat, lon], radius=5, color="#ffffff", weight=1,
                fill=True, fill_color=color, fill_opacity=0.88, opacity=1,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=name or uwi,
            ).add_to(fg)
        fg.add_to(m)


def _add_viewport_wells(m, df, viewport_uwis):
    """
    Render INDIVIDUAL clickable CircleMarkers for wells inside a user-drawn viewport,
    on top of the existing cluster layer. Triggered when the user draws a rectangle.

    These markers are interactive (click → popup → scout ticket) — unlike the
    underlying cluster bubbles which are passive density indicators.

    Args:
        m: folium.Map
        df: full wells DataFrame (filtered by current top-level filters)
        viewport_uwis: set/list of UWI strings to render as individual markers
    """
    if df.empty or not viewport_uwis:
        return 0

    vp_set = set(viewport_uwis)
    sub = df[df["uwi"].astype(str).isin(vp_set)].reset_index(drop=True)
    if sub.empty:
        return 0

    sc = sub["well_status"].astype(str).str.upper().fillna("UNKNOWN")
    fg = folium.FeatureGroup(name=f"📍 Viewport selection ({len(sub)})", show=True)

    for _i, row in sub.iterrows():
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (TypeError, ValueError):
            continue

        uwi    = row.get("uwi", "")
        name   = row.get("well_name") or ""
        status = sc.iat[_i]
        color  = STATUS_COLORS.get(status, "#888780")
        op     = row.get("operator_name") or "—"
        field  = row.get("field_name") or "—"
        spud   = str(row.get("spud_date") or "—")[:10]
        ftd    = row.get("final_td")
        td     = f"{float(ftd):,.0f} ft" if pd.notna(ftd) else "—"

        popup_html = (
            f"<div data-uwi=\"{uwi}\" "
            f"style='font-size:11px;line-height:1.4;padding:0'>"
            f"<b style='font-size:12px;color:#0f172a'>{name}</b><br>"
            f"<span style='font-family:monospace;font-size:10px;color:#888'>"
            f"{uwi}</span><br>"
            f"<span style='color:#475569;font-size:10px'>{op}</span><br>"
            f"<span style='color:#475569;font-size:10px'>{field}</span><br>"
            f"<b style='color:{color};font-size:10px'>{status}</b><br>"
            f"<span style='font-size:10px;color:#475569'>Spud {spud}</span><br>"
            f"<span style='font-size:10px;color:#475569'>TD {td}</span><br>"
            f"<span style='font-size:10px;color:#1a73e8;font-weight:600'>"
            f"📋 Open the tray for Scout Tickets<br>"
            f"and to export data</span>"
            f"</div>"
        )

        # Slightly larger radius (6 vs 5) and brighter outline so viewport
        # markers stand out from any background cluster bubbles
        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            color="#ffeb3b",   # yellow ring — distinguishes "in viewport"
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=0.95,
            opacity=1,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=name or uwi,
        ).add_to(fg)

    fg.add_to(m)
    return len(sub)


# ── GOM well marker rendering ────────────────────────────────────────────────
# REFACTOR: _build_gom_popup_html mirrors the inline popup HTML in
# _add_viewport_wells; _add_gom_wells_markers mirrors _add_viewport_wells
# itself. Both should consolidate with a generic well-marker renderer once
# we have a second per-region pattern in place.

def _build_gom_popup_html(well: dict) -> str:
    """
    Build the popup HTML for one GOM well.

    Designed to mirror the dv_well popup visual style while showing
    GOM-specific fields. The data-well-id attribute lets the click handler
    extract the GOM well's UUID (parallel to data-uwi for dv_well wells).

    Eight fields visible per the popup spec:
      1. Well name + Suffix
      2. BOEM API number
      3. Operator (company_name)
      4. Lease (surface + bottom area/block)
      5. Spud date
      6. Water depth (ft)
      7. Total depth MD / TVD (ft)
      8. Status code / Type code
    """
    well_id = well.get("well_id", "")
    name    = well.get("well_name") or "—"
    suffix  = well.get("well_name_suffix") or ""
    api     = well.get("api_well_number") or "—"
    op      = well.get("company_name") or "—"
    sl      = well.get("surface_lease_number") or "—"
    bl      = well.get("bottom_lease_number") or ""
    area    = well.get("bottom_area_code") or ""
    block   = (well.get("bottom_block_number") or "").strip()
    spud    = str(well.get("spud_date") or "—")[:10]

    # Numeric formatting with NaN protection
    def _fmt_ft(v):
        try:
            f = float(v)
            return f"{f:,.0f} ft" if f == f else "—"  # f==f filters NaN
        except (TypeError, ValueError):
            return "—"
    wd_ft   = _fmt_ft(well.get("water_depth_ft"))
    md_ft   = _fmt_ft(well.get("bh_total_md_ft"))
    tvd_ft  = _fmt_ft(well.get("tvd_ft"))

    # Compose lease label — show area/block if available
    lease_label = sl
    if area or block:
        lease_label = f"{sl} ({area} {block})".strip()

    status  = well.get("status_code") or "—"
    wtype   = well.get("type_code") or "—"

    # Friendly title — combine name + suffix when present
    title = f"{name} {suffix}".strip() if suffix else name

    # Color the status badge — teal for GOM (matches the layer's palette)
    return (
        f"<div data-well-id=\"{well_id}\" data-source=\"gom\" "
        f"style='font-size:11px;line-height:1.4;padding:0'>"
        f"<b style='font-size:12px;color:#0f172a'>🛢 {title}</b><br>"
        f"<span style='font-family:monospace;font-size:10px;color:#888'>"
        f"API {api}</span><br>"
        f"<span style='color:#475569;font-size:10px'>{op}</span><br>"
        f"<span style='color:#475569;font-size:10px'>Lease {lease_label}</span><br>"
        f"<b style='color:#0f766e;font-size:10px'>{status} · {wtype}</b><br>"
        f"<span style='font-size:10px;color:#475569'>Spud {spud}</span><br>"
        f"<span style='font-size:10px;color:#475569'>"
        f"WD {wd_ft} · MD {md_ft} · TVD {tvd_ft}</span>"
        f"</div>"
    )


def _add_gom_wells_markers(m, wells: list[dict]) -> int:
    """
    Render individual clickable CircleMarkers for drilled GOM wells.

    Called after a cell-Commit or circle-drill against GOM. Each marker
    is a circle filled with its status color (see BOEM_STATUS_COLORS)
    and an amber ring — the ring is the constant "drilled / interactive"
    cue, the fill tells you the well's status at a glance. The sidebar
    status checkboxes carry matching color swatches, so the sidebar
    doubles as the map legend.

    The popup uses _build_gom_popup_html which embeds data-well-id (the
    GOM UUID) so the click handler can identify which well was clicked.

    Args:
        m:     folium.Map
        wells: list of dicts as returned by _qry_gom_wells_in_bbox or
               _qry_gom_wells_in_circle

    Returns:
        number of markers rendered (for status caption)
    """
    if not wells:
        return 0

    fg = folium.FeatureGroup(
        name=f"🛢 GOM Wells Selection ({len(wells):,})",
        show=True,
    )

    rendered = 0
    for w in wells:
        try:
            lat = float(w["lat"])
            lon = float(w["lon"])
        except (TypeError, ValueError, KeyError):
            continue

        popup_html = _build_gom_popup_html(w)
        title      = w.get("well_name") or w.get("api_well_number") or "—"

        # Fill color is driven by the well's BOEM status_code. Unknown
        # or missing codes fall back to neutral slate inside
        # _boem_status_color.
        _fill = _boem_status_color(w.get("status_code", ""))

        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            color="#fbbf24",       # amber/gold ring — drilled marker
            weight=2,
            fill=True,
            fill_color=_fill,      # status color — see BOEM_STATUS_COLORS
            fill_opacity=0.9,
            opacity=1,
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=title,
        ).add_to(fg)
        rendered += 1

    fg.add_to(m)
    return rendered


# Trajectory simplification tuning. A GOM directional survey can carry
# hundreds to >3,700 stations per wellbore. Feeding every raw station to
# folium means streamlit-folium serializes tens of thousands of
# coordinate pairs into the map JS and the browser parses + renders all
# of them — that's the minute-plus stall on a 209-well draw, NOT the DB
# query (single indexed query, see _qry_gom_trajectories).
#
# Real GOM survey data splits into two populations:
#   - Vertical / near-vertical wells: thousands of stations occupying a
#     map footprint of only a few metres. These genuinely have no shape
#     to preserve at map zoom — collapsing them to ~2 points is correct.
#   - Deviated wells: 2-3 km of lateral reach with real doglegs and build
#     curves that the overlay exists to show.
# A single fixed tolerance can't serve both — it either flattens the
# deviated wells or fails to reduce the vertical ones. So tolerance is
# ADAPTIVE: each wellbore is simplified relative to its own bounding-box
# diagonal (a small %), with an absolute floor so a sub-metre vertical
# well doesn't get a degenerate near-zero tolerance.
#
# Douglas-Peucker keeps the *shape* (kickoff, build, doglegs, lateral)
# and drops redundant collinear vertices. _MAX_TRAJ_VERTICES is a hard
# safety cap so a pathologically noisy survey still can't blow up one
# polyline even if simplification can't reduce it enough.
_TRAJ_SIMPLIFY_FRAC  = 0.002      # tolerance = 0.2% of wellbore diagonal
_TRAJ_SIMPLIFY_FLOOR = 0.5        # absolute tolerance floor, in metres
_MAX_TRAJ_VERTICES   = 250        # hard per-wellbore vertex cap
_DEG_PER_M           = 1.0 / 111_320.0


def _adaptive_tol(points: list) -> float:
    """Per-wellbore Douglas-Peucker tolerance, in degrees.

    Scales to the wellbore's own extent: tolerance is _TRAJ_SIMPLIFY_FRAC
    of the lat/lon bounding-box diagonal, floored at _TRAJ_SIMPLIFY_FLOOR
    metres. A vertical well (tiny diagonal) gets the floor and collapses
    hard; a 2 km deviated well gets tens of metres and keeps its shape.
    """
    if len(points) < 3:
        return _TRAJ_SIMPLIFY_FLOOR * _DEG_PER_M
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    diag_deg = math.hypot(max(lats) - min(lats), max(lons) - min(lons))
    diag_m   = diag_deg / _DEG_PER_M
    tol_m    = max(diag_m * _TRAJ_SIMPLIFY_FRAC, _TRAJ_SIMPLIFY_FLOOR)
    return tol_m * _DEG_PER_M


def _perp_dist(pt, line_start, line_end) -> float:
    """Perpendicular distance from `pt` to the segment line_start→line_end.

    All points are (lat, lon). Treated as planar — fine for the small
    spans a single wellbore covers; the error from ignoring curvature is
    far below the simplification tolerance.
    """
    (y0, x0), (y1, x1), (y2, x2) = pt, line_start, line_end
    dy, dx = (y2 - y1), (x2 - x1)
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        # Degenerate segment — start == end. Fall back to point distance.
        return math.hypot(y0 - y1, x0 - x1)
    # Cross-product magnitude / segment length = perpendicular distance.
    return abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / math.sqrt(seg_len_sq)


def _douglas_peucker(points: list, tol: float) -> list:
    """Iterative Douglas-Peucker line simplification.

    Returns a subset of `points` (always keeps the first and last) such
    that no dropped point sat more than `tol` from the simplified line.
    Iterative (explicit stack) rather than recursive so a long survey
    can't hit Python's recursion limit.
    """
    n = len(points)
    if n < 3:
        return list(points)

    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]

    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        # Find the point farthest from the start→end chord.
        max_d, max_i = -1.0, -1
        a, b = points[start], points[end]
        for i in range(start + 1, end):
            d = _perp_dist(points[i], a, b)
            if d > max_d:
                max_d, max_i = d, i
        if max_d > tol:
            keep[max_i] = True
            stack.append((start, max_i))
            stack.append((max_i, end))

    return [points[i] for i in range(n) if keep[i]]


def _cap_vertices(points: list, cap: int) -> list:
    """Hard safety cap — if a wellbore still has more than `cap` points
    after Douglas-Peucker, evenly decimate down to `cap`. Always keeps
    the first and last station so surface and bottom-hole stay anchored.
    """
    n = len(points)
    if n <= cap:
        return points
    # Even stride sample, then force-include the last point.
    step = n / float(cap)
    idx = sorted(set(int(i * step) for i in range(cap)) | {n - 1})
    return [points[i] for i in idx]


@st.cache_data(ttl=300, show_spinner=False)
def _qry_gom_trajectories(_engine, well_ids: tuple) -> dict:
    """Survey-point trajectories for a set of GOM well_ids.

    Returns {well_id: [(lat, lon), ...]} — one ordered coordinate list
    per wellbore, stations ordered by measured depth. Each wellbore
    (including each sidetrack, which has its own well_id) is its own
    entry, so the renderer draws them as separate polylines.

    Cached on the well_id tuple — re-drilling the same set is free.
    Only points with both coordinates present are included; a survey
    station with a null lat/lon is skipped rather than breaking the line.

    Each wellbore's coordinate list is Douglas-Peucker simplified (and
    hard-capped at _MAX_TRAJ_VERTICES) BEFORE it's returned, so both the
    cache payload and the folium serialization stay small. A summary of
    the reduction is printed so the effect is visible, not silent.
    """
    if not well_ids:
        return {}
    # Parameterize the IN-list. well_ids is a tuple of UUID strings.
    _params = {f"w{i}": str(w) for i, w in enumerate(well_ids)}
    _in = ", ".join(f":{k}" for k in _params)
    sql = f"""
        SELECT CONVERT(VARCHAR(36), well_id) AS well_id,
               CAST(latitude  AS FLOAT) AS lat,
               CAST(longitude AS FLOAT) AS lon
        FROM dataview_gom.directional_survey_point
        WHERE well_id IN ({_in})
          AND latitude  IS NOT NULL
          AND longitude IS NOT NULL
        ORDER BY well_id, survey_point_md
    """
    out: dict = {}
    try:
        with _engine.connect().execution_options(timeout=30) as con:
            for r in con.execute(text(sql), _params):
                out.setdefault(r.well_id, []).append((r.lat, r.lon))
    except Exception as exc:
        st.warning(f"GOM trajectory query failed: {exc}")
        return {}

    # ── Simplify each wellbore before returning ──────────────────────
    # Raw survey stations are mostly collinear; Douglas-Peucker keeps the
    # shape and drops the redundancy. Tolerance is ADAPTIVE per wellbore
    # (see _adaptive_tol) — a vertical well collapses hard, a deviated
    # well keeps its curve. _cap_vertices is the hard backstop.
    # Single-station wellbores (len < 2) are left alone — the renderer
    # already skips anything under 2 points.
    _raw_total = 0
    _simp_total = 0
    for _wid, _pts in out.items():
        _raw_total += len(_pts)
        if len(_pts) < 2:
            _simp_total += len(_pts)
            continue
        _tol = _adaptive_tol(_pts)
        _simplified = _douglas_peucker(_pts, _tol)
        _simplified = _cap_vertices(_simplified, _MAX_TRAJ_VERTICES)
        out[_wid] = _simplified
        _simp_total += len(_simplified)

    # Visible, not silent — so the reduction is verifiable at a glance.
    if _raw_total:
        _pct = 100.0 * (1.0 - _simp_total / _raw_total)
        print(f"[GOM trajectories] {len(out):,} wellbores: "
              f"{_raw_total:,} raw stations → {_simp_total:,} points "
              f"({_pct:.1f}% reduction)")

    return out


def _add_gom_trajectories(m, wells: list[dict], engine) -> int:
    """Draw wellbore trajectory polylines for drilled GOM wells.

    Each wellbore is one polyline following its survey stations from
    surface to bottom hole. Sidetracks have their own well_id and survey
    rows, so they render as their own paths branching near the parent —
    no special branch logic needed.

    Path A design: only the currently-drilled wells get trajectories
    drawn, so the well set is always bounded by the drill. No reliance
    on a precomputed simplified-polyline table.

    Args:
        m:      folium.Map
        wells:  the drilled GOM well dicts (viewport_gom_wells)
        engine: SQLAlchemy engine

    Returns:
        number of trajectories drawn (for the status caption)
    """
    if not wells or engine is None:
        return 0

    # Collect well_ids from the drilled set. The dicts use "well_id"
    # (circle/bbox query shape) — fall back to "uwi" just in case.
    _wids = []
    for w in wells:
        _wid = str(w.get("well_id") or w.get("uwi") or "").strip()
        if _wid:
            _wids.append(_wid)
    if not _wids:
        return 0

    traj = _qry_gom_trajectories(engine, tuple(sorted(set(_wids))))
    if not traj:
        return 0

    fg = folium.FeatureGroup(
        name=f"🌀 GOM Trajectories ({len(traj):,})",
        show=True,
    )
    # well_id → well dict, for the polyline tooltip
    _by_id = {str(w.get("well_id") or w.get("uwi") or "").strip(): w
              for w in wells}

    drawn = 0
    for wid, coords in traj.items():
        # A polyline needs at least two points. A single-station well
        # (rare) has nothing to draw as a line.
        if len(coords) < 2:
            continue
        _w = _by_id.get(wid, {})
        _name = _w.get("well_name") or _w.get("api_well_number") or wid
        _sfx  = _w.get("well_name_suffix") or ""
        _label = f"{_name} {_sfx}".strip() if _sfx else _name
        folium.PolyLine(
            locations=coords,
            color="#06b6d4",     # cyan — distinct from the amber-ring markers
            weight=2,
            opacity=0.85,
            tooltip=f"{_label} — {len(coords):,} stations",
        ).add_to(fg)
        drawn += 1

    fg.add_to(m)
    return drawn



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


def _add_seismic_3d(m, df):
    """Render 3D seismic survey footprints as filled rectangles.

    Path A for seismic on the map: bbox-as-rectangle. Each 3D survey shows
    as a translucent blue rectangle bounded by its BBOX_MIN/MAX_LAT/LON.
    This is geometrically correct for 3D surveys (they ARE rectangular
    footprints) — unlike 2D lines, which need actual polyline extraction
    and are deferred to Stage B.

    Click any rectangle for a popup with file name, contractor, trace
    count, sample interval, EPSG, and survey date.
    """
    if df.empty:
        return
    fg = folium.FeatureGroup(
        name=f"🟦 Seismic 3D Surveys ({len(df):,})", show=False
    )

    for _, row in df.iterrows():
        # Defensive bbox sanity. Even after the SQL filter, some rows may
        # come back with min > max (rare segyio quirk). Skip those — a
        # negative-area rectangle would render as a line, confusing.
        try:
            min_lat = float(row["min_lat"])
            max_lat = float(row["max_lat"])
            min_lon = float(row["min_lon"])
            max_lon = float(row["max_lon"])
        except (TypeError, ValueError):
            continue
        if not (min_lat < max_lat and min_lon < max_lon):
            continue

        # Skip ludicrously large bboxes — these indicate a CDP_X/Y scalar
        # misread, where we got raw scaled coordinates instead of lat/lon.
        # Anything bigger than 5 degrees in either dimension is almost
        # certainly garbage for a 3D survey (largest single 3D surveys are
        # ~2 degrees on a side).
        if (max_lat - min_lat) > 5 or (max_lon - min_lon) > 5:
            continue

        # Build a popup with the survey metadata that's worth knowing
        # before someone digs deeper into the file. Trim long values.
        _name = row.get("survey_name") or row.get("line_name") \
                or row.get("file_name") or "Unnamed 3D"
        _name = str(_name)[:80]
        _popup = folium.Popup(
            f"<b>🟦 {_name}</b><br>"
            + _popup_table({
                "File":     str(row.get("file_name") or "—")[:80],
                "Contractor": str(row.get("contractor") or "—")[:60],
                "Date":     str(row.get("survey_date") or "—"),
                "Traces":   f"{int(row['trace_count']):,}"
                            if pd.notna(row.get("trace_count")) else "—",
                "Sample interval": f"{row['sample_interval']:g} μs"
                            if pd.notna(row.get("sample_interval")) else "—",
                "EPSG":     str(int(row["epsg_code"]))
                            if pd.notna(row.get("epsg_code")) else "—",
                "Extent":   f"{max_lat-min_lat:.3f}° × {max_lon-min_lon:.3f}°",
            }),
            max_width=280,
        )

        folium.Rectangle(
            bounds=[[min_lat, min_lon], [max_lat, max_lon]],
            color="#1d4ed8",
            weight=2,
            fill=True,
            fill_color="#3b82f6",
            fill_opacity=0.25,
            popup=_popup,
            tooltip=_name,
        ).add_to(fg)

    fg.add_to(m)


def _add_gom_well_grid(
    m,
    df: pd.DataFrame,
    step: float = 0.36,
    selected_set: set | None = None,
    interactive: bool = True,
) -> int:
    """
    Render the GOM wells density-grid overview layer.

    Same architectural pattern as _add_well_grid (main dv_well grid), but
    reads pre-aggregated cell rows from dataview_gom.well and renders them
    in a yellow→teal palette to distinguish GOM from the main wells layer
    (which uses yellow→red).

    Cells with high well counts are dark teal; sparse cells are pale
    yellow. The user can quickly see where GOM well density is high
    (productive areas like Mississippi Canyon, Green Canyon) vs low.

    Phase 2 update: cells are now clickable. Each cell carries a popup
    with the same "GRID_CELL|lat|lon|step|count" marker that the dv_well
    cells use, so the existing click handler in run() picks them up and
    toggles them in the shared `selected_cells` buffer. The cells in
    `selected_set` (string keys of "lat|lon") render with a bold blue
    outline so the user can see what's queued for Commit.

    Args:
        m: folium.Map
        df: result of _qry_gom_well_grid — columns lat_bin, lon_bin,
            well_count, center_lat, center_lon
        step: cell size in degrees (must match what was used to bin;
              default 0.36° matches _qry_gom_well_grid — ~25 miles)
        selected_set: optional set of "lat_bin|lon_bin" keys identifying
            cells the user has multi-selected for drill

    Returns:
        number of cells rendered (for status caption)
    """
    if df is None or df.empty:
        return 0

    import math

    # Log scale on counts so the heatmap is readable across the dynamic
    # range. Same approach as the main grid — GOM offshore blocks have
    # similar count-distribution properties (sparse fringe, dense core).
    max_count = max(int(df["well_count"].max()), 1)
    log_max = math.log10(max_count + 1) or 1.0

    # Yellow → teal palette. Distinct from the main wells layer
    # (yellow→red) so overlapping regions are visually distinguishable.
    # Six stops for smooth gradation.
    palette = [
        "#fff5b1",  # 0.0 — very pale yellow (few wells)
        "#d4f1d4",  # 0.2 — pale mint
        "#86efac",  # 0.4 — light teal-green
        "#34d399",  # 0.6 — teal-green
        "#14b8a6",  # 0.8 — teal (the requested GOM color)
        "#0f766e",  # 1.0 — deep teal (many wells)
    ]

    def _color_for(count: int) -> str:
        if count <= 0:
            return palette[0]
        t = math.log10(count + 1) / log_max
        idx = min(int(t * len(palette)), len(palette) - 1)
        return palette[idx]

    if selected_set is None:
        selected_set = set()

    # FeatureGroup name includes well count for at-a-glance scale awareness.
    total_wells = int(df["well_count"].sum())
    grid_group = folium.FeatureGroup(
        name=f"🛢 GOM Wells (grid · {total_wells:,})",
        show=True,
    )

    cells_rendered = 0
    for row in df.itertuples(index=False):
        try:
            lat_bin = float(row.lat_bin)
            lon_bin = float(row.lon_bin)
            count   = int(row.well_count)
        except (TypeError, ValueError):
            continue

        color = _color_for(count)
        bounds = [
            [lat_bin, lon_bin],
            [lat_bin + step, lon_bin + step],
        ]

        # Is this cell currently in the selection buffer?
        # The buffer is shared across area sources — Phase 3 will dispatch
        # the actual Commit drill based on active_area.
        _cell_key = f"{lat_bin:.4f}|{lon_bin:.4f}"
        _is_selected = _cell_key in selected_set

        # Selected cells get a bold blue outline. The teal fill color
        # (density-coded) stays the same so the user can still read
        # "I selected dense vs sparse cells." Unselected cells get the
        # default teal-dark thin border.
        if _is_selected:
            border_color  = "#1d4ed8"   # bold blue — matches dv_well selected style
            border_weight = 4
            tooltip_html  = f"<b>{count:,}</b> GOM wells — ✓ selected (click again to deselect)"
        else:
            border_color  = "#0f766e"   # dark teal — matches palette
            border_weight = 0.5
            tooltip_html  = f"<b>{count:,}</b> GOM wells — click to select"

        # Render as a Rectangle with a count tooltip. NO popup — popups
        # trigger streamlit-folium reruns when they auto-close, rebuilding
        # the entire map. Click coordinates come from last_object_clicked
        # at the run-level handler; cell identification is via floor-div
        # of click coords by step.
        # See _add_well_grid: when `interactive` is False (Circle mode)
        # the cell is inert so the circle-draw press isn't stolen by the
        # polygon click. Tooltip is dropped too since an inert layer
        # wouldn't surface it on hover anyway. As in _add_well_grid, the
        # `interactive` flag must be set on .options after construction —
        # folium 0.20's constructor kwarg for it is silently dropped.
        _rect = folium.Rectangle(
            bounds=bounds,
            color=border_color,
            weight=border_weight,
            fill=True,
            fill_color=color,
            fill_opacity=0.6,
            tooltip=(folium.Tooltip(tooltip_html, sticky=True)
                     if interactive else None),
        )
        _rect.options["interactive"] = interactive
        _rect.add_to(grid_group)
        cells_rendered += 1

    grid_group.add_to(m)
    return cells_rendered


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


def _build_gom_scout_ticket_html(well_id, well_row, engine=None):
    """
    Build a scout ticket for one GOM well.

    GOM wells live in dataview_gom.well, which is a header table — there
    are no GOM equivalents of dv_well's aux tables (formation tops,
    surveys, completions, production, cores) yet. So this ticket renders
    the sections the GOM schema can actually fill — Well Header,
    Location & Lease, Depths, Dates — and shows labelled PLACEHOLDER
    panels for the aux sections so the layout matches the dv_well ticket
    and it's obvious what will populate once those tables exist.

    well_row is a GOM well dict (the shape _qry_gom_wells_in_circle /
    _qry_gom_wells_in_bbox return, shadow-cached in tray_well_data). If
    `engine` is provided we refresh from dataview_gom.well by well_id so
    the ticket reflects current data even if the cached dict is stale.
    """
    # Refresh from the table when we can — the cached tray dict may be
    # from an earlier drill. Fall back to the cached row on any failure.
    if engine is not None and well_id:
        try:
            with engine.connect().execution_options(timeout=10) as con:
                _r = con.execute(text("""
                    SELECT CONVERT(VARCHAR(36), well_id) AS well_id,
                           well_name, well_name_suffix, api_well_number,
                           company_name, region,
                           surface_lease_number, bottom_lease_number,
                           bottom_area_code, bottom_block_number,
                           type_code, status_code, casing_cut_code,
                           CONVERT(VARCHAR(10), spud_date,        120) AS spud_date,
                           CONVERT(VARCHAR(10), total_depth_date, 120) AS total_depth_date,
                           CONVERT(VARCHAR(10), status_date,      120) AS status_date,
                           CAST(bh_total_md_ft         AS FLOAT) AS bh_total_md_ft,
                           CAST(true_vertical_depth_ft AS FLOAT) AS true_vertical_depth_ft,
                           CAST(tvd_subsea_ft          AS FLOAT) AS tvd_subsea_ft,
                           CAST(rkb_ft                 AS FLOAT) AS rkb_ft,
                           CAST(kop_ft                 AS FLOAT) AS kop_ft,
                           CAST(water_depth_ft         AS FLOAT) AS water_depth_ft,
                           CAST(surface_latitude  AS FLOAT) AS surface_latitude,
                           CAST(surface_longitude AS FLOAT) AS surface_longitude,
                           CAST(bottom_latitude   AS FLOAT) AS bottom_latitude,
                           CAST(bottom_longitude  AS FLOAT) AS bottom_longitude,
                           source_file
                    FROM dataview_gom.well
                    WHERE well_id = :wid
                """), {"wid": str(well_id)}).fetchone()
                if _r is not None:
                    well_row = dict(_r._mapping)
        except Exception:
            pass  # keep the cached well_row

    # Directional survey — pull this well's stations from
    # dataview_gom.directional_survey_point. A well can have hundreds or
    # thousands of stations, so the ticket shows a summary line plus the
    # first N stations rather than the whole trajectory. We query by
    # well_id (resolved by the well_id-resolution pass); falls back to
    # an empty result on any failure so the section just shows "none".
    _SRVY_PREVIEW_N = 15
    srvy_rows: list = []
    srvy_summary: dict = {}
    if engine is not None and well_id:
        try:
            with engine.connect().execution_options(timeout=10) as con:
                # Summary first — count, max MD, max inclination — cheap
                # aggregate over the indexed well_id.
                _s = con.execute(text("""
                    SELECT COUNT(*)            AS n_stations,
                           MAX(survey_point_md)  AS max_md,
                           MAX(survey_point_tvd) AS max_tvd,
                           MAX(incl_ang)         AS max_incl
                    FROM dataview_gom.directional_survey_point
                    WHERE well_id = :wid
                """), {"wid": str(well_id)}).fetchone()
                if _s is not None:
                    srvy_summary = dict(_s._mapping)
                # Preview rows — first N stations by measured depth.
                _sr = con.execute(text(f"""
                    SELECT TOP ({_SRVY_PREVIEW_N})
                           CAST(survey_point_md  AS FLOAT) AS md,
                           CAST(incl_ang         AS FLOAT) AS incl,
                           CAST(azimuth          AS FLOAT) AS azim,
                           CAST(survey_point_tvd AS FLOAT) AS tvd,
                           CAST(latitude         AS FLOAT) AS lat,
                           CAST(longitude        AS FLOAT) AS lon
                    FROM dataview_gom.directional_survey_point
                    WHERE well_id = :wid
                    ORDER BY survey_point_md
                """), {"wid": str(well_id)}).fetchall()
                srvy_rows = [dict(r._mapping) for r in _sr]
        except Exception:
            srvy_rows = []
            srvy_summary = {}

    def _g(*keys):
        """First non-empty value across possible key names, else em-dash."""
        for k in keys:
            v = well_row.get(k)
            if v is not None and str(v).strip() not in ("", "None", "nan"):
                return v
        return chr(8212)

    # Header fields — tolerate both the refreshed-row names and the
    # circle/bbox dict names (they mostly overlap; tvd differs).
    name   = _g("well_name")
    suffix = well_row.get("well_name_suffix") or ""
    title  = f"{name} {suffix}".strip() if suffix and name != chr(8212) else name
    api    = _g("api_well_number", "api_num")
    op     = _g("company_name", "operator_name")
    status = str(_g("status_code")).strip()
    wtype  = str(_g("type_code")).strip()
    status_disp = _boem_status_label(status) if status != chr(8212) else chr(8212)
    status_col  = _boem_status_color(status) if status != chr(8212) else "#888"

    # Lease / location
    sl     = _g("surface_lease_number")
    bl     = _g("bottom_lease_number")
    area   = well_row.get("bottom_area_code") or ""
    block  = (str(well_row.get("bottom_block_number") or "")).strip()
    area_disp = _boem_area_name(area) if area else chr(8212)
    area_block = f"{area_disp} ({area} {block})".strip() if area else chr(8212)
    region = _g("region")

    def _coords(latk, lonk):
        lat = well_row.get(latk); lon = well_row.get(lonk)
        try:
            if lat is None or lon is None:
                return chr(8212)
            latf = float(lat); lonf = float(lon)
            if latf != latf or lonf != lonf:   # NaN guard
                return chr(8212)
            ns = "N" if latf >= 0 else "S"
            ew = "E" if lonf >= 0 else "W"
            return f"{abs(latf):.6f}{ns}  {abs(lonf):.6f}{ew}"
        except (TypeError, ValueError):
            return chr(8212)
    surf_loc = _coords("surface_latitude", "surface_longitude")
    bott_loc = _coords("bottom_latitude", "bottom_longitude")

    # Depths — tvd column name differs between the refreshed row
    # (true_vertical_depth_ft) and the circle/bbox dict (tvd_ft).
    md   = well_row.get("bh_total_md_ft")
    tvd  = (well_row.get("true_vertical_depth_ft")
            if well_row.get("true_vertical_depth_ft") is not None
            else well_row.get("tvd_ft"))
    tvdss = well_row.get("tvd_subsea_ft")
    rkb  = well_row.get("rkb_ft")
    kop  = well_row.get("kop_ft")
    wd   = well_row.get("water_depth_ft")

    spud = str(_g("spud_date"))[:10]
    tdd  = str(_g("total_depth_date"))[:10]
    std  = str(_g("status_date"))[:10]
    src  = _g("source_file")

    _ph = ("<div style='padding:10px 14px;color:#94a3b8;font-size:12px;"
           "font-style:italic;background:#f8fafc;border:1px solid #e2e8f0;"
           "border-top:none'>Not yet loaded for Gulf of America wells — "
           "this section will populate when the data is available.</div>")

    # ── Directional Survey section ───────────────────────────────────────
    # Real section now that dataview_gom.directional_survey_point is
    # loaded. Shows a summary line (station count, max MD/TVD, max
    # inclination) plus the first N stations. If the well has no survey
    # rows, falls back to a "no survey data" note rather than the
    # generic placeholder — the data path exists, this well just lacks it.
    _n_srvy = srvy_summary.get("n_stations") or 0
    if _n_srvy and srvy_rows:
        _more = _n_srvy - len(srvy_rows)
        _srvy_caption = (
            f"Directional Survey — {_n_srvy:,} station"
            f"{'s' if _n_srvy != 1 else ''}"
            + (f", showing first {len(srvy_rows)}" if _more > 0 else "")
        )
        # Summary strip above the station table
        _srvy_summary_html = (
            "<div style='padding:7px 14px;font-size:12px;color:#475569;"
            "background:#f1f5f9;border:1px solid #cbd5e1;border-top:none'>"
            f"Max MD <b>{_fmt(srvy_summary.get('max_md'), suffix=' ft')}</b>"
            f" &nbsp;·&nbsp; Max TVD "
            f"<b>{_fmt(srvy_summary.get('max_tvd'), suffix=' ft')}</b>"
            f" &nbsp;·&nbsp; Max Inclination "
            f"<b>{_fmt(srvy_summary.get('max_incl'), fmt=',.1', suffix='°')}</b>"
            "</div>"
        )
        # Station rows — MD / Inclination / Azimuth / TVD / Lat / Lon
        _srvy_body = "".join(
            _td([
                _fmt(r.get("md"),   suffix=" ft"),
                _fmt(r.get("incl"), fmt=",.2", suffix="°"),
                _fmt(r.get("azim"), fmt=",.2", suffix="°"),
                _fmt(r.get("tvd"),  suffix=" ft"),
                (f"{r['lat']:.6f}" if r.get("lat") is not None else chr(8212)),
                (f"{r['lon']:.6f}" if r.get("lon") is not None else chr(8212)),
            ], alt=(i % 2 == 1))
            for i, r in enumerate(srvy_rows)
        )
        _srvy_section = (
            _section(_srvy_caption)
            + _srvy_summary_html
            + _tbl(
                _th(["MD", "Inclination", "Azimuth", "TVD",
                     "Latitude", "Longitude"])
                + _srvy_body
            )
        )
    else:
        # Data path exists, this well just has no survey stations.
        _srvy_section = (
            _section("Directional Survey")
            + "<div style='padding:10px 14px;color:#94a3b8;font-size:12px;"
              "font-style:italic;background:#f8fafc;border:1px solid #e2e8f0;"
              "border-top:none'>No directional survey stations found for "
              "this well.</div>"
        )

    html = f"""
    <div style='font-family:Arial,Helvetica,sans-serif;border:2px solid #334155;
                border-radius:8px;overflow:hidden;margin-bottom:8px;
                background:#ffffff;color:#1e293b'>
      <div style='background:#334155;color:#ffffff;padding:14px 18px;
                  border-bottom:4px solid {status_col};
                  display:flex;justify-content:space-between;align-items:center'>
        <div>
          <div style='font-size:17px;font-weight:700;letter-spacing:1.5px;color:#ffffff'>WELL SCOUT TICKET</div>
          <div style='font-size:12px;color:#cbd5e1;margin-top:2px'>DataView &nbsp;·&nbsp; Gulf of America &nbsp;·&nbsp; {op}</div>
        </div>
        <span style='background:{status_col};color:#ffffff;padding:4px 14px;
              border-radius:12px;font-size:12px;font-weight:700;letter-spacing:0.5px;
              border:1px solid rgba(255,255,255,0.25)'>{status_disp}</span>
      </div>

      {_section("Well Header")}
      {_tbl(
        _th(["API","Well Name","Well Type","Status"]) +
        _td([api, f"<b>{title}</b>", wtype, status_disp]) +
        _th(["Operator","Region","Source File",""]) +
        _td([op, region, f"<span style='font-size:11px'>{src}</span>", ""], alt=True) +
        _th(["Well ID (UUID)","","",""]) +
        _td([f"<span style='font-family:monospace;font-size:11px'>{well_id}</span>",
             "", "", ""])
      )}

      {_section("Location & Lease")}
      {_tbl(
        _th(["Surface Lease","Bottom Lease","Area / Block",""]) +
        _td([sl, bl, area_block, ""]) +
        _th(["Surface Location","Bottom Location","",""]) +
        _td([surf_loc, bott_loc, "", ""], alt=True)
      )}

      {_section("Depths")}
      {_tbl(
        _th(["Total Depth MD","True Vertical Depth","TVD Subsea","Water Depth"]) +
        _td([_fmt(md, suffix=" ft"), _fmt(tvd, suffix=" ft"),
             _fmt(tvdss, suffix=" ft"), _fmt(wd, suffix=" ft")]) +
        _th(["RKB Elevation","Kickoff Point (KOP)","",""]) +
        _td([_fmt(rkb, suffix=" ft"), _fmt(kop, suffix=" ft"), "", ""], alt=True)
      )}

      {_section("Dates")}
      {_tbl(
        _th(["Spud Date","Total Depth Date","Status Date",""]) +
        _td([spud or chr(8212), tdd or chr(8212), std or chr(8212), ""])
      )}

      {_section("Stratigraphy — Formation Tops")}
      {_ph}

      {_srvy_section}

      {_section("Completions & Stimulation")}
      {_ph}

      {_section("Production")}
      {_ph}

      <div style='background:#334155;color:#cbd5e1;font-size:10px;
                  padding:6px 14px;text-align:center;letter-spacing:0.5px'>
        CONFIDENTIAL &nbsp;|&nbsp; {op}
        &nbsp;|&nbsp; {title}
        &nbsp;|&nbsp; DataView Scout Ticket &nbsp;·&nbsp; Gulf of America
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

def run(engine=None):
    if not HAS_FOLIUM:
        st.error("pip install folium streamlit-folium")
        return
    if engine is None:
        st.info("Connect to the DataView database first.")
        return

    # Module-level first-run flag must be declared global up front so the
    # reset block below can read and write it.
    global _PROCESS_FIRST_RUN_DONE

    # ── Cold-start reset ───────────────────────────────────────────────
    # When the Streamlit process FIRST runs this module (process startup,
    # not just a re-render), force a clean slate for:
    #   - wm_area_sel (the Area dropdown) — defaults to "— Select area —"
    #   - _wm_prev_area_id (the "what was last selected" tracker)
    #   - _drawn_bounds (any prior auto-zoom bounds that would re-fit map)
    # We detect first-run via a module-level global, NOT session_state,
    # because session_state can survive Streamlit restarts in some
    # configurations and that's exactly what we're guarding against.
    if not _PROCESS_FIRST_RUN_DONE:
        _PROCESS_FIRST_RUN_DONE = True
        # Force Area selector back to placeholder
        st.session_state["wm_area_sel"] = "— Select area —"
        # Clear the area-change tracker so the auto-zoom logic doesn't
        # see "selection changed from None to placeholder" and fire
        st.session_state["_wm_prev_area_id"] = "none"
        # Drop any prior auto-zoom bounds so the map opens at its
        # default basemap centroid instead of yesterday's Permian view
        st.session_state.pop("_drawn_bounds", None)

    # Reset the sticky "preload all wells" flag on every page entry. The flag
    # was originally meant to remember "user already triggered the wells
    # preload in THIS render cycle, don't re-fire it" — but Streamlit's
    # session_state persists across cold starts of Streamlit and across
    # browser refreshes, so it became a permanent trap: once set in any
    # session, every subsequent cold start would re-fire the 30s _qry_wells
    # preload. The Area-selector partitioning makes that preload unnecessary
    # on first paint — the grid layers query their own tables directly. So:
    # reset to False on every entry. The flag will be re-set later in the
    # same render cycle if a Query type that needs wells gets selected.
    st.session_state["_wells_already_loaded"] = False

    _status = st.empty()

    # ── Phased progress indicator at the top of the page ───────────────
    # A single shared progress bar + message that any slow operation can
    # drive through phases (query → process → render). Hidden when idle.
    # Operations call _phase(pct, "Status text") to update; _phase(100, "")
    # clears both widgets. The widgets are placed at the top so the user
    # always sees them during long loads — they don't have to look down
    # at the map area to know something is happening.
    _phase_msg = st.empty()
    _phase_bar = st.empty()

    def _phase(pct: int, text: str = ""):
        """Update or clear the top-of-page progress indicator.

        Args:
            pct: 0–100 progress percent. pct >= 100 clears the indicator.
            text: status message to display alongside the bar.
        """
        if pct >= 100:
            _phase_msg.empty()
            _phase_bar.empty()
        else:
            if text:
                _phase_msg.info(text)
            _phase_bar.progress(min(max(pct, 0), 99))

    # Lazy-load strategy: skip the expensive _qry_wells call on first load.
    # Grid mode is the default and doesn't need the full wells list — the
    # density polygons come from a separate aggregation query (sub-second).
    # We only pay the cost of pulling 50K+ wells when the user actually
    # needs them: switches to Wells mode, opens search dropdowns, or uses
    # the AI filter.
    _need_wells = (
        st.session_state.get("map_mode", "grid") == "wells"
        or st.session_state.get("ai_filter_spec") is not None
        or st.session_state.get("_wells_already_loaded", False)
    )

    if _need_wells:
        # Wells mode (or AI filter / dropdown active) — load the full well list.
        # This is the 30-second hit. Show a real progress bar at the top so the
        # user knows the system is working and roughly when it'll finish.
        #
        # We can't get true progress from a single SQL query, so we use a
        # three-stage indicator with sleeps that match typical execution time:
        #   0–40%  during DB query (the slowest part)
        #   40–80% during JSON parse
        #   80–100% during pandas conversion + cache write
        # If the query takes longer than expected, we hold at 80% until done.
        #
        # Schema dispatch: the Area selector (top4) renders AFTER this
        # loader, so active_area isn't set yet. Read the user's last area
        # choice from session state — same lookahead pattern Zoom-To and
        # the Query whitelist use. A GOM-only area loads from
        # dataview_gom.well; everything else uses the dv_well path.
        _wells_area_label = st.session_state.get("wm_area_sel")
        _wells_area = next(
            (a for a in AREAS if a["label"] == _wells_area_label),
            AREAS[0],
        )
        _wells_srcs = _wells_area.get("sources", [])
        _use_gom_wells = ("gom" in _wells_srcs and "main" not in _wells_srcs)

        _prog_msg = _status.empty()
        _prog_bar = st.progress(0)
        _prog_msg.info("⏳ Loading wells from DataView — this takes ~20-30 seconds…")
        try:
            _prog_bar.progress(10)
            if _use_gom_wells:
                _wells_raw = _qry_gom_wells(engine)
            else:
                _wells_raw = _qry_wells(engine)
            _prog_bar.progress(80)
            _prog_msg.info(f"⏳ Processing {len(_wells_raw):,} wells…")
            st.session_state["_wells_already_loaded"] = True
            _prog_bar.progress(100)
            _prog_msg.success(f"✅ Loaded {len(_wells_raw):,} wells")
        except Exception as _wq_err:
            _prog_msg.error(f"Wells load failed: {_wq_err}")
            _wells_raw = []
        finally:
            # Clear the progress widgets shortly after completion. They've
            # served their purpose; leaving them clutters the UI.
            import time
            time.sleep(0.5)
            _prog_bar.empty()
            _prog_msg.empty()
    else:
        # Grid mode default — show grid immediately, skip the heavy query
        _wells_raw = []

    _status.info("⏳ Loading spatial layers…")
    shp_layers = _load_shp_layers(engine)
    _status.empty()
    # counts_df loaded lazily below — only when a "Has X" filter is active

    # Apply AI filter if active (only meaningful when we have wells)
    _ai_spec = st.session_state.get("ai_filter_spec")
    _display_wells = (
        _apply_ai_filter(_wells_raw, _ai_spec)
        if _ai_spec and _wells_raw
        else _wells_raw
    )

    # Convert list-of-dicts to DataFrame once — all downstream code unchanged.
    # In lazy-load case this is an empty DataFrame, which is fine: the grid
    # render path doesn't use it, and the dropdowns/filters gracefully show
    # empty lists.
    wells_df  = pd.DataFrame(_display_wells) if _display_wells else pd.DataFrame()
    # Build the UWI index used for scout-ticket lookups.
    # Two sources:
    #   1. _wells_raw — the full wells list (populated only in Wells mode or
    #      when filters force a wells load)
    #   2. tray_well_data — the shadow cache populated by grid-cell drills
    #      and rectangle drills (always available regardless of mode)
    # We combine them so scout tickets work whether the user is in grid mode
    # with drilled wells OR in wells mode with the full list.
    uwi_index = {w["uwi"]: w for w in _wells_raw}
    _shadow = st.session_state.get("tray_well_data", {})
    for _u, _w in _shadow.items():
        # Tray-shadow wells fill in only where _wells_raw didn't already cover
        if _u not in uwi_index:
            uwi_index[_u] = _w

    # ── Resolve the active Area BEFORE rendering the top bar ──────────
    # The Area selector widget lives in top4 (rightmost column), but the
    # Zoom-To (top2) and Query (top3) dropdowns need to know the active
    # area to build their options. Streamlit renders columns in code
    # order, so top2/top3 would otherwise see a stale wm_area_sel from
    # the previous run — that's the "Query only shows All wells" bug.
    #
    # Fix: resolve active_area here, up front, from the session-state
    # value the Area widget wrote on the LAST run. On the run where the
    # user changes the area, the widget in top4 updates wm_area_sel, and
    # because the widget key is bound, st.session_state["wm_area_sel"]
    # already reflects the NEW selection by the time this code runs on
    # the NEXT script execution. The Area widget in top4 still renders
    # and drives the selection; this block just reads the current value
    # early so every dropdown in the top bar agrees within one run.
    _area_labels_display = [
        (a["label"] if a["enabled"] else f"{a['label']} (no data)")
        for a in AREAS
    ]
    _area_sel_current = st.session_state.get("wm_area_sel",
                                             _area_labels_display[0])
    try:
        _active_idx = _area_labels_display.index(_area_sel_current)
    except ValueError:
        _active_idx = 0
    active_area = AREAS[_active_idx]

    # ── Top bar above map: Background | Zoom | Query | Area ────────────
    top1, top2, top3, top4 = st.columns([1, 1, 2, 1])
    with top1:
        basemap = st.selectbox("🖼 Background", list(BASEMAPS.keys()),
                               index=0, key="wm_basemap")
    with top2:
        # Zoom-To options depend on the active Area, resolved above.
        _zt_sources = active_area.get("sources", [])
        try:
            if "gom" in _zt_sources and "main" not in _zt_sources:
                # GOM-only area → OCS protraction-area targets
                zoom_targets = _qry_gom_zoom_targets(engine)
            elif "main" in _zt_sources:
                # West Texas / All regions → dv_well fields/basins/counties.
                # (All-regions uses the main targets; GOM area-code targets
                # would bloat the list. Good enough — refine later if needed.)
                zoom_targets = _qry_zoom_targets(engine)
            else:
                # No area selected (placeholder) — nothing to zoom to yet
                zoom_targets = [{"label": "— Zoom to location —",
                                 "lat": None, "lon": None, "zoom": 6}]
        except Exception:
            zoom_targets = [{"label": "— Zoom to location —",
                             "lat": None, "lon": None, "zoom": 7}]

        # If the previously-selected zoom target isn't in the new list
        # (area changed), reset to the placeholder. Pop the widget key so
        # the selectbox re-inits from index 0 without an illegal write.
        _zt_labels = [t["label"] for t in zoom_targets]
        _prev_zt = st.session_state.get("wm_zoom_target")
        if _prev_zt and _prev_zt not in _zt_labels:
            st.session_state.pop("wm_zoom_target", None)

        zoom_sel    = st.selectbox("🔍 Zoom to", _zt_labels,
                                   index=0, key="wm_zoom_target")
        zoom_target = next((t for t in zoom_targets
                            if t["label"]==zoom_sel), None)
    with top3:
        # Master list of every query type the page knows how to run.
        # label → qtype-key. Each AREAS entry's "queries" list says which
        # of these keys are valid for that area's schema.
        QUERIES = {
            "All wells":None,"By operator":"operator","By field":"field",
            "By county":"county","By well type":"well_type",
            "By source":"source",
            "By area":"area",
            "Has formation tops":"has_tops","Has production data":"has_prod",
            "Has DST":"has_dst","Has directional survey":"has_survey",
            "Has core data":"has_core","Has petro interpretation":"has_petro",
        }
        # Map qtype-key → label so we can go from a whitelist entry back
        # to its display label. "all" is the key for the None ("All
        # wells") option.
        _qkey_to_label = {("all" if v is None else v): k
                          for k, v in QUERIES.items()}

        # The active area was resolved up front (before the top columns).
        # Use it directly — no stale-lookahead needed. active_area's
        # "queries" list is the whitelist of valid query-type keys for
        # that area's schema.
        _allowed_qkeys = active_area.get("queries", ["all"])
        # Build the visible options in QUERIES order, keeping only the
        # ones whitelisted for this area.
        _query_labels = [
            _qkey_to_label[k] for k in
            ["all","operator","field","county","well_type","source","area",
             "has_tops","has_prod","has_dst","has_survey",
             "has_core","has_petro"]
            if k in _allowed_qkeys and k in _qkey_to_label
        ]

        # If the previously-selected query isn't valid for the new area
        # (e.g. user had "By field" selected, then switched to GOM which
        # doesn't offer it), drop the stale selection so the selectbox
        # falls back to the first option. Pop rather than assign — you
        # can't set a widget's state key after it's instantiated, but
        # popping it before instantiation is fine.
        _prev_qsel = st.session_state.get("wm_query_sel")
        if _prev_qsel is not None and _prev_qsel not in _query_labels:
            st.session_state.pop("wm_query_sel", None)

        qsel   = st.selectbox("📋 Query", _query_labels,
                              key="wm_query_sel")
        qtype  = QUERIES[qsel]
        qvalue = None
        # If user picks a query type that needs wells data, trigger a load
        # on the next rerun (no-op if already loaded).
        if qtype in ("operator", "field", "county", "well_type", "source", "area",
                     "has_tops", "has_prod", "has_dst",
                     "has_survey", "has_core", "has_petro"):
            if not st.session_state.get("_wells_already_loaded", False):
                st.session_state["_wells_already_loaded"] = True
                st.rerun()
    with top4:
        # Area selector — partitions which region's well data renders on the
        # map. Single-select. "All regions" shows everything from every
        # available source. Disabled regions appear in the list but are
        # treated as "All regions" (no data to show yet).
        #
        # active_area was already resolved up front (before the top
        # columns) so Zoom-To and Query could use it within the same run.
        # This widget renders the selector and writes wm_area_sel; the
        # display list it uses is the same _area_labels_display computed
        # up front. We don't re-derive active_area here — the up-front
        # resolution is authoritative for this run. When the user picks a
        # different area, wm_area_sel updates and the NEXT run's up-front
        # resolution picks it up.
        area_sel = st.selectbox(
            "📍 Area", _area_labels_display,
            index=_active_idx, key="wm_area_sel",
            help="Partition wells by producing area. Each area reads from "
                 "its own schema (e.g., dataview_gom.well for GOM). "
                 "'All regions' shows every available source.",
        )

        # Auto-zoom to the area's centroid when the selection changes.
        # We compare the chosen id to the last-seen id and trigger a one-shot
        # _drawn_bounds set so the existing fit_bounds machinery snaps the
        # map to the right region.
        # The placeholder area (id="none") doesn't trigger auto-zoom — it
        # has no meaningful destination, just stays wherever the user is.
        _prev_area_id = st.session_state.get("_wm_prev_area_id")
        if (active_area["enabled"]
                and active_area["id"] != "none"
                and active_area["id"] != _prev_area_id):
            st.session_state["_wm_prev_area_id"] = active_area["id"]
            # Compute a small bounding box from the centroid + zoom-derived
            # span. Lower zoom = bigger span. The fit_bounds receiver expects
            # [[min_lat, min_lon], [max_lat, max_lon]].
            _clat, _clon, _czoom = active_area["center"]
            # Rough span based on zoom: each zoom level halves the span
            _span = max(0.5, 30.0 / (2 ** (_czoom - 4)))
            st.session_state["_drawn_bounds"] = [
                [_clat - _span/2, _clon - _span],
                [_clat + _span/2, _clon + _span],
            ]
            # Mark this as a ONE-SHOT fit. The map consumer will pop the
            # bounds after applying them once, so subsequent reruns (e.g.
            # cell clicks) don't keep snapping the view back to the area
            # overview. Cell-Commit drills and circle drills set
            # _drawn_bounds WITHOUT this flag — those persist correctly.
            st.session_state["_drawn_bounds_oneshot"] = True
            # Also reset any cell selection from the prior area — different
            # region, different cells, no carry-over makes sense
            st.session_state["selected_cells"] = []
            st.session_state.pop("_last_grid_click", None)
        if qtype == "operator" and not wells_df.empty:
            qvalue = st.selectbox("Operator",
                sorted(wells_df["operator_name"].dropna().unique()),
                key="wm_q_op", label_visibility="collapsed")
        elif qtype == "field" and not wells_df.empty:
            qvalue = st.selectbox("Field",
                sorted(wells_df["field_name"].dropna().unique()),
                key="wm_q_field", label_visibility="collapsed")
        elif qtype == "county" and not wells_df.empty:
            qvalue = st.selectbox("County",
                sorted(wells_df["county"].dropna().unique()),
                key="wm_q_county", label_visibility="collapsed")
        elif qtype == "well_type" and not wells_df.empty:
            qvalue = st.selectbox("Well Type",
                sorted(wells_df["well_type"].dropna().unique()),
                key="wm_q_wtype", label_visibility="collapsed")
        elif qtype == "source" and not wells_df.empty:
            _src_opts = sorted(wells_df["source"].dropna().unique()) if "source" in wells_df.columns else []
            qvalue = st.selectbox("Source", _src_opts,
                key="wm_q_source", label_visibility="collapsed") if _src_opts else None
        elif qtype == "area" and not wells_df.empty:
            _area_opts = sorted(wells_df["area"].dropna().unique()) if "area" in wells_df.columns else []
            qvalue = st.selectbox("Area", _area_opts,
                key="wm_q_area", label_visibility="collapsed") if _area_opts else None

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

        # Status — the checkbox list is schema-aware. Which status values
        # exist depends on the active area's table:
        #   GOM (dataview_gom.well)  → raw BOEM status_code values
        #                              (PA, ST, COM, TA, …)
        #   main / dv_well           → if wells are loaded, the distinct
        #                              well_status values; otherwise the
        #                              standard PPDM 3.9 fallback set.
        # Pulling GOM codes is a cheap cached GROUP BY, so the sidebar can
        # show the right values without loading the full wells list.
        _area_is_gom = ("gom" in active_area.get("sources", [])
                        and "main" not in active_area.get("sources", []))
        if _area_is_gom:
            all_statuses = _qry_gom_status_codes(engine)
            if not all_statuses:
                # Query failed or table empty — degrade gracefully rather
                # than showing dv_well's PPDM codes, which would be wrong
                # for GOM. An empty list means "no status filter shown".
                all_statuses = []
        elif not wells_df.empty:
            all_statuses = sorted(wells_df["well_status"].dropna().unique())
        else:
            all_statuses = [
                "ACTIVE", "DRY", "LOCATION", "PLUGGED",
                "PLUGGED_AND_ABANDONED", "UNKNOWN",
            ]
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
            # For GOM, show a color swatch + friendly label so the
            # sidebar doubles as the map legend. Streamlit checkbox
            # labels strip inline HTML, so the swatch can't go in the
            # label itself — instead we lay out [swatch | checkbox] in
            # two columns, the swatch being a small HTML block whose
            # background is the status color. For non-GOM areas there's
            # no swatch; the code is shown as-is.
            # The checkbox VALUE is always the raw code — the filter
            # compares status_code against sel_statuses — so the label
            # and swatch are purely cosmetic.
            if _area_is_gom:
                _sw_col, _cb_col = st.columns([1, 12])
                with _sw_col:
                    st.markdown(
                        f"<div style='width:12px;height:12px;border-radius:3px;"
                        f"background:{_boem_status_color(o)};margin-top:6px;'>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
                with _cb_col:
                    _checked = st.checkbox(_boem_status_label(o),
                                           key=f"wm_status_{o}")
            else:
                _checked = st.checkbox(f"● {o}", key=f"wm_status_{o}")
            if _checked:
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
            # GOM wells are now driven by the top-bar Area selector — no
            # separate checkbox here. The Area dropdown is the single
            # source of truth for which region's wells render on the map.
            # GOM Trajectories is rendered outside this expander (below)
            # so it's visible without expanding Overlays first.

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
        # Safe filter — if nothing selected fall back to show all.
        # When wells_df is empty (lazy-load not yet fired), dff is also empty
        # — the grid render path handles that gracefully (it has its own data).
        _ss  = sel_statuses or list(all_statuses)
        counts_df = pd.DataFrame()  # populated lazily if a has_X filter is used
        if wells_df.empty:
            dff = wells_df  # empty
        else:
            # Include wells with NULL well_status unless the user has
            # explicitly deselected statuses (i.e. _ss < all_statuses).
            # OSDU wells and other sources may not have well_status set.
            _status_explicitly_filtered = bool(sel_statuses) and \
                set(sel_statuses) != set(all_statuses)
            if _status_explicitly_filtered:
                mask = wells_df["well_status"].isin(_ss)
            else:
                # No explicit status filter — show everything including NULLs
                mask = pd.Series(True, index=wells_df.index)
            # Single-value query filters (top bar)
            if qtype == "operator" and qvalue:
                mask &= wells_df["operator_name"] == qvalue
            elif qtype == "field" and qvalue:
                mask &= wells_df["field_name"] == qvalue
            elif qtype == "county" and qvalue:
                mask &= wells_df["county"] == qvalue
            elif qtype == "well_type" and qvalue:
                mask &= wells_df["well_type"] == qvalue
            elif qtype == "source" and qvalue:
                if "source" in wells_df.columns:
                    mask &= wells_df["source"] == qvalue
            elif qtype == "area" and qvalue:
                if "area" in wells_df.columns:
                    mask &= wells_df["area"] == qvalue
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

        # Diagnostic — remove after confirming source filter works
        if qtype == "source" and qvalue:
            _src_col_exists = "source" in wells_df.columns
            _src_vals = sorted(wells_df["source"].dropna().unique().tolist()) \
                        if _src_col_exists else []
            st.caption(
                f"🔬 Source filter debug: "
                f"col_exists={_src_col_exists} · "
                f"values_in_df={_src_vals} · "
                f"filter_value={repr(qvalue)} · "
                f"wells_df={len(wells_df)} rows · "
                f"dff={len(dff)} rows · "
                f"has_lat={dff['lat'].notna().sum() if not dff.empty else 0}"
            )
        if wells_df.empty:
            st.caption(
                "🔵 Grid mode (wells not yet loaded — switch to Wells mode "
                "or pick a filter to load the full well list)"
                + (f" · {len(active_db)} DB layer(s)" if active_db else "")
                + (f" · {len(active_shp)} shapefile(s)" if active_shp else "")
            )
        else:
            st.caption(
                f"**{len(dff)}** of **{len(wells_df)}** wells"
                + (f" · {len(active_db)} DB layer(s)" if active_db else "")
                + (f" · {len(active_shp)} shapefile(s)" if active_shp else "")
            )

        # ── Map mode toggle ──────────────────────────────────────────────
        # Grid mode: server-aggregated density polygons (~100s, fast).
        # Wells mode: full cluster markers + rectangle viewport (original).
        # Default to grid because on first load (50K wells) it's dramatically
        # faster to serialize. User can flip to Wells when they need detail.
        _mode_col, _mode_help = st.columns([3, 5])
        with _mode_col:
            _current_mode = st.session_state.get("map_mode", "grid")
            _new_mode = st.radio(
                "Map mode",
                options=["grid", "wells", "geojson"],
                index={"grid":0,"wells":1,"geojson":2}.get(_current_mode,0),
                format_func=lambda m: (
                    "🔵 Grid" if m == "grid"
                    else "📍 Wells" if m == "wells"
                    else "🗺️ GeoJSON"
                ),
                horizontal=True,
                label_visibility="collapsed",
                key="map_mode_radio",
            )
            if _new_mode != _current_mode:
                st.session_state["map_mode"] = _new_mode
                # Switching modes invalidates the viewport markers / drawn
                # bounds — wipe them so they don't linger across modes.
                if _new_mode == "grid":
                    st.session_state["viewport_uwis"] = []
                st.rerun()
        with _mode_help:
            if _new_mode == "grid":
                st.caption(
                    "🔵 **Grid mode** — click cells to select, **Commit** to drill. "
                    "Toggle 'Show grid' to hide the heatmap."
                )
            elif _new_mode == "geojson":
                st.caption(
                    "🗺️ **GeoJSON mode** — renders wells from a .shp file "
                    "as a fast GeoJSON layer. Click any well to open its "
                    "scout ticket from the database."
                )
            elif _new_mode == "wells":
                st.caption(
                    "📍 **Wells mode** — cluster bubbles + rectangle viewport. "
                    "Switch to 🔵 Grid for a fast aggregated view of all wells."
                )

        # ── Grid-mode controls — Show toggle + multi-select commit ────────
        # Only relevant when in grid mode. Lays out as:
        #   [ Show grid ☑ ]  [ Selection: 3 cells (1,847 wells) ]  [ ✅ Commit ] [ ✗ Clear ]
        # On commit: drill the bbox of the union of selected cells, hide
        # the grid, zoom the map to the selection extent. Cap: 5,000 wells.
        if _new_mode == "grid":
            _MAX_WELLS = 5000

            _sel = list(st.session_state.get("selected_cells", []))
            _sel_n     = len(_sel)

            # Look up cell well counts from the cached grid queries. Cells
            # are stored as (lat_bin, lon_bin, _) — the third element is a
            # placeholder zero from the coord-based click handler since the
            # click event itself doesn't carry the count. We re-query the
            # grid (which is @st.cache_data, so subsequent calls are free)
            # and match each selected cell to its row.
            _sel_wells = 0
            if _sel:
                # Determine which grids are active (could be one or both)
                _src = active_area.get("sources", [])
                _main_grid = None
                _gom_grid = None
                if "main" in _src:
                    try:
                        _main_grid = _qry_well_grid(engine, step=0.035)
                    except Exception:
                        _main_grid = None
                if "gom" in _src:
                    try:
                        _gom_grid = _qry_gom_well_grid(engine)
                    except Exception:
                        _gom_grid = None

                # For each selected cell, hit-test against whichever grid
                # has a matching bin. Cells are deduped by sig already, so
                # a cell can only belong to one grid even if both are active.
                for _cell in _sel:
                    _cl_lat, _cl_lon = float(_cell[0]), float(_cell[1])
                    _cell_count = 0
                    # Try main grid first (step 0.035)
                    if _main_grid is not None and not _main_grid.empty:
                        _match = _main_grid[
                            (_main_grid["lat_bin"].round(4) == round(_cl_lat, 4)) &
                            (_main_grid["lon_bin"].round(4) == round(_cl_lon, 4))
                        ]
                        if not _match.empty:
                            _cell_count = int(_match.iloc[0]["well_count"])
                    # If no match in main, try GOM grid (step 0.36)
                    if _cell_count == 0 and _gom_grid is not None and not _gom_grid.empty:
                        _match = _gom_grid[
                            (_gom_grid["lat_bin"].round(4) == round(_cl_lat, 4)) &
                            (_gom_grid["lon_bin"].round(4) == round(_cl_lon, 4))
                        ]
                        if not _match.empty:
                            _cell_count = int(_match.iloc[0]["well_count"])
                    _sel_wells += _cell_count

            _over_cap  = _sel_wells > _MAX_WELLS

            c1, c2, c3, c4 = st.columns([2, 4, 2, 1])
            with c1:
                _show_grid = st.toggle(
                    "Show grid",
                    value=st.session_state.get("grid_visible", True),
                    key="grid_visible_toggle",
                    help="Hide the density grid to see just the drilled wells",
                )
                if _show_grid != st.session_state.get("grid_visible", True):
                    st.session_state["grid_visible"] = _show_grid
                    st.rerun()

                # Selection mode — Cells vs Circle. These two input modes
                # both listen to map mouse events, and they conflict: a
                # circle drill is a press-drag-release gesture, but if the
                # press lands on a grid cell, the cell-click handler grabs
                # it and the circle never starts. Making the modes mutually
                # exclusive fixes that — in Circle mode the cell-click
                # handler is skipped entirely (see the cell-click block),
                # so the drag gesture is unambiguous. Default is Cells.
                _sel_mode = st.radio(
                    "Selection mode",
                    options=["Cells", "Circle"],
                    index=0 if st.session_state.get(
                        "gom_sel_mode", "Cells") == "Cells" else 1,
                    key="gom_sel_mode_radio",
                    horizontal=True,
                    help="Cells: click grid cells to multi-select. "
                         "Circle: draw a radius circle on the map. "
                         "Only one is active at a time so the click and "
                         "drag gestures don't fight each other.",
                )
                if _sel_mode != st.session_state.get("gom_sel_mode", "Cells"):
                    st.session_state["gom_sel_mode"] = _sel_mode
                    # Switching modes clears any half-made cell selection —
                    # it wouldn't make sense to carry pending cells into
                    # Circle mode.
                    if _sel_mode == "Circle":
                        st.session_state["selected_cells"] = []
                        st.session_state.pop("_last_grid_click", None)
                    st.rerun()

            with c2:
                if _sel_n == 0:
                    # No cells selected — but wells may be loaded from a
                    # previous drill (cell Commit or circle). Tell the user
                    # which state they're in so the Clear button isn't a
                    # mystery.
                    _vp_count = len(st.session_state.get("viewport_uwis", []))
                    if _vp_count:
                        st.caption(
                            f"📍 **{_vp_count:,}** wells loaded. Click more "
                            f"cells or draw a circle to refine, or **Clear** "
                            f"to start over."
                        )
                    else:
                        st.caption(
                            "💡 Click grid cells to multi-select, then "
                            "**Commit** to drill the combined area. Or draw "
                            "a circle for a radius drill."
                        )
                elif _over_cap:
                    st.error(
                        f"⚠️ Selection: **{_sel_n}** cell(s) · "
                        f"~**{_sel_wells:,}** wells — over the {_MAX_WELLS:,} "
                        f"cap. Deselect dense cells before committing."
                    )
                else:
                    st.success(
                        f"📐 Selection: **{_sel_n}** cell(s) · "
                        f"~**{_sel_wells:,}** wells "
                        f"(cap {_MAX_WELLS:,})"
                    )

            with c3:
                _commit_disabled = (_sel_n == 0) or _over_cap
                if st.button(
                    "✅ Commit",
                    key="grid_commit_btn",
                    disabled=_commit_disabled,
                    use_container_width=True,
                    type="primary",
                ):
                    # Determine drill targets from the active area's sources.
                    # Each source has its own step and drill query:
                    #   "main" → 0.035° step → _qry_wells_in_bbox (dv_well)
                    #   "gom"  → 0.36° step → _qry_gom_wells_in_bbox (dataview_gom.well)
                    # If both are active (All regions), we drill both and
                    # store results separately so each renders with its
                    # own marker style.
                    _active_sources = active_area.get("sources", [])

                    # Compute the bbox of the union of selected cells.
                    # Use the step of whichever source is active (or the
                    # finer of the two if both). Cell coords are stored
                    # with whichever step they were clicked at; we add the
                    # step to get the cell's east/north edge.
                    if "main" in _active_sources and "gom" not in _active_sources:
                        _step = 0.035
                    elif "gom" in _active_sources and "main" not in _active_sources:
                        _step = 0.36
                    else:
                        # All-regions or unexpected — use the finer step
                        # since that's what cells were rendered at.
                        _step = 0.035

                    _lats = [c[0] for c in _sel] + [c[0] + _step for c in _sel]
                    _lons = [c[1] for c in _sel] + [c[1] + _step for c in _sel]
                    _bbox_min_lat = min(_lats)
                    _bbox_max_lat = max(_lats)
                    _bbox_min_lon = min(_lons)
                    _bbox_max_lon = max(_lons)

                    # Drill each active source. Errors from one source
                    # don't block the other — collect results independently.
                    _drilled_main: list = []
                    _drilled_gom:  list = []
                    _total_main = 0
                    _total_gom  = 0

                    # Phase the drill — query phase per source, then a
                    # final processing phase before rerun. The map rebuild
                    # phase (after rerun) is handled separately by the
                    # grid/marker render blocks which drive _phase too.
                    _phase(10, f"📐 Drilling up to {_MAX_WELLS:,} wells from {_sel_n} cell(s)…")

                    if "main" in _active_sources:
                        try:
                            _phase(25, f"📐 Querying dv_well in selection bbox…")
                            _drilled_main, _total_main = _qry_wells_in_bbox(
                                engine,
                                _bbox_min_lat, _bbox_max_lat,
                                _bbox_min_lon, _bbox_max_lon,
                                limit=_MAX_WELLS,
                            )
                        except Exception as _qe:
                            st.error(f"Main drill failed: {_qe}")

                    if "gom" in _active_sources:
                        try:
                            _phase(55, f"🛢 Querying dataview_gom.well in selection bbox…")
                            _drilled_gom, _total_gom = _qry_gom_wells_in_bbox(
                                engine,
                                _bbox_min_lat, _bbox_max_lat,
                                _bbox_min_lon, _bbox_max_lon,
                                limit=_MAX_WELLS,
                            )
                        except Exception as _qe:
                            st.error(f"GOM drill failed: {_qe}")

                    _phase(85, "📐 Processing drill results…")
                    _total_drilled = len(_drilled_main) + len(_drilled_gom)

                    if _total_drilled:
                        # Store main-source results in viewport_uwis +
                        # tray_well_data shadow (existing pattern).
                        if _drilled_main:
                            st.session_state.viewport_uwis = [
                                w["uwi"] for w in _drilled_main
                            ]
                            _shadow = st.session_state.get("tray_well_data", {})
                            for w in _drilled_main:
                                _shadow[w["uwi"]] = w
                            st.session_state["tray_well_data"] = _shadow
                        else:
                            # No main drill this time — clear stale viewport
                            # so it doesn't carry over from a prior drill
                            st.session_state.viewport_uwis = []

                        # Store GOM-source results in their own viewport
                        # key. The render path checks this separately and
                        # uses _add_gom_wells_markers (amber-ring teal-fill
                        # style) for these wells.
                        if _drilled_gom:
                            st.session_state["viewport_gom_wells"] = _drilled_gom
                        else:
                            st.session_state["viewport_gom_wells"] = []

                        # Tell the map to fit to the selection bounds.
                        # No oneshot flag — this is a real drill, the fit
                        # should persist until Clear or another drill.
                        st.session_state["_drawn_bounds"] = [
                            [_bbox_min_lat, _bbox_min_lon],
                            [_bbox_max_lat, _bbox_max_lon],
                        ]

                        # Hide the grid — user wants to see the wells now.
                        # Set the internal grid_visible flag, and POP the
                        # widget's session_state key rather than assigning
                        # it — Streamlit forbids writing a widget's key
                        # after the widget has instantiated (the toggle
                        # renders earlier in the script than this Commit
                        # handler). Popping is allowed; on the next rerun
                        # the toggle re-initializes from grid_visible via
                        # its value= argument.
                        st.session_state["grid_visible"] = False
                        st.session_state.pop("grid_visible_toggle", None)

                        # Clear the selection buffer — drill done
                        st.session_state["selected_cells"] = []
                        st.session_state.pop("_last_grid_click", None)

                        # Build a status message reflecting which sources fired
                        _parts = []
                        if _drilled_main:
                            _parts.append(f"{len(_drilled_main):,} main")
                        if _drilled_gom:
                            _parts.append(f"{len(_drilled_gom):,} GOM")
                        st.success(
                            f"📐 Loaded **{' + '.join(_parts)}** wells "
                            f"from {_sel_n} cell(s). Grid hidden — toggle "
                            f"'Show grid' to select more."
                        )
                        st.rerun()
                    else:
                        st.info("No wells found in selected cells")

            with c4:
                # Clear button now clears EVERYTHING map-selection-related:
                # - cell multi-select buffer
                # - drilled wells from any source (cell Commit or circle)
                # - drawn circle (re-allows drawing the same shape again)
                # - drawn bounds (so map doesn't snap back to the old area)
                # - restores grid visibility so user can start a fresh selection
                # Does NOT touch the tray — that's separate, persistent across
                # drills. Use 🗑 Clear Tray at the bottom of the page for that.
                _has_wells  = bool(st.session_state.get("viewport_uwis")) or \
                              bool(st.session_state.get("viewport_gom_wells"))
                _has_drawn  = bool(st.session_state.get("processed_drawings"))
                _clear_disabled = not (_sel_n or _has_wells or _has_drawn)
                if st.button(
                    "✗ Clear",
                    key="grid_clear_btn",
                    disabled=_clear_disabled,
                    use_container_width=True,
                    help="Clear cells, drilled wells, and drawn circles",
                ):
                    # Cell-selection buffer
                    st.session_state["selected_cells"] = []
                    st.session_state.pop("_last_grid_click", None)
                    # Drilled wells viewport — both sources
                    st.session_state["viewport_uwis"] = []
                    st.session_state["viewport_gom_wells"] = []
                    # Drawn shapes — clearing the dedupe set lets the same
                    # circle be redrawn from scratch (Leaflet.Draw itself
                    # keeps its drawn layers until user uses the trash icon
                    # in the toolbar, which is independent of this)
                    st.session_state["processed_drawings"] = set()
                    # Map fit — drop the bounds so the map returns to
                    # the default/centroid view, not the last drilled area
                    st.session_state.pop("_drawn_bounds", None)
                    # Bring the grid back so the user can pick again.
                    # Set grid_visible, POP the widget key (assigning a
                    # widget's key after it instantiated is forbidden —
                    # see Commit handler comment). Toggle re-inits from
                    # grid_visible on the next rerun.
                    st.session_state["grid_visible"] = True
                    st.session_state.pop("grid_visible_toggle", None)
                    # Signal the view-persist JS to wipe its sessionStorage
                    # entry on the next render. Otherwise Clear would land
                    # the map back on the last-viewed area, not the default.
                    st.session_state["_reset_saved_view"] = True
                    st.rerun()

        # GOM Trajectories toggle — rendered outside the 💾 Overlays
        # expander so it's always visible when GOM is active. The
        # Overlays expander is collapsed by default, making the checkbox
        # invisible until the user knows to look for it. Moving it here
        # keeps it alongside the other GOM-specific grid controls
        # (Selection mode, Show grid) that the user interacts with after
        # drilling wells. The Overlays expander version is removed to
        # avoid a duplicate key; this is now the single source of truth.
        if _area_is_gom and _new_mode == "grid":
            _gom_traj_on = st.checkbox(
                "🌀 GOM Trajectories",
                key="wm_db_gom_traj",
                help="Draw wellbore survey paths for the currently-drilled "
                     "GOM wells. Drill a cell or circle first, then toggle "
                     "this on. Each sidetrack shows as its own path.",
            )
            if _gom_traj_on:
                active_db.add("db_gom_trajectories")

        # Build map — always show basemap even if no wells
        bm   = BASEMAPS.get(basemap, BASEMAPS["OpenStreetMap"])

        # Center priority:
        #   1. _drawn_bounds — set by circle Haversine drill or cell Commit.
        #      This is the authoritative "show me this area" signal. It's
        #      stored as [[min_lat, min_lon], [max_lat, max_lon]] in session
        #      state and used directly without needing the wells in dff.
        #   2. viewport_uwis + dff lookup — older path for when wells came
        #      via the main wells query (used to be the rectangle workflow).
        #   3. Explicit zoom target from dropdown.
        #   4. Default: centroid of full filtered dataset.
        _viewport_bounds = None

        # Path 1: _drawn_bounds — authoritative for circle/cell drills.
        # The handlers that set it already padded if appropriate.
        _drawn = st.session_state.get("_drawn_bounds")
        if _drawn and isinstance(_drawn, list) and len(_drawn) == 2:
            try:
                _db_min_lat = float(_drawn[0][0])
                _db_min_lon = float(_drawn[0][1])
                _db_max_lat = float(_drawn[1][0])
                _db_max_lon = float(_drawn[1][1])
                # Pad 15% so the selection isn't pressed against the map edge.
                # Smaller than the wells-in-dff path because _drawn_bounds is
                # already the circle's bbox, not a wells-extent-bbox.
                _pad_lat = max(0.005, (_db_max_lat - _db_min_lat) * 0.15)
                _pad_lon = max(0.005, (_db_max_lon - _db_min_lon) * 0.15)
                _viewport_bounds = [
                    [_db_min_lat - _pad_lat, _db_min_lon - _pad_lon],
                    [_db_max_lat + _pad_lat, _db_max_lon + _pad_lon],
                ]
                lat0 = (_db_min_lat + _db_max_lat) / 2
                lon0 = (_db_min_lon + _db_max_lon) / 2
                zoom0 = 11  # initial guess, fit_bounds will adjust precisely
            except (TypeError, ValueError, IndexError):
                _viewport_bounds = None

        # Path 2: viewport_uwis present in dff — legacy path for when wells
        # came in via the main query (full wells_df). Still useful in wells
        # mode or when the main dataset is loaded.
        if _viewport_bounds is None:
            _viewport_uwis_for_center = st.session_state.get("viewport_uwis", [])
            if _viewport_uwis_for_center and not dff.empty:
                _vp_set  = set(_viewport_uwis_for_center)
                _vp_subset = dff[dff["uwi"].astype(str).isin(_vp_set)]
                if not _vp_subset.empty:
                    _vp_lats = _vp_subset["lat"].astype(float)
                    _vp_lons = _vp_subset["lon"].astype(float)
                    _vp_min_lat, _vp_max_lat = float(_vp_lats.min()), float(_vp_lats.max())
                    _vp_min_lon, _vp_max_lon = float(_vp_lons.min()), float(_vp_lons.max())
                    # Pad bounds 30% so zoom is comfortable, not crowded.
                    _pad_lat = max(0.005, (_vp_max_lat - _vp_min_lat) * 0.3)
                    _pad_lon = max(0.005, (_vp_max_lon - _vp_min_lon) * 0.3)
                    _viewport_bounds = [
                        [_vp_min_lat - _pad_lat, _vp_min_lon - _pad_lon],
                        [_vp_max_lat + _pad_lat, _vp_max_lon + _pad_lon],
                    ]
                    lat0 = (_vp_min_lat + _vp_max_lat) / 2
                    lon0 = (_vp_min_lon + _vp_max_lon) / 2
                    zoom0 = 11

        if _viewport_bounds is None:
            # No viewport — use zoom_target or compute a sensible default.
            # Note: we deliberately do NOT try to preserve user pan/zoom
            # state here. Subscribing to streamlit-folium's center/zoom
            # returns either triggers extra reruns or doesn't reliably
            # report back in this version, so the trade-off isn't worth
            # it. Users may see the map snap to default after a cell click
            # — that's the cost of keeping pan smooth.
            if zoom_target and zoom_target.get("lat"):
                lat0  = zoom_target["lat"]
                lon0  = zoom_target["lon"]
                zoom0 = zoom_target["zoom"]
                # Build a bounding box around the zoom target so it goes
                # through the same fit_bounds + SKIP_FLAG machinery as
                # drills. Without this, the view-persist JS restores the
                # user's last saved view and the zoom target never takes.
                # Box half-size shrinks as zoom level grows — roughly the
                # span folium shows at that zoom for a 500px-tall map.
                # The x2 widens the box ~1 zoom level further out, so a
                # Zoom-To lands with the area in context rather than
                # filling the whole viewport.
                _zt_zoom = zoom_target["zoom"]
                _zt_half = (180.0 / (2 ** _zt_zoom)) * 2.0   # degrees, rough
                _viewport_bounds = [
                    [lat0 - _zt_half, lon0 - _zt_half],
                    [lat0 + _zt_half, lon0 + _zt_half],
                ]
            elif not dff.empty:
                # Wells loaded — center on their centroid
                lat0  = dff["lat"].mean()
                lon0  = dff["lon"].mean()
                zoom0 = 7
            elif active_area["id"] == "none":
                # No area selected — show a neutral default view. Don't
                # query dv_well for a centroid; with no area picked, the
                # user hasn't said "I want to see anything specific,"
                # so we shouldn't auto-zoom into wherever the legacy
                # dv_well data happens to live. Zoom 3 gives a comfortable
                # USA-wide view that fits typical screens better than 4.
                lat0, lon0, zoom0 = 39.0, -98.0, 3   # US centroid
            elif "main" in active_area.get("sources", []):
                # An area that uses the main dv_well source IS selected.
                # Use the dv_well centroid as the initial view (cheap
                # aggregation query, falls back to US center on failure).
                try:
                    _center_grid = _qry_well_grid(engine, step=0.035)
                    if not _center_grid.empty:
                        lat0 = float(_center_grid["center_lat"].mean())
                        lon0 = float(_center_grid["center_lon"].mean())
                        zoom0 = 7
                    else:
                        lat0, lon0, zoom0 = 39.0, -98.0, 4
                except Exception:
                    lat0, lon0, zoom0 = 39.0, -98.0, 4
            else:
                # An area is selected that doesn't include "main" (e.g. GOM).
                # Use that area's registered center as the fallback. The
                # auto-zoom code normally handles this via _drawn_bounds,
                # but if that hasn't fired yet, fall back to AREAS center.
                _clat, _clon, _czoom = active_area["center"]
                lat0, lon0, zoom0 = float(_clat), float(_clon), int(_czoom)

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

        # Consume one-shot _drawn_bounds. The area-change auto-zoom sets
        # _drawn_bounds_oneshot=True so the bounds fit the map ONCE on
        # area selection, then we drop them. Without this pop, every
        # subsequent rerun (cell clicks, layer toggles, etc.) would
        # re-fit the view, destroying any manual zoom the user did to
        # pick a specific cell. Drills (cell-Commit, circle) set
        # _drawn_bounds WITHOUT the oneshot flag, so they persist.
        #
        # IMPORTANT: capture whether THIS render is doing a fit BEFORE
        # we pop the bounds. The view-persist JS later reads SKIP_FLAG
        # to know if Python is doing a fit (in which case JS skips the
        # saved-view restore). If we pop the bounds before SKIP_FLAG is
        # computed, the JS thinks Python did NO fit, restores the old
        # GOM view, and the user lands in the ocean instead of West Texas.
        _is_oneshot_fit_this_render = bool(
            st.session_state.get("_drawn_bounds_oneshot")
        )
        if _is_oneshot_fit_this_render:
            st.session_state.pop("_drawn_bounds", None)
            st.session_state.pop("_drawn_bounds_oneshot", None)

        if bm.get("overlay"):
            folium.TileLayer(
                tiles=bm["overlay"], attr=bm["attr"],
                name="Labels", overlay=True,
                control=False, opacity=1.0,
            ).add_to(m)

        # Mode dispatch — set by the radio toggle above the map.
        # "grid" = fast aggregated overview (server-side binning)
        # "wells" = full clusters + viewport markers (full wells list)
        # Grid mode doesn't need the wells dataframe — only wells mode does.
        # Default to grid on first load (matches session_state init below).
        _map_mode = st.session_state.get("map_mode", "grid")
        _skip_folium = False

        if _map_mode == "grid":
            # Honor the "Show grid" toggle — when off, we still pass through
            # grid mode but skip the grid render. The user gets just the
            # basemap + any drilled wells. This is the workflow for "I
            # already drilled, now I want to see just the wells without
            # the heatmap underneath."
            # ALSO: gate on the Area selector. The main grid reads from
            # dataview.dv_well, which currently holds the legacy KGS data.
            # The Area registry tags this source as "main". If the selected
            # area doesn't include "main", skip rendering the main grid.
            _show_main_grid = (
                st.session_state.get("grid_visible", True)
                and "main" in active_area.get("sources", [])
            )
            if _show_main_grid:
                _msg.info(f"🔵 Loading grid overview…")
                try:
                    _phase(15, "📊 Querying West Texas wells — typically 10-15 seconds…")
                    _grid_df = _qry_well_grid(engine, step=0.035)
                    _phase(50, f"📊 Aggregating {int(_grid_df['well_count'].sum()):,} wells into grid cells…")
                    # Pass current selection set so cells the user has
                    # multi-selected get the bold-blue-outline render.
                    _sel = st.session_state.get("selected_cells", [])
                    _sel_keys = {f"{c[0]:.4f}|{c[1]:.4f}" for c in _sel}
                    # In Circle selection mode the grid cells must be inert
                    # so a circle-draw press that lands on a cell isn't
                    # consumed by the cell's click handler. Cells mode keeps
                    # them interactive for click-to-select.
                    _grid_interactive = (
                        st.session_state.get("gom_sel_mode", "Cells") == "Cells"
                    )
                    _cell_count = _add_well_grid(
                        m, _grid_df, step=0.035, selected_set=_sel_keys,
                        interactive=_grid_interactive,
                    )
                    # NOTE: do NOT _phase(100) here — the bar persists
                    # through to the st_folium call below which is the
                    # real long pole. Final clear happens after that.
                    if _cell_count:
                        _sel_n = len(_sel_keys)
                        _sel_note = f" · {_sel_n} selected" if _sel_n else ""
                        _msg.info(
                            f"🔵 Grid: {_cell_count:,} cells · "
                            f"{int(_grid_df['well_count'].sum()):,} wells aggregated"
                            f"{_sel_note}"
                        )
                    else:
                        _msg.info("🔵 No wells to aggregate")
                except Exception as _e:
                    _phase(100)
                    st.warning(f"Grid render skipped: {_e}")
                    # If grid fails for any reason, fall back to wells mode
                    # so the user still sees something.
                    st.session_state["map_mode"] = "wells"
            else:
                _msg.info("🔵 Grid hidden — toggle 'Show grid' to bring it back")

            # In grid mode, drilled wells (from clicking a cell or drawing
            # a rectangle) still render as yellow markers ON TOP of the
            # grid. This way the user can drill into one cell and see its
            # individuals while the rest of the map keeps showing the grid
            # density layer.
            _viewport_uwis = st.session_state.get("viewport_uwis", [])
            if _viewport_uwis:
                try:
                    # Build a small dataframe from the tray-shadow cache
                    # (the wells query that populated viewport_uwis also
                    # stashed full data in tray_well_data). This avoids
                    # needing the full wells_df in grid mode.
                    shadow = st.session_state.get("tray_well_data", {})
                    if shadow:
                        _vp_df = pd.DataFrame([
                            shadow[u] for u in _viewport_uwis
                            if u in shadow
                        ])
                        if not _vp_df.empty:
                            _vp_count = _add_viewport_wells(
                                m, _vp_df, _viewport_uwis
                            )
                            if _vp_count:
                                _msg.info(
                                    f"🔵 Grid + {_vp_count:,} drilled wells"
                                )
                except Exception as _e:
                    st.warning(f"Drilled wells render skipped: {_e}")
                    st.session_state["viewport_uwis"] = []
        elif _map_mode == "geojson":
            # GeoJSON / pydeck mode — loads pre-built wells.geojson,
            # filters in memory, renders via pydeck (WebGL).
            # The pydeck map replaces Folium entirely for this mode.
            _full_gj = _load_well_geojson()
            _all_features = _full_gj.get("features", [])

            if not _all_features:
                _msg.warning(
                    "🗺️ No wells.geojson file found. Run "
                    "`python build_well_geojson.py` to generate it, "
                    "or click **Refresh GeoJSON** below."
                )
            else:
                # Build filter options from the loaded data
                _schemas = sorted({f["properties"].get("schema","")
                                   for f in _all_features} - {""})
                _areas   = sorted({f["properties"].get("area","")
                                   for f in _all_features} - {""})
                _sources = sorted({f["properties"].get("source","")
                                   for f in _all_features} - {""})

                _gj_c1, _gj_c2, _gj_c3 = st.columns(3)
                _gj_schema = _gj_c1.selectbox(
                    "Schema",
                    ["all"] + _schemas,
                    format_func=lambda s: {
                        "all": "All schemas",
                        "dataview": "DataView",
                        "gom": "GOM",
                    }.get(s, s),
                    key="gj_schema",
                )
                _gj_area = _gj_c2.selectbox(
                    "Area",
                    ["— All —"] + _areas,
                    key="gj_area",
                )
                _gj_source = _gj_c3.selectbox(
                    "Source",
                    ["— All —"] + _sources,
                    key="gj_source",
                )

                _basemap_opts = {
                    "Dark": "mapbox://styles/mapbox/dark-v10",
                    "Light": "mapbox://styles/mapbox/light-v10",
                    "Streets": "mapbox://styles/mapbox/streets-v11",
                    "Satellite": "mapbox://styles/mapbox/satellite-v9",
                    "Satellite + Labels": "mapbox://styles/mapbox/satellite-streets-v11",
                    "Outdoors": "mapbox://styles/mapbox/outdoors-v11",
                }
                _gj_bm = _gj_c1.selectbox(
                    "Basemap",
                    list(_basemap_opts.keys()),
                    key="gj_basemap",
                )
                _pdk_style = _basemap_opts[_gj_bm]

                _filtered = _filter_geojson(
                    _full_gj,
                    schema=_gj_schema,
                    area="" if _gj_area == "— All —" else _gj_area,
                    source="" if _gj_source == "— All —" else _gj_source,
                )
                _feats = _filtered.get("features", [])
                _n = len(_feats)

                if _n:
                    _meta = _full_gj.get("metadata", {})
                    _gen = _meta.get("generated", "unknown")[:19]
                    _msg.info(
                        f"🗺️ {_n:,} wells"
                        f" (of {len(_all_features):,} total)"
                        f" · generated {_gen}"
                    )

                    # Build pydeck data from features
                    import pydeck as pdk

                    _dk_data = []
                    for _f in _feats:
                        _p = _f.get("properties", {})
                        _c = _f.get("geometry", {}).get("coordinates", [])
                        if len(_c) < 2:
                            continue
                        _dk_data.append({
                            "lon": _c[0],
                            "lat": _c[1],
                            "uwi": _p.get("uwi", ""),
                            "name": _p.get("name", ""),
                            "operator": _p.get("operator", ""),
                            "field": _p.get("field", ""),
                            "county": _p.get("county", ""),
                            "status": _p.get("status", ""),
                            "source": _p.get("source", ""),
                            "area": _p.get("area", ""),
                            "td": _p.get("td") or 0,
                        })

                    # Calculate view center from data
                    if _dk_data:
                        _avg_lat = sum(d["lat"] for d in _dk_data) / len(_dk_data)
                        _avg_lon = sum(d["lon"] for d in _dk_data) / len(_dk_data)
                    else:
                        _avg_lat, _avg_lon = 32.0, -100.0

                    _view = pdk.ViewState(
                        latitude=_avg_lat,
                        longitude=_avg_lon,
                        zoom=6,
                        pitch=0,
                    )

                    # ScatterplotLayer — each point is a GPU pixel
                    _layer = pdk.Layer(
                        "ScatterplotLayer",
                        data=_dk_data,
                        get_position=["lon", "lat"],
                        get_fill_color=[29, 158, 117, 220],  # #1D9E75
                        get_line_color=[10, 60, 45, 255],
                        get_radius=80,
                        radius_min_pixels=2,
                        radius_max_pixels=8,
                        pickable=True,
                        auto_highlight=True,
                        highlight_color=[255, 200, 0, 200],
                    )

                    # Tooltip on hover
                    _tooltip = {
                        "html": (
                            "<b>{uwi}</b><br>"
                            "{name}<br>"
                            "<i>{operator}</i><br>"
                            "{field} · {county}<br>"
                            "Status: {status} · Source: {source}"
                        ),
                        "style": {
                            "backgroundColor": "#1a1a2e",
                            "color": "white",
                            "fontSize": "12px",
                            "padding": "8px",
                            "borderRadius": "4px",
                        },
                    }

                    # Render the pydeck map — this replaces st_folium for
                    # this mode. The map renders via WebGL, not DOM elements.
                    _dk_event = st.pydeck_chart(
                        pdk.Deck(
                            layers=[_layer],
                            initial_view_state=_view,
                            map_style=_pdk_style,
                            tooltip=_tooltip,
                        ),
                        use_container_width=True,
                        height=550,
                        on_select="rerun",
                        selection_mode="single-object",
                        key="pydeck_wells",
                    )

                    # Handle click → scout ticket
                    if _dk_event and _dk_event.selection:
                        _sel_objs = _dk_event.selection.get("objects", {})
                        _sel_points = _sel_objs.get("ScatterplotLayer", [])

                        if _sel_points:
                            _clicked = _sel_points[0]
                            _clicked_uwi = _clicked.get("uwi", "")
                            if _clicked_uwi:
                                st.session_state.scout_uwi = _clicked_uwi
                                if _clicked_uwi not in st.session_state.get("clicked_uwis", []):
                                    if "clicked_uwis" not in st.session_state:
                                        st.session_state.clicked_uwis = []
                                    st.session_state.clicked_uwis.append(_clicked_uwi)

                    # Skip the Folium render below — pydeck is the map
                    _skip_folium = True

                else:
                    _msg.info("🗺️ No wells match the selected filters.")

            # Refresh button
            if st.button("🔄 Refresh GeoJSON", key="gj_refresh_btn",
                         help="Re-query the database and rebuild wells.geojson"):
                with st.spinner("Rebuilding wells.geojson…"):
                    try:
                        from build_well_geojson import build_geojson
                        import json as _json_mod
                        _gj_data = build_geojson(engine, schema="all")
                        from pathlib import Path as _P
                        _gj_path = _P(__file__).parent / "wells.geojson"
                        _gj_path.write_text(
                            _json_mod.dumps(_gj_data), encoding="utf-8")
                        st.session_state.pop("_well_geojson_data", None)
                        _n_ref = _gj_data["metadata"]["total_wells"]
                        st.success(
                            f"✅ Rebuilt wells.geojson — {_n_ref:,} wells")
                        st.rerun()
                    except Exception as _e:
                        st.error(f"Refresh failed: {_e}")

        elif not dff.empty:
            # Wells mode — needs the full wells dataframe (lazy-loaded
            # when user picked Wells mode or used a filter).
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
                    _vp_count = _add_viewport_wells(m, dff, _viewport_uwis)
                    if _vp_count:
                        _msg.info(f"📍 Viewport: {_vp_count:,} individual markers")
                except Exception as _e:
                    st.warning(f"Viewport render skipped: {_e}")
                    st.session_state["viewport_uwis"] = []
        else:
            # Wells mode but no wells loaded yet — this shouldn't happen
            # because lazy-load fires when mode == "wells", but be defensive.
            _msg.info("📍 Wells mode — no wells loaded yet")

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
        if "db_fields" in active_db:
            _add_fields(m, _qry_fields(engine))
        if "db_basins" in active_db:
            _add_basins(m, _qry_basins(engine))
        if "db_seismic_3d" in active_db:
            _msg.info("🟦 Loading 3D seismic surveys…")
            _add_seismic_3d(m, _qry_seismic_3d(engine))

        # GOM wells render gated on BOTH the Area selector AND grid_visible.
        # "gom" in sources comes from the AREAS registry. grid_visible
        # follows the Show grid toggle and is set False by Commit/Circle
        # drill so the user can see drilled wells without the heatmap.
        # Combining the grid (60-80+ cells) with drilled markers (potentially
        # hundreds) is heavy for st_folium's iframe serialization, so
        # honoring grid_visible here keeps the map light after a drill.
        _show_gom_grid = (
            "gom" in active_area.get("sources", [])
            and st.session_state.get("grid_visible", True)
        )
        if _show_gom_grid:
            _msg.info("🛢 Loading GOM wells grid…")
            try:
                _phase(15, "🛢 Querying Gulf of America wells — typically 15-20 seconds…")
                _gom_grid_df = _qry_gom_well_grid(engine)
                _phase(50, f"🛢 Aggregating {int(_gom_grid_df['well_count'].sum()):,} GOM wells into grid cells…")
                _sel_gom = st.session_state.get("selected_cells", [])
                _sel_gom_keys = {f"{c[0]:.4f}|{c[1]:.4f}" for c in _sel_gom}
                # Circle mode → inert cells so the draw gesture isn't stolen
                # by a cell click. Cells mode → interactive for selection.
                _gom_grid_interactive = (
                    st.session_state.get("gom_sel_mode", "Cells") == "Cells"
                )
                _add_gom_well_grid(
                    m, _gom_grid_df,
                    step=0.36,
                    selected_set=_sel_gom_keys,
                    interactive=_gom_grid_interactive,
                )
                # NOTE: do NOT _phase(100) here — bar persists to st_folium
            except Exception as _e:
                _phase(100)
                st.warning(f"GOM grid render skipped: {_e}")

        # Phase 4: render individual GOM well markers after a Commit drill.
        # The Commit handler stashes drilled wells in viewport_gom_wells;
        # _add_gom_wells_markers renders them as amber-ring teal-fill
        # CircleMarkers with popups built by _build_gom_popup_html.
        # Independent of the grid layer — drilled markers can show alongside
        # OR without the grid heatmap depending on Show grid toggle state.
        #
        # Status filter: the sidebar status checkboxes are schema-aware —
        # for GOM they list the real status_code values. Apply that
        # filter to the drilled wells here so unchecking a status (e.g.
        # "PA") drops those wells from the map. sel_statuses is the list
        # of currently-checked codes; an empty list means "show all"
        # (mirrors the dv_well path's _ss fallback so the map never goes
        # blank just because every box is unchecked-then-rechecked).
        _gom_drilled = st.session_state.get("viewport_gom_wells", [])
        if _gom_drilled and _area_is_gom and sel_statuses:
            _before = len(_gom_drilled)
            _gom_drilled = [
                w for w in _gom_drilled
                if str(w.get("status_code", "")).strip() in sel_statuses
            ]
            _filtered_out = _before - len(_gom_drilled)
        else:
            _filtered_out = 0
        if _gom_drilled:
            _phase(70, f"🛢 Rendering {len(_gom_drilled):,} drilled GOM wells…")
            if _filtered_out:
                _msg.info(
                    f"🛢 Rendering {len(_gom_drilled):,} drilled GOM wells "
                    f"({_filtered_out:,} hidden by status filter)…"
                )
            else:
                _msg.info(f"🛢 Rendering {len(_gom_drilled):,} drilled GOM wells…")
            _add_gom_wells_markers(m, _gom_drilled)
            # NOTE: do NOT _phase(100) here — bar persists to st_folium

            # GOM trajectories — draw wellbore survey paths for the same
            # drilled set when the overlay toggle is on. Uses the
            # status-filtered _gom_drilled list, so trajectories follow
            # the same status filter as the markers. Sidetracks have
            # their own well_id and render as their own polylines.
            if "db_gom_trajectories" in active_db:
                _msg.info("🌀 Drawing GOM wellbore trajectories…")
                _n_traj = _add_gom_trajectories(m, _gom_drilled, engine)
                if _n_traj:
                    _msg.info(f"🌀 Drew {_n_traj:,} GOM trajectories…")

        for lay in active_shp:
            _msg.info(f"🗂 Loading {lay.get('layer_name','layer')}…")
            _add_shapefile_layer(m, engine, lay)

        folium.LayerControl(collapsed=False).add_to(m)

        # Draw toolbar — circle only. The circle is a bulk cell-selector for
        # grid mode: drawing one selects every cell whose bbox intersects the
        # circle's bbox. Wells drill happens at Commit, same as click-select.
        from folium.plugins import Draw
        Draw(
            export=False,
            position="topleft",
            draw_options={
                "circle":       {
                    "shapeOptions": {"color": "#1d4ed8", "weight": 2},
                    "metric":       False,
                    "showRadius":   True,        # show radius while drawing
                    # repeatMode left False: with it True, the Leaflet.Draw
                    # event sequence (drawstart/drawstop) gets out of sync
                    # with the drag guard's DV_DRAW_ACTIVE flag, and the
                    # guard ends up eating the mouseup that finalizes the
                    # circle. False keeps circle completion reliable —
                    # click the toolbar icon once per circle. The mode
                    # radio still handles the cell-click vs circle gesture
                    # conflict, which was the part that actually mattered.
                    # "Sticky circle" can revisit later as its own task,
                    # with proper attention to the drag-guard interaction.
                    "repeatMode":   False,
                    # Lift Leaflet.Draw's hidden maxRadius cap. The default
                    # in some versions silently restricts circles to tens of
                    # km — we want to allow continent-scale circles, capped
                    # only by the 5,000-well Haversine return (which warns
                    # if exceeded). 5,000,000 m = 5,000 km, plenty of room.
                    "maxRadius":    5_000_000,
                    "minRadius":    100,         # 100 m minimum (sanity floor)
                    "feet":         False,       # use km, not feet
                },
                "rectangle":    False,
                "polygon":      False,
                "marker":       False,
                "circlemarker": False,
                "polyline":     False,
            },
            edit_options={"edit": False, "remove": True},
        ).add_to(m)

        # ── JS patch: distinguish pan-drag from click on cells ──────────
        # Problem: when the user click-and-drags inside a grid cell to pan
        # the map, Leaflet fires BOTH the pan-drag AND a click event on
        # the cell, which opens the cell's popup → streamlit-folium reports
        # the popup → Streamlit re-runs → cell gets toggled into selection.
        # That's unwanted: a drag is a pan, not a selection gesture.
        #
        # Fix: track the mouse position at mousedown. On mouseup, if the
        # cursor moved more than DRAG_THRESHOLD pixels, suppress the
        # subsequent click event by calling stopPropagation/preventDefault
        # before Leaflet's handler runs. Only "honest" clicks (no movement)
        # reach the cell's popup-open handler.
        #
        # Threshold of 5 pixels is the standard UI convention for distinguishing
        # click from drag — small enough that an unintended hand tremor doesn't
        # cancel a click, large enough that any deliberate pan registers.
        from branca.element import MacroElement
        from jinja2 import Template
        drag_guard = MacroElement()
        drag_guard._name = "dv_drag_click_guard"
        drag_guard._template = Template(u"""
            {% macro script(this, kwargs) %}
            (function() {
                function install() {
                    var maps = document.querySelectorAll('.leaflet-container');
                    if (!maps.length) {
                        setTimeout(install, 200);
                        return;
                    }
                    if (window.DV_DRAG_GUARD_INSTALLED) return;
                    window.DV_DRAG_GUARD_INSTALLED = true;

                    var DRAG_THRESHOLD = 5;   // pixels
                    var downX = null, downY = null, moved = false;

                    // Track whether a Leaflet.Draw tool is currently drawing.
                    // While drawing, the guard must NOT interfere — the draw
                    // tool's own mouseup→click pipeline needs to complete to
                    // finalize the shape. Hooking Leaflet's draw:drawstart /
                    // draw:drawstop events is the official way to know this.
                    window.DV_DRAW_ACTIVE = false;
                    function hookDrawEvents() {
                        // Look for any Leaflet map instance and subscribe to
                        // its draw events. We walk window for L objects and
                        // any _leaflet_id-bearing DOM elements.
                        if (typeof L === 'undefined') {
                            setTimeout(hookDrawEvents, 200);
                            return;
                        }
                        // Leaflet stashes the map instance on the container
                        // element under a non-standard property. Find it.
                        maps.forEach(function(el) {
                            // The map instance is associated via L._leaflet_id
                            // on the container's child elements. Walk
                            // window-level Leaflet map registry instead.
                            for (var k in window) {
                                try {
                                    var v = window[k];
                                    if (v && v._container === el &&
                                        typeof v.on === 'function') {
                                        v.on('draw:drawstart', function() {
                                            window.DV_DRAW_ACTIVE = true;
                                        });
                                        v.on('draw:drawstop', function() {
                                            // Small delay so the finalize
                                            // mouseup/click sequence completes
                                            // before we re-enable the guard.
                                            setTimeout(function() {
                                                window.DV_DRAW_ACTIVE = false;
                                            }, 150);
                                        });
                                    }
                                } catch (e) { /* skip */ }
                            }
                        });
                    }
                    hookDrawEvents();

                    maps.forEach(function(mapEl) {
                        // Capture phase so we see mousedown/up BEFORE Leaflet does.
                        mapEl.addEventListener('mousedown', function(ev) {
                            if (ev.button !== 0) return;   // left button only
                            if (window.DV_DRAW_ACTIVE) return;  // hands off draw tool
                            downX = ev.clientX;
                            downY = ev.clientY;
                            moved = false;
                        }, true);

                        mapEl.addEventListener('mousemove', function(ev) {
                            if (downX === null) return;
                            if (window.DV_DRAW_ACTIVE) return;
                            var dx = Math.abs(ev.clientX - downX);
                            var dy = Math.abs(ev.clientY - downY);
                            if (dx > DRAG_THRESHOLD || dy > DRAG_THRESHOLD) {
                                moved = true;
                            }
                        }, true);

                        mapEl.addEventListener('mouseup', function(ev) {
                            if (window.DV_DRAW_ACTIVE) {
                                // Don't interfere with circle/shape finalize
                                downX = null; downY = null;
                                return;
                            }
                            downX = null; downY = null;
                            if (moved) {
                                // Suppress the click event that Leaflet will
                                // fire next on this mouseup. One-shot capture
                                // listener with a 100ms safety timeout.
                                var killClick = function(ce) {
                                    ce.stopPropagation();
                                    ce.preventDefault();
                                    mapEl.removeEventListener('click', killClick, true);
                                };
                                mapEl.addEventListener('click', killClick, true);
                                setTimeout(function() {
                                    mapEl.removeEventListener('click', killClick, true);
                                }, 100);
                            }
                        }, true);
                    });
                }
                install();
            })();
            {% endmacro %}
        """)
        drag_guard._parent = m
        m.add_child(drag_guard)

        # ── JS: persist map view (center+zoom) across Streamlit reruns ──
        # Saves the user's pan/zoom to sessionStorage on every moveend, and
        # restores on init. This is independent of streamlit-folium's
        # returned_objects — we communicate state via the browser, not
        # via Python. Result: clicking a cell triggers a rerun (Streamlit
        # rebuilds the map), but the JS restore puts the map right back
        # where the user was looking.
        #
        # Storage key: 'dv_map_view' in sessionStorage (per-tab, survives
        # reruns within the same tab, cleared on tab close).
        #
        # Conflict resolution: Python's m.fit_bounds() call wins over the
        # restore for active drills (circle / cell Commit). We signal this
        # via the window.DV_SKIP_VIEW_RESTORE flag — set just before
        # rendering when _drawn_bounds is in play.
        # _has_active_fit signals to the view-persist JS that Python is
        # doing a fit_bounds on THIS render, so JS should skip its saved-
        # view restore. Includes BOTH persistent drilled bounds (still in
        # session) AND the one-shot bounds we just consumed for this
        # render. Without the OR, area changes would lose their fit to
        # the JS's stale saved view from the previous area.
        _has_active_fit = (
            bool(st.session_state.get("_drawn_bounds"))
            or _is_oneshot_fit_this_render
            or (_viewport_bounds is not None)
        )
        _reset_saved_view = bool(st.session_state.pop("_reset_saved_view", False))
        view_persist = MacroElement()
        view_persist._name = "dv_view_persist"
        view_persist._template = Template(u"""
            {% macro script(this, kwargs) %}
            (function() {
                var SKIP_FLAG  = """ + ("true" if _has_active_fit else "false") + u""";
                var RESET_FLAG = """ + ("true" if _reset_saved_view else "false") + u""";
                var STORAGE_KEY = 'dv_map_view';

                // If user just hit Clear, wipe the saved view BEFORE any
                // restore logic runs.
                if (RESET_FLAG) {
                    try { sessionStorage.removeItem(STORAGE_KEY); }
                    catch (e) { /* silent */ }
                }

                function install() {
                    if (typeof L === 'undefined') {
                        setTimeout(install, 100);
                        return;
                    }
                    // Find the map instance — Leaflet via folium attaches it
                    // as a window-level variable. Walk the window for any L.Map.
                    var mapInst = null;
                    for (var k in window) {
                        try {
                            var v = window[k];
                            if (v && typeof v === 'object'
                                && v instanceof L.Map
                                && !v.__dv_view_persist_bound) {
                                mapInst = v;
                                break;
                            }
                        } catch (e) { /* skip */ }
                    }
                    if (!mapInst) {
                        setTimeout(install, 100);
                        return;
                    }
                    mapInst.__dv_view_persist_bound = true;

                    // RESTORE: read saved view and apply, UNLESS Python is
                    // actively fitting to a drilled selection. In that case
                    // the saved view would override the fit_bounds and the
                    // map wouldn't zoom to the new selection.
                    if (!SKIP_FLAG) {
                        try {
                            var raw = sessionStorage.getItem(STORAGE_KEY);
                            if (raw) {
                                var v = JSON.parse(raw);
                                if (v && typeof v.lat === 'number'
                                    && typeof v.lng === 'number'
                                    && typeof v.zoom === 'number') {
                                    // Defer until after Leaflet's own init.
                                    setTimeout(function() {
                                        mapInst.setView(
                                            [v.lat, v.lng], v.zoom,
                                            { animate: false }
                                        );
                                    }, 0);
                                }
                            }
                        } catch (e) {
                            // Bad JSON or storage disabled — silent fallback
                        }
                    }

                    // SAVE: on moveend (pan release, zoom release, programmatic
                    // setView), record the new view. Throttle to 200ms so a
                    // rapid pan doesn't write 50 times.
                    var saveTimer = null;
                    function saveView() {
                        if (saveTimer) clearTimeout(saveTimer);
                        saveTimer = setTimeout(function() {
                            try {
                                var c = mapInst.getCenter();
                                var z = mapInst.getZoom();
                                sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
                                    lat:  c.lat,
                                    lng:  c.lng,
                                    zoom: z
                                }));
                            } catch (e) { /* silent */ }
                        }, 200);
                    }
                    mapInst.on('moveend', saveView);
                    mapInst.on('zoomend', saveView);

                    // If Python did a fit_bounds (drilled selection), save
                    // the resulting view too — so subsequent unrelated
                    // reruns keep the drilled view as the saved state.
                    if (SKIP_FLAG) {
                        setTimeout(saveView, 500);
                    }
                }
                install();
            })();
            {% endmacro %}
        """)
        view_persist._parent = m
        m.add_child(view_persist)


        # Crosshair cursor over map, pointer over markers
        folium.Element("""
            <style>
            .leaflet-container       { cursor: crosshair !important; }
            .leaflet-interactive     { cursor: pointer   !important; }
            </style>
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
        # We subscribe ONLY to events we actually consume — fewer events means
        # fewer Streamlit reruns, which means fewer pan/zoom grey-outs.
        #   last_object_clicked: lat/lon of the clicked object. Used for GRID
        #     CELL clicks — the handler floor-divides by step to identify
        #     which cell. Cells have NO popups so this is the only click
        #     signal for them.
        #   last_object_clicked_popup: popup HTML/text. Used for well marker
        #     clicks (popup contains UWI or well_id).
        #   all_drawings: used for circle draw → Haversine well drill.
        # We do NOT subscribe to last_clicked (fires on every mouse-down).
        # We also do NOT subscribe to center/zoom (unreliable + triggers reruns).
        _ret = [
            "last_object_clicked",
            "last_object_clicked_popup",
            "all_drawings",
        ]
        # The st_folium call below is the actual long pole — it serializes
        # the whole map to HTML/JS and the browser parses + renders it.
        # That's the part the user actually waits for (10-30 sec depending
        # on map complexity). Keep the top-of-page progress visible
        # THROUGH this call so the user knows it's still working.
        # Force widget re-render when selection changes.
        # Without this, streamlit-folium preserves the iframe across reruns
        # when only the map's content changes, and selected-cell highlights
        # (blue border) don't appear until something else forces a rebuild.
        # By appending a hash of selected_cells to the widget key, every
        # selection-state change creates a "new" widget instance that
        # streamlit-folium re-serializes from scratch — picking up the
        # updated cell borders. View-persist JS uses sessionStorage so
        # pan/zoom survives key changes.
        _sel_for_key = st.session_state.get("selected_cells", [])
        _sel_key_hash = hash(tuple(sorted(
            f"{c[0]:.4f}|{c[1]:.4f}" for c in _sel_for_key
        )))
        _map_widget_key = f"well_map_folium_{_sel_key_hash}"

        if _skip_folium:
            map_data = None
        else:
          _phase(90, "🌐 Rendering map in browser…")
          try:
            map_data = st_folium(
                m, height=500, use_container_width=True,
                returned_objects=_ret,
                key=_map_widget_key,
            )
          except TypeError:
            # Older streamlit-folium that doesn't support use_container_width
            map_data = st_folium(
                m, width=None, height=500,
                returned_objects=_ret,
                key=_map_widget_key,
            )
        _phase(100)
        _msg.empty()

        # Instructional hint for the spatial select tools
        st.caption(
            "💡 **Map:** Toggle **Show grid** to see/hide the density heatmap. "
            "**Click cells** to add them to a multi-select, then **Commit** to "
            "drill the combined area. **OR** draw a **circle** (left toolbar) "
            "to drill wells inside a radius directly — up to 5,000 wells. "
            "Click any well marker to add it to the tray. **Esc** cancels."
        )

        # ── Session state init ────────────────────────────────────────
        if "clicked_uwis" not in st.session_state:
            st.session_state.clicked_uwis = []
        if "scout_uwi" not in st.session_state:
            st.session_state.scout_uwi = None
        if "map_mode" not in st.session_state:
            # Default to fast aggregated overview. User can switch to wells
            # mode for the rectangle drill-down workflow.
            st.session_state.map_mode = "grid"
        if "grid_visible" not in st.session_state:
            # Show the density grid by default. User can toggle off to focus
            # on already-drilled wells without grid clutter.
            st.session_state.grid_visible = True
        if "selected_cells" not in st.session_state:
            # Multi-select buffer for grid cells. Each entry is a tuple of
            # (lat_bin, lon_bin, count). Cleared after Commit drills the
            # bbox of the union of selections, or after Clear.
            st.session_state.selected_cells = []

        # ── Spatial select — circle on map drills wells via Haversine ────
        # When the user draws a circle, we run a Haversine wells-in-radius
        # query against dv_well. The 5,000-well cap applies; over that we
        # warn and don't render. This REPLACES the current viewport (cells
        # and any previous circle drill).
        #
        # streamlit-folium / Leaflet.Draw serializes a drawn circle in one
        # of two ways depending on version:
        #   (a) GeoJSON Point with `properties.radius` (true circle)
        #   (b) GeoJSON Polygon (the circle approximated as a polygon)
        # We handle both — for (a) we use center+radius directly, for (b)
        # we derive an approximate center+radius from the polygon's bbox.
        _CIRCLE_CAP = 5000

        _raw_drawings = map_data.get("all_drawings") if map_data else None
        drawings = []
        if isinstance(_raw_drawings, list):
            drawings = _raw_drawings
        elif isinstance(_raw_drawings, dict):
            drawings = _raw_drawings.get("features", [])

        # Dedupe — don't reprocess the same drawing on every rerun
        if "processed_drawings" not in st.session_state:
            st.session_state.processed_drawings = set()

        if drawings:
            for drawing in drawings:
                geom   = drawing.get("geometry", {})
                gtype  = geom.get("type", "")
                coords = geom.get("coordinates", [])
                props  = drawing.get("properties", {}) or {}

                _geom_hash = hash(json.dumps(geom, sort_keys=True))
                if _geom_hash in st.session_state.processed_drawings:
                    continue

                try:
                    _center_lat = _center_lon = _radius_m = None

                    if gtype == "Point" and coords:
                        # True circle: GeoJSON Point with radius in metres
                        _center_lon, _center_lat = coords[0], coords[1]
                        _radius_m = float(props.get("radius", 0))

                    elif gtype == "Polygon" and coords:
                        # Approximated as polygon — derive center + radius
                        # from the polygon's bbox.
                        ring = coords[0]
                        _min_lat = min(c[1] for c in ring)
                        _max_lat = max(c[1] for c in ring)
                        _min_lon = min(c[0] for c in ring)
                        _max_lon = max(c[0] for c in ring)
                        _center_lat = (_min_lat + _max_lat) / 2.0
                        _center_lon = (_min_lon + _max_lon) / 2.0
                        # Radius = half the diagonal in metres (rough but
                        # captures the user's intended area)
                        import math as _m
                        _dlat_m = (_max_lat - _min_lat) * 111000.0 / 2.0
                        _dlon_m = (_max_lon - _min_lon) * 111000.0 * \
                                  _m.cos(_m.radians(_center_lat)) / 2.0
                        _radius_m = _m.sqrt(_dlat_m ** 2 + _dlon_m ** 2)

                    st.session_state.processed_drawings.add(_geom_hash)

                    if _center_lat is None or _radius_m is None or _radius_m <= 0:
                        continue

                    # Determine drill targets from active_area sources, same
                    # pattern as the cell-Commit dispatch. Each source has
                    # its own circle query that handles its schema's
                    # coordinate columns and indexes.
                    _active_sources = active_area.get("sources", [])
                    if not _active_sources:
                        st.warning(
                            "⭕ Pick an area first (Area dropdown above the "
                            "map) before drawing a circle. The circle drill "
                            "needs to know which dataset to query."
                        )
                        st.session_state.processed_drawings.discard(_geom_hash)
                        continue

                    # Drill each active source. Errors from one source don't
                    # block the other.
                    _circle_main: list = []
                    _circle_gom:  list = []
                    _total_main = 0
                    _total_gom  = 0

                    with st.spinner(
                        f"Querying wells within {_radius_m/1000:.1f} km…"
                    ):
                        if "main" in _active_sources:
                            try:
                                _circle_main, _total_main = _qry_wells_in_circle(
                                    engine,
                                    _center_lat, _center_lon, _radius_m,
                                    limit=_CIRCLE_CAP,
                                )
                            except Exception as _qe:
                                st.error(f"Main circle query failed: {_qe}")

                        if "gom" in _active_sources:
                            try:
                                _circle_gom, _total_gom = _qry_gom_wells_in_circle(
                                    engine,
                                    _center_lat, _center_lon, _radius_m,
                                    limit=_CIRCLE_CAP,
                                )
                            except Exception as _qe:
                                st.error(f"GOM circle query failed: {_qe}")

                    _circle_total_loaded = len(_circle_main) + len(_circle_gom)
                    _circle_total_found = _total_main + _total_gom

                    if _circle_total_found == 0:
                        st.info(
                            f"No wells found within {_radius_m/1000:.1f} km of "
                            f"({_center_lat:.4f}, {_center_lon:.4f})"
                        )
                    elif (_total_main > _CIRCLE_CAP) or (_total_gom > _CIRCLE_CAP):
                        st.warning(
                            f"⚠️ Over the {_CIRCLE_CAP:,} cap "
                            f"(main: {_total_main:,}, GOM: {_total_gom:,}) — "
                            f"draw a smaller circle to inspect this area."
                        )
                        # Don't replace viewport — keep what was there
                    else:
                        # REPLACE both viewports — circle is a fresh look,
                        # not additive. Same pattern as cell Commit.
                        if _circle_main:
                            st.session_state.viewport_uwis = [
                                w["uwi"] for w in _circle_main
                            ]
                            # Cache full data for tray/scout lookups
                            _shadow = st.session_state.get("tray_well_data", {})
                            for w in _circle_main:
                                _shadow[w["uwi"]] = w
                            st.session_state["tray_well_data"] = _shadow
                        else:
                            st.session_state.viewport_uwis = []

                        if _circle_gom:
                            st.session_state["viewport_gom_wells"] = _circle_gom
                        else:
                            st.session_state["viewport_gom_wells"] = []

                        # Map zooms to center of circle at a zoom level
                        # appropriate to see the whole radius. We do that by
                        # setting _drawn_bounds to the circle's bbox — the
                        # map fits to those bounds on next render.
                        import math as _m
                        _dlat = _radius_m / 111000.0
                        _dlon = _radius_m / (
                            111000.0 * max(_m.cos(_m.radians(_center_lat)), 0.01)
                        )
                        st.session_state["_drawn_bounds"] = [
                            [_center_lat - _dlat, _center_lon - _dlon],
                            [_center_lat + _dlat, _center_lon + _dlon],
                        ]

                        # Clear any cell-selection — circle replaces that
                        # workflow's output too
                        st.session_state["selected_cells"] = []

                        # Hide the grid — same as cell Commit. User sees the
                        # drilled wells without heatmap clutter. Toggle 'Show
                        # grid' to bring it back for another selection.
                        # Pop the widget key (not write) to avoid Streamlit's
                        # "can't modify widget state after instantiation" error.
                        st.session_state["grid_visible"] = False
                        st.session_state.pop("grid_visible_toggle", None)

                        # Build status message reflecting which sources fired
                        _parts = []
                        if _circle_main:
                            _parts.append(f"{len(_circle_main):,} main")
                        if _circle_gom:
                            _parts.append(f"{len(_circle_gom):,} GOM")
                        st.success(
                            f"⭕ Loaded **{' + '.join(_parts)}** wells "
                            f"within {_radius_m/1000:.1f} km. "
                            f"Grid hidden — toggle 'Show grid' to draw "
                            f"another circle."
                        )
                        st.rerun()

                except Exception as _e:
                    st.warning(f"Circle drill failed: {_e}")

        # ── Parse click — grid cell (coords) OR well UWI (popup) ────────
        # Two distinct click sources:
        #   1. last_object_clicked   → lat/lon of clicked element. Used for
        #      grid cells (which have no popup). The handler floor-divides
        #      the click coords by the active area's step to find the
        #      cell, then toggles it in selected_cells.
        #   2. last_object_clicked_popup → popup text. Used for well marker
        #      clicks (popups contain UWI/well_id for tray pickup).

        # Determine the step for the active area's grid (for cell hit-test)
        _active_sources = active_area.get("sources", [])
        # If active area has both main and gom, we need to know which grid
        # the click landed in. Step values differ — main is 0.035°, gom
        # is 0.36°. A click could be in either. We test against both and
        # take the one whose floor-cell exists in the rendered grid data.
        # For now: if only one source is active, use that step. If both
        # are active, we'll test the click against both grids by hit-test.
        _cell_steps = []
        if "main" in _active_sources:
            _cell_steps.append(("main", 0.035))
        if "gom" in _active_sources:
            _cell_steps.append(("gom", 0.36))

        _coord_click = map_data.get("last_object_clicked") if map_data else None
        # If the same click also returned popup content, it was a well marker
        # click (markers have popups, cells don't). Skip the cell-click path
        # in that case — otherwise floor-dividing the marker's coords would
        # toggle a grid cell underneath, polluting the selection buffer.
        _click_popup = map_data.get("last_object_clicked_popup") if map_data else None
        _handled_as_cell = False

        # Selection mode gate: cell-click toggling only happens in "Cells"
        # mode. In "Circle" mode the cell-click handler is skipped entirely
        # so a press-drag-release that starts on a grid cell isn't stolen
        # by the cell toggler — the circle gesture stays unambiguous.
        _cells_mode = st.session_state.get("gom_sel_mode", "Cells") == "Cells"

        if (_cells_mode and _coord_click and _cell_steps
                and st.session_state.get("grid_visible", True)
                and not _click_popup):
            try:
                _click_lat = float(_coord_click.get("lat"))
                _click_lon = float(_coord_click.get("lng"))
            except (TypeError, ValueError, AttributeError):
                _click_lat = _click_lon = None

            if _click_lat is not None and _click_lon is not None:
                # For each active grid source, compute the cell that contains
                # this click. The "cell" is identified by its SW corner from
                # floor-division. Same algorithm the grid query uses to bin.
                # If multiple sources are active (All regions), we use the
                # FINER grid since its cells are smaller — that maps cleanly
                # to a single physical clicked rectangle.
                _best_step = min(s[1] for s in _cell_steps)
                _gc_lat = (_click_lat // _best_step) * _best_step
                _gc_lon = (_click_lon // _best_step) * _best_step
                _gc_sig = f"{_gc_lat:.4f}|{_gc_lon:.4f}"

                # Dedupe: streamlit-folium keeps returning the same click
                # coordinates across reruns until something else is clicked.
                # Without this guard we'd toggle on every rerun.
                if st.session_state.get("_last_grid_click") != _gc_sig:
                    st.session_state["_last_grid_click"] = _gc_sig

                    # Toggle this cell in/out of the selection buffer.
                    # We use a placeholder well count of 0 — the actual
                    # count isn't needed here; Commit reads the cell bbox
                    # from the (lat, lon) and queries fresh.
                    _sel = list(st.session_state.get("selected_cells", []))
                    _existing_idx = next(
                        (i for i, c in enumerate(_sel)
                         if f"{c[0]:.4f}|{c[1]:.4f}" == _gc_sig),
                        None,
                    )
                    if _existing_idx is not None:
                        _sel.pop(_existing_idx)
                    else:
                        _sel.append((_gc_lat, _gc_lon, 0))
                    st.session_state["selected_cells"] = _sel
                    _handled_as_cell = True
                    st.rerun()

        # If the click wasn't a cell click, fall through to popup-based
        # well marker handling.
        clicked = map_data.get("last_object_clicked_popup") if map_data else None
        if clicked and not _handled_as_cell:
            _clicked_str = str(clicked)

            # GOM wells: this version of streamlit-folium strips HTML
            # attributes from the popup and returns only visible text, so
            # data-well-id never survives the round trip. The GOM popup
            # text does include a line "API <number>", and the BOEM API
            # number is unique per well — so we parse that out and look
            # the well up in viewport_gom_wells by api_well_number. From
            # the matched dict we get the real well_id (UUID) and every
            # field, then shadow-cache it in tray_well_data keyed by
            # well_id so uwi_index and the scout panel can find it.
            _uwi = None
            _gom_api_match = (
                re.search(r'\bAPI\s+(\d{8,16})\b', _clicked_str)
                if "gom" in active_area.get("sources", [])
                else None
            )
            if _gom_api_match:
                _gom_api = _gom_api_match.group(1).strip()
                _gom_pool = st.session_state.get("viewport_gom_wells", [])
                _gom_hit = next(
                    (w for w in _gom_pool
                     if str(w.get("api_well_number", "")).strip() == _gom_api),
                    None,
                )
                if _gom_hit is not None:
                    _uwi = str(_gom_hit.get("well_id", "")).strip()
                    if _uwi:
                        _shadow = st.session_state.get("tray_well_data", {})
                        # Key by well_id (the UUID); preserve every GOM
                        # field for the scout builder; tag the source so
                        # the scout panel dispatches to the GOM builder.
                        _shadow[_uwi] = {**_gom_hit, "uwi": _uwi,
                                         "_source": "gom"}
                        st.session_state["tray_well_data"] = _shadow

            # dv_well wells: data-uwi attribute, then digit-pattern
            # fallbacks. Only run if the GOM branch didn't already
            # resolve a well_id.
            if _uwi is None:
                # Primary: data-uwi attribute (works on older streamlit-folium
                # that returns full popup HTML)
                m2 = re.search(r'data-uwi="([^"]+)"', _clicked_str)
                if m2:
                    _uwi = m2.group(1).strip()
                else:
                    # Fallbacks: try several patterns for different popup
                    # formats (older HTML-preserving vs newer text-only
                    # streamlit-folium)
                    for pat in [
                        # HTML-preserving: monospace span around UWI
                        r"font-family:monospace[^>]*>([^<]+)<",
                        # 14-digit UWI surrounded by whitespace (KS, TX RRC).
                        # The popup title and UWI may be on the same line in
                        # streamlit-folium's plain-text return, so we can't
                        # require start/end of line.
                        r"(?<!\d)(\d{14})(?!\d)",
                        # 12-16 digit UWI, more permissive — only used if 14
                        # didn't match (rare format variations).
                        r"(?<!\d)(\d{12,16})(?!\d)",
                        # Dashed UWI format (e.g., "15-009-00865-0000")
                        r"(\d{2}-\d{3}-\d{5}-\d{2,4}(?:-\d{2})?)",
                        # PPDM US-prefix format
                        r"(US[0-9]{14})",
                    ]:
                        m2 = re.search(pat, _clicked_str)
                        if m2:
                            _uwi = m2.group(1).strip()
                            break

            if _uwi:
                # Click adds to tray only. Scout ticket is NOT auto-shown —
                # the user opens it explicitly from the tray UI when they
                # want it. This avoids spamming the user with a full ticket
                # render every time they tap a well to bookmark it.
                if _uwi not in st.session_state.clicked_uwis:
                    st.session_state.clicked_uwis.append(_uwi)

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
                    if not well_row:
                        continue
                    # Dispatch by identifier shape: GOM wells are keyed by
                    # a UUID well_id (36 chars, dashed); dv_well wells use
                    # PPDM-style UWIs. A dict tagged _source="gom" (set by
                    # the GOM popup-click handler) is the explicit signal;
                    # the UUID-shape check is the fallback.
                    _is_gom = (
                        well_row.get("_source") == "gom"
                        or (isinstance(uwi, str)
                            and len(uwi) == 36
                            and uwi.count("-") == 4)
                    )
                    if _is_gom:
                        _html += _build_gom_scout_ticket_html(uwi, well_row, engine)
                    else:
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
                    # Tray label is schema-aware. GOM well dicts use
                    # well_name + well_name_suffix and company_name;
                    # dv_well uses well_name and operator_name. Read
                    # whichever the dict actually has so GOM tray rows
                    # show the full name and operator, not a bare stub.
                    _wn_base = well.get("well_name") or cu
                    _wn_sfx  = well.get("well_name_suffix") or ""
                    wn = (f"{_wn_base} {_wn_sfx}".strip()
                          if _wn_sfx else _wn_base)
                    op = (well.get("operator_name")
                          or well.get("company_name") or "")
                    _label = f"🛢 **{wn}** — {op}" if op else f"🛢 **{wn}**"
                    checked = st.checkbox(
                        _label,
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
                        # Clear grid-click dedupe so the same cell can be
                        # re-clicked, and the drawn bounds so the map
                        # repositions correctly next time
                        st.session_state.pop("_last_grid_click", None)
                        st.session_state.pop("_drawn_bounds", None)
                        # Also clear the multi-cell selection buffer, and
                        # bring the grid back so the user can pick again.
                        # POP the widget key (assigning it after the widget
                        # instantiated is forbidden — see Commit handler).
                        st.session_state["selected_cells"] = []
                        st.session_state["grid_visible"] = True
                        st.session_state.pop("grid_visible_toggle", None)
                        st.rerun()





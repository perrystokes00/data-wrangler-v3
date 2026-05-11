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

def _add_well_grid(m, df: pd.DataFrame, step: float = 0.035) -> int:
    """
    Renders the grid-density overview layer.

    Each non-empty cell becomes a square polygon, fill-colored by log-scaled
    well count (light yellow → dark red). Tooltip shows the count.

    This is the low-load alternative to FastMarkerCluster. Use when the user
    wants a fast overview of where the wells are, without paying the cost of
    serializing 50K individual markers.

    Args:
        m: folium.Map
        df: result of _qry_well_grid — columns lat_bin, lon_bin, well_count,
            center_lat, center_lon
        step: cell size in degrees (must match what was used to bin)

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

        # Render as a Rectangle with a count tooltip and a clickable popup
        # that the click handler recognizes. The "GRID_CELL|lat|lon|step|count"
        # marker is the contract — the click handler in run() regex-matches
        # this and fires a bbox query for that cell.
        # We embed the marker via a hidden span (not data attribute) because
        # modern streamlit-folium strips HTML attributes from popup data.
        # The visible markup is human-friendly; the marker is plain text.
        _cell_marker = (
            f"GRID_CELL|{lat_bin:.4f}|{lon_bin:.4f}|{step:.4f}|{count}"
        )
        folium.Rectangle(
            bounds=bounds,
            color="#7f1d1d",      # dark red border
            weight=0.5,
            fill=True,
            fill_color=color,
            fill_opacity=0.55,
            tooltip=folium.Tooltip(
                f"<b>{count:,}</b> wells — click to drill in",
                sticky=True,
            ),
            popup=folium.Popup(
                (
                    f"<div style='font-size:11px;line-height:1.4'>"
                    f"<b style='font-size:12px'>{count:,} wells</b><br>"
                    f"<span style='color:#475569'>"
                    f"Area: {lat_bin:.2f}–{lat_bin + step:.2f}°N, "
                    f"{lon_bin:.2f}–{lon_bin + step:.2f}°W</span><br>"
                    f"<span style='color:#1a73e8;font-size:10px;font-weight:600'>"
                    f"📍 Loading individual wells…</span><br>"
                    # The marker — kept visible (small/grey) so streamlit-folium
                    # preserves it in the click return. Don't remove this line.
                    f"<span style='font-size:8px;color:#cbd5e1;"
                    f"font-family:monospace'>{_cell_marker}</span>"
                    f"</div>"
                ),
                max_width=260,
            ),
        ).add_to(grid_group)

    grid_group.add_to(m)
    return len(df)


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

def run(engine=None):
    if not HAS_FOLIUM:
        st.error("pip install folium streamlit-folium")
        return
    if engine is None:
        st.info("Connect to the DataView database first.")
        return

    _status = st.empty()

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
        _status.info("⏳ Querying wells from DataView…")
        _wells_raw = _qry_wells(engine)
        st.session_state["_wells_already_loaded"] = True
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
    uwi_index = {w["uwi"]: w for w in _wells_raw}  # full index for scout tickets

    # ── Top bar above map: Background | Zoom | Query ────────────────
    top1, top2, top3 = st.columns([1, 1, 2])
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
        # If user picks a query type that needs wells data, trigger a load
        # on the next rerun (no-op if already loaded).
        if qtype in ("operator", "field", "county", "well_type",
                     "has_tops", "has_prod", "has_dst",
                     "has_survey", "has_core", "has_petro"):
            if not st.session_state.get("_wells_already_loaded", False):
                st.session_state["_wells_already_loaded"] = True
                st.rerun()
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

        # Status — when wells haven't been loaded yet, use the standard
        # PPDM 3.9 status set. This lets the user toggle status filters
        # without paying the cost of loading all 50K wells upfront.
        if not wells_df.empty:
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
            mask = wells_df["well_status"].isin(_ss)
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

        # Caption — show different info depending on whether wells are loaded
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
                options=["grid", "wells"],
                index=0 if _current_mode == "grid" else 1,
                format_func=lambda m: (
                    "🔵 Grid (overview)" if m == "grid"
                    else "📍 Wells (detail)"
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
                    "🔵 **Grid mode** — fast aggregated overview. "
                    "Switch to 📍 Wells to draw a rectangle and inspect individual wells."
                )
            else:
                st.caption(
                    "📍 **Wells mode** — cluster bubbles + rectangle viewport. "
                    "Switch to 🔵 Grid for a fast aggregated view of all wells."
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
            # Mode dispatch — set by the radio toggle above the map.
            # "grid" = fast aggregated overview (server-side binning)
            # "wells" = full clusters + viewport markers (current default behavior)
            _map_mode = st.session_state.get("map_mode", "wells")

            if _map_mode == "grid":
                _msg.info(f"🔵 Loading grid overview…")
                try:
                    _grid_df = _qry_well_grid(engine, step=0.035)
                    _cell_count = _add_well_grid(m, _grid_df, step=0.035)
                    if _cell_count:
                        _msg.info(
                            f"🔵 Grid: {_cell_count:,} cells · "
                            f"{int(_grid_df['well_count'].sum()):,} wells aggregated"
                        )
                    else:
                        _msg.info("🔵 No wells to aggregate")
                except Exception as _e:
                    st.warning(f"Grid render skipped: {_e}")
                    # If grid fails for any reason, fall back to wells mode
                    # so the user still sees something.
                    st.session_state["map_mode"] = "wells"

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
            else:
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
        # We subscribe to a few different click signals so we catch whichever
        # streamlit-folium populates for Rectangle (grid cell) clicks vs
        # CircleMarker (well) clicks vs map background clicks.
        _ret = [
            "last_object_clicked_popup",
            "last_object_clicked",
            "last_clicked",
            "all_drawings",
        ]
        try:
            map_data = st_folium(
                m, height=500, use_container_width=True,
                returned_objects=_ret,
                key="well_map_folium",
            )
        except TypeError:
            # Older streamlit-folium that doesn't support use_container_width
            map_data = st_folium(
                m, width=None, height=500,
                returned_objects=_ret,
                key="well_map_folium",
            )
        _msg.empty()

        # Instructional hint for the spatial select tools
        st.caption(
            "💡 **Map:** **🔵 Grid mode** shows density (each colored cell = "
            "wells in that area). **Click a cell** to drill into its wells "
            "(up to 1,000). **Draw a rectangle** to drill into a custom area "
            "(up to 2,000 wells). Click any individual well marker to add "
            "to the tray. Open the tray to view scout tickets and export. "
            "**Esc** cancels rectangle drawing."
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

                        # Mark this drawing processed regardless of outcome
                        st.session_state.processed_drawings.add(_geom_hash)

                        # PHASE 1: Server-side bbox query.
                        # Replaces the old in-memory filter, which doesn't
                        # scale past ~50K wells (full set has to be in
                        # browser/Python). Bbox query with the spatial
                        # index returns wells inside in sub-second time
                        # even at 4M scale.
                        #
                        # Returns (wells_list, total_count). If total_count
                        # exceeds the cap, we don't render — we ask the user
                        # to draw a smaller box. Capped to keep browser sane.
                        # Rectangle cap: 2000 wells. Above this, browser
                        # starts to feel sluggish on each rerun. Single
                        # grid-cell drill stays at 1000 — rectangles can be
                        # bigger since the user is actively choosing the
                        # area.
                        BBOX_LIMIT = 2000
                        with st.spinner("Querying wells in selected area…"):
                            try:
                                _bbox_wells, _bbox_total = _qry_wells_in_bbox(
                                    engine,
                                    min_lat, max_lat,
                                    min_lon, max_lon,
                                    limit=BBOX_LIMIT,
                                )
                            except Exception as _qe:
                                st.error(f"Bbox query failed: {_qe}")
                                _bbox_wells, _bbox_total = [], 0

                        if _bbox_total == 0:
                            st.info("No wells found in drawn area")
                        elif _bbox_total > BBOX_LIMIT:
                            # Too many wells — render nothing, ask the user
                            # to refine. Keeps the browser from drowning in
                            # markers.
                            st.warning(
                                f"⚠️ **{_bbox_total:,} wells** in selected area — "
                                f"too many to render individually "
                                f"(cap: {BBOX_LIMIT:,}). "
                                f"**Draw a smaller box** or zoom in further."
                            )
                            # Don't clear viewport_uwis — the previous
                            # selection (if any) stays useful
                        else:
                            # Renderable count — extract UWIs and stash the
                            # well data. The viewport markers render in BOTH
                            # grid and wells modes now, so we don't force a
                            # mode switch. User stays in whatever mode they
                            # were in (typically grid).
                            selected = [w["uwi"] for w in _bbox_wells]
                            st.session_state.viewport_uwis = selected

                            # Tray-shadow cache: stash full data for every
                            # well loaded into a viewport, so scout tickets
                            # work for tray entries even after the user pans
                            # away and the bbox cache expires.
                            shadow = st.session_state.get("tray_well_data", {})
                            for w in _bbox_wells:
                                shadow[w["uwi"]] = w
                            st.session_state["tray_well_data"] = shadow

                            st.success(
                                f"📐 Viewport: **{len(selected):,}** wells loaded "
                                f"as individual markers. Click wells to add to tray."
                            )
                            st.rerun()
                except Exception as _e:
                    st.warning(f"Spatial select failed: {_e}")

        # ── Parse clicked popup — grid cell OR well UWI ─────────────────
        clicked = map_data.get("last_object_clicked_popup") if map_data else None
        if clicked:
            _clicked_str = str(clicked)

            # First check: is this a GRID_CELL click? Drill into that cell.
            # Format: GRID_CELL|min_lat|min_lon|step|count
            _grid_match = re.search(
                r"GRID_CELL\|(-?\d+\.\d+)\|(-?\d+\.\d+)\|(\d+\.\d+)\|(\d+)",
                _clicked_str,
            )
            if _grid_match:
                _gc_lat = float(_grid_match.group(1))
                _gc_lon = float(_grid_match.group(2))
                _gc_step = float(_grid_match.group(3))
                _gc_count = int(_grid_match.group(4))

                # Dedupe: streamlit-folium keeps returning the same click
                # data across reruns until something else is clicked. Without
                # this check we'd re-fire the bbox query every rerun.
                _gc_sig = f"{_gc_lat:.4f}|{_gc_lon:.4f}"
                if st.session_state.get("_last_grid_click") != _gc_sig:
                    st.session_state["_last_grid_click"] = _gc_sig

                    if _gc_count > 1000:
                        st.warning(
                            f"⚠️ Cell has **{_gc_count:,} wells** — too many to "
                            f"render individually (cap: 1000). Use the rectangle "
                            f"tool to draw a smaller box inside the cell."
                        )
                    else:
                        with st.spinner(f"Loading {_gc_count:,} wells from cell…"):
                            try:
                                _cell_wells, _cell_total = _qry_wells_in_bbox(
                                    engine,
                                    _gc_lat, _gc_lat + _gc_step,
                                    _gc_lon, _gc_lon + _gc_step,
                                    limit=2000,
                                )
                            except Exception as _qe:
                                st.error(f"Cell query failed: {_qe}")
                                _cell_wells, _cell_total = [], 0

                        if _cell_wells:
                            st.session_state.viewport_uwis = [
                                w["uwi"] for w in _cell_wells
                            ]
                            # Cache full well data for scout-ticket lookups
                            shadow = st.session_state.get("tray_well_data", {})
                            for w in _cell_wells:
                                shadow[w["uwi"]] = w
                            st.session_state["tray_well_data"] = shadow
                            # Set drawn bounds so the map zooms to the cell
                            st.session_state["_drawn_bounds"] = [
                                [_gc_lat, _gc_lon],
                                [_gc_lat + _gc_step, _gc_lon + _gc_step],
                            ]
                            # STAY in grid mode — drilled wells render as
                            # yellow markers on top of the grid layer.
                            # User keeps the density overview everywhere else.
                            st.success(
                                f"📐 Loaded {len(_cell_wells):,} wells from "
                                f"selected cell."
                            )
                            st.rerun()
                        else:
                            st.info("No wells found in cell")

            # Otherwise: well UWI extraction (existing behavior)
            else:
                _uwi = None
                # Primary: data-uwi attribute (works on older streamlit-folium
                # that returns full popup HTML)
                m2 = re.search(r'data-uwi="([^"]+)"', _clicked_str)
                if m2:
                    _uwi = m2.group(1).strip()
                else:
                    # Fallbacks: try several patterns for different popup formats
                    # (older HTML-preserving vs newer text-only streamlit-folium)
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
                        # Clear grid-click dedupe so the same cell can be
                        # re-clicked, and the drawn bounds so the map
                        # repositions correctly next time
                        st.session_state.pop("_last_grid_click", None)
                        st.session_state.pop("_drawn_bounds", None)
                        st.rerun()





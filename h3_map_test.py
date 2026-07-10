"""
h3_map_test.py — Standalone proof-of-concept for H3 hex density map.

Reads dataview_federation.v_well_density_r{4,5,6,7} and renders each
H3 cell as a Folium polygon, colored by well_count. Zoom-adaptive:
choose resolution based on a slider in the sidebar.

Not integrated with page_well_map.py — this is a scratch page to
prove the data → render pipeline works. If it shows hexes correctly,
the same pattern lifts into page_well_map.py tomorrow.

Run:
    streamlit run h3_map_test.py

Requirements:
    pip install h3 folium streamlit-folium sqlalchemy pyodbc pandas
"""

from __future__ import annotations

import json
import time

import folium
import h3
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from streamlit_folium import st_folium


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
CONN_STR = (
    "mssql+pyodbc://@localhost\\SQLEXPRESS/DataView"
    "?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
)

st.set_page_config(page_title="H3 Hex Test", layout="wide")
st.title("🔶 H3 Density Map — Proof of Concept")
st.caption(
    "Renders dataview_federation.v_well_density_r{N} as Folium hex polygons. "
    "If you see hexes, the H3 pipeline works end-to-end."
)


# -----------------------------------------------------------------------------
# Cached engine and density loader
# -----------------------------------------------------------------------------
@st.cache_resource
def get_engine():
    return create_engine(CONN_STR)


@st.cache_data(ttl=600, show_spinner="Loading H3 density…")
def load_density(resolution: int, schema_filter: str | None) -> pd.DataFrame:
    """
    Fetch (h3, well_count, dv_schema) from the density view at this resolution.

    schema_filter:
        None           — all schemas
        "dataview"     — onshore
        "dataview_gom" — offshore
    """
    view = f"dataview_federation.v_well_density_r{resolution}"
    if schema_filter is None:
        sql = f"""
            SELECT h3, SUM(well_count) AS well_count
            FROM {view}
            GROUP BY h3
        """
        params = {}
    else:
        sql = f"""
            SELECT h3, well_count
            FROM {view}
            WHERE dv_schema = :schema
        """
        params = {"schema": schema_filter}

    t0 = time.time()
    df = pd.read_sql(text(sql), get_engine(), params=params)
    elapsed = time.time() - t0
    st.session_state["_last_query_ms"] = int(elapsed * 1000)
    return df


# -----------------------------------------------------------------------------
# Sidebar controls
# -----------------------------------------------------------------------------
st.sidebar.header("Controls")

resolution = st.sidebar.select_slider(
    "H3 Resolution",
    options=[4, 5, 6, 7],
    value=5,
    help=(
        "R4: ~390 hexes (continent)\n"
        "R5: ~1,847 hexes (state)\n"
        "R6: ~8,853 hexes (county)\n"
        "R7: ~37,232 hexes (play)"
    ),
)

schema_choice = st.sidebar.radio(
    "Schema",
    options=["All schemas", "dataview (onshore)", "dataview_gom (offshore)"],
    index=0,
)
schema_filter = {
    "All schemas":            None,
    "dataview (onshore)":     "dataview",
    "dataview_gom (offshore)": "dataview_gom",
}[schema_choice]

show_labels = st.sidebar.checkbox("Show well count labels", value=False,
                                  help="Adds text labels on each hex (busy at R6/R7).")


# -----------------------------------------------------------------------------
# Data load
# -----------------------------------------------------------------------------
df = load_density(resolution, schema_filter)

if df.empty:
    st.error("No data returned. Check that the density views are populated.")
    st.stop()

# -----------------------------------------------------------------------------
# Color ramp — log-scale because well counts span orders of magnitude
# -----------------------------------------------------------------------------
import math


def color_for(count: int, max_count: int) -> str:
    """
    Map well_count to a viridis-like color. Log-scale because density
    is heavy-tailed (a few hexes have tens of thousands of wells, most
    have a handful).
    """
    if max_count <= 1:
        return "#440154"
    # Log-scale normalize to [0,1]
    t = math.log10(max(count, 1)) / math.log10(max(max_count, 10))
    t = min(max(t, 0.0), 1.0)
    # 5-stop viridis-ish ramp
    stops = [
        (0.00, (68,  1,   84)),   # dark purple
        (0.25, (59,  82,  139)),  # blue
        (0.50, (33,  144, 141)),  # teal
        (0.75, (94,  201, 98)),   # green
        (1.00, (253, 231, 37)),   # yellow
    ]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t <= t1:
            frac = (t - t0) / (t1 - t0) if t1 > t0 else 0
            r = int(c0[0] + (c1[0] - c0[0]) * frac)
            g = int(c0[1] + (c1[1] - c0[1]) * frac)
            b = int(c0[2] + (c1[2] - c0[2]) * frac)
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#fde725"


max_count = int(df["well_count"].max())
total_cells = len(df)
total_wells = int(df["well_count"].sum())
elapsed_ms = st.session_state.get("_last_query_ms", 0)

# -----------------------------------------------------------------------------
# Stats line
# -----------------------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Cells", f"{total_cells:,}")
col2.metric("Total wells", f"{total_wells:,}")
col3.metric("Densest cell", f"{max_count:,} wells")
col4.metric("Query time", f"{elapsed_ms} ms")


# -----------------------------------------------------------------------------
# Build Folium map
# -----------------------------------------------------------------------------
# Default view: rough US center (covers dataview + GOM in one frame)
m = folium.Map(
    location=[35.0, -95.0],
    zoom_start=4,
    tiles="OpenStreetMap",
    prefer_canvas=True,
)

# Build a single GeoJSON FeatureCollection — faster than adding 8K
# individual polygons because Folium serializes everything once and
# Leaflet renders via vector layer batching.
features = []
for _, row in df.iterrows():
    h3_id = row["h3"]
    count = int(row["well_count"])
    try:
        # h3 v4.x returns (lat, lon) tuples
        boundary = h3.cell_to_boundary(h3_id)
    except Exception:
        continue

    # GeoJSON wants [lon, lat] (X, Y) order, opposite of h3's (lat, lon)
    coords = [[lon, lat] for lat, lon in boundary]
    # Close the polygon ring
    if coords and coords[0] != coords[-1]:
        coords.append(coords[0])

    features.append({
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [coords]},
        "properties": {
            "h3": h3_id,
            "count": count,
            "color": color_for(count, max_count),
        },
    })

geojson_data = {"type": "FeatureCollection", "features": features}


def _style_fn(feature):
    return {
        "fillColor": feature["properties"]["color"],
        "color": "#222",
        "weight": 0.4,
        "fillOpacity": 0.65,
    }


def _highlight_fn(_):
    return {"weight": 2, "color": "#fff", "fillOpacity": 0.85}


folium.GeoJson(
    geojson_data,
    name=f"H3 R{resolution}",
    style_function=_style_fn,
    highlight_function=_highlight_fn,
    tooltip=folium.GeoJsonTooltip(
        fields=["h3", "count"],
        aliases=["H3 cell:", "Wells:"],
        sticky=True,
        labels=True,
    ),
).add_to(m)

# Optional labels — use a MarkerCluster-free direct DivIcon to keep it cheap
if show_labels:
    for f in features:
        # Recompute centroid from the polygon ring for label placement
        coords = f["geometry"]["coordinates"][0]
        clat = sum(c[1] for c in coords[:-1]) / (len(coords) - 1)
        clon = sum(c[0] for c in coords[:-1]) / (len(coords) - 1)
        folium.map.Marker(
            [clat, clon],
            icon=folium.DivIcon(
                icon_size=(40, 16),
                icon_anchor=(20, 8),
                html=(
                    '<div style="font-size:10px;font-weight:600;'
                    'text-align:center;color:#fff;'
                    'text-shadow:0 0 2px #000,0 0 4px #000;">'
                    f'{f["properties"]["count"]:,}</div>'
                ),
            ),
        ).add_to(m)


# -----------------------------------------------------------------------------
# Render
# -----------------------------------------------------------------------------
st_folium(m, width=None, height=700, returned_objects=[])

st.caption(
    f"Resolution R{resolution} · {schema_choice} · "
    f"{total_cells:,} hex cells covering {total_wells:,} wells · "
    f"query {elapsed_ms} ms"
)

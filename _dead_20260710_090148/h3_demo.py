"""
h3_demo.py — standalone, READ-ONLY demo of the H3 hex density grid.

What it does, and just as importantly what it does NOT do:
  • Reads surface_latitude / surface_longitude from dataview.dv_well (SELECT only)
  • Computes the H3 cells in Python, in memory
  • Counts wells per cell and draws the hexagons on a Folium map

It never writes to the database, never adds columns, and never imports or
touches your map app. It runs on its own port, so it cannot break anything —
the worst case is it shows no hexes (e.g. if no wells have coordinates yet).

Run it on its own (any free port):
    streamlit run h3_demo.py --server.port 8599

Set the Server / Database in the sidebar to whichever project you want to see.
Requires: pip install h3 folium   (streamlit, pandas, sqlalchemy, pyodbc you have)
"""
from collections import Counter
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import create_engine, text

try:
    import h3
except ImportError:
    st.error("The h3 package isn't installed:  pip install h3")
    st.stop()
import branca.colormap as bcm
import folium

st.set_page_config(page_title="H3 hex grid demo", layout="wide")

# ── connection (editable in the sidebar; nothing is written) ──────────────
st.sidebar.header("Connection")
server   = st.sidebar.text_input("Server",   r"PERRY\SQLEXPRESS")
database = st.sidebar.text_input("Database", "DataView_Demo")
schema   = st.sidebar.text_input("Schema",   "dataview")
table    = st.sidebar.text_input("Table",    "dv_well")
lat_col  = st.sidebar.text_input("Lat column", "surface_latitude")
lon_col  = st.sidebar.text_input("Lon column", "surface_longitude")
res      = st.sidebar.slider("H3 resolution", 4, 7, 6,
                             help="Lower = bigger hexes / fewer cells")


@st.cache_resource(show_spinner=False)
def _engine(srv, db):
    odbc = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={srv};"
            f"DATABASE={db};Trusted_Connection=yes;")
    return create_engine(f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}")


@st.cache_data(show_spinner="Reading well coordinates…")
def _load(srv, db, sch, tbl, lat, lon):
    eng = _engine(srv, db)
    with eng.connect() as c:
        return pd.read_sql(text(
            f"SELECT [{lat}] AS lat, [{lon}] AS lon "
            f"FROM [{sch}].[{tbl}] "
            f"WHERE [{lat}] IS NOT NULL AND [{lon}] IS NOT NULL"), c)


def _to_cell(lat, lon, r):
    return (h3.latlng_to_cell(lat, lon, r) if hasattr(h3, "latlng_to_cell")
            else h3.geo_to_h3(lat, lon, r))


def _ring(cell):
    """GeoJSON [lng, lat] ring, closed."""
    if hasattr(h3, "cell_to_boundary"):
        ring = [[lng, lat] for (lat, lng) in h3.cell_to_boundary(cell)]
    else:
        ring = [list(p) for p in h3.h3_to_geo_boundary(cell, geo_json=True)]
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


st.title("H3 hex density grid — demo")
st.caption("Read-only. Computes hexagons in memory from existing coordinates — "
           "nothing is written to your database.")

try:
    df = _load(server, database, schema, table, lat_col, lon_col)
except Exception as exc:
    st.error(f"Could not read {schema}.{table}: {exc}")
    st.stop()

if df.empty:
    st.warning(f"No rows in {schema}.{table} have both {lat_col} and {lon_col}. "
               "Nothing to draw yet.")
    st.stop()

# compute + aggregate on the fly
counts = Counter()
for la, lo in zip(df["lat"], df["lon"]):
    try:
        counts[_to_cell(float(la), float(lo), res)] += 1
    except Exception:
        pass

if not counts:
    st.warning("Coordinates present but no cells computed — check the values.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Wells with coords", f"{len(df):,}")
c2.metric(f"Hex cells (r{res})", f"{len(counts):,}")
c3.metric("Busiest cell", f"{max(counts.values()):,} wells")

vmax = max(counts.values())
cmap = bcm.LinearColormap(
    ["#2b83ba", "#abdda4", "#ffffbf", "#fdae61", "#d7191c"],
    vmin=1, vmax=vmax, caption=f"Wells per H3 r{res} cell")

fc = {"type": "FeatureCollection", "features": [
    {"type": "Feature",
     "properties": {"h3": cell, "count": n},
     "geometry": {"type": "Polygon", "coordinates": [_ring(cell)]}}
    for cell, n in counts.items()]}

m = folium.Map(tiles="cartodbpositron", control_scale=True)
folium.GeoJson(
    fc,
    style_function=lambda f: {
        "fillColor": cmap(f["properties"]["count"]),
        "color": "#22222255", "weight": 0.5, "fillOpacity": 0.6},
    highlight_function=lambda _f: {"weight": 2, "color": "#111"},
    tooltip=folium.GeoJsonTooltip(fields=["h3", "count"],
                                  aliases=["Cell", "Wells"]),
).add_to(m)
cmap.add_to(m)
m.fit_bounds([[df["lat"].min(), df["lon"].min()],
              [df["lat"].max(), df["lon"].max()]])

components.html(m.get_root().render(), height=640)

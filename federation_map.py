"""
federation_map.py
=================
Standalone Streamlit map for the Snowflake Well Federation.
Queries WELL_FEDERATION.CURATED.WELL_MASTER directly.

Usage:
    streamlit run federation_map.py --server.port 8503

Set environment variables:
    SNOWFLAKE_ACCOUNT=YDWXNCV-VL88062
    SNOWFLAKE_USER=PMSTOKES00
    SNOWFLAKE_PASSWORD=your_password
"""
import os
import time
import streamlit as st
import pydeck as pdk

st.set_page_config(page_title="Well Federation Map", layout="wide",
                   page_icon="🗺️")

# ── Snowflake connection ─────────────────────────────────────────────

@st.cache_resource
def get_connection():
    import snowflake.connector
    return snowflake.connector.connect(
        account=os.environ.get("SNOWFLAKE_ACCOUNT", "YDWXNCV-VL88062"),
        user=os.environ.get("SNOWFLAKE_USER", "PMSTOKES00"),
        password=os.environ.get("SNOWFLAKE_PASSWORD", ""),
        database="WELL_FEDERATION",
        warehouse="WV_WH",
        role="ACCOUNTADMIN",
    )


@st.cache_data(ttl=300)
def get_summary():
    """Get well counts by state."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT province_state, COUNT(*) AS cnt,
               COUNT(DISTINCT operator_name) AS operators,
               COUNT(DISTINCT field_name) AS fields
        FROM WELL_FEDERATION.CURATED.WELL_MASTER
        WHERE province_state IS NOT NULL AND province_state != ''
        GROUP BY province_state
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    cur.close()
    return rows


@st.cache_data(ttl=60)
def query_wells(state, county=None, limit=100000):
    """Query wells for map rendering."""
    conn = get_connection()
    cur = conn.cursor()

    where = "WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL"
    if state and state != "All":
        where += f" AND province_state = '{state}'"
    if county and county != "All":
        where += f" AND county = '{county}'"

    sql = f"""
        SELECT uwi, well_name, operator_name, field_name,
               surface_latitude, surface_longitude,
               county, province_state, well_status, well_type,
               source_list
        FROM WELL_FEDERATION.CURATED.WELL_MASTER
        {where}
        LIMIT {limit}
    """

    t0 = time.time()
    cur.execute(sql)
    columns = [desc[0].lower() for desc in cur.description]
    rows = cur.fetchall()
    cur.close()

    wells = []
    for row in rows:
        d = dict(zip(columns, row))
        try:
            lat = float(d["surface_latitude"])
            lon = float(d["surface_longitude"])
        except (ValueError, TypeError):
            continue
        if lat == 0 and lon == 0:
            continue
        wells.append({
            "lon": lon, "lat": lat,
            "uwi": d.get("uwi", ""),
            "name": d.get("well_name", "") or "",
            "operator": d.get("operator_name", "") or "",
            "field": d.get("field_name", "") or "",
            "county": d.get("county", "") or "",
            "state": d.get("province_state", "") or "",
            "status": d.get("well_status", "") or "",
            "type": d.get("well_type", "") or "",
            "source": d.get("source_list", "") or "",
        })

    return wells, time.time() - t0


@st.cache_data(ttl=300)
def get_counties(state):
    """Get county list for a state."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT DISTINCT county FROM WELL_FEDERATION.CURATED.WELL_MASTER
        WHERE province_state = '{state}' AND county IS NOT NULL AND county != ''
        ORDER BY county
    """)
    counties = [row[0] for row in cur.fetchall()]
    cur.close()
    return counties


# ── Status colors ────────────────────────────────────────────────────

STATUS_COLORS = {
    "OIL": [34, 197, 94, 220],
    "GAS": [239, 68, 68, 220],
    "D&A": [156, 163, 175, 180],
    "DRY": [156, 163, 175, 180],
    "SWD": [96, 165, 250, 220],
    "INJ": [96, 165, 250, 220],
    "LOC": [251, 191, 36, 220],
    "PA": [120, 120, 120, 180],
    "TA": [249, 115, 22, 220],
    "A": [34, 197, 94, 220],
    "ACTIVE": [34, 197, 94, 220],
    "COM": [16, 185, 129, 220],
}
DEFAULT_COLOR = [29, 158, 117, 180]


def get_color(status):
    s = (status or "").upper()
    if s in STATUS_COLORS:
        return STATUS_COLORS[s]
    for key in STATUS_COLORS:
        if key in s:
            return STATUS_COLORS[key]
    return DEFAULT_COLOR


# ── UI ───────────────────────────────────────────────────────────────

st.title("🗺️ Well Federation Map")
st.caption("Powered by Snowflake WELL_FEDERATION · CURATED.WELL_MASTER")

# Check connection
try:
    summary = get_summary()
except Exception as e:
    st.error(f"Cannot connect to Snowflake: {e}")
    st.info("Set SNOWFLAKE_PASSWORD environment variable before running.")
    st.stop()

# Sidebar
with st.sidebar:
    st.header("Federation Summary")
    total = sum(row[1] for row in summary)
    st.metric("Total Wells", f"{total:,}")

    st.divider()
    for row in summary:
        state, cnt, ops, flds = row
        st.caption(f"**{state}**: {cnt:,} wells · {ops:,} operators")

    st.divider()
    st.header("Filters")

    states = ["All"] + [row[0] for row in summary]
    sel_state = st.selectbox("State", states)

    sel_county = "All"
    if sel_state and sel_state != "All":
        counties = get_counties(sel_state)
        sel_county = st.selectbox("County", ["All"] + counties)

    max_wells = st.select_slider("Max wells",
        options=[10000, 25000, 50000, 100000, 250000, 500000],
        value=100000)

    st.divider()
    basemaps = {
        "Navigation": "mapbox://styles/mapbox/navigation-day-v1",
        "Streets": "mapbox://styles/mapbox/streets-v12",
        "Satellite": "mapbox://styles/mapbox/satellite-streets-v12",
        "Dark": "mapbox://styles/mapbox/dark-v11",
        "Light": "mapbox://styles/mapbox/light-v11",
        "Outdoors": "mapbox://styles/mapbox/outdoors-v12",
    }
    sel_basemap = st.selectbox("Basemap", list(basemaps.keys()))

# Query wells
with st.spinner(f"Querying Snowflake…"):
    county_arg = sel_county if sel_county != "All" else None
    wells, query_time = query_wells(sel_state, county_arg, max_wells)

if not wells:
    st.warning("No wells found for the selected filters.")
    st.stop()

# Add colors
for w in wells:
    w["color"] = get_color(w["status"])

# Stats bar
c1, c2, c3, c4 = st.columns(4)
c1.metric("Wells Displayed", f"{len(wells):,}")
c2.metric("Query Time", f"{query_time:.2f}s")
operators = len({w["operator"] for w in wells if w["operator"]})
c3.metric("Operators", f"{operators:,}")
counties = len({w["county"] for w in wells if w["county"]})
c4.metric("Counties", f"{counties:,}")

# Map
avg_lat = sum(w["lat"] for w in wells) / len(wells)
avg_lon = sum(w["lon"] for w in wells) / len(wells)

view = pdk.ViewState(
    latitude=avg_lat, longitude=avg_lon,
    zoom=6, pitch=0, bearing=0)

layer = pdk.Layer("ScatterplotLayer",
    data=wells,
    get_position=["lon", "lat"],
    get_fill_color="color",
    get_line_color=[40, 40, 40, 180],
    get_radius=30,
    radius_min_pixels=2,
    radius_max_pixels=12,
    pickable=True,
    auto_highlight=True,
    highlight_color=[255, 200, 0, 200])

tooltip = {
    "html": "<b>{uwi}</b><br>{name}<br>"
            "<i>{operator}</i><br>"
            "{field} · {county}, {state}<br>"
            "Status: {status} · Type: {type}<br>"
            "Source: {source}",
    "style": {"backgroundColor": "#1a1a2e",
              "color": "white", "fontSize": "12px",
              "padding": "8px", "borderRadius": "4px"}}

st.pydeck_chart(
    pdk.Deck(layers=[layer],
             initial_view_state=view,
             map_style=basemaps[sel_basemap],
             tooltip=tooltip),
    use_container_width=True, height=650)

# Legend
with st.expander("Legend"):
    cols = st.columns(6)
    legend = [
        ("🟢", "Oil / Active"), ("🔴", "Gas"),
        ("🔵", "Injection / SWD"), ("⚫", "P&A / Dry"),
        ("🟡", "Location"), ("🟠", "Shut-in / TA"),
    ]
    for i, (icon, label) in enumerate(legend):
        cols[i].caption(f"{icon} {label}")

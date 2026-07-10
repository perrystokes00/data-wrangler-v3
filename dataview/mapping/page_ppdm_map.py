"""
page_ppdm_map.py — Data Wrangler · PPDM Interactive Map
=========================================================
Folium-based interactive map showing PPDM wells, seismic surveys
and (if loaded) field boundaries and well log locations.

Layers:
  🛢️  Wells          — points from dbo.WELL (lat/lon from SURFACE_LATITUDE/LONGITUDE)
  🌊  Seismic        — lines/rectangles from las_catalog.SEIS_FILE_CATALOG
  🔷  Fields         — polygons from dbo.FIELD (if lat/lon available)

Clicking a well marker shows a popup with UWI, well name, operator,
status, spud date and a link to the well log catalog.
"""

from __future__ import annotations
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_engine():
    engine = st.session_state.get("engine")
    if engine is not None:
        return engine
    try:
        from dataview.core.db_pool import get_engine
        return get_engine()
    except ImportError:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _load_wells(_engine, limit: int = 5000) -> pd.DataFrame:
    """Cache well data for 5 minutes. Underscore prefix tells Streamlit not to hash the engine."""
    from sqlalchemy import text
    try:
        rows = _engine.connect().execute(text(f"""
            SELECT TOP {limit}
                w.UWI,
                w.WELL_NAME,
                w.CURRENT_STATUS,
                w.SPUD_DATE,
                w.SURFACE_LATITUDE,
                w.SURFACE_LONGITUDE,
                ISNULL(ba.LONG_NAME, ba.SHORT_NAME) AS OPERATOR,
                ISNULL(f.FIELD_NAME,  '')            AS FIELD_NAME,
                ISNULL(w.COUNTRY_ISO, '')            AS COUNTRY
            FROM dbo.WELL w
            LEFT JOIN dbo.BUSINESS_ASSOCIATE ba
                ON ba.BUSINESS_ASSOCIATE_ID = w.BA_ID
            LEFT JOIN dbo.FIELD f
                ON f.FIELD_ID = w.FIELD_ID
            WHERE w.SURFACE_LATITUDE  IS NOT NULL
              AND w.SURFACE_LONGITUDE IS NOT NULL
              AND w.SURFACE_LATITUDE  BETWEEN -90  AND 90
              AND w.SURFACE_LONGITUDE BETWEEN -180 AND 180
            ORDER BY w.UWI
        """)).fetchall()
        return pd.DataFrame(rows, columns=[
            "UWI","WELL_NAME","STATUS","SPUD_DATE",
            "LAT","LON","OPERATOR","FIELD","COUNTRY"
        ])
    except Exception as e:
        # Fallback — try without the FIELD join in case dbo.FIELD doesn't exist
        try:
            rows = _engine.connect().execute(text(f"""
                SELECT TOP {limit}
                    w.UWI, w.WELL_NAME, w.CURRENT_STATUS, w.SPUD_DATE,
                    w.SURFACE_LATITUDE, w.SURFACE_LONGITUDE,
                    ISNULL(ba.LONG_NAME, ba.SHORT_NAME) AS OPERATOR,
                    '' AS FIELD_NAME, ISNULL(w.COUNTRY_ISO, '') AS COUNTRY
                FROM dbo.WELL w
                LEFT JOIN dbo.BUSINESS_ASSOCIATE ba
                    ON ba.BUSINESS_ASSOCIATE_ID = w.BA_ID
                WHERE SURFACE_LATITUDE  IS NOT NULL
                  AND SURFACE_LONGITUDE IS NOT NULL
                  AND SURFACE_LATITUDE  BETWEEN -90  AND 90
                  AND SURFACE_LONGITUDE BETWEEN -180 AND 180
                ORDER BY UWI
            """)).fetchall()
            return pd.DataFrame(rows, columns=[
                "UWI","WELL_NAME","OPERATOR","STATUS",
                "SPUD_DATE","LAT","LON","FIELD","COUNTRY"
            ])
        except Exception as e2:
            # Final fallback — absolute minimum columns
            try:
                rows = _engine.connect().execute(text(f"""
                    SELECT TOP {limit}
                        UWI, WELL_NAME, OPERATOR, CURRENT_STATUS,
                        SPUD_DATE, SURFACE_LATITUDE, SURFACE_LONGITUDE
                    FROM dbo.WELL
                    WHERE SURFACE_LATITUDE  IS NOT NULL
                      AND SURFACE_LONGITUDE IS NOT NULL
                      AND SURFACE_LATITUDE  BETWEEN -90  AND 90
                      AND SURFACE_LONGITUDE BETWEEN -180 AND 180
                    ORDER BY UWI
                """)).fetchall()
                df = pd.DataFrame(rows, columns=[
                    "UWI","WELL_NAME","OPERATOR","STATUS",
                    "SPUD_DATE","LAT","LON"
                ])
                df["FIELD"]   = ""
                df["COUNTRY"] = ""
                return df
            except Exception as e3:
                st.warning(f"Could not load wells: {e3}")
                return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def _load_seismic(_engine) -> pd.DataFrame:
    """Cache seismic data for 5 minutes."""
    from sqlalchemy import text
    try:
        rows = _engine.connect().execute(text("""
            SELECT SEIS_FILE_ID, FILE_FORMAT, SURVEY_NAME, LINE_NAME,
                   DIMENSIONALITY,
                   MIN_LAT, MAX_LAT, MIN_LON, MAX_LON,
                   MIN_X, MAX_X, MIN_Y, MAX_Y,
                   TRACE_COUNT, SHOT_COUNT
            FROM [las_catalog].[SEIS_FILE_CATALOG]
            WHERE (MIN_LAT IS NOT NULL OR MIN_X IS NOT NULL)
              AND ACTIVE_IND = 'Y'
        """)).fetchall()
        return pd.DataFrame(rows, columns=[
            "ID","FORMAT","SURVEY","LINE","DIM",
            "MIN_LAT","MAX_LAT","MIN_LON","MAX_LON",
            "MIN_X","MAX_X","MIN_Y","MAX_Y",
            "TRACES","SHOTS"
        ])
    except Exception:
        return pd.DataFrame()


def _make_map(wells_df: pd.DataFrame,
              seis_df:  pd.DataFrame,
              show_wells: bool,
              show_seis:  bool,
              well_colour_by: str,
              basemap: str) -> str:
    """Build a Folium map and return the HTML string."""
    try:
        import folium
        from folium.plugins import MarkerCluster
    except ImportError:
        raise ImportError(
            "folium is not installed. Run in your venv:\n\n"
            "    pip install folium\n\n"
            "Then restart Data Wrangler."
        )

    # ── Base map ──────────────────────────────────────────────────────────
    _TILES = {
        "OpenStreetMap": "OpenStreetMap",
        "Satellite (Esri)": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "Topo (Esri)":  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "Light":        "CartoDB positron",
        "Dark":         "CartoDB dark_matter",
    }

    # Determine map centre
    centre_lat, centre_lon, zoom = 20.0, 0.0, 2
    if show_wells and not wells_df.empty:
        centre_lat = float(wells_df["LAT"].mean())
        centre_lon = float(wells_df["LON"].mean())
        zoom = int(6)
    elif show_seis and not seis_df.empty and seis_df["MIN_LAT"].notna().any():
        centre_lat = float(seis_df["MIN_LAT"].dropna().mean())
        centre_lon = float(seis_df["MIN_LON"].dropna().mean())
        zoom = int(7)

    tile = _TILES.get(basemap, "OpenStreetMap")
    if tile.startswith("http"):
        m = folium.Map(location=[centre_lat, centre_lon], zoom_start=zoom,
                       tiles=tile, attr="Esri")
    else:
        m = folium.Map(location=[centre_lat, centre_lon], zoom_start=zoom,
                       tiles=tile)

    # ── Well colour mapping ────────────────────────────────────────────────
    _STATUS_COLOURS = {
        "PRODUCER":   "#2CA02C",
        "INJECTOR":   "#1F77B4",
        "ABANDONED":  "#7F7F7F",
        "DRY":        "#D62728",
        "SUSPENDED":  "#FF7F0E",
        "PLUGGED":    "#8C564B",
    }

    def _well_colour(row):
        if well_colour_by == "Status":
            s = str(row.get("STATUS","")).upper()
            for k, c in _STATUS_COLOURS.items():
                if k in s: return c
            return "#9467BD"
        elif well_colour_by == "Operator":
            ops = list({str(r.get("OPERATOR","")) for _, r in wells_df.iterrows()
                        if r.get("OPERATOR")})
            _OP_COLS = ["#1F4E79","#D62728","#2CA02C","#FF7F0E","#9467BD",
                        "#8C564B","#E377C2","#17BECF","#BCBD22","#7F7F7F"]
            op = str(row.get("OPERATOR",""))
            idx = ops.index(op) % len(_OP_COLS) if op in ops else 0
            return _OP_COLS[idx]
        return "#1F4E79"

    # ── Wells layer ────────────────────────────────────────────────────────
    if show_wells and not wells_df.empty:
        cluster = MarkerCluster(name="🛢️ Wells", show=True)
        for _, row in wells_df.iterrows():
            colour = _well_colour(row)
            popup_html = f"""
            <div style='font-family:sans-serif;min-width:200px'>
              <b style='font-size:14px'>{row.get('WELL_NAME') or row.get('UWI','')}</b><br>
              <hr style='margin:4px 0'>
              <b>UWI:</b> {row.get('UWI','—')}<br>
              <b>Operator:</b> {row.get('OPERATOR','—')}<br>
              <b>Status:</b> {row.get('STATUS','—')}<br>
              <b>Field:</b> {row.get('FIELD','—')}<br>
              <b>Spud:</b> {str(row.get('SPUD_DATE','—'))[:10]}<br>
              <b>Country:</b> {row.get('COUNTRY','—')}
            </div>"""
            folium.CircleMarker(
                location=[float(row["LAT"]), float(row["LON"])],
                radius=6,
                color=colour,
                fill=True,
                fill_color=colour,
                fill_opacity=0.8,
                weight=1.5,
                popup=folium.Popup(popup_html, max_width=280),
                tooltip=str(row.get("WELL_NAME") or row.get("UWI",""))
            ).add_to(cluster)
        cluster.add_to(m)

    # ── Seismic layer ──────────────────────────────────────────────────────
    _SEIS_COLOURS = ["#E377C2","#FF7F0E","#BCBD22","#17BECF","#9467BD"]

    if show_seis and not seis_df.empty:
        surveys = seis_df["SURVEY"].fillna("Unknown").unique()
        seis_layer = folium.FeatureGroup(name="🌊 Seismic", show=True)

        for si, survey in enumerate(surveys):
            svy_df  = seis_df[seis_df["SURVEY"].fillna("Unknown") == survey]
            colour  = _SEIS_COLOURS[si % len(_SEIS_COLOURS)]

            for _, row in svy_df.iterrows():
                dim = str(row.get("DIM","2D"))

                # Geographic coords available
                if pd.notna(row.get("MIN_LAT")) and pd.notna(row.get("MAX_LAT")):
                    mn_lat = float(row["MIN_LAT"]); mx_lat = float(row["MAX_LAT"])
                    mn_lon = float(row["MIN_LON"]); mx_lon = float(row["MAX_LON"])
                    popup_html = (
                        f"<b>{row.get('SURVEY','')}</b><br>"
                        f"Line: {row.get('LINE','—')}<br>"
                        f"Format: {row.get('FORMAT','')}<br>"
                        f"Traces: {row.get('TRACES','—')}"
                    )
                    if dim == "3D":
                        folium.Rectangle(
                            bounds=[[mn_lat, mn_lon],[mx_lat, mx_lon]],
                            color=colour, fill=True, fill_opacity=0.15,
                            weight=2,
                            popup=folium.Popup(popup_html, max_width=200),
                            tooltip=str(row.get("SURVEY",""))
                        ).add_to(seis_layer)
                    else:
                        folium.PolyLine(
                            locations=[[mn_lat, mn_lon],[mx_lat, mx_lon]],
                            color=colour, weight=3, opacity=0.8,
                            popup=folium.Popup(popup_html, max_width=200),
                            tooltip=str(row.get("LINE") or row.get("SURVEY",""))
                        ).add_to(seis_layer)

        seis_layer.add_to(m)

    # Layer control
    folium.LayerControl(collapsed=False).add_to(m)

    return m._repr_html_()


# ── Main page ──────────────────────────────────────────────────────────────

def run():
    st.title("🗺️ PPDM Interactive Map")
    st.caption("Wells, seismic surveys and field boundaries from your PPDM database.")

    try:
        import folium
        _folium_ver = folium.__version__
    except ImportError as _fim:
        import sys
        st.error(
            f"**folium is not installed in this Python environment.**\n\n"
            f"Python executable: `{sys.executable}`\n\n"
            f"Run: `{sys.executable} -m pip install folium`\n\n"
            f"Then restart Data Wrangler."
        )
        return
    st.caption(f"folium {_folium_ver} ✅")

    engine = _get_engine()
    if engine is None:
        st.warning("No database connection. Connect via the main pipeline first.")
        return

    # ── Controls ──────────────────────────────────────────────────────────
    with st.sidebar:
        st.divider()
        st.markdown("**🗺️ Map controls**")
        basemap = st.selectbox(
            "Base map",
            ["OpenStreetMap","Light","Dark","Satellite (Esri)","Topo (Esri)"],
            key="map_basemap"
        )
        st.markdown("**Layers**")
        show_wells = st.checkbox("🛢️ Wells",   value=True,  key="map_show_wells")
        show_seis  = st.checkbox("🌊 Seismic", value=True,  key="map_show_seis")
        if show_wells:
            well_colour_by = st.selectbox(
                "Colour wells by",
                ["Status", "Operator", "Uniform"],
                key="map_well_colour"
            )
        else:
            well_colour_by = "Uniform"
        well_limit = st.slider("Max wells", 100, 10000, 500, 100,
                               key="map_well_limit")
        if st.button("🔄 Refresh map", key="map_refresh"):
            # Clear all map caches
            _load_wells.clear()
            _load_seismic.clear()
            for k in list(st.session_state.keys()):
                if k.startswith("map_html"):
                    st.session_state.pop(k)
            st.rerun()
        st.divider()

    # ── Load data ─────────────────────────────────────────────────────────
    cache_key = f"map_html_{basemap}_{show_wells}_{show_seis}_{well_colour_by}_{well_limit}"

    if cache_key not in st.session_state:
        with st.spinner("Loading map data…"):
            wells_df = _load_wells(engine, limit=well_limit) if show_wells else pd.DataFrame()
            seis_df  = _load_seismic(engine) if show_seis else pd.DataFrame()
        st.caption(f"Data loaded — {len(wells_df):,} wells, {len(seis_df):,} seismic files")

        col1, col2, col3 = st.columns(3)
        col1.metric("Wells on map",   len(wells_df))
        col2.metric("Seismic files",  len(seis_df))
        col3.metric("Surveys",
                    seis_df["SURVEY"].nunique() if not seis_df.empty else 0)

        with st.spinner("Rendering map…"):
            html = _make_map(
                wells_df, seis_df,
                show_wells, show_seis,
                well_colour_by, basemap
            )
        st.session_state[cache_key] = (html, len(wells_df), len(seis_df))
    else:
        html, n_wells, n_seis = st.session_state[cache_key]
        col1, col2, col3 = st.columns(3)
        col1.metric("Wells on map",  n_wells)
        col2.metric("Seismic files", n_seis)

    html, *_ = st.session_state[cache_key]
    components.html(html, height=680, scrolling=False)

    st.caption(
        "🛢️ Well markers cluster at lower zoom levels — zoom in to see individual wells.  "
        "Click any marker for details.  "
        "Use the layer control (top right of map) to toggle layers."
    )

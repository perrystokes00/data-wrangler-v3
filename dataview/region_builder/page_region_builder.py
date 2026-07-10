"""
page_region_builder.py  —  DataView V3
=======================================
Region Builder — interactive tool for defining state regions by
lassoing counties on a map.

WORKFLOW:
    1. Pick a state from the dropdown
    2. Counties for that state render on the map
    3. Draw a polygon (lasso) around the counties you want grouped
    4. Counties whose centroid is inside the lasso are highlighted
    5. Name the group, click "Add to group"
    6. Repeat for as many groups as you need
    7. Click "Export as Python dict" to copy a STATE_REGIONS dict to
       clipboard
    8. Paste into state_regions.py at V3's project root

OUTPUT SHAPE (matches petroleum_regions.py):
    STATE_REGIONS = {
        "— none —": (None, []),
        "South Texas": ("TX", ["Atascosa", "Bee", "DeWitt", ...]),
        "West Texas":  ("TX", ["Andrews", "Borden", ...]),
        ...
    }

ARCHITECTURE NOTES:
    - Reads TIGER 2024 US Counties shapefile (path in CONFIG below)
    - Centroid-based inclusion: a county is "selected" if its centroid
      falls inside the drawn polygon. Boundary-crossing counties get
      decided by where their centroid lies, which is unambiguous and
      fast.
    - Single-state groups only (matches PETROLEUM_REGIONS pattern)
    - No persistence — refresh loses work. Export to clipboard, paste
      into a .py file yourself.

DEPENDENCIES:
    pip install geopandas shapely streamlit-folium folium

WIRING INTO app.py:
    elif S.app_mode == "region_builder":
        try:
            from dataview.region_builder import page_region_builder
            page_region_builder.render(S.engine)
        except Exception as e:
            st.error(f"Region Builder error: {e}")
            import traceback
            st.code(traceback.format_exc())
"""
from __future__ import annotations

import streamlit as st
from typing import Any

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

# Path to TIGER counties shapefile. Update if you move the file.
COUNTIES_SHP = (
    r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai"
    r"\data_wrangler\data_wrangler_v3\spatial\tl_2024_us_county.shp"
)

# ═══════════════════════════════════════════════════════════════════════
# IMPORTS WITH FALLBACKS
# ═══════════════════════════════════════════════════════════════════════

try:
    import geopandas as gpd
    HAS_GPD = True
except ImportError:
    HAS_GPD = False

try:
    import folium
    from folium.plugins import Draw
    from streamlit_folium import st_folium
    HAS_FOLIUM = True
except ImportError:
    HAS_FOLIUM = False

try:
    from shapely.geometry import shape as shapely_shape
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False


# FIPS state code → 2-letter USPS code. Used as a fallback if the
# shapefile lacks the STUSPS column. TIGER 2023+ includes STUSPS
# directly; older versions don't.
FIPS_TO_USPS = {
    "01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT",
    "10":"DE","11":"DC","12":"FL","13":"GA","15":"HI","16":"ID","17":"IL",
    "18":"IN","19":"IA","20":"KS","21":"KY","22":"LA","23":"ME","24":"MD",
    "25":"MA","26":"MI","27":"MN","28":"MS","29":"MO","30":"MT","31":"NE",
    "32":"NV","33":"NH","34":"NJ","35":"NM","36":"NY","37":"NC","38":"ND",
    "39":"OH","40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD",
    "47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA","54":"WV",
    "55":"WI","56":"WY",
    # Territories — usually skipped for petroleum work but included
    # for completeness
    "60":"AS","66":"GU","69":"MP","72":"PR","78":"VI",
}

# Colors cycled through for completed groups so the user can visually
# distinguish them on the map. After the palette is exhausted, groups
# fall back to neutral gray (sad but readable). Picked for visibility
# on CartoDB Positron's pale background; muted enough not to overwhelm
# the active-selection teal.
GROUP_COLORS = [
    "#e6550d",  # orange
    "#756bb1",  # purple
    "#31a354",  # green
    "#c994c7",  # pink
    "#fdae6b",  # peach
    "#9ecae1",  # sky blue
    "#a1d99b",  # light green
    "#bcbddc",  # lavender
]
DEFAULT_GROUP_COLOR = "#9e9e9e"   # neutral gray


def _color_for_group(group_idx: int) -> str:
    """Index → palette color, cycling through after exhaustion."""
    if group_idx < len(GROUP_COLORS):
        return GROUP_COLORS[group_idx]
    return DEFAULT_GROUP_COLOR


# ═══════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _load_counties() -> Any:
    """Load TIGER counties once per session and cache. Returns a
    GeoDataFrame in EPSG:4326 with columns: state, county_name,
    centroid_lat, centroid_lon, geometry."""
    gdf = gpd.read_file(COUNTIES_SHP)

    # Reproject to web-friendly WGS84
    if gdf.crs is None:
        # Assume NAD83 (TIGER default) if undeclared
        gdf = gdf.set_crs("EPSG:4269")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")

    # Pick the state column — STUSPS preferred, STATEFP fallback
    cols_upper = {c.upper(): c for c in gdf.columns}
    if "STUSPS" in cols_upper:
        gdf["state"] = gdf[cols_upper["STUSPS"]]
    elif "STATEFP" in cols_upper:
        gdf["state"] = gdf[cols_upper["STATEFP"]].map(FIPS_TO_USPS)
    else:
        raise ValueError(
            "Couldn't find STUSPS or STATEFP column in the shapefile. "
            f"Columns present: {list(gdf.columns)}"
        )

    # Pick the county name column — NAME is standard TIGER
    if "NAME" in cols_upper:
        gdf["county_name"] = gdf[cols_upper["NAME"]]
    elif "NAMELSAD" in cols_upper:
        # NAMELSAD includes "County" suffix — strip it
        gdf["county_name"] = (
            gdf[cols_upper["NAMELSAD"]]
            .str.replace(" County", "", regex=False)
            .str.strip()
        )
    else:
        raise ValueError(
            "Couldn't find NAME or NAMELSAD column. "
            f"Columns present: {list(gdf.columns)}"
        )

    # Precompute centroids — used for point-in-polygon inclusion test.
    # We compute in 4326 which is technically distorted at high latitudes,
    # but for US counties this is well within acceptable error. For more
    # precision we'd reproject to an equal-area CRS, compute centroids,
    # then reproject back — overkill for this tool.
    # Suppress GeoPandas' "geographic CRS" warning — we know, and the
    # error is sub-100m at US latitudes, which is fine for centroid-
    # based county selection.
    import warnings as _warnings
    with _warnings.catch_warnings():
        _warnings.filterwarnings(
            "ignore", message="Geometry is in a geographic CRS"
        )
        gdf["centroid_lat"] = gdf.geometry.centroid.y
        gdf["centroid_lon"] = gdf.geometry.centroid.x

    return gdf[["state", "county_name", "centroid_lat", "centroid_lon",
                "geometry"]].copy()


# ═══════════════════════════════════════════════════════════════════════
# MAP RENDERING
# ═══════════════════════════════════════════════════════════════════════

def _render_map(state_gdf, selected_counties: set[str],
                groups_for_state: dict[str, list[str]] = None):
    """Render the state's counties on a Folium map.

    Style precedence (later wins):
      - default     gray outline, near-transparent fill
      - in a group  per-group color (palette cycled)
      - active sel  teal — the lasso-in-progress selection

    `groups_for_state` maps group_name → [county_names], scoped to the
    current state (caller filters by state before passing).

    Returns the raw drawing dict (or None) when the user draws a polygon."""
    if state_gdf.empty:
        st.warning("No counties for this state.")
        return None

    groups_for_state = groups_for_state or {}

    # Build a county-name → (group_name, color) lookup so style_function
    # can paint each county in its group's color in O(1). Order of
    # iteration determines color assignment — uses the dict's insertion
    # order, which matches the order the user defined the groups.
    county_to_group_color = {}
    for idx, (gname, gcounties) in enumerate(groups_for_state.items()):
        color = _color_for_group(idx)
        for cname in gcounties:
            # Last-writer-wins is fine here — if a county somehow ends
            # up in two groups (overlap is allowed), the most recent
            # group's color shows. Visually obvious; not silently broken.
            county_to_group_color[cname] = (gname, color)

    # Center the map on the state's bbox centroid
    minx, miny, maxx, maxy = state_gdf.total_bounds
    center = ((miny + maxy) / 2, (minx + maxx) / 2)

    # Rough zoom based on state size
    span = max(maxx - minx, maxy - miny, 0.5)
    if span < 2:   zoom = 8
    elif span < 5: zoom = 7
    elif span < 8: zoom = 6
    else:          zoom = 5

    m = folium.Map(location=center, zoom_start=zoom,
                   tiles="CartoDB positron")

    def _style(feature,
               selected=selected_counties,
               grp_lookup=county_to_group_color):
        name = feature["properties"]["county_name"]
        # Active selection wins — teal, prominent
        if name in selected:
            return {
                "fillColor": "#0a8a96",
                "color":     "#0a8a96",
                "weight":    2,
                "fillOpacity": 0.55,
            }
        # In a previously-defined group — color from palette
        if name in grp_lookup:
            _, color = grp_lookup[name]
            return {
                "fillColor": color,
                "color":     color,
                "weight":    1.5,
                "fillOpacity": 0.35,
            }
        # Default — pale outline
        return {
            "fillColor": "#cccccc",
            "color":     "#666666",
            "weight":    1,
            "fillOpacity": 0.10,
        }

    # Add group_name to feature properties so the tooltip can show it
    enriched = state_gdf.copy()
    enriched["group_name"] = enriched["county_name"].map(
        lambda n: county_to_group_color.get(n, ("", ""))[0]
    )
    # Replace blank group_name with a dash so tooltips read cleanly
    enriched["group_name"] = enriched["group_name"].replace("", "—")

    folium.GeoJson(
        enriched.__geo_interface__,
        name="counties",
        style_function=_style,
        tooltip=folium.GeoJsonTooltip(
            fields=["county_name", "group_name"],
            aliases=["County:", "Group:"],
            sticky=True,
        ),
    ).add_to(m)

    Draw(
        export=False,
        position="topleft",
        draw_options={
            "polygon": {
                "shapeOptions": {"color": "#0a8a96", "weight": 2,
                                  "fillOpacity": 0.1},
            },
            "rectangle": {
                "shapeOptions": {"color": "#0a8a96", "weight": 2,
                                  "fillOpacity": 0.1},
            },
            "circle":       False,
            "marker":       False,
            "polyline":     False,
            "circlemarker": False,
        },
        edit_options={"edit": True, "remove": True},
    ).add_to(m)

    state = st_folium(
        m, height=600, use_container_width=True,
        returned_objects=["all_drawings"],
        key="rb_map",
    )

    drawings = (state or {}).get("all_drawings") or []
    if drawings:
        return drawings[-1]
    return None


# ═══════════════════════════════════════════════════════════════════════
# SELECTION LOGIC
# ═══════════════════════════════════════════════════════════════════════

def _counties_inside_drawing(state_gdf, drawing) -> list[str]:
    """Given a drawing (GeoJSON feature dict from Folium Draw), return
    the list of county names whose centroid falls inside the drawing's
    geometry. Order is alphabetical for stable output."""
    if drawing is None:
        return []
    try:
        geom = shapely_shape(drawing["geometry"])
    except Exception:
        return []

    # Vectorized check via Shapely — fast even for 250 polygons.
    # Centroids are precomputed in _load_counties.
    inside = []
    for _, row in state_gdf.iterrows():
        from shapely.geometry import Point
        pt = Point(row["centroid_lon"], row["centroid_lat"])
        if geom.contains(pt):
            inside.append(row["county_name"])
    return sorted(inside)


# ═══════════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════════

def _format_export(groups: dict) -> str:
    """Format the accumulated groups as a Python dict literal,
    matching the new 3-tuple shape of petroleum_regions.py.

    Each value is (state_code, [county_names], (lat, lon, zoom)).
    The center tuple is auto-computed from the selected counties'
    bounding box when the group is added — see
    _compute_region_center()."""
    lines = []
    lines.append('"""')
    lines.append("state_regions.py")
    lines.append("=================")
    lines.append("State-region definitions, built via Region Builder.")
    lines.append("Same shape as petroleum_regions.py: each value is")
    lines.append('(state_code, [county_names], (lat, lon, zoom)).')
    lines.append("The center tuple is auto-computed at definition time")
    lines.append("from the lassoed counties' bounding box.")
    lines.append('"""')
    lines.append("")
    lines.append("STATE_REGIONS = {")
    lines.append('    "— none —": (None, [], None),')
    for name, value in groups.items():
        lines.append("")
        # Backward-compat: handle both 2-tuple (old) and 3-tuple (new)
        # entries that might be in session state during transition.
        if len(value) == 3:
            state, counties, center = value
        else:
            state, counties = value
            center = None
        # Format the center tuple — None or (lat, lon, zoom)
        if center is None:
            center_repr = "None"
        else:
            _clat, _clon, _czoom = center
            center_repr = f"({_clat:.4f}, {_clon:.4f}, {_czoom})"
        # Format county list — wrap at reasonable width
        if not counties:
            lines.append(
                f'    "{name}": ("{state}", [], {center_repr}),'
            )
        else:
            lines.append(f'    "{name}": ("{state}", [')
            # Break into lines of ~5 counties each
            for i in range(0, len(counties), 5):
                chunk = counties[i:i+5]
                quoted = ", ".join(f'"{c}"' for c in chunk)
                lines.append(f"        {quoted},")
            lines.append(f"    ], {center_repr}),")
    lines.append("}")
    return "\n".join(lines)


def _compute_region_center(
    state_gdf, county_names: list[str],
) -> tuple[float, float, int]:
    """Compute (center_lat, center_lon, zoom) for a region defined by
    a list of county names within a state.

    Center is the mean of the selected counties' centroids
    (already precomputed by _load_counties — stored in centroid_lat
    and centroid_lon columns).

    Zoom is derived from the bounding box span: tight clusters get
    higher zoom, sprawling regions get lower zoom. The mapping is
    tuned for Folium / OpenStreetMap tile zoom levels, where zoom 6
    is roughly state-level and zoom 10 is roughly county-level.

    Returns (lat, lon, zoom) as plain floats/int — JSON-serializable
    and Python-literal-friendly for the export."""
    if state_gdf.empty or not county_names:
        return (0.0, 0.0, 6)

    matching = state_gdf[state_gdf["county_name"].isin(county_names)]
    if matching.empty:
        # Fall back to whole-state centroid
        return (
            float(state_gdf["centroid_lat"].mean()),
            float(state_gdf["centroid_lon"].mean()),
            6,
        )

    center_lat = float(matching["centroid_lat"].mean())
    center_lon = float(matching["centroid_lon"].mean())

    # Span-based zoom — bigger span = lower zoom. Thresholds tuned
    # to match migrate_petroleum_regions.py / migrate_state_regions.py
    # so plays and state regions zoom consistently.
    lat_span = matching["centroid_lat"].max() - matching["centroid_lat"].min()
    lon_span = matching["centroid_lon"].max() - matching["centroid_lon"].min()
    span = max(lat_span, lon_span, 0.1)

    if   span < 0.5:  zoom = 10
    elif span < 1.0:  zoom = 9
    elif span < 2.0:  zoom = 8
    elif span < 4.0:  zoom = 7
    elif span < 8.0:  zoom = 6
    else:             zoom = 5

    return (center_lat, center_lon, zoom)


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def render(engine=None):
    """Entry point. `engine` is unused but kept for V3 page-protocol
    consistency (app.py passes it to every page)."""

    # ── Dependency checks ────────────────────────────────────────
    missing = []
    if not HAS_GPD:    missing.append("geopandas")
    if not HAS_FOLIUM: missing.append("folium, streamlit-folium")
    if not HAS_SHAPELY: missing.append("shapely")
    if missing:
        st.error(
            "Missing required packages: " + ", ".join(missing) +
            "\nInstall with: `pip install " +
            " ".join(p.split(",")[0].strip() for p in missing) + "`"
        )
        return

    st.title("🗺  Region Builder")
    st.caption(
        "Define state regions by lassoing counties on the map. Build "
        "as many groups as you need, then export to a Python dict."
    )

    # ── Load counties (cached) ───────────────────────────────────
    try:
        counties = _load_counties()
    except FileNotFoundError:
        st.error(
            f"County shapefile not found at:\n`{COUNTIES_SHP}`\n\n"
            "Edit COUNTIES_SHP at the top of page_region_builder.py "
            "if the file lives elsewhere."
        )
        return
    except Exception as e:
        st.error(f"Failed to load county shapefile: {e}")
        return

    # ── Session-state setup ──────────────────────────────────────
    if "rb_groups" not in st.session_state:
        # Map: group_name -> (state_code, sorted_county_list)
        st.session_state["rb_groups"] = {}

    # ── State picker (before columns so it can size the map) ─────
    states = sorted(counties["state"].dropna().unique().tolist())
    # Default to TX since that's where you'll likely start
    default_state_idx = states.index("TX") if "TX" in states else 0

    # ── Two-column layout: controls on left, map on right ────────
    # Matches page_well_map's layout convention. Keeps every control
    # visible alongside the map — no scrolling required to lasso
    # then name then add then see the result.
    ctrl, mapcol = st.columns([1, 3], gap="small")

    with ctrl:
        # State picker
        st.markdown("**State**")
        selected_state = st.selectbox(
            "State", states, index=default_state_idx,
            key="rb_state", label_visibility="collapsed",
        )
        state_gdf = counties[counties["state"] == selected_state].copy()
        st.caption(f"{len(state_gdf)} counties in {selected_state}")

        st.divider()

        # Selected counties panel — sits BEFORE map render call below.
        # We use a placeholder to defer rendering until after the map
        # call returns the drawing, so the count reflects what the
        # user just lassoed.
        sel_placeholder = st.container()

        st.divider()

        # Groups defined this session
        st.markdown("**Groups defined this session**")
        _groups_placeholder = st.container()

        # Export section — only renders when groups exist
        _export_placeholder = st.container()

    with mapcol:
        # Map. Caption above explains the interaction. Kept short for
        # the narrower right column (~75% width).
        st.caption(
            "🎯 Click the **polygon** or **rectangle** tool on the "
            "map, draw around counties to select them. Counties "
            "already in a group are colored by group."
        )

        # Filter completed groups to just those for the current state
        # so the map only colors what's relevant.
        # Handle both 2-tuple (old format) and 3-tuple (new with
        # center) entries — only need state + counties for the map.
        _groups_this_state = {}
        for gname, _gv in st.session_state["rb_groups"].items():
            _gstate = _gv[0]
            _gcounties = _gv[1]
            if _gstate == selected_state:
                _groups_this_state[gname] = _gcounties
        drawing = _render_map(
            state_gdf,
            _current_selected(state_gdf),
            groups_for_state=_groups_this_state,
        )

    # ── Post-map: process drawing, then populate left-column placeholders
    # If user drew something new, recompute selection
    if drawing is not None:
        sel = _counties_inside_drawing(state_gdf, drawing)
        st.session_state["rb_current_selection"] = sel
        st.session_state["rb_current_state"] = selected_state

    # If user switched states, clear the current (not-yet-committed) selection
    if st.session_state.get("rb_current_state") != selected_state:
        st.session_state["rb_current_selection"] = []
        st.session_state["rb_current_state"] = selected_state

    selected = st.session_state.get("rb_current_selection", [])

    # ── Fill the Selected-counties placeholder ───────────────────
    with sel_placeholder:
        st.markdown("**Selected counties**")
        if not selected:
            st.caption("Draw a polygon on the map to select counties.")
        else:
            st.success(f"{len(selected)} counties selected")
            with st.expander("Show list", expanded=False):
                st.write(", ".join(selected))
            # Group name input + Add button — stacked vertically since
            # the column is narrow. Add disabled until name entered.
            group_name = st.text_input(
                "Group name",
                value="",
                placeholder=f"e.g. South {selected_state}",
                key="rb_group_name",
                label_visibility="collapsed",
            )
            add_clicked = st.button(
                "➕ Add to groups", type="primary",
                use_container_width=True,
                disabled=not (group_name and group_name.strip()),
            )
            if add_clicked:
                name = group_name.strip()
                if name in st.session_state["rb_groups"]:
                    st.warning(
                        f"Group **{name}** already exists. "
                        "Delete it first."
                    )
                else:
                    # Compute the region's center from the selected
                    # counties — eyeballed-by-user becomes
                    # mathematically-precise. Stored alongside the
                    # county list so consumers (well_map's auto-zoom)
                    # can navigate to the region without recomputing.
                    center = _compute_region_center(state_gdf, selected)
                    st.session_state["rb_groups"][name] = (
                        selected_state, list(selected), center
                    )
                    # Clear selection so user can start the next group
                    st.session_state["rb_current_selection"] = []
                    st.session_state.pop("rb_group_name", None)
                    st.rerun()

    # ── Fill the Groups placeholder ──────────────────────────────
    groups = st.session_state["rb_groups"]
    with _groups_placeholder:
        if not groups:
            st.caption(
                "No groups yet. Lasso counties above, name the group, "
                "and click *Add to groups*."
            )
        else:
            for idx, (name, value) in enumerate(list(groups.items())):
                # Length-agnostic unpacking: 3-tuple (new) carries
                # (state, counties, center); 2-tuple (legacy) is
                # (state, counties). The display doesn't need the
                # center — only state and counties.
                state = value[0]
                counties_list = value[1]
                # Color index reflects the same per-state ordering
                # used by _render_map, so swatch matches map color.
                same_state_idx = sum(
                    1 for nm, v in list(groups.items())[:idx]
                    if v[0] == state
                )
                color = _color_for_group(same_state_idx)
                with st.expander(
                    f"{name}  ({state}, {len(counties_list)})",
                    expanded=False,
                ):
                    col_sw, col_b = st.columns([1, 2])
                    with col_sw:
                        st.markdown(
                            f"<div style='width:20px;height:20px;"
                            f"background:{color};border-radius:3px;"
                            f"border:1px solid #333;display:inline-block;'>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    with col_b:
                        if st.button(
                            "🗑 Delete", key=f"rb_del_{name}",
                            use_container_width=True,
                        ):
                            del st.session_state["rb_groups"][name]
                            st.rerun()
                    st.caption(", ".join(counties_list))

    # ── Fill the Export placeholder ──────────────────────────────
    with _export_placeholder:
        if groups:
            st.divider()
            st.markdown("**Export**")
            code = _format_export(groups)

            # Download is the trustworthy export path — produces an
            # actual file the browser saves with no clipboard API
            # involvement. Use it as the primary export.
            st.download_button(
                "💾 Download state_regions.py",
                data=code.encode("utf-8"),
                file_name="state_regions.py",
                mime="text/x-python",
                type="primary",
                use_container_width=True,
            )

            # Copy button as a secondary path. Code string is injected
            # into a JS const (not an HTML attribute) to avoid the
            # attribute-quote-escaping problem that broke v2.
            import json as _json
            _code_json = _json.dumps(code)
            _copy_html = """
            <button id="rb-copy-btn"
                style="
                    width: 100%;
                    padding: 0.5rem 1rem;
                    background: #f0f2f6;
                    border: 1px solid #cbd5e1;
                    border-radius: 0.5rem;
                    cursor: pointer;
                    font-size: 0.875rem;
                    color: #1e293b;
                    font-family: 'Source Sans Pro', sans-serif;
                ">
                📋 Copy to clipboard
            </button>
            <script>
                (function() {
                    const code = __CODE_JSON__;
                    const btn = document.getElementById('rb-copy-btn');
                    if (!btn) return;
                    btn.addEventListener('click', function() {
                        navigator.clipboard.writeText(code).then(
                            function() {
                                btn.textContent = '\u2713 Copied!';
                                btn.style.background = '#10b981';
                                btn.style.color = '#ffffff';
                                setTimeout(function() {
                                    btn.textContent =
                                        '📋 Copy to clipboard';
                                    btn.style.background = '#f0f2f6';
                                    btn.style.color = '#1e293b';
                                }, 2000);
                            },
                            function(err) {
                                btn.textContent = '\u2717 Copy failed';
                                btn.style.background = '#ef4444';
                                btn.style.color = '#ffffff';
                            }
                        );
                    });
                })();
            </script>
            """.replace("__CODE_JSON__", _code_json)
            from streamlit.components.v1 import html as _html
            _html(_copy_html, height=50)

            with st.expander("Preview code", expanded=False):
                st.code(code, language="python")

    # ── Help ─────────────────────────────────────────────────────
    with st.expander("How Region Builder works", expanded=False):
        st.markdown(
            "**Workflow:**\n"
            "1. Pick a state. The map shows that state's counties.\n"
            "2. Click the polygon or rectangle tool on the map and "
            "draw around the counties you want grouped.\n"
            "3. Counties whose centroid is inside your shape get "
            "highlighted in teal.\n"
            "4. Name the group, click **Add to groups**.\n"
            "5. The map clears; repeat for the next group.\n"
            "6. When you're done, copy the exported Python dict into "
            "`state_regions.py` at V3's project root.\n\n"
            "**Selection semantics:**\n"
            "- A county is included if its **centroid** falls inside "
            "the polygon you draw.\n"
            "- Counties touched but not fully covered are decided by "
            "where their centroid sits.\n"
            "- If you grab the wrong counties, click the trash icon on "
            "the drawn shape and redraw.\n\n"
            "**Persistence:**\n"
            "- Groups live in session state. Reload the page → groups "
            "are gone. Always export before closing.\n"
            "- The exported dict is a paste-into-a-file deliverable. "
            "Future work: write directly to a `dv_state_region` table."
        )


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _current_selected(state_gdf) -> set[str]:
    """Set of county names currently selected (not yet committed to
    a group). Restricted to the active state — switching states
    clears the visible selection."""
    sel = st.session_state.get("rb_current_selection", [])
    cur_state = st.session_state.get("rb_current_state")
    if state_gdf.empty:
        return set()
    if cur_state and cur_state != state_gdf["state"].iloc[0]:
        return set()
    return set(sel)

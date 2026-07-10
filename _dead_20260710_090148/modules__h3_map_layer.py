"""
modules/h3_map_layer.py
=======================
Render an H3 density grid as a colored Folium layer for page_well_map.

Two ways to get the cell counts:

  A) Aggregate dv_well directly (uses modules.h3_grids.build_density_grid).
     Simplest — no dependency on the view's column names.

  B) Read your existing dataview_federation.v_well_density_rN view.
     Reuses the live-aggregating views. Tell it which columns hold the
     cell id and the count (defaults guess 'h3'/'cell' and 'n'/'well_count').

Either way the polygons are built in Python from the H3 cell ids, because
SQL Express can't compute hexagon geometry.

    from modules.h3_map_layer import add_h3_density_layer
    add_h3_density_layer(fmap, S.engine, resolution=6)            # mode A
    add_h3_density_layer(fmap, S.engine, resolution=6,
                         view="dataview_federation.v_well_density_r6")  # mode B
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from sqlalchemy import text

from modules.h3_grids import (build_density_grid, cell_counts_to_geojson,
                              RESOLUTIONS)

# Blue → green → yellow → orange → red, matching the WranglerView heatmap feel.
_PALETTE = ["#2b83ba", "#abdda4", "#ffffbf", "#fdae61", "#d7191c"]


def _counts_from_view(engine, view: str,
                      cell_col: Optional[str], count_col: Optional[str]) -> pd.DataFrame:
    """Read cell + count from a density view, guessing column names if not given."""
    with engine.connect() as conn:
        df = pd.read_sql(text(f"SELECT * FROM {view}"), conn)
    lc = {c.lower(): c for c in df.columns}
    cell = cell_col or next((lc[k] for k in ("h3", "cell", "h3_cell") if k in lc), None)
    cnt  = count_col or next((lc[k] for k in ("n", "well_count", "cnt", "count") if k in lc), None)
    if cell is None or cnt is None:
        raise ValueError(
            f"Could not find cell/count columns in {view}; columns are "
            f"{list(df.columns)}. Pass cell_col=/count_col= explicitly.")
    return df[[cell, cnt]].rename(columns={cell: "cell", cnt: "n"})


def add_h3_density_layer(fmap, engine, resolution: int = 6,
                         where: Optional[str] = None,
                         view: Optional[str] = None,
                         cell_col: Optional[str] = None,
                         count_col: Optional[str] = None,
                         schema: str = "dataview",
                         table: str = "dv_well",
                         name: Optional[str] = None,
                         fill_opacity: float = 0.6,
                         show_legend: bool = True):
    """Add an H3 density choropleth to a Folium map. Returns the GeoJSON
    FeatureCollection (or None if there are no cells to draw)."""
    import folium
    import branca.colormap as bcm

    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution must be one of {RESOLUTIONS}")

    if view:
        counts = _counts_from_view(engine, view, cell_col, count_col)
        fc = cell_counts_to_geojson(counts)
    else:
        fc = build_density_grid(engine, resolution, schema, table, where)

    if not fc["features"]:
        return None

    vals = [f["properties"]["count"] for f in fc["features"]]
    vmin, vmax = min(vals), max(vals)
    if vmin == vmax:                      # avoid a degenerate colormap
        vmax = vmin + 1
    cmap = bcm.LinearColormap(
        _PALETTE, vmin=vmin, vmax=vmax,
        caption=f"Wells per H3 r{resolution} cell")

    folium.GeoJson(
        fc,
        name=name or f"Density r{resolution}",
        style_function=lambda feat: {
            "fillColor": cmap(feat["properties"]["count"]),
            "color": "#2226",
            "weight": 0.5,
            "fillOpacity": fill_opacity,
        },
        highlight_function=lambda _f: {"weight": 2, "color": "#111"},
        tooltip=folium.GeoJsonTooltip(
            fields=["h3", "count"], aliases=["Cell", "Wells"]),
    ).add_to(fmap)

    if show_legend:
        cmap.add_to(fmap)
    return fc

"""
page_well_documents.py
=====================
"Documents on the map" view.

  * Only wells that HAVE documents are dotted on the map. Files come from
    file_catalog.GLOBAL_FILE_CATALOG; the well key (UWI14), name and coordinates
    come from file_catalog.FILE_WELL_HEADER, joined on INVENTORY_ID. Coordinates
    live on the header, so a well shows as soon as it's cataloged — no promote
    needed.
  * Select wells three ways: draw a rectangle/polygon (multi-select), click a
    single dot, or pick from the dropdown fallback.
  * The selected wells' documents appear in a TABLE below the map, with an
    Open hyperlink per row. Because browsers block file:// links on many setups,
    a version-safe "open this file" picker below the table launches the chosen
    document in its native app (local) or downloads it.

Defensive: column names on both tables are discovered at runtime.
"""
from __future__ import annotations
import os
import sys
import subprocess

GFC = "file_catalog.GLOBAL_FILE_CATALOG"   # the files
FWH = "file_catalog.FILE_WELL_HEADER"      # per-file well header (UWI14, coords)
DOC_EXTS = ('.pdf', '.docx', '.doc', '.txt', '.rtf', '.md', '.html', '.htm',
            '.xlsx', '.xls', '.csv', '.tif', '.tiff', '.png', '.jpg', '.jpeg')


# ── column discovery ────────────────────────────────────────────────────────

def _columns(engine, schema, table):
    from sqlalchemy import text
    q = ("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
         "WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t")
    with engine.connect() as con:
        return {r[0].lower(): r[0] for r in con.execute(text(q),
                                                        {"s": schema, "t": table})}


def _pick(cols: dict, *candidates):
    for c in candidates:
        if c.lower() in cols:
            return cols[c.lower()]
    return None


# ── geometry: point-in-polygon (ray casting on the exterior ring) ────────────

def _poly_contains(rings, lon, lat):
    try:
        ring = rings[0]
    except Exception:
        return False
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and \
           (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


# ── data ────────────────────────────────────────────────────────────────────

def _wells_with_docs(engine, c):
    """One row per well that has documents: uwi, name, field, state, coords, count."""
    from sqlalchemy import text
    import pandas as pd
    ext_filter = ""
    if c["ext"]:
        vals = ", ".join("'" + e + "'" for e in DOC_EXTS)
        ext_filter = f"AND LOWER(g.[{c['ext']}]) IN ({vals})"
    sel_name  = f"MAX(h.[{c['wname']}])" if c["wname"] else "NULL"
    sel_field = f"MAX(h.[{c['field']}])" if c["field"] else "NULL"
    sel_state = f"MAX(h.[{c['state']}])" if c["state"] else "NULL"
    sel_lat   = f"AVG(TRY_CAST(h.[{c['lat']}] AS float))" if c["lat"] else "NULL"
    sel_lon   = f"AVG(TRY_CAST(h.[{c['lon']}] AS float))" if c["lon"] else "NULL"
    sql = f"""
        SELECT h.[{c['uwi']}] AS uwi,
               {sel_name}  AS well_name,
               {sel_field} AS field_name,
               {sel_state} AS province_state,
               {sel_lat}   AS lat,
               {sel_lon}   AS lon,
               COUNT(*)    AS n_files
          FROM {GFC} g
          JOIN {FWH} h ON h.[{c['inv_h']}] = g.[{c['inv_g']}]
         WHERE NULLIF(LTRIM(RTRIM(h.[{c['uwi']}])),'') IS NOT NULL
               {ext_filter}
         GROUP BY h.[{c['uwi']}]
    """
    with engine.connect() as con:
        out = pd.read_sql(text(sql), con)
    out["well_name"] = out["well_name"].fillna(out["uwi"])
    return out.sort_values(["uwi", "well_name"]).reset_index(drop=True)


def _documents_for(engine, uwis, c):
    """Documents for a list of UWIs, with the well name on each row.

    The path we hand back prefers the governed VAULT copy and falls back to the
    original network FILE_PATH only when a file hasn't been vaulted yet.
    """
    from sqlalchemy import text
    import pandas as pd
    uwis = [str(u) for u in uwis if u]
    if not uwis:
        return pd.DataFrame(columns=["uwi", "well_name", "file_name", "file_path",
                                     "file_ext", "doc_type", "readiness", "loc",
                                     "inventory_id", "catalog_status"])
    # path: COALESCE(vault, network); loc: where that path points
    if c["vault"] and c["path"]:
        path_sel = (f"COALESCE(NULLIF(g.[{c['vault']}],''), g.[{c['path']}]) "
                    "AS file_path")
        loc_sel = (f"CASE WHEN NULLIF(g.[{c['vault']}],'') IS NOT NULL "
                   "THEN 'vault' ELSE 'network' END AS loc")
    elif c["vault"]:
        path_sel, loc_sel = f"g.[{c['vault']}] AS file_path", "'vault' AS loc"
    elif c["path"]:
        path_sel, loc_sel = f"g.[{c['path']}] AS file_path", "'network' AS loc"
    else:
        path_sel, loc_sel = "NULL AS file_path", "'?' AS loc"
    sels = [f"h.[{c['uwi']}] AS uwi"]
    sels.append(f"h.[{c['wname']}] AS well_name" if c["wname"] else "NULL AS well_name")
    sels.append(f"g.[{c['name']}] AS file_name"  if c["name"]  else "NULL AS file_name")
    sels.append(path_sel)
    sels.append(loc_sel)
    sels.append(f"g.[{c['ext']}] AS file_ext"    if c["ext"]   else "NULL AS file_ext")
    sels.append(f"g.[{c['type']}] AS doc_type"   if c["type"]  else "NULL AS doc_type")
    sels.append(f"g.[{c['ready']}] AS readiness" if c["ready"] else "NULL AS readiness")
    sels.append(f"g.[{c['inv_g']}] AS inventory_id" if c["inv_g"] else "NULL AS inventory_id")
    sels.append(f"g.[{c['status']}] AS catalog_status" if c.get("status") else "NULL AS catalog_status")
    ph = ", ".join(f":u{i}" for i in range(len(uwis)))
    params = {f"u{i}": u for i, u in enumerate(uwis)}
    order = "ORDER BY uwi" + (f", g.[{c['name']}]" if c["name"] else "")
    sql = (f"SELECT {', '.join(sels)} FROM {GFC} g "
           f"JOIN {FWH} h ON h.[{c['inv_h']}] = g.[{c['inv_g']}] "
           f"WHERE h.[{c['uwi']}] IN ({ph}) {order}")
    with engine.connect() as con:
        return pd.read_sql(text(sql), con, params=params)


# ── open ─────────────────────────────────────────────────────────────────────

def _open_native(path):
    """Open a file in its native app on the machine running Streamlit (local)."""
    try:
        if os.name == "nt":
            os.startfile(path)                       # noqa: Windows only
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return None
    except Exception as e:
        return str(e)


def _viewer_exts():
    """Extensions the in-app file_viewer explicitly handles. Pulled from the
    viewer's own constants so this never drifts from what it can actually show;
    falls back to a static list if the module/structure changes."""
    try:
        try:
            from modules import file_viewer as fv
        except ImportError:
            from dataview.file_catalog import file_viewer as fv
        s = set()
        for nm in ("PDF_EXTS", "LAS_EXTS", "DLIS_EXTS", "LIS_EXTS", "SEGY_EXTS",
                   "P190_EXTS", "SHP_EXTS", "EXCEL_EXTS", "CSV_EXTS", "WORD_EXTS",
                   "IMAGE_EXTS"):
            s |= set(getattr(fv, nm, set()) or set())
        out = {str(e).lower().lstrip(".") for e in s}
        if out:
            return out
    except Exception:
        pass
    return {"pdf", "las", "dlis", "dlf", "dis", "lis", "segy", "sgy", "seg",
            "p190", "p90", "p1", "shp", "geojson", "gpkg", "kml", "kmz",
            "xlsx", "xls", "xlsm", "csv", "tsv", "docx", "doc",
            "tif", "tiff", "png", "jpg", "jpeg"}


def _drawn_bbox(polys):
    """Bounding box (min_lat, max_lat, min_lon, max_lon) of all drawn shapes."""
    lats, lons = [], []
    for rings in polys:
        try:
            for pt in rings[0]:           # exterior ring, [lon, lat] pairs
                lons.append(float(pt[0]))
                lats.append(float(pt[1]))
        except Exception:
            continue
    if not lats:
        return None
    return (min(lats), max(lats), min(lons), max(lons))


def _qry_seismic_segy(engine):
    """Seismic LINES backed by a real SEG-Y file — one row per header,
    ordered survey -> line so the page can group by survey."""
    from sqlalchemy import text
    import pandas as pd
    cols = ["survey_name", "line_name", "set_type", "contractor",
            "file_name", "file_path",
            "bmin_lat", "bmax_lat", "bmin_lon", "bmax_lon"]
    try:
        with engine.connect() as con:
            return pd.read_sql(text("""
                SELECT sh.SURVEY_NAME    AS survey_name,
                       sh.LINE_NAME      AS line_name,
                       sh.SEIS_SET_TYPE  AS set_type,
                       sh.CONTRACTOR     AS contractor,
                       fc.FILE_NAME      AS file_name,
                       fc.FILE_PATH      AS file_path,
                       sh.BBOX_MIN_LAT   AS bmin_lat,
                       sh.BBOX_MAX_LAT   AS bmax_lat,
                       sh.BBOX_MIN_LON   AS bmin_lon,
                       sh.BBOX_MAX_LON   AS bmax_lon
                  FROM file_catalog.FILE_SEIS_HEADER sh
                  JOIN file_catalog.GLOBAL_FILE_CATALOG fc
                       ON fc.INVENTORY_ID = sh.INVENTORY_ID
                 WHERE LOWER(fc.FILE_EXT) IN
                       ('.segy', 'segy', '.sgy', 'sgy', '.seg', 'seg')
                 ORDER BY sh.SURVEY_NAME, sh.LINE_NAME
            """), con)
    except Exception:
        return pd.DataFrame(columns=cols)


def seismic_2d_zones(engine, pad_deg=0.02):
    """One rough 'coverage zone' polygon per 2D survey, hulled from its line
    bboxes and softened so it reads as deliberately approximate."""
    from sqlalchemy import text
    import pandas as pd
    try:
        from shapely.geometry import MultiPoint
    except ImportError:
        return []
    try:
        with engine.connect() as con:
            df = pd.read_sql(text("""
                SELECT SURVEY_NAME AS survey,
                       TRY_CAST(BBOX_MIN_LAT AS FLOAT) AS mnla,
                       TRY_CAST(BBOX_MAX_LAT AS FLOAT) AS mxla,
                       TRY_CAST(BBOX_MIN_LON AS FLOAT) AS mnlo,
                       TRY_CAST(BBOX_MAX_LON AS FLOAT) AS mxlo
                  FROM file_catalog.FILE_SEIS_HEADER
                 WHERE SEIS_SET_TYPE = '2D'
                   AND TRY_CAST(BBOX_MIN_LAT AS FLOAT) IS NOT NULL
                   AND TRY_CAST(BBOX_MIN_LON AS FLOAT) IS NOT NULL
                   AND TRY_CAST(BBOX_MAX_LAT AS FLOAT) IS NOT NULL
                   AND TRY_CAST(BBOX_MAX_LON AS FLOAT) IS NOT NULL
            """), con)
    except Exception:
        return []
    zones = []
    for survey, gp in df.groupby("survey", sort=False):
        pts = []
        for r in gp.itertuples():
            pts += [(r.mnlo, r.mnla), (r.mnlo, r.mxla),
                    (r.mxlo, r.mxla), (r.mxlo, r.mnla)]
        try:
            hull = MultiPoint(pts).convex_hull.buffer(pad_deg)
        except Exception:
            continue
        if not hasattr(hull, "exterior") or hull.exterior is None:
            continue                                  # degenerate (single point)
        cen = hull.centroid
        zones.append({"survey": survey or "(unnamed)", "n_lines": len(gp),
                      "ring": [[y, x] for x, y in hull.exterior.coords],
                      "centroid": [cen.y, cen.x]})
    return zones


def seismic_3d_footprints(engine):
    """One bbox rectangle per 3D survey that is backed by a real SEG-Y file.
    3D footprints are real areal patches, so the stored bbox IS the footprint
    — no hull, just the rectangle."""
    from sqlalchemy import text
    import pandas as pd
    try:
        with engine.connect() as con:
            df = pd.read_sql(text("""
                SELECT sh.SURVEY_NAME AS survey,
                       MIN(TRY_CAST(sh.BBOX_MIN_LAT AS FLOAT)) AS mnla,
                       MAX(TRY_CAST(sh.BBOX_MAX_LAT AS FLOAT)) AS mxla,
                       MIN(TRY_CAST(sh.BBOX_MIN_LON AS FLOAT)) AS mnlo,
                       MAX(TRY_CAST(sh.BBOX_MAX_LON AS FLOAT)) AS mxlo,
                       COUNT(*) AS n
                  FROM file_catalog.FILE_SEIS_HEADER sh
                  JOIN file_catalog.GLOBAL_FILE_CATALOG fc
                       ON fc.INVENTORY_ID = sh.INVENTORY_ID
                 WHERE sh.SEIS_SET_TYPE = '3D'
                   AND LOWER(fc.FILE_EXT) IN
                       ('.segy', 'segy', '.sgy', 'sgy', '.seg', 'seg')
                   AND TRY_CAST(sh.BBOX_MIN_LAT AS FLOAT) IS NOT NULL
                   AND TRY_CAST(sh.BBOX_MIN_LON AS FLOAT) IS NOT NULL
                   AND TRY_CAST(sh.BBOX_MAX_LAT AS FLOAT) IS NOT NULL
                   AND TRY_CAST(sh.BBOX_MAX_LON AS FLOAT) IS NOT NULL
                 GROUP BY sh.SURVEY_NAME
            """), con)
    except Exception:
        return []
    out = []
    for r in df.itertuples():
        try:
            mnla, mxla = float(r.mnla), float(r.mxla)
            mnlo, mxlo = float(r.mnlo), float(r.mxlo)
        except (TypeError, ValueError):
            continue
        if mnla == mxla and mnlo == mxlo:
            continue                                  # zero-area point
        ring = [[mnla, mnlo], [mnla, mxlo], [mxla, mxlo],
                [mxla, mnlo], [mnla, mnlo]]
        out.append({"survey": r.survey or "(unnamed)", "n_lines": int(r.n),
                    "ring": ring,
                    "centroid": [(mnla + mxla) / 2.0, (mnlo + mxlo) / 2.0]})
    return out



def _qry_seismic_in_bbox(engine, mn_lat, mx_lat, mn_lon, mx_lon):
    """2D + 3D seismic surveys whose stored bbox OVERLAPS the drawn box.

    We only have each survey's bounding box (3D footprints are real rectangles;
    2D lines store just the box around the line, not the path). So 'intersects
    the box' is an axis-aligned bbox-overlap test. For 3D that's exact; for 2D
    it's an over-match (the line is somewhere in its box), which is the honest
    best with bbox-only geometry.
    """
    from sqlalchemy import text
    import pandas as pd
    cols = ["id", "set_type", "survey_name", "line_name", "contractor",
            "survey_date", "shot_first", "shot_last", "file_name", "file_path"]
    try:
        with engine.connect() as con:
            return pd.read_sql(text("""
                SELECT sh.SEIS_HEADER_ID AS id, sh.SEIS_SET_TYPE AS set_type,
                       sh.SURVEY_NAME AS survey_name, sh.LINE_NAME AS line_name,
                       sh.CONTRACTOR AS contractor, sh.SURVEY_DATE AS survey_date,
                       sh.SHOT_FIRST AS shot_first, sh.SHOT_LAST AS shot_last,
                       fc.FILE_NAME AS file_name, fc.FILE_PATH AS file_path
                  FROM file_catalog.FILE_SEIS_HEADER sh
                  LEFT JOIN file_catalog.GLOBAL_FILE_CATALOG fc
                         ON fc.INVENTORY_ID = sh.INVENTORY_ID
                 WHERE sh.SEIS_SET_TYPE IN ('2D', '3D')
                   AND TRY_CAST(sh.BBOX_MIN_LAT AS FLOAT) IS NOT NULL
                   AND TRY_CAST(sh.BBOX_MAX_LAT AS FLOAT) IS NOT NULL
                   AND TRY_CAST(sh.BBOX_MIN_LON AS FLOAT) IS NOT NULL
                   AND TRY_CAST(sh.BBOX_MAX_LON AS FLOAT) IS NOT NULL
                   AND TRY_CAST(sh.BBOX_MAX_LAT AS FLOAT) >= :mnlat
                   AND TRY_CAST(sh.BBOX_MIN_LAT AS FLOAT) <= :mxlat
                   AND TRY_CAST(sh.BBOX_MAX_LON AS FLOAT) >= :mnlon
                   AND TRY_CAST(sh.BBOX_MIN_LON AS FLOAT) <= :mxlon
                 ORDER BY sh.SEIS_SET_TYPE, sh.SURVEY_NAME, sh.LINE_NAME
            """), con, params={"mnlat": mn_lat, "mxlat": mx_lat,
                               "mnlon": mn_lon, "mxlon": mx_lon})
    except Exception:
        return pd.DataFrame(columns=cols)


# ── page ────────────────────────────────────────────────────────────────────

def run(engine, dialect=None):
    import streamlit as st
    import pandas as pd
    from pathlib import Path

    dlct = dialect or getattr(getattr(engine, "dialect", None), "name", None)

    top = st.columns([6, 1.2])
    top[0].subheader("📂 Well Documents")
    if top[1].button("🔄 Refresh", use_container_width=True,
                     help="Reload from the catalog — use after adding new data"):
        try:
            st.cache_data.clear()
        except Exception:
            pass
        st.rerun()
    st.caption("Only wells that have documents are shown. Click a dot or use the "
               "dropdown to pick a well; SEG-Y seismic surveys are listed below "
               "the map.")

    g = _columns(engine, "file_catalog", "GLOBAL_FILE_CATALOG")
    h = _columns(engine, "file_catalog", "FILE_WELL_HEADER")
    c = {
        "inv_g": _pick(g, "INVENTORY_ID"),
        "inv_h": _pick(h, "INVENTORY_ID"),
        "uwi":   _pick(h, "UWI14", "UWI"),
        "name":  _pick(g, "FILE_NAME", "FILENAME", "NAME"),
        "path":  _pick(g, "FILE_PATH", "FILEPATH", "PATH"),
        "vault": _pick(g, "VAULT_PATH"),
        "ext":   _pick(g, "FILE_EXT", "EXTENSION", "EXT"),
        "type":  _pick(g, "DOC_TYPE"),
        "ready": _pick(g, "CATALOG_READINESS", "READINESS"),
        "status": _pick(g, "CATALOG_STATUS", "CATALOG_READINESS"),
        "wname": _pick(h, "WELL_NAME"),
        "field": _pick(h, "FIELD_NAME"),
        "state": _pick(h, "PROVINCE_STATE", "STATE"),
        "lat":   _pick(h, "SURFACE_LATITUDE", "LATITUDE", "LAT"),
        "lon":   _pick(h, "SURFACE_LONGITUDE", "LONGITUDE", "LON"),
    }
    if not (c["uwi"] and c["inv_g"] and c["inv_h"]):
        st.error("Could not locate the FILE_WELL_HEADER ↔ GLOBAL_FILE_CATALOG "
                 "link (UWI14 / INVENTORY_ID).")
        return

    wells = _wells_with_docs(engine, c)
    if wells.empty:
        st.info("No documents with a well (UWI) found in the catalog yet.")
        return

    # ── field / state filters ────────────────────────────────────────────────
    fc1, fc2 = st.columns(2)
    with fc1:
        fields = ["(all fields)"] + sorted(
            str(x) for x in wells["field_name"].dropna().unique())
        f_sel = st.selectbox("Field", fields)
    with fc2:
        states = ["(all states)"] + sorted(
            str(x) for x in wells["province_state"].dropna().unique())
        s_sel = st.selectbox("State", states)
    if f_sel != "(all fields)":
        wells = wells[wells["field_name"] == f_sel]
    if s_sel != "(all states)":
        wells = wells[wells["province_state"] == s_sel]
    if wells.empty:
        st.info("No wells with documents match that filter.")
        return

    mapped = wells.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    st.write(f"**{len(wells):,}** well(s) with documents · "
             f"**{int(wells['n_files'].sum()):,}** file(s) · "
             f"{len(mapped):,} plotted.")
    show_zones = st.checkbox(
        "Show seismic coverage (2D zones + 3D footprints)", value=False,
        help="Amber blobs = roughly where each 2D survey sits; teal rectangles "
             "= 3D survey footprints. These ignore the well filters above "
             "(seismic isn't well-bound).")

    # ── map (click a dot to pick a well) ────────────────────────────────────
    click_uwi = None
    drawn = None
    if not mapped.empty:
        import folium
        from streamlit_folium import st_folium
        m = folium.Map(tiles="CartoDB positron")
        all_lats = list(mapped["lat"])
        all_lons = list(mapped["lon"])
        for r in mapped.itertuples():
            folium.CircleMarker(
                location=[r.lat, r.lon], radius=6,
                color="#1A3A6A", fill=True, fill_color="#2E75B6",
                fill_opacity=0.85, weight=1,
                tooltip=folium.Tooltip(
                    f"<b>{r.well_name}</b><br>{r.uwi}<br>"
                    f"{int(r.n_files)} file(s)"),
                popup=folium.Popup(str(r.uwi), max_width=200),
            ).add_to(m)
        n_zones = n_foot = 0
        if show_zones:
            _zones = seismic_2d_zones(engine)
            _foot = seismic_3d_footprints(engine)
            n_zones, n_foot = len(_zones), len(_foot)
            if not _zones and not _foot:
                st.caption("No seismic coverage to show — need 2D/3D rows in "
                           "FILE_SEIS_HEADER with a stored bbox (and shapely "
                           "installed for the 2D zones).")
            for z in _zones:
                folium.Polygon(
                    locations=z["ring"], color="#8A5A00", weight=1,
                    fill=True, fill_color="#E0A030", fill_opacity=0.15,
                    tooltip=folium.Tooltip(
                        f"<b>📈 2D seismic</b><br>{z['survey']}<br>"
                        f"{z['n_lines']} line(s)"),
                    popup=folium.Popup(
                        f"<b>📈 2D seismic survey</b><br>"
                        f"<b>{z['survey']}</b><br>{z['n_lines']} line(s)",
                        max_width=260),
                ).add_to(m)
                for la, lo in z["ring"]:
                    all_lats.append(la)
                    all_lons.append(lo)
            for f in _foot:
                folium.Polygon(
                    locations=f["ring"], color="#0E6E6E", weight=2,
                    fill=True, fill_color="#19A0A0", fill_opacity=0.18,
                    tooltip=folium.Tooltip(
                        f"<b>▦ 3D footprint</b><br>{f['survey']}<br>"
                        f"{f['n_lines']} file(s)"),
                    popup=folium.Popup(
                        f"<b>▦ 3D seismic footprint</b><br>"
                        f"<b>{f['survey']}</b><br>{f['n_lines']} file(s)",
                        max_width=260),
                ).add_to(m)
                for la, lo in f["ring"]:
                    all_lats.append(la)
                    all_lons.append(lo)
        # frame everything we drew, so off-screen zones can't hide
        if all_lats and all_lons:
            m.fit_bounds([[min(all_lats), min(all_lons)],
                          [max(all_lats), max(all_lons)]])
        if n_zones or n_foot:
            st.caption(f"{n_zones} 2D zone(s) · {n_foot} 3D footprint(s) drawn — "
                       "map zoomed to include them.")
        # Draw control: a rectangle/polygon selects every well (and seismic
        # survey) inside it — the multi-select the page intends.
        from folium.plugins import Draw
        Draw(export=False,
             draw_options={"polyline": False, "circle": False,
                           "circlemarker": False, "marker": False,
                           "rectangle": True, "polygon": True},
             edit_options={"edit": False}).add_to(m)
        sd = st_folium(m, height=480, use_container_width=True,
                       returned_objects=["last_object_clicked_popup",
                                         "all_drawings"])
        sd = sd or {}
        if sd.get("last_object_clicked_popup"):
            click_uwi = str(sd["last_object_clicked_popup"]).strip()
        drawn = sd.get("all_drawings")
        # TEMP debug: see exactly what the map returns (remove once working)
        with st.expander("🐞 map return (debug)", expanded=False):
            st.write({"has_drawings": bool(drawn),
                      "n_drawings": len(drawn) if drawn else 0,
                      "clicked_popup": sd.get("last_object_clicked_popup")})
            if drawn:
                st.json(drawn)

    # Resolve the drawn shape to a bbox ONCE, here, so everything below (the
    # seismic list AND the well selection) is constrained to the same drawn area.
    draw_bbox = None
    if drawn:
        _rings = []
        for _feat in drawn:
            try:
                _geom = _feat.get("geometry", {})
                if _geom.get("type") == "Polygon":
                    _rings.append(_geom["coordinates"])
            except Exception:
                continue
        draw_bbox = _drawn_bbox(_rings) if _rings else None

    # ── seismic surveys backed by a real SEG-Y file ─────────────────────────
    # Constrained to the drawn area when a shape is on the map; otherwise all.
    sg = _qry_seismic_segy(engine)
    if draw_bbox is not None and not sg.empty and "bmin_lat" in sg.columns:
        mn_lat, mx_lat, mn_lon, mx_lon = draw_bbox
        # a survey is "in the area" if its bbox OVERLAPS the drawn bbox
        sg = sg[(sg["bmin_lat"] <= mx_lat) & (sg["bmax_lat"] >= mn_lat) &
                (sg["bmin_lon"] <= mx_lon) & (sg["bmax_lon"] >= mn_lon)
                ].reset_index(drop=True)
    _scope = " in drawn area" if draw_bbox is not None else ""
    nsurv = sg["survey_name"].nunique() if not sg.empty else 0
    st.markdown(f"#### 📈 Seismic surveys (SEG-Y){_scope} — {nsurv} survey(s) · "
                f"{len(sg)} line(s)")
    if sg.empty:
        if draw_bbox is not None:
            st.caption("No SEG-Y seismic surveys fall in the drawn area.")
        else:
            st.caption("No SEG-Y-backed seismic surveys in the catalog yet.")
    else:
        k = 0
        # query is already ordered survey_name → line_name
        for survey, g in sg.groupby("survey_name", sort=False):
            set_types = "/".join(sorted({str(t) for t in g["set_type"]
                                         if t})) or "—"
            contractor = next((str(c) for c in g["contractor"] if c), "")
            label = (f"📈 {survey or '(unnamed survey)'}  ·  {set_types}"
                     f"  ·  {len(g)} line(s)")
            if contractor:
                label += f"  ·  {contractor}"
            with st.expander(label, expanded=False):
                for r in g.itertuples():
                    fp = r.file_path
                    nm = r.file_name or (os.path.basename(fp) if fp else "(line)")
                    line = str(r.line_name or "(no line name)")
                    cc = st.columns([5.6, 1.4])
                    cc[0].write(f"↳ {line}"
                                + (f"  ·  📄 {r.file_name}" if r.file_name else ""))
                    with cc[1]:
                        if st.button("View", key=f"sv_{k}",
                                     use_container_width=True):
                            ext = (os.path.splitext(nm)[1] or ".segy").lower()
                            st.session_state["docview"] = {
                                "path": fp, "name": nm, "ext": ext}
                            st.rerun()
                    k += 1

    # ── in-app viewer for LAS / LIS / DLIS / SEG-Y / docs ────────────────────
    dv = st.session_state.get("docview")
    if dv:
        st.divider()
        h1, h2 = st.columns([6, 1])
        h1.markdown(f"#### 🔬 Viewer — {dv.get('name', '')}")
        if h2.button("✕ Close", key="docview_close", use_container_width=True):
            st.session_state.pop("docview", None)
            st.rerun()
        pth = dv.get("path")
        if not pth:
            st.warning("No file path was recorded for this item in the catalog.")
        elif not os.path.exists(pth):
            st.error(f"File not found where the catalog points:\n\n`{pth}`\n\n"
                     "The path may be a network location this machine can't reach.")
        else:
            try:
                try:
                    from dataview.file_catalog.file_viewer import view as _view_file
                except ImportError:
                    from dataview.file_catalog.file_viewer import view as _view_file
                _view_file(pth, dv.get("ext"))
            except Exception as e:
                import traceback
                st.error(f"In-app viewer error: "
                         f"{str(e).splitlines()[0][:200]}")
                with st.expander("details"):
                    st.code(traceback.format_exc())
                if st.button("Open in native app instead", key="docview_native"):
                    err = _open_native(pth)
                    if err:
                        st.error(err)

    # ── resolve the selection ────────────────────────────────────────────────
    labels = {f"{r.uwi} — {r.well_name}  ({int(r.n_files)} file(s))": str(r.uwi)
              for r in wells.itertuples()}
    options = list(labels)
    uwi_to_label = {u: lab for lab, u in labels.items()}

    # keep the stored dropdown value valid
    if st.session_state.get("docwell") not in options:
        st.session_state["docwell"] = options[0] if options else None
    # sync only a NEW dot click into the dropdown. Clicks persist across reruns,
    # so without this change-guard a stale click would keep overriding whatever
    # the user picks in the dropdown — which is exactly the "dropdown does
    # nothing" bug.
    if click_uwi and click_uwi != st.session_state.get("_last_click_uwi"):
        if click_uwi in uwi_to_label:
            st.session_state["docwell"] = uwi_to_label[click_uwi]
        st.session_state["_last_click_uwi"] = click_uwi

    # ── box-select: a drawn rectangle/polygon picks every well + seismic inside
    box_uwis = []
    box_seis = None
    if draw_bbox is not None:
        mn_lat, mx_lat, mn_lon, mx_lon = draw_bbox
        inside = mapped[
            (mapped["lat"] >= mn_lat) & (mapped["lat"] <= mx_lat) &
            (mapped["lon"] >= mn_lon) & (mapped["lon"] <= mx_lon)]
        box_uwis = [str(u) for u in inside["uwi"].tolist()]
        try:
            box_seis = _qry_seismic_in_bbox(engine, mn_lat, mx_lat,
                                            mn_lon, mx_lon)
        except Exception:
            box_seis = None
        ns = 0 if box_seis is None else len(box_seis)
        st.success(f"Drawn area selects {len(box_uwis)} well(s) and "
                   f"{ns} seismic survey(s).")

    if draw_bbox is not None:
        # a box is on the map — honor it exactly, even if it selects nothing
        # (don't silently fall back to the dropdown's last well, which looks
        # like the map picked wells it didn't).
        selected = box_uwis
        if box_uwis:
            st.caption("Showing documents for the wells in the drawn area. Clear "
                       "the drawing (trash icon on the map) to go back to "
                       "single-pick.")
        else:
            st.info("The drawn area contains no wells. Drag the box over some "
                    "well dots, or clear the drawing to pick from the dropdown.")
        if box_seis is not None and len(box_seis):
            with st.expander(f"📈 Seismic in drawn area ({len(box_seis)})",
                             expanded=True):
                st.dataframe(box_seis, use_container_width=True,
                             hide_index=True)
    else:
        choice = st.selectbox("Well — pick one, or click a dot on the map",
                              options, key="docwell")
        selected = [labels[choice]]

    # ── documents table ──────────────────────────────────────────────────────
    docs = _documents_for(engine, selected, c).reset_index(drop=True)
    if c["type"] and not docs.empty:
        types = sorted(t for t in docs["doc_type"].dropna().unique())
        if types:
            picks = st.multiselect("Filter by document type", types,
                                   default=types, key="doc_type_filter")
            docs = docs[docs["doc_type"].isin(picks)].reset_index(drop=True)

    st.markdown(f"### Documents — {len(selected)} well(s) · {len(docs)} file(s)")
    if docs.empty:
        st.info("No documents for the current selection.")
        return

    MAXROWS = 500
    shown = docs.head(MAXROWS).reset_index(drop=True)
    if len(docs) > MAXROWS:
        st.warning(f"Showing the first {MAXROWS} of {len(docs)} files — narrow by "
                   f"type or draw a smaller area.")

    def _fname(n, p):
        return n or (os.path.basename(p) if p else "(unnamed)")

    # native grid (no page-wide CSS): tick the rows you want, act on them below
    grid = pd.DataFrame({
        "Open?": [False] * len(shown),
        "Well": shown["well_name"].fillna(shown["uwi"]).astype(str),
        "File": [(("📦 " if l == "vault" else "🌐 " if l == "network" else "")
                  + _fname(n, fp))
                 for l, n, fp in zip(shown["loc"], shown["file_name"],
                                     shown["file_path"])],
    })
    edited = st.data_editor(
        grid, hide_index=True, use_container_width=True, key="docgrid",
        column_config={
            "Open?": st.column_config.CheckboxColumn("Open?", default=False,
                                                     width="small"),
            "Well": st.column_config.TextColumn("Well", disabled=True),
            "File": st.column_config.TextColumn("File", disabled=True,
                                                width="large"),
        },
        disabled=["Well", "File"],
    )
    try:
        checked = [i for i, v in enumerate(edited["Open?"].tolist()) if v]
    except Exception:
        checked = []

    VIEW_EXTS = _viewer_exts()

    st.markdown("#### Open / view selected")
    if not checked:
        st.caption("Tick the rows you want. LAS / LIS / DLIS / SEG-Y open in the "
                   "in-app viewer (the File Catalog's Browse & view); documents "
                   "open in their native app. Uses the vault copy (📦) when "
                   "available, otherwise the network file (🌐).")
    else:
        for j in checked:
            d = shown.iloc[j]
            fp = d["file_path"]
            nm = _fname(d["file_name"], fp)
            tag = "📦" if d["loc"] == "vault" else "🌐"
            ext = str(d["file_ext"] or os.path.splitext(nm)[1]).lower().lstrip(".")
            is_view = ext in VIEW_EXTS
            col = st.columns([5, 1.4, 1.6])
            col[0].write(f"{tag} {d['well_name'] or d['uwi']} — {nm}")
            with col[1]:
                if st.button("View" if is_view else "Open", key=f"o_{j}",
                             use_container_width=True):
                    if is_view:
                        st.session_state["docview"] = {
                            "path": fp, "name": nm, "ext": "." + ext}
                        st.rerun()
                    elif not fp or not os.path.exists(fp):
                        st.warning(f"Not found on disk: {fp}")
                    else:
                        err = _open_native(fp)
                        if err:
                            st.error(err)
                        elif hasattr(st, "toast"):
                            st.toast(f"Opened {nm}")
                        else:
                            st.success(f"Opened {nm}")
            with col[2]:
                if fp and os.path.exists(fp):
                    try:
                        with open(fp, "rb") as fh:
                            st.download_button("Download", fh.read(), file_name=nm,
                                               key=f"d_{j}", use_container_width=True)
                    except Exception as e:
                        st.caption(f"unreadable: {str(e)[:40]}")
                else:
                    st.caption("not on disk")

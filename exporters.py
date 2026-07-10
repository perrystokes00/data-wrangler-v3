"""
exporters.py — DataView v3 result-set exporters.

One module, one registry. Every writer reads from a CANONICAL column contract,
so you map your `dataview` results-list columns to canonical names once (in
_normalize) and every format just works.

Formats:
    csv, excel, geojson, shapefile, gdb,
    petrel_header, petrel_deviation, geographix, witsml, ppdm,
    snowflake_share (action), database (action)

Two kinds of exporters:
  * FILE writers      -> write a file, return its path.  fn(df, path, surveys=...)
  * ACTION exporters  -> push to Snowflake / a DB.        fn(df, **ctx)

Survey-dependent formats (petrel_deviation, witsml) take a `surveys` DataFrame
of directional-survey stations; if it's None they export headers only.

Usage:
    import exporters
    path = exporters.export(df, "geojson", out_dir, "wells", surveys=srv_df)
    # or in Streamlit:
    exporters.render_export_ui(df, surveys=srv_df, sf_conn=conn, db_engine=eng)
"""
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pandas as pd

# ──────────────────────────────────────────────────────────────────────────
# CANONICAL COLUMN CONTRACT
# Map your results-list columns -> canonical names here. Matching is
# case-insensitive; the first source column found wins. Missing canonical
# columns come through as empty, so a partial result set still exports.
# ──────────────────────────────────────────────────────────────────────────
WELL_CANON = {
    "uwi":             ["UWI", "API_14", "API14", "WELL_ID", "WELLID", "API_WELL_NUMBER"],
    "api":             ["API_NUM", "API", "API_10", "API10", "API_NUMBER", "API_WELL_NUMBER"],
    "well_name":       ["WELL_NAME", "WELLNAME", "WELL_NM", "NAME"],
    "well_num":        ["WELL_NUM", "WELL_NO", "WELLNUM", "WELL_NUMBER", "WELL_NAME_SUFFIX"],
    "operator":        ["OPERATOR_NAME", "OPERATOR", "OPER", "CONAME", "ORG_OPER_N", "COMPANY_NAME"],
    "field":           ["FIELD_NAME", "FIELD"],
    "county":          ["COUNTY", "PARISH", "PARISH_NAM"],
    "state":           ["PROVINCE_STATE", "STATE", "ST"],
    "country":         ["COUNTRY"],
    "lat":             ["SURFACE_LATITUDE", "LATITUDE", "LAT", "WH_LAT", "SURF_LAT", "Y"],
    "lon":             ["SURFACE_LONGITUDE", "LONGITUDE", "LON", "LONG", "WH_LONG", "SURF_LON", "X"],
    "bottom_lat":      ["BOTTOM_HOLE_LATITUDE", "BOTTOM_LATITUDE", "BH_LAT", "BOTTOM_LAT"],
    "bottom_lon":      ["BOTTOM_HOLE_LONGITUDE", "BOTTOM_LONGITUDE", "BH_LON", "BH_LONG", "BOTTOM_LON"],
    "status":          ["STD_WELL_STATUS", "WELL_STATUS", "STATUS", "STATUS_CODE"],
    "type":            ["STD_WELL_TYPE", "WELL_TYPE", "TYPE", "TYPE_CODE"],
    "spud_date":       ["SPUD_DATE", "SPUD", "DT_SPUD"],
    "completion_date": ["COMPLETION_DATE", "COMP_DATE", "DT_COMP"],
    "plug_date":       ["ABANDONMENT_DATE", "PLUG_DATE", "PLUG"],
    "td":              ["FINAL_TD", "TD", "TOTAL_DEPTH", "DTD", "MEASURED_D", "BH_TOTAL_MD_FT"],
    "tvd":             ["TVD", "TRUE_VERTICAL_DEPTH", "TRUE_VERTICAL_DEPTH_FT"],
    "ground_elev":     ["GROUND_ELEVATION", "GL", "GROUND_ELEV"],
    "kb_elev":         ["KB_ELEVATION", "KB", "KB_ELEV", "RKB_FT"],
    "formation":       ["PRODUCING_FORMATION", "FORMATION", "FORMATIONS", "FORMATION_AT_TD"],
}

SURVEY_CANON = {
    "uwi": ["UWI", "API_WELL_NUMBER", "API_14", "WELL_ID", "WELLID"],
    "md":  ["MD", "MD_FT", "MEASURED_DEPTH", "DEPTH", "SURVEY_POINT_MD"],
    "inc": ["INC", "INCL", "INCLINATION", "INCLINATION_DEG", "INCL_ANG"],
    "azi": ["AZI", "AZIM", "AZIMUTH", "AZIMUTH_DEG"],
    "tvd": ["TVD", "TVD_FT", "SURVEY_POINT_TVD"],
    "ns":  ["NS", "NORTH_SOUTH", "NORTHING", "Y_OFFSET", "NS_OFFSET"],
    "ew":  ["EW", "EAST_WEST", "EASTING", "X_OFFSET", "EW_OFFSET"],
    "lat": ["SURFACE_LATITUDE", "LATITUDE", "LAT"],
    "lon": ["SURFACE_LONGITUDE", "LONGITUDE", "LON", "LONG"],
}


def _normalize(df: pd.DataFrame, canon: dict) -> pd.DataFrame:
    """Return a frame with canonical columns, filled from the first matching
    source column (case-insensitive). Missing canon columns -> empty/NA."""
    upper = {str(c).upper(): c for c in df.columns}
    out = {}
    for canon_name, aliases in canon.items():
        src = next((upper[a] for a in aliases if a in upper), None)
        out[canon_name] = df[src] if src is not None else pd.Series([None] * len(df))
    return pd.DataFrame(out)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def fetch_surveys(engine, uwis, source="onshore", batch=1000):
    """Pull directional-survey stations for the selected wells into a frame the
    survey-dependent exporters (petrel_deviation, witsml, osdu trajectory) read.

    source="onshore" -> dataview.dv_well_dir_srvy_sta (keyed by uwi)
    source="gom"     -> dataview_gom.directional_survey_point (keyed by api_well_number)

    UWIs are de-duplicated and queried in batches to stay under SQL Server's
    2100-parameter limit. Returns raw columns; _normalize() maps them to the
    SURVEY_CANON contract at export time.
    """
    from sqlalchemy import bindparam, text

    uwis = [str(u) for u in dict.fromkeys(uwis) if u is not None and str(u) != ""]
    if not uwis:
        return pd.DataFrame()

    if source == "gom":
        sql = ("SELECT api_well_number AS uwi, survey_point_md, incl_ang, azimuth, "
               "survey_point_tvd, latitude, longitude "
               "FROM dataview_gom.directional_survey_point "
               "WHERE api_well_number IN :uwis "
               "ORDER BY api_well_number, survey_point_md")
    else:
        sql = ("SELECT uwi, survey_id, station_id, md, incl, azim, tvd, "
               "ns_offset, ew_offset, surface_latitude, surface_longitude "
               "FROM dataview.dv_well_dir_srvy_sta "
               "WHERE uwi IN :uwis "
               "ORDER BY uwi, survey_id, md")

    stmt = text(sql).bindparams(bindparam("uwis", expanding=True))
    frames = []
    for i in range(0, len(uwis), batch):
        frames.append(pd.read_sql(stmt, engine, params={"uwis": uwis[i:i + batch]}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ──────────────────────────────────────────────────────────────────────────
# FILE WRITERS  (each: fn(df, path, surveys=None) -> path)
# ──────────────────────────────────────────────────────────────────────────
def to_csv(df, path, surveys=None):
    df.to_csv(path, index=False)
    return path


def _xl_engine():
    """xlsxwriter is much faster than openpyxl for writing; fall back if absent."""
    try:
        import xlsxwriter  # noqa: F401
        return "xlsxwriter"
    except Exception:
        return "openpyxl"


def to_excel(df, path, surveys=None):
    with pd.ExcelWriter(path, engine=_xl_engine()) as xl:
        df.to_excel(xl, sheet_name="Wells", index=False)
        if surveys is not None and len(surveys):
            surveys.to_excel(xl, sheet_name="Surveys", index=False)
    return path


def _point_features(w):
    feats = []
    lat, lon = _num(w["lat"]), _num(w["lon"])
    for i in range(len(w)):
        if pd.isna(lat.iloc[i]) or pd.isna(lon.iloc[i]):
            continue
        props = {k: (None if pd.isna(w[k].iloc[i]) else w[k].iloc[i])
                 for k in w.columns if k not in ("lat", "lon")}
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [float(lon.iloc[i]), float(lat.iloc[i])]},
            "properties": props,
        })
    return feats


def to_geojson(df, path, surveys=None):
    w = _normalize(df, WELL_CANON)
    fc = {"type": "FeatureCollection", "features": _point_features(w)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, default=str)
    return path


def _geodataframe(df):
    import geopandas as gpd
    from shapely.geometry import Point
    w = _normalize(df, WELL_CANON).copy()
    lat, lon = _num(w["lat"]), _num(w["lon"])
    keep = ~(lat.isna() | lon.isna())
    w = w[keep].reset_index(drop=True)
    geom = [Point(xy) for xy in zip(lon[keep], lat[keep])]
    return gpd.GeoDataFrame(w, geometry=geom, crs="EPSG:4326")


# Shapefile field names are capped at 10 chars; map canon -> short names.
_SHP_FIELDS = {
    "well_name": "WELL_NAME", "well_num": "WELL_NUM", "operator": "OPERATOR",
    "field": "FIELD", "county": "COUNTY", "state": "STATE", "country": "COUNTRY",
    "bottom_lat": "BOT_LAT", "bottom_lon": "BOT_LON", "status": "STATUS",
    "type": "TYPE", "spud_date": "SPUD_DT", "completion_date": "COMP_DT",
    "plug_date": "PLUG_DT", "td": "TD", "tvd": "TVD", "ground_elev": "GL_ELEV",
    "kb_elev": "KB_ELEV", "formation": "FORMATION", "uwi": "UWI", "api": "API",
}


def to_shapefile(df, path, surveys=None):
    gdf = _geodataframe(df).rename(columns=_SHP_FIELDS)
    gdf.to_file(path, driver="ESRI Shapefile")
    return path


def _gdb_safe(df):
    """Classic File GDB stores Int32/Float64 but not Int64 — OGR would warn and
    silently downcast Int64 to Float64. Downcast int64 columns to int32 first
    (safe for the small counts/ids we export) so they stay integers."""
    out = df.copy()
    for c in out.columns:
        if str(out[c].dtype) == "int64":
            col = out[c]
            if len(col) == 0 or int(col.abs().max()) <= 2_147_483_647:
                out[c] = col.astype("int32")
    return out


def to_gdb(df, path, surveys=None):
    gdf = _gdb_safe(_geodataframe(df).rename(columns=_SHP_FIELDS))
    gdf.to_file(path, driver="OpenFileGDB", layer="wells")
    return path


def to_petrel_header(df, path, surveys=None):
    """Petrel well-heads import: tab-delimited Well / X(lon) / Y(lat) / KB / TD.
    Maps directly in Petrel's 'Import well heads (ASCII)' column picker."""
    w = _normalize(df, WELL_CANON)
    cols = ["uwi", "well_name", "lon", "lat", "kb_elev", "td", "operator", "field"]
    hdr = ["UWI", "WELL", "X", "Y", "KB", "TD", "OPERATOR", "FIELD"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Petrel well heads — UWI WELL X(lon) Y(lat) KB TD OPERATOR FIELD\n")
        f.write("\t".join(hdr) + "\n")
        for i in range(len(w)):
            row = [("" if pd.isna(w[c].iloc[i]) else str(w[c].iloc[i])) for c in cols]
            f.write("\t".join(row) + "\n")
    return path


def to_petrel_deviation(df, path, surveys=None):
    """Petrel deviation survey ASCII: WELL  MD  INCL  AZIM, grouped per well.
    Imports via Petrel 'Well path/deviation (ASCII)'."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(_petrel_deviation_text(surveys))
    return path


# ── Petrel full-set bundle ────────────────────────────────────────────────
# A single zip of tab-delimited ASCII files, one per section, each importable
# by the matching Petrel wizard. Header + stratigraphy (tops) + directional
# survey + completions + production, so a whole well set lands in Petrel from
# one download.

def _petrel_cell(v):
    """Stringify a cell for tab-delimited ASCII; blank for nulls."""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v)


def _col_has_data(series):
    """True if a column holds at least one non-blank value across the set."""
    if series is None:
        return False
    return any(_petrel_cell(v).strip() != "" for v in series)


def _petrel_table_text(df, cols, comment, empty_msg):
    """Flat tab-delimited table. `cols` is a list of (source_col, HEADER)."""
    lines = [comment, "\t".join(h for _, h in cols)]
    if df is None or not len(df):
        lines.append(empty_msg)
        return "\n".join(lines) + "\n"
    out = pd.DataFrame()
    for src, h in cols:
        out[h] = (df[src].map(_petrel_cell) if src in df.columns
                  else [""] * len(df))
    body = out.apply(lambda r: "\t".join(r.values), axis=1).tolist()
    return "\n".join(lines + body) + "\n"


def _petrel_heads_text(df):
    if df is None or not len(df):
        return "# Petrel well heads — (no wells)\n"
    w = _normalize(df, WELL_CANON)
    # Full candidate set in the requested order. Any column that's entirely
    # blank across this well set is dropped, so onshore exports don't carry
    # empty KB/GROUND_ELEV/TVD columns while GOM exports keep them when filled.
    candidates = [
        ("uwi", "UWI"), ("well_name", "WELL"), ("api", "API"),
        ("lon", "X"), ("lat", "Y"), ("kb_elev", "KB"),
        ("ground_elev", "GROUND_ELEV"), ("td", "TD"), ("tvd", "TVD"),
        ("operator", "OPERATOR"), ("field", "FIELD"), ("county", "COUNTY"),
        ("state", "STATE"), ("type", "TYPE"), ("status", "STATUS"),
        ("spud_date", "SPUD_DATE"), ("completion_date", "COMP_DATE"),
    ]
    cols = [(src, h) for src, h in candidates
            if src in w.columns and _col_has_data(w[src])]
    return _petrel_table_text(
        w, cols,
        "# Petrel well heads — tab-delimited; empty columns omitted",
        "# (no wells)")


def _petrel_tops_text(tops):
    return _petrel_table_text(
        tops,
        [("uwi", "WELL"), ("formation", "SURFACE"), ("top_depth", "MD"),
         ("tvd_top", "TVD"), ("base_depth", "BASE_MD"), ("tvd_base", "BASE_TVD")],
        "# Petrel well tops — WELL SURFACE MD TVD (one row per pick)",
        "# (no formation tops supplied)")


def _petrel_completions_text(comps):
    return _petrel_table_text(
        comps,
        [("uwi", "WELL"), ("completion_type", "TYPE"), ("top_depth", "TOP_MD"),
         ("base_depth", "BASE_MD"), ("completion_date", "DATE"),
         ("completion_status", "STATUS"), ("strat_unit_name", "FORMATION"),
         ("lateral_length_ft", "LATERAL_FT"), ("stage_count", "STAGES"),
         ("total_proppant_lbs", "PROPPANT_LBS"), ("total_fluid_bbl", "FLUID_BBL")],
        "# Petrel completions — perforation/treatment intervals (tab-delimited)",
        "# (no completions supplied)")


def _petrel_production_text(prod):
    return _petrel_table_text(
        prod,
        [("uwi", "WELL"), ("prod_date", "DATE"), ("oil_vol", "OIL"),
         ("gas_vol", "GAS"), ("water_vol", "WATER")],
        "# Petrel production — WELL DATE OIL GAS WATER (monthly volumes)",
        "# (no production supplied)")


def _petrel_deviation_text(surveys):
    lines = ["# Petrel deviation — WELL MD INCL AZIM (one block per well)"]
    if surveys is None or not len(surveys):
        lines.append("# (no survey stations supplied)")
        return "\n".join(lines) + "\n"
    s = _normalize(surveys, SURVEY_CANON)
    s = s.assign(md=_num(s["md"]),
                 inc=_num(s["inc"]).fillna(0.0),
                 azi=_num(s["azi"]).fillna(0.0))
    s = s.dropna(subset=["md"]).sort_values(["uwi", "md"])
    for uwi, grp in s.groupby("uwi", sort=False):
        lines.append(f"\nWELL {uwi}")
        lines.append("MD\tINCL\tAZIM")
        block = (grp["md"].map("{:.2f}".format) + "\t"
                 + grp["inc"].map("{:.2f}".format) + "\t"
                 + grp["azi"].map("{:.2f}".format)).tolist()
        lines.extend(block)
    return "\n".join(lines) + "\n"


_PETREL_README = (
    "PETREL IMPORT SET — DataWrangler\n"
    "Each file is tab-delimited; map columns in the matching Petrel wizard.\n\n"
    "  well_heads.dat  -> Import > Well heads (ASCII): UWI, WELL, X(lon), Y(lat), KB, TD\n"
    "  well_tops.dat   -> Import > Well tops (ASCII): WELL, SURFACE, MD, TVD\n"
    "  deviation.dev   -> Import > Well path/deviation (ASCII): MD/INCL/AZIM per well\n"
    "  completions.dat -> Import as well attributes or perforation intervals\n"
    "                     (WELL, TOP_MD, BASE_MD, ...)\n"
    "  production.dat  -> Import production (volumes): WELL, DATE, OIL, GAS, WATER\n\n"
    "Suggested order: heads -> deviation -> tops -> completions -> production.\n"
)


def to_petrel_bundle(bundle, path):
    """Petrel import set: one zip with well heads, well tops (stratigraphy),
    deviation surveys, completions and production — each a tab-delimited ASCII
    file Petrel can import, plus a README mapping files to import wizards."""
    import zipfile
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("well_heads.dat",  _petrel_heads_text(bundle.get("wells")))
        z.writestr("well_tops.dat",   _petrel_tops_text(bundle.get("tops")))
        z.writestr("deviation.dev",   _petrel_deviation_text(bundle.get("surveys")))
        z.writestr("completions.dat", _petrel_completions_text(bundle.get("completions")))
        z.writestr("production.dat",  _petrel_production_text(bundle.get("production")))
        z.writestr("README.txt",      _PETREL_README)
    return path



def to_geographix(df, path, surveys=None):
    """GeoGraphix WellBase ASCII import: comma-delimited well headers with
    GGX-style field names."""
    w = _normalize(df, WELL_CANON)
    cols = ["uwi", "well_name", "well_num", "operator", "field", "county",
            "state", "lat", "lon", "status", "type", "spud_date",
            "completion_date", "td"]
    hdr = ["UWI", "WELL_NAME", "WELL_NUMBER", "OPERATOR", "FIELD", "COUNTY",
           "STATE", "SURF_LAT", "SURF_LONG", "STATUS", "WELL_TYPE",
           "SPUD_DATE", "COMP_DATE", "TOTAL_DEPTH"]
    out = w[cols].copy()
    out.columns = hdr
    out.to_csv(path, index=False)
    return path


def to_witsml(df, path, surveys=None):
    """WITSML 1.4.1.1 wellSet: <well> headers + optional <trajectory> per well."""
    NS = "http://www.witsml.org/schemas/1series"
    ET.register_namespace("", NS)
    w = _normalize(df, WELL_CANON)
    root = ET.Element(f"{{{NS}}}wellSet", version="1.4.1.1")
    lat, lon = _num(w["lat"]), _num(w["lon"])

    surv = _normalize(surveys, SURVEY_CANON) if (surveys is not None and len(surveys)) else None
    if surv is not None:
        surv = surv.assign(md=_num(surv["md"]), inc=_num(surv["inc"]),
                           azi=_num(surv["azi"]), tvd=_num(surv["tvd"]))

    for i in range(len(w)):
        uwi = w["uwi"].iloc[i]
        well = ET.SubElement(root, f"{{{NS}}}well", uid=str(uwi or i))
        ET.SubElement(well, f"{{{NS}}}name").text = str(w["well_name"].iloc[i] or uwi or "")
        if not pd.isna(w["api"].iloc[i]):
            ET.SubElement(well, f"{{{NS}}}numAPI").text = str(w["api"].iloc[i])
        if not pd.isna(w["operator"].iloc[i]):
            ET.SubElement(well, f"{{{NS}}}operator").text = str(w["operator"].iloc[i])
        if not (pd.isna(lat.iloc[i]) or pd.isna(lon.iloc[i])):
            loc = ET.SubElement(well, f"{{{NS}}}wellLocation")
            ET.SubElement(loc, f"{{{NS}}}latitude").text = f"{lat.iloc[i]:.6f}"
            ET.SubElement(loc, f"{{{NS}}}longitude").text = f"{lon.iloc[i]:.6f}"
        if surv is not None:
            grp = surv[surv["uwi"].astype(str) == str(uwi)].dropna(subset=["md"]).sort_values("md")
            if len(grp):
                traj = ET.SubElement(root, f"{{{NS}}}trajectory",
                                     uid=f"{uwi}_traj", uidWell=str(uwi or i))
                ET.SubElement(traj, f"{{{NS}}}nameWell").text = str(w["well_name"].iloc[i] or uwi or "")
                for j, (_, r) in enumerate(grp.iterrows()):
                    st = ET.SubElement(traj, f"{{{NS}}}trajectoryStation", uid=str(j))
                    ET.SubElement(st, f"{{{NS}}}md", uom="ft").text = f"{r['md']:.2f}"
                    if not pd.isna(r["inc"]):
                        ET.SubElement(st, f"{{{NS}}}incl", uom="dega").text = f"{r['inc']:.2f}"
                    if not pd.isna(r["azi"]):
                        ET.SubElement(st, f"{{{NS}}}azi", uom="dega").text = f"{r['azi']:.2f}"
                    if not pd.isna(r["tvd"]):
                        ET.SubElement(st, f"{{{NS}}}tvd", uom="ft").text = f"{r['tvd']:.2f}"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


# PPDM 3.9 WELL-table column names (single-table extract).
_PPDM_FIELDS = {
    "uwi": "UWI", "api": "GOVERNMENT_ID", "well_name": "WELL_NAME",
    "well_num": "WELL_NUM", "operator": "OPERATOR", "field": "POOL_FIELD",
    "county": "COUNTY", "state": "PROVINCE_STATE", "country": "COUNTRY",
    "lat": "SURFACE_LATITUDE", "lon": "SURFACE_LONGITUDE",
    "bottom_lat": "BOTTOM_HOLE_LATITUDE", "bottom_lon": "BOTTOM_HOLE_LONGITUDE",
    "status": "CURRENT_STATUS", "type": "FLUID_TYPE",
    "spud_date": "SPUD_DATE", "completion_date": "FINAL_DRILL_DATE",
    "plug_date": "ABANDONMENT_DATE", "td": "FINAL_TD", "tvd": "MAX_TVD",
    "ground_elev": "GROUND_ELEVATION", "kb_elev": "DEPTH_DATUM_ELEV",
    "formation": "PROD_FORMATION",
}


def to_ppdm(df, path, surveys=None):
    """PPDM 3.9 WELL-table extract (CSV) with PPDM column names."""
    w = _normalize(df, WELL_CANON).rename(columns=_PPDM_FIELDS)
    w.to_csv(path, index=False)
    return path


def _osdu_acl(owners, viewers, partition):
    dom = "dataservices.energy"
    return {
        "owners":  owners  or [f"data.default.owners@{partition}.{dom}"],
        "viewers": viewers or [f"data.default.viewers@{partition}.{dom}"],
    }


def _osdu_legal(legaltags, countries, partition):
    return {
        "legaltags": legaltags or [f"{partition}-public-usa-dataset-1"],
        "otherRelevantDataCountries": list(countries),
        "status": "compliant",
    }


def to_osdu(df, path, surveys=None, *, data_partition="opendes",
            acl_owners=None, acl_viewers=None, legaltags=None, countries=("US",),
            include_wellbores=True, as_manifest=True, kind_version="1.0.0",
            source="DataView"):
    """OSDU export: WKS master-data--Well (+ master-data--Wellbore) JSON records.

    Each record carries the OSDU envelope (id / kind / acl / legal / data).
    Spatial location is emitted as a GeoJSON FeatureCollection, API as a
    NameAlias, well status as a FacilityState, TD on the Wellbore.

    NOTE: acl, legal.legaltags and the data_partition are instance-specific —
    set them to your OSDU partition's real values before ingesting. Confirm the
    schema kind_version against your platform (defaults to 1.0.0). With
    as_manifest=True the output is a Manifest-ingestion document; otherwise a
    plain array of records for the Storage bulk API.
    """
    w = _normalize(df, WELL_CANON)
    lat, lon, td = _num(w["lat"]), _num(w["lon"]), _num(w["td"])
    acl = _osdu_acl(acl_owners, acl_viewers, data_partition)
    legal = _osdu_legal(legaltags, countries, data_partition)
    p, kv = data_partition, kind_version

    records = []
    for i in range(len(w)):
        uwi = str(w["uwi"].iloc[i] or w["api"].iloc[i] or i)
        wid = uwi.replace(":", "_")
        data = {"FacilityName": (None if pd.isna(w["well_name"].iloc[i])
                                 else str(w["well_name"].iloc[i])),
                "FacilityID": uwi, "Source": source}
        if not pd.isna(w["api"].iloc[i]):
            data["NameAliases"] = [{
                "AliasName": str(w["api"].iloc[i]),
                "AliasNameTypeID": f"{p}:reference-data--AliasNameType:UniqueIdentifier:"}]
        if not (pd.isna(lat.iloc[i]) or pd.isna(lon.iloc[i])):
            data["SpatialLocation"] = {
                "Wgs84Coordinates": {
                    "type": "FeatureCollection",
                    "features": [{"type": "Feature",
                                  "geometry": {"type": "Point",
                                               "coordinates": [float(lon.iloc[i]), float(lat.iloc[i])]},
                                  "properties": {}}]},
                "SpatialGeometryTypeID": f"{p}:reference-data--SpatialGeometryType:Point:",
                "CoordinateReferenceSystemID":
                    f"{p}:reference-data--CoordinateReferenceSystem:Geographic2D.EPSG.4326:"}
        if not pd.isna(w["status"].iloc[i]):
            st_id = str(w["status"].iloc[i]).replace(" ", "")
            data["FacilityStates"] = [{
                "FacilityStateTypeID": f"{p}:reference-data--FacilityStateType:{st_id}:"}]
        records.append({"id": f"{p}:master-data--Well:{wid}",
                        "kind": f"osdu:wks:master-data--Well:{kv}",
                        "acl": acl, "legal": legal,
                        "data": {k: v for k, v in data.items() if v is not None}})
        if include_wellbores:
            wb = {"FacilityName": data.get("FacilityName"),
                  "WellID": f"{p}:master-data--Well:{wid}:", "Source": source}
            if not pd.isna(td.iloc[i]):
                wb["TotalDepthMeasuredDepth"] = float(td.iloc[i])
            records.append({"id": f"{p}:master-data--Wellbore:{wid}",
                            "kind": f"osdu:wks:master-data--Wellbore:{kv}",
                            "acl": acl, "legal": legal,
                            "data": {k: v for k, v in wb.items() if v is not None}})

    payload = ({"kind": "osdu:wks:Manifest:1.0.0", "MasterData": records}
               if as_manifest else records)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


# ──────────────────────────────────────────────────────────────────────────
# ACTION EXPORTERS  (push to Snowflake / a DB; no file)
# ──────────────────────────────────────────────────────────────────────────
def to_database(df, engine, schema, table, if_exists="replace"):
    """Write the result set into a target DB table via SQLAlchemy.
    Works for SQL Server / Snowflake / Oracle engines."""
    df.to_sql(table, engine, schema=schema, if_exists=if_exists, index=False)
    loc = f"{schema}.{table}" if schema else table
    return f"{loc} ({len(df):,} rows)"


def to_snowflake_share(df, sf_conn, database, schema, table, share_name,
                       accounts=None):
    """Materialize the result set as a Snowflake table, then create/refresh a
    secure share exposing it. `accounts` is an optional list of consumer
    account identifiers to add to the share."""
    from snowflake.connector.pandas_tools import write_pandas
    cur = sf_conn.cursor()
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {database}.{schema}")
    df2 = df.copy()
    df2.columns = [str(c).upper() for c in df2.columns]
    write_pandas(sf_conn, df2, table.upper(), database=database, schema=schema,
                 auto_create_table=True, overwrite=True, quote_identifiers=False)
    cur.execute(f"CREATE SHARE IF NOT EXISTS {share_name}")
    cur.execute(f"GRANT USAGE ON DATABASE {database} TO SHARE {share_name}")
    cur.execute(f"GRANT USAGE ON SCHEMA {database}.{schema} TO SHARE {share_name}")
    cur.execute(f"GRANT SELECT ON TABLE {database}.{schema}.{table} TO SHARE {share_name}")
    for acct in (accounts or []):
        cur.execute(f"ALTER SHARE {share_name} ADD ACCOUNTS = {acct}")
    cur.close()
    return f"Share {share_name} -> {database}.{schema}.{table} ({len(df):,} rows)"


# ──────────────────────────────────────────────────────────────────────────
# REGISTRY
# ──────────────────────────────────────────────────────────────────────────
REGISTRY = {
    "csv":              {"label": "CSV",                      "ext": "csv",     "fn": to_csv,             "kind": "file"},
    "excel":            {"label": "Excel (.xlsx)",            "ext": "xlsx",    "fn": to_excel,           "kind": "file"},
    "geojson":          {"label": "GeoJSON",                  "ext": "geojson", "fn": to_geojson,         "kind": "file"},
    "shapefile":        {"label": "Shapefile (zip the .shp)", "ext": "shp",     "fn": to_shapefile,       "kind": "file"},
    "gdb":              {"label": "File Geodatabase (.gdb)",  "ext": "gdb",     "fn": to_gdb,             "kind": "file"},
    "petrel":           {"label": "Petrel (full set)",        "ext": "zip",     "fn": to_petrel_bundle,   "kind": "file"},
    "petrel_header":    {"label": "Petrel well heads",        "ext": "dat",     "fn": to_petrel_header,   "kind": "file"},
    "petrel_deviation": {"label": "Petrel deviation survey",  "ext": "dev",     "fn": to_petrel_deviation,"kind": "file", "needs_surveys": True},
    "geographix":       {"label": "GeoGraphix WellBase",      "ext": "csv",     "fn": to_geographix,      "kind": "file"},
    "witsml":           {"label": "WITSML 1.4.1.1",           "ext": "xml",     "fn": to_witsml,          "kind": "file", "needs_surveys": True},
    "ppdm":             {"label": "PPDM 3.9 WELL extract",    "ext": "csv",     "fn": to_ppdm,            "kind": "file"},
    "osdu":             {"label": "OSDU (WKS manifest)",      "ext": "json",    "fn": to_osdu,            "kind": "file"},
    "snowflake_share":  {"label": "Snowflake Secure Share",   "ext": None,      "fn": to_snowflake_share, "kind": "action"},
    "database":         {"label": "Database table",           "ext": None,      "fn": to_database,        "kind": "action"},
}


def export(df, fmt, out_dir, basename="export", surveys=None, **opts):
    """Run a FILE exporter; returns the output path. Extra **opts are passed to
    the writer (used by OSDU for partition / acl / legal config)."""
    spec = REGISTRY[fmt]
    if spec["kind"] != "file":
        raise ValueError(f"{fmt} is an action exporter — call its fn directly with context.")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{basename}.{spec['ext']}")
    return spec["fn"](df, path, surveys=surveys, **opts)


# ──────────────────────────────────────────────────────────────────────────
# STREAMLIT UI
# ──────────────────────────────────────────────────────────────────────────
def _package_for_download(path, fmt, basename):
    """Shapefile = many sibling files; GDB = a directory. Zip those so the
    download is a single file. Everything else passes through."""
    import zipfile
    if fmt == "shapefile":
        stem = os.path.splitext(path)[0]
        sidecars = (".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix")
        zpath = stem + "_shp.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for ext in sidecars:
                f = stem + ext
                if os.path.exists(f):
                    z.write(f, os.path.basename(f))
        return zpath, basename + ".shp.zip"
    if fmt == "gdb":
        zpath = path.rstrip("/\\") + ".zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for dp, _, files in os.walk(path):
                for f in files:
                    fp = os.path.join(dp, f)
                    z.write(fp, os.path.relpath(fp, os.path.dirname(path)))
        return zpath, os.path.basename(path) + ".zip"
    return path, os.path.basename(path)


def render_export_ui(df, surveys=None, sf_conn=None, db_engine=None,
                     out_dir="exports", basename="wells", survey_source="onshore"):
    """Drop into the results-list page: a format picker + download/run button.

    If a survey-dependent format is chosen and `surveys` wasn't supplied but a
    `db_engine` is, stations are fetched on demand via fetch_surveys() using the
    UWIs in `df` and `survey_source` ("onshore" or "gom")."""
    import streamlit as st
    if df is None or not len(df):
        st.info("No results to export.")
        return

    labels = {k: v["label"] for k, v in REGISTRY.items()}
    fmt = st.selectbox("Export format", list(labels), format_func=lambda k: labels[k])
    spec = REGISTRY[fmt]

    if spec.get("needs_surveys"):
        if surveys is None and db_engine is not None:
            uwis = _normalize(df, WELL_CANON)["uwi"].dropna().tolist()
            with st.spinner("Fetching survey stations…"):
                surveys = fetch_surveys(db_engine, uwis, source=survey_source)
        n = 0 if surveys is None else len(surveys)
        st.caption(f"{n:,} survey stations available."
                   if n else "No survey data — this exports well headers only.")

    if spec["kind"] == "file":
        opts = {}
        if fmt == "osdu":
            c1, c2 = st.columns(2)
            part = c1.text_input("OSDU data partition", "opendes")
            opts["data_partition"] = part
            opts["legaltags"] = [c2.text_input("Legal tag", f"{part}-public-usa-dataset-1")]
            opts["as_manifest"] = st.checkbox("Wrap as load manifest", True)
            opts["include_wellbores"] = st.checkbox("Include wellbore records", True)
            st.caption("Set the partition, legal tag and ACL to your OSDU "
                       "instance's real values before ingesting.")
        if st.button(f"Build {spec['label']}"):
            with st.spinner("Building export…"):
                path = export(df, fmt, out_dir, basename, surveys=surveys, **opts)
                dl_path, dl_name = _package_for_download(path, fmt, basename)
            with open(dl_path, "rb") as fh:
                st.download_button("Download", fh.read(), file_name=dl_name)
    elif fmt == "database":
        c1, c2 = st.columns(2)
        schema = c1.text_input("Target schema", "dbo")
        table = c2.text_input("Target table", "EXPORTED_WELLS")
        if st.button("Write to database"):
            if db_engine is None:
                st.error("No database engine provided to the export UI.")
            else:
                st.success(to_database(df, db_engine, schema, table))
    elif fmt == "snowflake_share":
        share = st.text_input("Share name", "DATAVIEW_SHARE")
        tbl = st.text_input("Table", "SHARED_WELLS")
        if st.button("Create / refresh share"):
            if sf_conn is None:
                st.error("No Snowflake connection provided to the export UI.")
            else:
                st.success(to_snowflake_share(df, sf_conn, "WELL_FEDERATION",
                                              "SHARED", tbl, share))


# ══════════════════════════════════════════════════════════════════════════
# SCOUT-TICKET DATA BUNDLE
# The export page pulls the same five sections the scout tickets show — well
# header, formation tops, directional survey, completion summary, production
# summary — and hands them to every format that can carry multiple tables.
# ══════════════════════════════════════════════════════════════════════════
_SECTION_SQL = {
        "tops": "SELECT uwi, strat_unit_name AS formation, top_depth, base_depth, "
                "gross_thickness, tvd_top, tvd_base, lithology, "
                "owc_depth, goc_depth, gwc_depth "
                "FROM dataview.dv_well_formation_top "
                "WHERE uwi IN :uwis ORDER BY uwi, top_depth",
        "surveys": "SELECT uwi, survey_id, station_id, md, incl, azim, tvd, ns_offset, "
                   "ew_offset, surface_latitude, surface_longitude, dls "
                   "FROM dataview.dv_well_dir_srvy_sta WHERE uwi IN :uwis "
                   "ORDER BY uwi, survey_id, md",
        "completions": "SELECT uwi, completion_type, completion_design, well_orientation, "
                       "completion_date, strat_unit_name, completion_status, primary_fluid, "
                       "top_depth, base_depth, lateral_length_ft, stage_count, total_clusters, "
                       "avg_cluster_spacing_ft, frac_fluid_system, proppant_type, "
                       "total_fluid_bbl, total_proppant_lbs, fluid_intensity_bbl_ft, "
                       "proppant_intensity_lbs_ft FROM dataview.dv_well_completion "
                       "WHERE uwi IN :uwis ORDER BY uwi, completion_date",
        "frac_stages": "SELECT uwi, completion_id, stage_num, stage_top_depth, "
                       "stage_base_depth, num_clusters, cluster_spacing_ft, fluid_system, "
                       "fluid_volume_bbl, proppant_type, proppant_mesh, proppant_mass_lbs, "
                       "max_proppant_conc_ppg, breakdown_pressure_psi, isip_psi, "
                       "avg_treating_pressure_psi, max_treating_pressure_psi, avg_rate_bpm, "
                       "max_rate_bpm, screen_out_ind FROM dataview.dv_well_stimulation "
                       "WHERE uwi IN :uwis ORDER BY uwi, completion_id, stage_num",
        "dst": "SELECT uwi, test_date, test_type, top_depth, base_depth, test_result, "
               "max_oil_rate, max_gas_rate, api_gravity FROM dataview.dv_well_dst "
               "WHERE uwi IN :uwis ORDER BY uwi, test_date",
        "cores": "SELECT uwi, core_num, core_type, core_show, strat_unit_name, top_depth, "
                 "base_depth, core_length, recovery_length, recovery_pct, core_date, "
                 "photo_count FROM dataview.dv_well_core WHERE uwi IN :uwis "
                 "ORDER BY uwi, top_depth",
        "core_samples": "SELECT uwi, sample_id, sample_type, sample_depth, lithology, "
                        "hydrocarbon_show, porosity_frac*100.0 AS porosity_pct, "
                        "permeability_air_md AS permeability_md, bulk_density_g_cc AS bulk_density, "
                        "water_saturation_frac*100.0 AS water_saturation, "
                        "oil_saturation_frac*100.0 AS oil_saturation "
                        "FROM dataview.dv_well_core_sample WHERE uwi IN :uwis "
                        "ORDER BY uwi, sample_depth",
        "core_photos": "SELECT uwi, photo_type, lighting, file_path, file_name, top_depth, "
                       "base_depth, tray_num FROM dataview.dv_well_core_photo "
                       "WHERE uwi IN :uwis AND active_ind='Y' ORDER BY uwi, tray_num, photo_type",
        "petrophysics": "SELECT z.uwi, z.zone_name, z.zone_type, z.strat_unit_name, "
                        "z.top_depth, z.base_depth, z.tvd_top, z.tvd_base, "
                        "z.gross_thickness, z.net_thickness, z.net_to_gross, "
                        "z.vsh_avg, z.phi_total_avg, z.phi_effective_avg, z.phi_method, "
                        "z.sw_avg, z.sw_method, z.sh_avg, "
                        "z.perm_avg_md, z.perm_geomean_md, z.perm_method, "
                        "z.bvw_avg, z.bvh_avg, z.fluid_type, z.pay_flag, "
                        "z.pay_cutoff_phi, z.pay_cutoff_sw, z.pay_cutoff_vsh, z.hcpv, "
                        "i.interp_name, i.software, i.formation_water_resist AS rw, "
                        "i.archie_a, i.archie_m, i.archie_n "
                        "FROM dataview.dv_well_petro_zone z "
                        "LEFT JOIN dataview.dv_well_petro_interp i "
                        "ON i.uwi=z.uwi AND i.interp_id=z.interp_id "
                        "WHERE z.uwi IN :uwis ORDER BY z.uwi, z.top_depth",
        "production": "SELECT pe.uwi, pv.period_date AS prod_date, "
                      "SUM(CASE WHEN pv.fluid_type='OIL' THEN ISNULL(pv.volume,0) ELSE 0 END) AS oil_vol, "
                      "SUM(CASE WHEN pv.fluid_type='GAS' THEN ISNULL(pv.volume,0) ELSE 0 END) AS gas_vol, "
                      "SUM(CASE WHEN pv.fluid_type='WATER' THEN ISNULL(pv.volume,0) ELSE 0 END) AS water_vol "
                      "FROM dataview.dv_prod_volume pv "
                      "JOIN dataview.dv_prod_entity pe ON pe.prod_entity_id=pv.prod_entity_id "
                      "WHERE pe.uwi IN :uwis GROUP BY pe.uwi, pv.period_date "
                      "ORDER BY pe.uwi, pv.period_date",
}


def fetch_bundle(engine, uwis, source="onshore", batch=1000, sections=None):
    """Return the requested scout-ticket sections for the selected wells. Only
    the keys named in `sections` are queried (default: all four). GOM
    (dataview_gom) only has survey points."""
    from sqlalchemy import bindparam, text

    want = set(sections) if sections is not None else {"tops", "surveys", "dst", "cores", "core_samples", "core_photos", "petrophysics", "completions", "frac_stages", "production"}
    uwis = [str(u) for u in dict.fromkeys(uwis) if u is not None and str(u) != ""]
    out = {}
    if not uwis:
        return {k: pd.DataFrame() for k in want}
    if source == "gom":
        if "surveys" in want:
            out["surveys"] = fetch_surveys(engine, uwis, source="gom", batch=batch)
        return out

    queries = _SECTION_SQL
    import time
    # SSMS runs with ARITHABORT ON; pyodbc connects with it OFF, which makes the
    # optimizer compile a *different*, worse plan for the identical query — the
    # classic "instant in SSMS, slow in the app" gap (an oversized sort memory
    # grant that then stalls on 1 GB Express). Set it ON once on a single shared
    # connection and run every section on it (also avoids per-section connect
    # overhead). OPTION (RECOMPILE) keeps the plan honest per run.
    with engine.connect() as conn:
        conn.exec_driver_sql("SET ARITHABORT ON")
        for key, sql in queries.items():
            if key not in want:
                continue
            stmt = text(sql + "\nOPTION (RECOMPILE)").bindparams(
                bindparam("uwis", expanding=True))
            frames = []
            _t0 = time.time()
            try:
                for i in range(0, len(uwis), batch):
                    frames.append(pd.read_sql(stmt, conn,
                                              params={"uwis": uwis[i:i + batch]}))
                out[key] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
                _dt = time.time() - _t0
                if _dt > 1.0:
                    print(f"[fetch_bundle] section '{key}': "
                          f"{len(out[key]):,} rows in {_dt:.1f}s  ← slow query")
            except Exception as e:
                print(f"[fetch_bundle] section '{key}' failed: {e}")
                out[key] = pd.DataFrame()
    return out


# section key -> (Excel sheet label, file/layer name, PPDM table name)
_SECTION_META = {
    "tops":        ("Formation Tops",     "formation_tops",     "WELL_FORMATION"),
    "surveys":     ("Directional Survey", "directional_survey", "WELL_DIR_SRVY_STATION"),
    "completions": ("Completion Summary", "completions",        "WELL_COMPLETION"),
    "frac_stages":  ("Frac Stages",          "frac_stages",        "WELL_STIM_STAGE"),
    "production":  ("Production Summary",  "production",         "PDEN_VOL_SUMMARY"),
    "dst":         ("DST",                  "drill_stem_tests",   "WELL_TEST"),
    "cores":       ("Core Runs",            "core_runs",          "WELL_CORE"),
    "core_samples":("Core Sample Analysis", "core_samples",       "WELL_CORE_ANALYSIS"),
    "core_photos": ("Core Photographs",     "core_photos",        "WELL_CORE_PHOTO"),
    "petrophysics":("Petrophysics",         "petrophysics",       "WELL_PETRO_ZONE"),
}


def _excel_sheet(xl, sheet, df):
    if df is None or not len(df):
        pd.DataFrame({"Note": ["No data"]}).to_excel(xl, sheet_name=sheet, index=False)
        return
    df.to_excel(xl, sheet_name=sheet, index=False)
    ws = xl.sheets[sheet]
    # Column widths computed from the DataFrame (vectorized, sampled) — far
    # faster than walking every worksheet cell, and works for both engines.
    widths = []
    for c in df.columns:
        body = df[c].head(1000).astype(str).str.len().max()
        widths.append(min(max(len(str(c)), int(body or 0)) + 2, 40))
    if hasattr(ws, "set_column"):          # xlsxwriter
        ws.freeze_panes(1, 0)
        for i, w in enumerate(widths):
            ws.set_column(i, i, w)
    else:                                  # openpyxl
        from openpyxl.utils import get_column_letter
        ws.freeze_panes = "A2"
        for i, w in enumerate(widths):
            ws.column_dimensions[get_column_letter(i + 1)].width = w


def to_excel_bundle(bundle, path):
    with pd.ExcelWriter(path, engine=_xl_engine()) as xl:
        _excel_sheet(xl, "Well Header", bundle["wells"].drop(columns=["lat", "lon"], errors="ignore"))
        for key, (label, _, _) in _SECTION_META.items():
            if key in bundle:
                _excel_sheet(xl, label, bundle[key])
    return path


def to_csv_zip_bundle(bundle, path):
    import zipfile
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("wells.csv",
                   bundle["wells"].drop(columns=["lat", "lon"], errors="ignore").to_csv(index=False))
        for key, (_, fname, _) in _SECTION_META.items():
            if key in bundle:
                df = bundle[key] if bundle[key] is not None else pd.DataFrame()
                z.writestr(f"{fname}.csv", df.to_csv(index=False))
    return path


def to_gdb_bundle(bundle, path):
    import pyogrio
    _gdb_safe(_geodataframe(bundle["wells"]).rename(columns=_SHP_FIELDS)).to_file(
        path, driver="OpenFileGDB", layer="wells")
    for key, (_, layer, _) in _SECTION_META.items():
        df = bundle.get(key)
        if df is not None and len(df):
            pyogrio.write_dataframe(_gdb_safe(df), path, layer=layer,
                                    driver="OpenFileGDB", append=True)
    return path


def to_ppdm_zip_bundle(bundle, path):
    import zipfile
    wells = _normalize(bundle["wells"], WELL_CANON).rename(columns=_PPDM_FIELDS)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("WELL.csv", wells.to_csv(index=False))
        for key, (_, _, ppdm) in _SECTION_META.items():
            if key in bundle:
                df = bundle[key] if bundle[key] is not None else pd.DataFrame()
                z.writestr(f"{ppdm}.csv", df.to_csv(index=False))
    return path


_BUNDLE_WRITERS = {"excel": (to_excel_bundle, "xlsx"), "csv": (to_csv_zip_bundle, "zip"),
                   "gdb": (to_gdb_bundle, "gdb"),
                   "ppdm": (to_ppdm_zip_bundle, "zip"),
                   "petrel": (to_petrel_bundle, "zip")}


def export_bundle(bundle, fmt, out_dir, basename="export", **opts):
    """Run an exporter against the full scout-ticket bundle. Multi-table formats
    use a bundle writer; the rest use the wells frame (+ surveys) as before."""
    os.makedirs(out_dir, exist_ok=True)
    if fmt in _BUNDLE_WRITERS:
        fn, ext = _BUNDLE_WRITERS[fmt]
        return fn(bundle, os.path.join(out_dir, f"{basename}_{fmt}.{ext}"))
    spec = REGISTRY[fmt]
    path = os.path.join(out_dir, f"{basename}.{spec['ext']}")
    return spec["fn"](bundle["wells"], path, surveys=bundle.get("surveys"), **opts)


# ── Per-tool documentation shown on the export page ───────────────────────
FORMAT_INFO = {
    "csv": {"desc": "Comma-separated tables — the universal interchange.",
            "howto": "Opens in Excel, pandas, or any database import. Delivered as a zip with one CSV per section.",
            "includes": "Wells, formation tops, directional survey, completions, production."},
    "excel": {"desc": "Multi-sheet workbook, one sheet per scout-ticket section.",
              "howto": "Open in Excel or Google Sheets. Sheets: Well Header, Formation Tops, Directional Survey, Completion Summary, Production Summary.",
              "includes": "All five scout-ticket sections."},
    "ppdm": {"desc": "PPDM 3.9-shaped extract with PPDM table and column names.",
             "howto": "Load into a PPDM store or hand to a PPDM consultant. Zip of CSVs named for their PPDM tables.",
             "includes": "WELL, formation tops, directional survey, completions, production."},
    "geojson": {"desc": "Open spatial format (RFC 7946).",
                "howto": "Drop into QGIS/ArcGIS, Leaflet/Mapbox, or GitHub. Wells as point features with attributes.",
                "includes": "Well-header points (one feature per well)."},
    "shapefile": {"desc": "ESRI shapefile — the GIS lingua franca.",
                  "howto": "Add to ArcGIS/QGIS. Delivered as a zip of .shp/.shx/.dbf/.prj; field names truncated to 10 chars.",
                  "includes": "Well-header points."},
    "gdb": {"desc": "ESRI File Geodatabase — Esri's native multi-layer container.",
            "howto": "Unzip and open the .gdb in ArcGIS Pro. Spatial wells feature class plus a table per section.",
            "includes": "Wells (feature class) + tops + survey + completions + production, as tables."},
    "petrel": {"desc": "Petrel import set — one zip of tab-delimited ASCII files.",
               "howto": "Unzip, then import each file with its Petrel wizard (see README.txt inside): well heads, well tops, deviation, completions, production.",
               "includes": "Well header, stratigraphy (tops), directional survey, completions, production."},
    "petrel_header": {"desc": "Petrel well-heads ASCII.",
                      "howto": "In Petrel: Import → Well heads (ASCII). Tab-delimited UWI/X/Y/KB/TD; map columns in the wizard.",
                      "includes": "Well headers (surface location, KB, TD)."},
    "petrel_deviation": {"desc": "Petrel deviation-survey ASCII.",
                         "howto": "In Petrel: Import → Well path/deviation (ASCII). One MD/INCL/AZIM block per well.",
                         "includes": "Directional-survey stations."},
    "geographix": {"desc": "GeoGraphix WellBase import file.",
                   "howto": "Import via the GGX WellBase ASCII importer. Comma-delimited headers with GGX field names.",
                   "includes": "Well headers."},
    "witsml": {"desc": "WITSML 1.4.1.1 — the industry XML standard.",
               "howto": "Load into any WITSML store or consumer. <well> headers plus a <trajectory> per surveyed well.",
               "includes": "Well headers + directional-survey trajectories."},
    "osdu": {"desc": "OSDU Well-Known-Schema records (master-data Well + Wellbore).",
             "howto": "Ingest via OSDU Manifest/Storage. Set your data partition and legal tag below first.",
             "includes": "Well + Wellbore master-data records (spatial, API alias, status, TD)."},
    "database": {"desc": "Write the selected wells into a table on an external SQL Server / Oracle / Snowflake database.",
                 "howto": "Paste a full connection string for the target database, then give the schema and table.",
                 "includes": "Well-header rows."},
    "snowflake_share": {"desc": "Publish the wells as a Snowflake secure share.",
                        "howto": "Paste a Snowflake connection string, then give the database, schema, table and share name; the wells are written to a table and shared.",
                        "includes": "Well-header rows."},
}

FORMAT_GROUPS = [
    ("📄 Tabular & exchange", ["csv", "excel", "ppdm"]),
    ("🗺 GIS / mapping", ["geojson", "shapefile", "gdb"]),
    ("🛢 Interpretation apps", ["petrel", "geographix"]),
    ("☁ Data platforms", ["osdu", "database", "snowflake_share"]),
]


_FULL_BUNDLE_FMTS = {"excel", "csv", "gdb", "ppdm"}   # can hold all sections
_SURVEY_FMTS = {"petrel_deviation", "witsml", "osdu"}         # use the survey section
_PETREL_SECTIONS = {"wells", "tops", "surveys", "completions", "production"}

_SECTION_ORDER = ["wells", "tops", "surveys", "dst", "cores", "core_samples", "core_photos", "petrophysics", "completions", "frac_stages", "production"]
_FRIENDLY = {"wells": "well header", "tops": "formation tops",
             "surveys": "directional survey", "completions": "completions",
             "production": "production", "dst": "DST", "cores": "core runs",
             "core_samples": "core analysis", "core_photos": "core photos",
             "petrophysics": "petrophysics", "completions": "completions",
             "frac_stages": "frac stages"}


def _capability(fmt):
    """Which sections a format can physically carry."""
    if fmt == "petrel":
        return set(_PETREL_SECTIONS)
    if fmt in _FULL_BUNDLE_FMTS:
        return {"wells", "tops", "surveys", "dst", "cores", "core_samples",
                "core_photos", "petrophysics", "completions", "frac_stages", "production"}
    if fmt in _SURVEY_FMTS:
        return {"wells", "surveys"}
    return {"wells"}


def _sections_for_format(fmt, selected):
    """What gets exported = checked sections ∩ what the format can hold (the
    well header is always included)."""
    if fmt == "petrel":
        # The Petrel set always ships all five files regardless of the
        # data-to-include picker, so it's a complete, self-contained import.
        return set(_PETREL_SECTIONS)
    return ({"wells"} | set(selected)) & _capability(fmt)


def _get_export_bundle(engine, wells, uwis, source, fmt, selected):
    """Fetch exactly the sections this format will use, cached in session_state
    by the well set + section set. Header/spatial formats hit no database."""
    import streamlit as st
    want = _sections_for_format(fmt, selected) - {"wells"}
    if not want:
        return {"wells": wells}
    key = str(hash((tuple(sorted(map(str, uwis))), source, tuple(sorted(want)))))
    cache = st.session_state.get("_exp_cache")
    if cache and cache.get("key") == key:
        return cache["bundle"]
    label = ", ".join(_FRIENDLY[s] for s in _SECTION_ORDER if s in want)
    with st.spinner(f"Gathering {label}…"):
        if source == "gom":
            sect = fetch_bundle(engine, uwis, source=source, sections=want)
        else:
            try:
                import export_bcp
                sect = export_bcp.fetch_bundle_bcp(engine, uwis, sections=want)
            except Exception as _bcp_err:
                print(f"[export] BCP fetch unavailable, using pyodbc: {_bcp_err}")
                sect = fetch_bundle(engine, uwis, source=source, sections=want)
        bundle = {"wells": wells, **sect}
    st.session_state["_exp_cache"] = {"key": key, "bundle": bundle}
    return bundle


def _card():
    """A bordered container (a 'card'); falls back to a plain container on
    Streamlit versions without the border kwarg."""
    import streamlit as st
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def _card_help(text):
    """Gold '?' help badge in the upper-right corner of the enclosing card.
    Call as the FIRST element inside `with _card():`. Self-anchoring (carries
    its own relative wrapper) and reuses the global .card-help CSS injected by
    app_v3.py."""
    import streamlit as st, html as _html
    if not text:
        return
    # Encode newlines as &#10; so Streamlit's markdown parser doesn't split
    # this HTML on blank lines (which would dump the tooltip text onto the
    # page). The browser decodes &#10; back to a newline, rendered via
    # white-space: pre-line in the .card-help::after CSS.
    _safe = _html.escape(str(text), quote=True).replace("\r", "").replace("\n", "&#10;")
    st.markdown(
        "<div style='position:relative;width:100%;height:0;z-index:7'>"
        "<span class='card-help' style='top:2px;right:2px' "
        f"data-help=\"{_safe}\">?</span>"
        "</div>",
        unsafe_allow_html=True)


def _render_format_card(fmt, engine, wells, uwis, source, out_dir, basename, selected):
    import streamlit as st
    spec = REGISTRY[fmt]
    info = FORMAT_INFO.get(fmt, {})
    will = [s for s in _SECTION_ORDER if s in _sections_for_format(fmt, selected)]
    with _card():
        _will = ", ".join(_FRIENDLY[s] for s in will)
        help_text = (
            f"{info.get('desc', '')}\n\n"
            f"Includes: {_will}\n\n"
            f"How to use: {info.get('howto', '')}"
        )
        _card_help(help_text)
        st.markdown(f"**{spec['label']}**")

        opts = {}
        if fmt == "osdu":
            part = st.text_input("Data partition", "opendes", key="osdu_part")
            opts["data_partition"] = part
            opts["legaltags"] = [st.text_input("Legal tag", f"{part}-public-usa-dataset-1",
                                               key="osdu_lt")]

        if spec["kind"] == "file":
            if st.button(f"Build {spec['label']}", key=f"build_{fmt}"):
                bundle = _get_export_bundle(engine, wells, uwis, source, fmt, selected)
                with st.spinner("Building…"):
                    path = export_bundle(bundle, fmt, out_dir, basename, **opts)
                    dl, name = _package_for_download(path, fmt, basename)
                with open(dl, "rb") as fh:
                    st.download_button("⬇ Download", fh.read(), file_name=name, key=f"dl_{fmt}")


def _engine_from_conn_str(conn_str):
    """Build a SQLAlchemy engine from a full connection string (URL). The string
    itself carries the dialect/driver; credentials in it are used only to open
    the connection and are not stored by this module."""
    from sqlalchemy import create_engine
    cs = (conn_str or "").strip()
    if not cs:
        raise ValueError("Enter a connection string.")
    return create_engine(cs)


_DB_CONN_HELP = (
    "Full SQLAlchemy URL. Examples — "
    "SQL Server: mssql+pyodbc://user:pass@host/DB?driver=ODBC+Driver+17+for+SQL+Server  •  "
    "Oracle: oracle+oracledb://user:pass@host:1521/?service_name=ORCLPDB1  •  "
    "Snowflake: snowflake://user:pass@account/DB?warehouse=WH&role=ROLE"
)


def _render_connector(fmt, engine, wells):
    """Full-width connector form (Database / Snowflake share). The user supplies
    a connection string, so these render outside the card grid for room."""
    import streamlit as st
    spec = REGISTRY[fmt]
    info = FORMAT_INFO.get(fmt, {})
    with _card():
        _howto = info.get("howto", "")
        if fmt == "database":
            _badge = _DB_CONN_HELP + (("\n\n" + _howto) if _howto else "")
        elif fmt == "snowflake_share":
            _badge = ("Connection string: "
                      "snowflake://user:pass@account/DB?warehouse=WH&role=ROLE"
                      + (("\n\n" + _howto) if _howto else ""))
        else:
            _badge = _howto
        _card_help(_badge)
        st.markdown(f"**{spec['label']}**")

        if fmt == "database":
            st.caption("Write the selected wells' header rows into a table on an external "
                       "SQL Server / Oracle / Snowflake database.")
            conn_str = st.text_input("Connection string", key="db_conn")
            c1, c2, c3 = st.columns(3)
            schema = c1.text_input("Schema", key="db_sch")
            table = c2.text_input("Table", "EXPORTED_WELLS", key="db_tbl")
            mode = c3.selectbox("If exists", ["replace", "append", "fail"], key="db_mode")
            if st.button("Write to database", key="db_write"):
                try:
                    eng = _engine_from_conn_str(conn_str)
                    with st.spinner("Writing…"):
                        msg = to_database(wells, eng, schema or None, table, if_exists=mode)
                    eng.dispose()
                    st.success("Wrote " + msg)
                except Exception as e:
                    st.error(f"Write failed: {type(e).__name__}: {e}")

        elif fmt == "snowflake_share":
            st.caption("Materialize the wells as a Snowflake table and publish it as a secure share.")
            conn_str = st.text_input(
                "Snowflake connection string", key="sf_conn")
            c1, c2 = st.columns(2)
            database = c1.text_input("Database", key="sf_db")
            schema = c2.text_input("Schema", "PUBLIC", key="sf_sch")
            c3, c4 = st.columns(2)
            table = c3.text_input("Table", "SHARED_WELLS", key="sf_tbl")
            share = c4.text_input("Share name", "DATAVIEW_SHARE", key="sf_share")
            if st.button("Create / refresh share", key="sf_write"):
                if not (database and schema and table and share):
                    st.error("Database, schema, table and share name are required.")
                else:
                    eng = raw = None
                    try:
                        eng = _engine_from_conn_str(conn_str)
                        raw = eng.raw_connection()
                        sf_conn = getattr(raw, "driver_connection", None) or raw.connection
                        with st.spinner("Creating share…"):
                            msg = to_snowflake_share(wells, sf_conn, database, schema, table, share)
                        st.success(msg)
                    except Exception as e:
                        st.error(f"Share failed: {type(e).__name__}: {e}")
                    finally:
                        if raw is not None:
                            raw.close()
                        if eng is not None:
                            eng.dispose()


def count_vaulted_documents(engine, uwis, batch=500):
    """Cheap COUNT of vaulted documents matched to the given wells — used to
    label the click-through button without pulling the full list."""
    from sqlalchemy import bindparam, text

    uwis = [str(u) for u in dict.fromkeys(uwis) if u is not None and str(u) != ""]
    if not uwis:
        return 0
    sql = ("SELECT COUNT(*) AS n "
           "FROM file_catalog.GLOBAL_FILE_CATALOG g "
           "JOIN file_catalog.VAULT_FILE v ON v.INVENTORY_ID = g.INVENTORY_ID "
           "WHERE g.MATCHED_UWI IN :uwis "
           "AND ISNULL(g.FLAG_DELETE, 'N') <> 'Y'")
    stmt = text(sql).bindparams(bindparam("uwis", expanding=True))
    total = 0
    for i in range(0, len(uwis), batch):
        try:
            df = pd.read_sql(stmt, engine, params={"uwis": uwis[i:i + batch]})
            total += int(df.iloc[0, 0])
        except Exception:
            pass
    return total


def fetch_vaulted_documents(engine, uwis, batch=500):
    """Vaulted documents associated with the given wells. Inner-joins
    GLOBAL_FILE_CATALOG to VAULT_FILE on INVENTORY_ID, so only files that have
    a protected vault copy are returned, surfacing the stable VAULT_PATH rather
    than the original (movable) source path. One row per file."""
    from sqlalchemy import bindparam, text

    uwis = [str(u) for u in dict.fromkeys(uwis) if u is not None and str(u) != ""]
    if not uwis:
        return pd.DataFrame()

    sql = ("SELECT g.MATCHED_UWI AS uwi, "
           "(SELECT TOP 1 h.WELL_NAME FROM file_catalog.FILE_WELL_HEADER h "
           " WHERE h.INVENTORY_ID = g.INVENTORY_ID) AS well_name, "
           "g.FILE_NAME, g.FILE_TYPE_GROUP, "
           "v.CATEGORY, v.VAULT_PATH, v.VAULTED_AT "
           "FROM file_catalog.GLOBAL_FILE_CATALOG g "
           "JOIN file_catalog.VAULT_FILE v ON v.INVENTORY_ID = g.INVENTORY_ID "
           "WHERE g.MATCHED_UWI IN :uwis "
           "AND ISNULL(g.FLAG_DELETE, 'N') <> 'Y' "
           "ORDER BY g.MATCHED_UWI, g.FILE_TYPE_GROUP, g.FILE_NAME")
    stmt = text(sql).bindparams(bindparam("uwis", expanding=True))
    frames = []
    for i in range(0, len(uwis), batch):
        try:
            frames.append(pd.read_sql(stmt, engine,
                                      params={"uwis": uwis[i:i + batch]}))
        except Exception:
            pass
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def render_documents_panel(engine, uwis, source="onshore"):
    """Click-through view of the *vaulted* documents catalogued against the
    wells in the result set. A button (labelled with the count) opens a panel
    with a per-well rollup, the full file list pointing at the vault copies,
    and a CSV download. Restricting to vaulted files means the paths shown
    can't be deleted or moved out from under the catalog."""
    import streamlit as st

    key = "show_docs_view"
    n = count_vaulted_documents(engine, uwis)
    if n == 0:
        st.caption("📄 No vaulted documents are matched to these wells yet "
                   "(run the vault copy to protect them first).")
        st.session_state.pop(key, None)
        return

    if not st.session_state.get(key, False):
        if st.button(f"📄 View associated documents ({n:,})",
                     key="docs_view_open"):
            st.session_state[key] = True
            st.rerun()
        return

    # Opened — pull the full list now.
    docs = fetch_vaulted_documents(engine, uwis)
    top = st.columns([6, 1])
    top[0].markdown(
        f"<span style='color:#bbb;font-size:.9em'>{len(docs):,} vaulted "
        f"document(s) across {docs['uwi'].nunique():,} well(s)</span>",
        unsafe_allow_html=True,
    )
    if top[1].button("✖ Hide", key="docs_view_close"):
        st.session_state[key] = False
        st.session_state.pop("docs_view_target", None)
        st.rerun()

    # Just the file list (with well name next to the UWI).
    cols = [c for c in ["uwi", "well_name", "FILE_NAME", "FILE_TYPE_GROUP",
                        "CATEGORY", "VAULT_PATH", "VAULTED_AT"]
            if c in docs.columns]
    st.caption("All vaulted files")
    st.dataframe(docs[cols], use_container_width=True, hide_index=True)

    # Open a file in the catalog's universal viewer — the same one Browse &
    # View uses (modules.file_viewer.view) — pointed at the protected vault
    # copy and rendered inline below. Download stays as a fallback.
    import os
    st.caption("Open a file")
    opts = {}
    for i, r in enumerate(docs.itertuples(), start=1):
        ftg = r.FILE_TYPE_GROUP if pd.notna(r.FILE_TYPE_GROUP) else ""
        label = f"{i}. {r.FILE_NAME}  ({ftg})"
        opts[label] = (r.VAULT_PATH,
                       os.path.splitext(str(r.FILE_NAME))[1].lower())
    pick = st.selectbox("File", list(opts.keys()), key="docs_open_pick",
                        label_visibility="collapsed")
    sel_path, sel_ext = opts.get(pick, (None, ""))
    oc1, oc2 = st.columns([1, 1])
    if oc1.button("👁 View in catalog viewer", key="docs_open_btn",
                  use_container_width=True):
        st.session_state["docs_view_target"] = (sel_path, sel_ext)
    try:
        if sel_path and os.path.exists(sel_path) \
                and os.path.getsize(sel_path) < 200 * 1024 * 1024:
            with open(sel_path, "rb") as _fh:
                oc2.download_button(
                    "⬇ Download file", _fh.read(),
                    file_name=os.path.basename(sel_path),
                    key="docs_open_dl", use_container_width=True)
        else:
            oc2.caption("Too large to download — use the viewer.")
    except Exception:
        pass

    # Inline render of the selected file via the universal viewer, with a
    # close button at the bottom to dismiss it.
    _vt = st.session_state.get("docs_view_target")
    if _vt:
        _vpath, _vext = _vt
        if _vpath and os.path.exists(_vpath):
            try:
                try:
                    from modules.file_viewer import view as _fview
                except ImportError:
                    from file_viewer import view as _fview
                _fview(_vpath, _vext)
            except Exception as e:
                st.error(f"Viewer error: {e}")
        else:
            st.warning(f"File not found in vault: {_vpath}")
        if st.button("✖ Close document", key="docs_view_close_doc",
                     use_container_width=True):
            st.session_state.pop("docs_view_target", None)
            st.rerun()

    st.download_button(
        "⬇ Documents CSV",
        docs.to_csv(index=False).encode("utf-8"),
        file_name="associated_documents.csv",
        mime="text/csv", key="docs_csv_dl",
    )


def render_export_page(header_df, engine, uwis, source="onshore",
                       basename="DataView_wells", out_dir="exports"):
    """Full export page: pick which data sections to include, then build any
    format. The page renders immediately; only the checked sections are queried,
    and only when you build."""
    import streamlit as st
    if header_df is None or not len(header_df):
        st.info("No wells selected. Add wells to the tray, then open Export.")
        return

    st.markdown(
        """<style>
        .block-container, [data-testid="stMainBlockContainer"]{ padding-top:5.0rem !important; }

        /* cards in a row share the tallest height so their buttons line up */
        div[data-testid="stHorizontalBlock"]{ align-items:stretch; }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]{ display:flex; }
        div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] > div{ width:100%; }

        div[data-testid="stVerticalBlockBorderWrapper"]{
            border:2px solid #FFD400 !important;
            border-radius:12px;
            background:#171717;
            box-shadow:0 0 10px rgba(255,212,0,.25);
        }
        /* equal height + action button at the bottom: ONLY for grid cards
           (border wrappers inside a column). Full-width connectors are
           excluded so their forms sit flush under the title — no white gap. */
        div[data-testid="stColumn"] div[data-testid="stVerticalBlockBorderWrapper"]{
            height:100%;
            min-height:84px;
        }
        div[data-testid="stColumn"] div[data-testid="stVerticalBlockBorderWrapper"] > div{ height:100%; }
        div[data-testid="stColumn"] div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"]{
            height:100%;
            display:flex;
            flex-direction:column;
            gap:.3rem;
        }
        div[data-testid="stColumn"] div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"] > div:last-child{
            margin-top:auto;
        }
        div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMarkdownContainer"],
        div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stMarkdownContainer"] *,
        div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCaptionContainer"],
        div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCaptionContainer"] *,
        div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stWidgetLabel"] *{
            color:#ffffff !important;
        }
        </style>""",
        unsafe_allow_html=True,
    )

    wells = header_df.copy()
    if source == "gom" and "api_well_number" in wells.columns:
        wells = wells.assign(uwi=wells["api_well_number"])
        uwis = wells["uwi"].dropna().astype(str).tolist()

    st.markdown(
        "<div style='font-size:1.7rem;font-weight:800;color:#FFD400;"
        "letter-spacing:.3px;margin:.1rem 0 .35rem'>⬇ DataWrangler Exporter</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<span style='color:#bbb;font-size:0.9em'>{len(wells):,} wells · "
        "<b>data to include</b> · Well header always included "
        "(sections are added wherever a format supports them; single-layer "
        "formats stay header-only):</span>",
        unsafe_allow_html=True,
    )

    # Documents catalogued against the wells in this result set.
    render_documents_panel(engine, uwis, source=source)

    # Compact section picker: a single multi-select (pills if available) instead
    # of 11 column checkboxes, which the theme/card CSS blew up into tall empty
    # cards. "Well header" is implicit (always included).
    _SECTION_PICK = [
        ("Formation tops", "tops"),
        ("Directional survey", "surveys"),
        ("Completions", "completions"),
        ("Frac stages", "frac_stages"),
        ("Production (slow)", "production"),
        ("DST", "dst"),
        ("Core runs", "cores"),
        ("Core analysis", "core_samples"),
        ("Core photos", "core_photos"),
        ("Petrophysics", "petrophysics"),
    ]
    _sec_labels = [lbl for lbl, _ in _SECTION_PICK]
    _sec_default = ["Formation tops", "Directional survey", "Completions"]
    _ca, _cb, _ = st.columns([2, 2, 6])
    if _ca.button("Select all", key="sec_all", use_container_width=True):
        st.session_state["exp_sections"] = _sec_labels
        st.rerun()
    if _cb.button("Clear all", key="sec_none", use_container_width=True):
        st.session_state["exp_sections"] = []
        st.rerun()
    # Don't pass default once the key is set via the buttons (Streamlit forbids
    # a keyed widget having both a default and a session-state value).
    _seckw = {} if "exp_sections" in st.session_state else {"default": _sec_default}
    try:
        _picked = st.pills(
            "Data sections", _sec_labels, selection_mode="multi",
            key="exp_sections", label_visibility="collapsed", **_seckw)
    except (AttributeError, TypeError):
        _picked = st.multiselect(
            "Data sections", _sec_labels,
            key="exp_sections", label_visibility="collapsed", **_seckw)
    _picked = set(_picked or [])
    selected = {"wells"} | {key for lbl, key in _SECTION_PICK if lbl in _picked}

    connectors = {"database", "snowflake_share"}
    for group, fmts in FORMAT_GROUPS:
        st.markdown(f"### {group}")
        grid = [f for f in fmts if f not in connectors]
        for i in range(0, len(grid), 3):
            cols = st.columns(3)
            for col, fmt in zip(cols, grid[i:i + 3]):
                with col:
                    _render_format_card(fmt, engine, wells, uwis, source,
                                        out_dir, basename, selected)
        for fmt in fmts:
            if fmt in connectors:
                _render_connector(fmt, engine, wells)

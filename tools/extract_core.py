"""
extract_core.py
===============
Streamlit-free home for the file header-extraction logic.

This module is imported BOTH by page_workbench (the UI) and, crucially, by the
pipeline's process-pool workers. It deliberately imports NOTHING from streamlit
or page_workbench so a `ProcessPoolExecutor` worker can `import extract_core`
and parse a file in a clean subprocess without dragging the whole UI (and its
streamlit import) into every child process.

`_extract_fields` is the single source of truth for header extraction — it is
defined here and re-exported by page_workbench (`from extract_core import
_extract_fields`), so there is exactly one copy of the dispatch logic. The
per-format parsers it uses (segy_header, modules.pdf_survey_catalog,
modules.lis_catalog, modules.shapefile_catalog, modules.csv_catalog,
modules.file_summarizer, lasio, dlisio) are imported lazily inside the function
in their own try/except, so they resolve at call time in whatever process and
degrade gracefully if a given parser is unavailable.
"""
import os
import re
import time
from pathlib import Path

# ── Extension sets (canonical) ─────────────────────────────────────────────
# Defined here so the parser and the UI share one definition; page_workbench
# imports these back. Add a new format extension here, not in two places.
PDF_EXTS    = {".pdf"}
LAS_EXTS    = {".las"}
DLIS_EXTS   = {".dlis", ".dlf", ".dis"}
LIS_EXTS    = {".lis"}
SEGY_EXTS   = {".segy", ".sgy", ".seg"}
P190_EXTS   = {".p190", ".p90", ".p1"}
SHP_EXTS    = {".shp", ".gpkg", ".kml", ".kmz"}
OFFICE_EXTS = {".xlsx", ".xls", ".xlsm", ".docx", ".doc",
               ".ods", ".odt", ".odp"}   # ODF: routed through summarize()
CSV_EXTS    = {".csv", ".tsv"}
IMAGE_EXTS  = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
WITSML_EXTS = {".xml"}
JSON_LOG_EXTS = {".json"}
LOG_EXTS    = LAS_EXTS | DLIS_EXTS | LIS_EXTS


def _clean_survey_name(raw: str) -> str:
    """Strip volume/acquisition metadata from a SEG-Y survey name so the same
    survey's variants (different sample rate, vintage, processing) collapse to
    one survey identity for dedup. Volume detail belongs on dv_seis_line, not in
    the survey name.

    SEG-Y text headers pack everything on one line, e.g.
        "CENTRAL EROMANGA BASIN 80 SEISMIC SURVEY, AUG, 1980, SAMPLE INT:4M"
    We keep the survey identity and cut at the first metadata marker (a date
    token, SAMPLE INT, or a trailing processing tag). Defensive against the
    messy free-text these headers contain (stray control/garbage chars,
    inconsistent spacing). Falls back to the trimmed raw name if nothing matches.
    """
    if not raw:
        return raw
    s = str(raw)
    # Normalize whitespace and drop non-printable/garbage chars (e.g. the stray
    # '¦' seen in real headers) so the cut points match reliably.
    s = re.sub(r"[^\x20-\x7E]", " ", s)          # keep printable ASCII only
    s = re.sub(r"\s+", " ", s).strip()
    # Cut at the first metadata marker. Markers, in priority order:
    #   - ", <MONTH>"  (date: JAN..DEC)  - ", <4-digit year>"
    #   - "SAMPLE INT" / "SAMPLE RATE"   - ", NANOSECOND"/processing tails
    _markers = [
        r",\s*(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\b",
        r",\s*(?:19|20)\d{2}\b",
        r"\bSAMPLE\s*(?:INT|RATE)\b",
        r",\s*\d+\s*M?S\b",                       # ", 4MS" trailing sample tag
    ]
    cut = len(s)
    for pat in _markers:
        m = re.search(pat, s, re.IGNORECASE)
        if m and m.start() < cut:
            cut = m.start()
    cleaned = s[:cut].strip().rstrip(",").strip()
    return cleaned or s          # never return empty — fall back to full string


def _normalize_uwi(v):
    """Normalize a UWI to bare digits (no dashes/spaces/dots), the canonical
    form used throughout the system (dv_well, gold, scout-ticket resolution).
    A CSV/LAS UWI like '42-329-10001-0000' or '17-031-10035-0000' must become
    '42329100010000' so it matches the bare-14 keys everywhere else.
    Returns None for empty/missing. Leaves non-numeric ids (rare) as-is after
    stripping separators, so a genuinely alphanumeric id isn't destroyed.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("none", "nan"):
        return None
    import re as _re
    stripped = _re.sub(r"[\s\-\.]", "", s)
    return stripped or None


def _identity_from_filename(fpath: str) -> dict:
    """Derive well identity from a filename when the file's own header lacks it.
    Common for binary log formats (DLIS/LIS) where the origin/header carries no
    UWI or a junk internal id, but the filename is meaningful — e.g.
    'WHITING_BURK_177.lis' or 'ANADARKO_BURK_145.dlis'.

    Returns {well_name, operator_hint}. well_name is the filename stem (cleaned);
    operator_hint is the first underscore/space-delimited token if it looks like
    a name (alphabetic), else None. Callers decide whether to trust the hint.
    """
    stem = os.path.splitext(os.path.basename(fpath))[0].strip()
    out = {"well_name": stem or None, "operator_hint": None}
    parts = re.split(r"[_\s]+", stem)
    if parts and parts[0].isalpha() and len(parts[0]) > 2:
        out["operator_hint"] = parts[0].title()
    return out


def _shp_outline_wkt(fpath: str):
    """Read a (seismic) shapefile's geometry and return a single WGS84 WKT
    footprint suitable for a SQL Server geography column.

    - dissolves all features into one geometry (a survey may be several polygons
      or many 2D lines) so dv_seis_set gets one outline per survey file
    - reprojects to EPSG:4326 (geography SRID)
    - fixes ring orientation: shapefiles are commonly wound clockwise, which a
      geography column interprets as the COMPLEMENT (the whole Earth minus the
      polygon). We detect that (a valid-earth polygon can't exceed half the
      globe) via shapely and flip with orient(); the DB side also guards by
      area, but emitting correct WKT here avoids a whole-Earth round-trip.

    Returns a WKT string, or None if geometry can't be read.
    """
    try:
        import geopandas as gpd
        from shapely.ops import unary_union
        from shapely.geometry.polygon import orient
    except Exception:
        return None
    # Above this feature count, dissolving every geometry (unary_union) is the
    # dominant parse cost — a handful of huge shapefiles (e.g. 29k lease blocks)
    # can take seconds in a single worker. For those the exact dissolved outline
    # is overkill for a map footprint, so use the vectorized extent (total_bounds
    # → bbox), which is O(n) and effectively instant.
    SHP_OUTLINE_CAP = 2000
    try:
        gdf = gpd.read_file(fpath)
        if gdf.empty:
            return None
        # reproject to WGS84 lon/lat so the WKT matches geography SRID 4326
        if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)
        if len(gdf) > SHP_OUTLINE_CAP:
            from shapely.geometry import box
            minx, miny, maxx, maxy = gdf.total_bounds
            geom = box(minx, miny, maxx, maxy)     # survey extent, no dissolve
        else:
            geom = unary_union(list(gdf.geometry))  # exact footprint (small file)
        if geom is None or geom.is_empty:
            return None
        # Reorient polygonal geometry to CCW exterior (geography's left-hand
        # rule). orient(sign=1.0) makes exteriors CCW, holes CW. Lines are
        # returned unchanged. Applies per-polygon for multipolygons.
        gt = geom.geom_type
        if gt == "Polygon":
            geom = orient(geom, sign=1.0)
        elif gt == "MultiPolygon":
            from shapely.geometry import MultiPolygon
            geom = MultiPolygon([orient(p, sign=1.0) for p in geom.geoms])
        return geom.wkt
    except Exception:
        return None


def _extract_fields(fpath: str, fext: str) -> dict:
    """Extract header fields from a file. Returns flat dict.

    Returns a dict with skip_reason set (and all other fields at defaults)
    when the file should be skipped rather than extracted. Callers check
    for skip_reason before attempting any further processing. Skipped files
    are written with HEADER_EXTRACTED='S' so they are not re-attempted.
    """
    # ── Size gate — check before ANY extraction attempt ───────────────────────
    # Large files can hang extractors that parse entire file structures
    # (openpyxl XML parse, pdfplumber on scanned PDFs). Check file size
    # first and skip immediately if over the per-format threshold.
    # Thresholds are conservative — legitimate petroleum data files rarely
    # exceed these sizes for their header-only content.
    _SIZE_LIMITS_MB = {
        ".xlsx": 50,   # openpyxl XML parse scales with file size
        ".xls":  50,   # xlrd same issue
        ".xlsm": 50,
        ".pdf":  150,  # pdfplumber slow on large scanned PDFs
        ".docx": 100,  # python-docx is fast but guard against edge cases
        ".doc":  100,
        ".xml":  100,  # WITSML files with thousands of stations can be large
        ".json": 200,  # OSDU JSON with large production volumes or log data
    }
    _limit_mb = _SIZE_LIMITS_MB.get(fext)
    if _limit_mb is not None:
        try:
            _size_mb = Path(fpath).stat().st_size / (1024 * 1024)
            if _size_mb > _limit_mb:
                return {
                    "file_category": "UNKNOWN",
                    "report_type":   "UNKNOWN",
                    "confidence":    0.0,
                    "uwi": None, "well_name": None, "operator": None,
                    "well_field": None, "state": None, "county": None,
                    "latitude": None, "longitude": None,
                    "total_depth": None, "spud_date": None,
                    "rig_release": None, "survey_type": None,
                    "contractor": None,
                    "survey_name": None, "line_name": None,
                    "seis_set_type": None, "survey_date": None,
                    "bbox_min_lat": None, "bbox_max_lat": None,
                    "bbox_min_lon": None, "bbox_max_lon": None,
                    "epsg_code": None, "sample_interval": None,
                    "trace_count": None, "shot_first": None,
                    "shot_last": None,
                    "skip_reason": (
                        f"TOO_LARGE: {_size_mb:.1f} MB exceeds "
                        f"{_limit_mb} MB limit for {fext}"
                    ),
                }
        except OSError:
            pass  # Can't stat — let extraction proceed and fail naturally
    fields = {
        "file_category": "UNKNOWN",
        "report_type":   "UNKNOWN",
        "confidence":    0.0,
        # Well fields
        "uwi": None, "well_name": None, "operator": None,
        "well_field": None, "state": None, "county": None,
        "latitude": None, "longitude": None,
        "total_depth": None, "spud_date": None,
        "rig_release": None, "survey_type": None, "contractor": None,
        # Log curve fields — populated by LAS, DLIS, LIS, WITSML log, JSON log
        "curve_names": [], "n_curves": 0,
        # Seis fields
        "survey_name": None, "line_name": None,
        "seis_set_type": None, "survey_date": None,
        "bbox_min_lat": None, "bbox_max_lat": None,
        "bbox_min_lon": None, "bbox_max_lon": None,
        "epsg_code": None, "sample_interval": None,
        "trace_count": None, "shot_first": None, "shot_last": None,
        # 3D-specific geometry fields
        "il_min": None, "il_max": None,   # inline range
        "xl_min": None, "xl_max": None,   # crossline range
        "survey_outline": None,            # WKT polygon of survey footprint (WGS84)
    }

    try:
        if fext == ".pdf":
            fields["file_category"] = "WELL"
            try:
                # Single owner of PDF→fields resolution (classify + extended
                # classify + scout grid header). See pdf_survey_catalog.
                from dataview.file_catalog.pdf_survey_catalog import resolve_pdf_fields
                cl = resolve_pdf_fields(fpath)
                fields.update({
                    "report_type": cl.get("report_type","UNKNOWN"),
                    "uwi":         cl.get("uwi"),
                    "well_name":   cl.get("well_name"),
                    "operator":    cl.get("operator"),
                    "well_field":  cl.get("field"),
                    "state":       cl.get("state"),
                    "county":      cl.get("county"),
                    "latitude":    cl.get("latitude"),
                    "longitude":   cl.get("longitude"),
                    "total_depth": cl.get("total_depth"),
                    "spud_date":   cl.get("spud_date"),
                    "rig_release": cl.get("rig_release"),
                    "survey_type": cl.get("survey_type"),
                    "contractor":  cl.get("contractor"),
                    "confidence":  float(cl.get("confidence") or 0),
                })
            except Exception:
                pass

        elif fext == ".las":
            fields["file_category"] = "WELL"
            fields["report_type"]   = "WELL_LOG"
            try:
                import lasio
                # header-only: skip the curve-data array (faster, we only need
                # the ~Well and ~Curve header sections).
                las = lasio.read(fpath, ignore_data=True)
                def _wv(m):
                    try:
                        v = str(las.well[m].value).strip()
                        return v if v and v.lower() not in (
                            "","unknown","none","--") else None
                    except Exception:
                        return None
                # identity fields (top level — what the catalog row needs).
                # operator = COMP/PROV (well owner); SRVC is the service company
                # → contractor. Keep them distinct.
                fields.update({
                    "uwi":         _wv("UWI") or _wv("API"),
                    "well_name":   _wv("WELL"),
                    "operator":    _wv("COMP") or _wv("PROV"),
                    "well_field":  _wv("FLD")  or _wv("FIELD"),
                    "state":       _wv("STAT") or _wv("STATE"),
                    "county":      _wv("CNTY") or _wv("COUNTY"),
                    "latitude":    _wv("SLAT") or _wv("LAT"),
                    "longitude":   _wv("SLON") or _wv("LON") or _wv("LONG"),
                    "total_depth": _wv("STOP") or _wv("TD"),
                    "spud_date":   _wv("SPUD") or _wv("DATE"),
                    "contractor":  _wv("SRVC") or _wv("SERVICE"),
                })
                # curve/log details (format-specific block — what a log
                # consumer needs). Curve names come from the ~Curve header.
                try:
                    cnames = [c.mnemonic for c in las.curves]
                except Exception:
                    cnames = []
                fields["details"] = {
                    "curves":      len(cnames),
                    "curve_names": cnames,
                    "depth_start": _wv("STRT"),
                    "depth_stop":  _wv("STOP"),
                    "depth_step":  _wv("STEP"),
                    "null_value":  _wv("NULL"),
                }
            except Exception:
                pass

        elif fext in DLIS_EXTS:
            # DLIS origins frequently have NO UWI (well_id often empty) and an
            # internal log id for the name. The FILENAME is the authoritative
            # identity for DLIS (e.g. ANADARKO_BURK_145.dlis). Verified against
            # ANADARKO_BURK_145.dlis (2026-06-26): well_id empty, origin name
            # 'A/5-1' (junk), filename gives the real identity.
            fields["file_category"] = "WELL"
            fields["report_type"]   = "WELL_LOG"
            try:
                import dlisio, os as _os
                f, *tail = dlisio.dlis.load(fpath)
                lfs = [f] + list(tail)
                origs = list(f.origins)
                o = origs[0] if origs else None
                def _ov(attr):
                    v = str(getattr(o, attr, "") or "").strip() if o else ""
                    return v or None
                stem = _identity_from_filename(fpath)["well_name"]
                # The origin's well_name is frequently an internal log id
                # (e.g. 'A/5-1') rather than the real well. The FILENAME is the
                # authoritative identity for DLIS (e.g. ANADARKO_BURK_145), so
                # prefer the filename; keep the origin name in details.
                _orig_wn = _ov("well_name")
                fields.update({
                    "uwi":        _ov("well_id"),          # often empty in DLIS
                    "well_name":  stem or _orig_wn,        # filename wins
                    "well_field": _ov("field_name"),
                    "operator":   _ov("company"),
                    "contractor": _ov("producer_name"),
                })
                try:
                    fields["details"] = {
                        "logical_files": len(lfs),
                        "channels": sum(len(lf.channels) for lf in lfs),
                        "frames":   sum(len(lf.frames)   for lf in lfs),
                        "origin_well_name": _ov("well_name"),  # internal log id
                    }
                except Exception:
                    pass
                try:
                    for lf in lfs: lf.close()
                except Exception:
                    pass
            except Exception:
                pass

        elif fext in LIS_EXTS:
            # LIS (older than DLIS) typically yields curves but NO header
            # identity — classify_lis returns null well_name/uwi/operator. Like
            # DLIS, the FILENAME is the authoritative identity (e.g.
            # WHITING_BURK_177.lis). Verified against WHITING_BURK_177.lis
            # (2026-06-26): header identity all null, 4 curves / 2 frames.
            fields["file_category"] = "WELL"
            fields["report_type"]   = "WELL_LOG"
            try:
                import os as _os
                from dataview.file_catalog.lis_catalog import classify_lis
                cl = classify_lis(fpath)
                stem = _identity_from_filename(fpath)["well_name"]
                fields.update({
                    "uwi":         cl.get("uwi"),
                    "well_name":   cl.get("well_name") or stem,  # filename fallback
                    "operator":    cl.get("operator"),
                    "well_field":  cl.get("well_field"),
                    "state":       cl.get("state"),
                    "county":      cl.get("county"),
                    "contractor":  cl.get("contractor"),
                    "confidence":  float(cl.get("confidence") or 0),
                })
                fields["details"] = {
                    "curves":      cl.get("n_curves", 0),
                    "curve_names": cl.get("curve_names", []),
                    "frames":      cl.get("n_frames", 0),
                    "depth_start": cl.get("depth_start"),
                    "depth_stop":  cl.get("depth_stop"),
                }
            except Exception:
                pass

        elif fext in SEGY_EXTS:
            fields["file_category"] = "SEIS"
            fields["report_type"]   = "SEISMIC"
            try:
                import re as _re
                from dataview.file_catalog.segy_header import read_segy_header
                h = read_segy_header(fpath)
                if h.get("ok"):
                    n_traces = h.get("n_traces") or 0
                    fields["trace_count"] = n_traces
                    if h.get("sample_interval_us"):
                        fields["sample_interval"] = h["sample_interval_us"]
                    # 2D/3D from the real inline/crossline grid; fall back to the
                    # old trace-count rule only when geometry was flat/missing
                    _dims = (h.get("dims") or "").replace("?", "")
                    if _dims not in ("2D", "3D"):
                        _dims = "3D" if n_traces > 10000 else "2D"
                    fields["seis_set_type"] = _dims
                    is_3d = _dims == "3D"
                    # header fields the segyio path never captured
                    if h.get("n_samples"):
                        fields["n_samples"] = h["n_samples"]
                    if h.get("format_desc"):
                        fields["sample_format"] = h["format_desc"]
                    if h.get("measurement_system"):
                        fields["measurement_system"] = h["measurement_system"]

                    # ── Text header — survey name, contractor, CRS hint ───
                    _epsg_hint = None
                    txt = h.get("textual_header") or ""
                    try:
                        m = _re.search(
                            r"(?:LINE|SURVEY|PROJECT|NAME)[:\s]+([^\r\n]+?)\s*$",
                            txt, _re.IGNORECASE | _re.MULTILINE)
                        if m:
                            _raw_name = m.group(1).strip()
                            # Root-cause fix: SEG-Y survey lines pack survey +
                            # acquisition + processing detail into one free-text
                            # line, e.g.
                            #   "CENTRAL EROMANGA BASIN 80 SEISMIC SURVEY, AUG,
                            #    1980, SAMPLE INT:4M"
                            # The trailing date / SAMPLE INT is VOLUME-level, not
                            # survey identity — keeping it makes the same survey's
                            # volumes look like different surveys. Cut the name at
                            # the first metadata marker so survey_name is just the
                            # survey; volume detail (sample rate) lives on
                            # dv_seis_line. _clean_survey_name is defined at module
                            # top; falls back to the raw name if nothing matches.
                            _clean = _clean_survey_name(_raw_name)
                            fields["survey_name"] = _clean[:255]
                            # If the header carried a sample interval in-text and
                            # we didn't already get one from the binary header,
                            # capture it from the stripped tail.
                            if not fields.get("sample_interval"):
                                _si = _re.search(
                                    r"SAMPLE\s*INT[^\d]*(\d+(?:\.\d+)?)",
                                    _raw_name, _re.IGNORECASE)
                                if _si:
                                    try:
                                        fields["sample_interval"] = float(_si.group(1))
                                    except ValueError:
                                        pass
                        m2 = _re.search(
                            r"CONTRACTOR[:\s]+([A-Za-z0-9_\-\s\.]+)",
                            txt, _re.IGNORECASE)
                        if m2:
                            fields["contractor"] = m2.group(1).strip()[:255]
                        m3 = _re.search(r"EPSG[:\s]*(\d{4,6})", txt,
                                        _re.IGNORECASE)
                        if m3:
                            _epsg_hint = int(m3.group(1))
                        else:
                            mz = _re.search(
                                r"UTM[_\-\s]*(?:ZONE[_\-\s]*)?(\d{1,2})\s*([NS]?)",
                                txt, _re.IGNORECASE)
                            if mz:
                                zone_num = int(mz.group(1))
                                hemi = mz.group(2).upper() or "N"
                                _epsg_hint = (32600 + zone_num
                                              if hemi != "S"
                                              else 32700 + zone_num)
                    except Exception:
                        pass

                    # ── Inline / crossline range (3D only) ─────────
                    ilr = h.get("inline_range")
                    xlr = h.get("crossline_range")
                    if is_3d and ilr:
                        fields["il_min"] = int(ilr[0])
                        fields["il_max"] = int(ilr[1])
                    if is_3d and xlr:
                        fields["xl_min"] = int(xlr[0])
                        fields["xl_max"] = int(xlr[1])

                    # CDP points come back already coordinate-scalar-applied, so
                    # the reprojection/hull block below consumes xs/ys exactly as
                    # the segyio path did — just without the re-scaling step.
                    xs, ys = [], []
                    for _px, _py in (h.get("cdp_points") or []):
                        if _px != 0 and _py != 0:
                            xs.append(_px)
                            ys.append(_py)

                    if xs and ys:
                        # ── Coordinate system detection ───────────────────────
                        # If all X values are in [-180, 180] and Y in [-90, 90]
                        # the coords are already geographic (WGS84 or similar).
                        # Otherwise they are projected (UTM, state plane, etc.)
                        # and need reprojection before storing as lat/lon.
                        _is_geo = (
                            all(-180 <= v <= 180 for v in xs) and
                            all(-90  <= v <= 90  for v in ys)
                        )

                        if _is_geo:
                            lons, lats = xs, ys
                            if not _epsg_hint:
                                fields["epsg_code"] = 4326
                            else:
                                fields["epsg_code"] = _epsg_hint
                        else:
                            # Projected coordinates — attempt reprojection.
                            # Use the EPSG hint from the text header if found,
                            # otherwise try to infer the UTM zone from the
                            # coordinate values themselves (works for most
                            # petroleum surveys in WGS84 UTM).
                            lons, lats = [], []
                            _src_epsg = _epsg_hint
                            if not _src_epsg:
                                # Infer UTM zone from median easting.
                                # UTM easting is 100,000–900,000 m;
                                # zone = floor((lon + 180) / 6) + 1.
                                # We can reverse: median_x ≈ 500,000 (central
                                # meridian) + (zone-1)*6 - 180 degrees offset.
                                # Rough but works for most cases.
                                try:
                                    med_x = sorted(xs)[len(xs) // 2]
                                    med_y = sorted(ys)[len(ys) // 2]
                                    # Easting in UTM is typically 100k-900k
                                    if 100_000 < abs(med_x) < 1_000_000:
                                        # Deduce zone from rough longitude
                                        approx_lon = (med_x - 500_000) / 111_320
                                        zone = int((approx_lon + 180) / 6) + 1
                                        zone = max(1, min(60, zone))
                                        _src_epsg = (32600 + zone
                                                     if med_y >= 0
                                                     else 32700 + zone)
                                except Exception:
                                    pass

                            if _src_epsg:
                                fields["epsg_code"] = _src_epsg
                                try:
                                    from pyproj import Transformer
                                    _tf = Transformer.from_crs(
                                        f"EPSG:{_src_epsg}", "EPSG:4326",
                                        always_xy=True)
                                    for _x, _y in zip(xs, ys):
                                        _lon, _lat = _tf.transform(_x, _y)
                                        if (-180 <= _lon <= 180 and
                                                -90 <= _lat <= 90):
                                            lons.append(_lon)
                                            lats.append(_lat)
                                except Exception:
                                    # pyproj not available or transform failed —
                                    # store raw values and flag for review
                                    lons, lats = xs, ys
                                    fields["epsg_code"] = _src_epsg
                            else:
                                # Can't determine CRS — store raw and flag
                                lons, lats = xs, ys

                        if lons and lats:
                            fields.update({
                                "bbox_min_lon": min(lons),
                                "bbox_max_lon": max(lons),
                                "bbox_min_lat": min(lats),
                                "bbox_max_lat": max(lats),
                            })

                            # ── Survey outline polygon (WKT) ──────────────────
                            # Convex hull of the sampled points gives a good
                            # approximation of the survey footprint for plotting.
                            # For 2D lines this is effectively the line extent;
                            # for 3D it's the survey polygon.
                            # Requires shapely — skip silently if unavailable.
                            try:
                                from shapely.geometry import (
                                    MultiPoint, mapping)
                                from shapely import wkt as _swkt
                                pts = MultiPoint(
                                    list(zip(lons, lats)))
                                hull = pts.convex_hull
                                if not hull.is_empty:
                                    fields["survey_outline"] = hull.wkt
                            except Exception:
                                pass

            except Exception:
                pass

        elif fext in P190_EXTS:
            # UKOOA P1/90 seismic navigation. Header records use fixed CODES
            # (H0100 survey area, H0102 vessel, H0103 source, H0200 date), NOT
            # free-text keywords. Data records start with 'S' (source centre) or
            # 'R' (receiver). Coordinates are commonly PROJECTED easting/northing
            # (UTM/grid), not lat/long — so we expose them as a projected bbox in
            # details rather than mislabelling them as lon/lat.
            # Verified against sample_2d.p190 / sample_3d.p190 (UKOOA P1/90).
            fields["file_category"] = "SEIS"
            fields["report_type"]   = "SEISMIC"
            try:
                import os as _os
                pts = []          # (easting, northing) from S/R records
                survey = vessel = source = sdate = None
                with open(fpath, "r", errors="replace") as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        rec = line[0].upper()
                        if rec == "H":
                            code = line[1:5]                 # e.g. '0100'
                            val  = line[5:].strip()
                            # strip a trailing lone counter/zero column
                            val  = re.sub(r"\s{2,}\d+(\s+\d+)*\s*$", "", val).strip()
                            # strip the leading label words (the UKOOA code's
                            # human label precedes the actual value), e.g.
                            # 'SURVEY AREA SOUTH CHINA SEA' -> 'SOUTH CHINA SEA',
                            # 'VESSEL DETAILS M.V.CONTRACTOR' -> 'M.V.CONTRACTOR'
                            for _lbl in ("SURVEY AREA", "VESSEL DETAILS",
                                         "SOURCE DETAILS", "STREAMER DETAILS",
                                         "SURVEY DATE"):
                                if val.upper().startswith(_lbl):
                                    val = val[len(_lbl):].strip()
                                    break
                            if code == "0100" and not survey:
                                survey = val[:255]
                            elif code == "0102" and not vessel:
                                vessel = val[:255]
                            elif code == "0103" and not source:
                                source = val[:255]
                            elif code == "0200" and not sdate:
                                sdate = val[:255]
                        elif rec in ("S", "R"):
                            # Coordinate columns vary by UKOOA P1/90 revision.
                            # KNOWN LIMITATION: some variants (e.g. sample_3d)
                            # pack easting+northing with no separator
                            # ('5627450.06372300.0'), which neither the
                            # fixed-width nor whitespace path below recovers.
                            # Identity (survey/vessel/date/2D-3D) is parsed from
                            # the H records regardless; the coordinate bbox is
                            # best-effort. Verified: sample_2d parses points,
                            # sample_3d gets identity but not the bbox.
                            e = n = None
                            try:
                                e = float(line[46:55]); n = float(line[55:64])
                            except Exception:
                                parts = line.split()
                                for i in range(len(parts) - 1):
                                    try:
                                        _e = float(parts[i]); _n = float(parts[i+1])
                                        if abs(_e) > 1000 or abs(_n) > 1000:
                                            e, n = _e, _n; break
                                    except ValueError:
                                        continue
                            if e is not None and n is not None and (e or n):
                                pts.append((e, n))

                if survey:
                    fields["survey_name"] = survey
                if vessel:
                    fields["contractor"] = vessel
                # 2D/3D: P1/90 doesn't encode it directly; infer from filename
                stem = _os.path.basename(fpath).lower()
                fields["seis_set_type"] = ("3D" if "3d" in stem
                                           else "2D" if "2d" in stem else None)
                det = {"survey_area": survey, "vessel": vessel,
                       "source": source, "survey_date": sdate,
                       "n_points": len(pts)}
                if pts:
                    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
                    fields["trace_count"] = len(pts)
                    # Geographic only if values fall in lat/long ranges;
                    # otherwise they're projected E/N — keep in details, don't
                    # write bogus lon/lat.
                    _geo = (all(-180 <= v <= 180 for v in xs) and
                            all(-90  <= v <= 90  for v in ys))
                    if _geo:
                        fields.update({
                            "bbox_min_lon": min(xs), "bbox_max_lon": max(xs),
                            "bbox_min_lat": min(ys), "bbox_max_lat": max(ys),
                        })
                    else:
                        det["projected_bbox"] = {
                            "min_e": min(xs), "max_e": max(xs),
                            "min_n": min(ys), "max_n": max(ys),
                        }
                fields["details"] = det
            except Exception:
                pass

        elif fext in SHP_EXTS:
            # Default category is set from the classifier below, NOT hardcoded to
            # SEIS. A shapefile is only "SEIS" if it's genuinely a seismic feature
            # type — otherwise a lease/field/boundary shapefile (which often has a
            # "survey" column meaning a LAND survey) would fabricate a bogus
            # seismic survey in FILE_SEIS_HEADER.
            fields["file_category"] = "UNKNOWN"
            fields["report_type"]   = "SHAPEFILE"
            try:
                from dataview.mapping.shapefile_catalog import classify_shapefile
                cl = classify_shapefile(fpath)
                fields["confidence"] = float(cl.get("confidence") or 0)
                if cl.get("crs_epsg"):
                    fields["epsg_code"] = cl["crs_epsg"]
                if cl.get("bounds"):
                    b = cl["bounds"]
                    fields.update({
                        "bbox_min_lon": b.get("minx"),
                        "bbox_max_lon": b.get("maxx"),
                        "bbox_min_lat": b.get("miny"),
                        "bbox_max_lat": b.get("maxy"),
                    })
                # Pull sample values from DBF attribute extraction
                sd = cl.get("sample_data", {})
                if sd.get("sample_uwis"):
                    fields["uwi"] = sd["sample_uwis"][0]
                if sd.get("sample_well_names"):
                    fields["well_name"] = sd["sample_well_names"][0]
                if sd.get("top_operators"):
                    fields["operator"] = sd["top_operators"][0]
                if sd.get("sample_fields"):
                    fields["well_field"] = sd["sample_fields"][0]
                if sd.get("sample_surveys"):
                    fields["survey_name"] = sd["sample_surveys"][0]
                # Map feature_type → file_category. Only genuine seismic feature
                # types become SEIS (→ FILE_SEIS_HEADER). WELL → WELL. Everything
                # else routes to its own spatial table (field/lease/boundary/
                # pipeline) and carries its footprint WKT in spatial_outline so
                # promote can build a geography column. _shp_outline_wkt reorients
                # inverted rings (shapefiles are commonly CW; geography wants CCW)
                # so the WKT yields a valid, correctly-sized geography — not the
                # whole-Earth complement a raw CW polygon produces.
                ft = cl.get("feature_type", "")
                # map classifier feature_type -> file_category for routing
                _FT_CATEGORY = {
                    "WELL":       "WELL",
                    "SEISMIC_2D": "SEIS",
                    "SEISMIC_3D": "SEIS",
                    "FIELD":      "FIELD",
                    "LEASE":      "LAND_TRACT",
                    "BOUNDARY":   "BOUNDARY",
                    "PIPELINE":   "PIPELINE",
                }
                cat = _FT_CATEGORY.get(ft, "SPATIAL")
                fields["file_category"] = cat
                if cat == "SEIS":
                    _wkt = _shp_outline_wkt(fpath)
                    if _wkt:
                        fields["survey_outline"] = _wkt   # seismic's own slot
                elif cat in ("FIELD", "LAND_TRACT", "BOUNDARY", "PIPELINE"):
                    _wkt = _shp_outline_wkt(fpath)
                    if _wkt:
                        fields["spatial_outline"] = _wkt  # generic spatial slot
                # canonical details block — the spatial metadata that defines a
                # shapefile (geometry, feature count, CRS, attribute columns).
                fields["details"] = {
                    "feature_type":  ft or None,
                    "feature_count": cl.get("feature_count"),
                    "geometry_type": cl.get("geometry_type"),
                    "crs_epsg":      cl.get("crs_epsg"),
                    "attributes":    cl.get("attributes", []),
                    "bounds":        cl.get("bounds"),
                }
            except Exception:
                pass

        elif fext in CSV_EXTS:
            # Opt-in only: CSV/TSV are never in the default scan set (ALL_EXTS),
            # so a file reaches here only when '.csv'/'.tsv' was hand-entered in
            # the Formats-to-scan box. Dedicated delimited-table extractor —
            # NOT the Office/Excel summarizer, which yields nothing on raw CSV.
            #
            # The import is tried SEPARATELY from the parse: a missing module
            # (csv_catalog deployed to ROOT instead of modules\, or stale
            # __pycache__) is a deploy error, not a per-file parse error — it
            # must surface as a visible issue, not silently leave file_category
            # at 'UNKNOWN' (which skips the FILE_WELL_HEADER write entirely).
            _classify_csv = None
            try:
                from dataview.file_catalog.csv_catalog import classify_csv as _classify_csv
            except Exception as _imp_e:
                fields["report_type"]  = "CSV_NOLOADER"
                fields["extract_error"] = (
                    "csv_catalog not importable — deploy to modules\\, not "
                    f"ROOT; clear __pycache__ ({type(_imp_e).__name__})")
            if _classify_csv is not None:
                try:
                    cl = _classify_csv(fpath)
                    fields["file_category"] = cl.get("file_category", "OTHER")
                    fields["report_type"]   = cl.get("report_type", "CSV")
                    fields.update({
                        "uwi":         cl.get("uwi"),      # raw; writer bare-14s it
                        "well_name":   cl.get("well_name"),
                        "operator":    cl.get("operator"),
                        "well_field":  cl.get("well_field"),
                        "state":       cl.get("state"),
                        "county":      cl.get("county"),
                        "latitude":    cl.get("latitude"),
                        "longitude":   cl.get("longitude"),
                        "total_depth": cl.get("total_depth"),
                        "spud_date":   cl.get("spud_date"),
                        "confidence":  float(cl.get("confidence") or 0),
                    })
                except Exception as _csv_e:
                    fields["extract_error"] = (
                        f"csv parse failed: {type(_csv_e).__name__}: {_csv_e}")[:200]

        elif fext in OFFICE_EXTS:
            fields["file_category"] = "WELL"
            fields["report_type"]   = "OFFICE"
            try:
                from dataview.file_catalog.file_summarizer import summarize
                s = summarize(fpath)
                fields.update({
                    "uwi":        s.get("uwi"),
                    "well_name":  s.get("well_name"),
                    "operator":   s.get("key_fields", {}).get("operator") or
                                  s.get("key_fields", {}).get("company"),
                    "well_field": s.get("key_fields", {}).get("field"),
                    "confidence": float(
                        s.get("key_fields", {}).get("confidence") or 0),
                })
                # Pull report/doc type — check sheet_detail for known schema
                # names (BOEM_BOREHOLE, KGS_WELL etc.) first, then fall back
                # to generic table_type / doc_type.
                _sheet_detail = s.get("key_fields", {}).get("sheet_detail", [])
                _schema = (_sheet_detail[0].get("table_type")
                           if _sheet_detail else None)
                rt = (_schema or
                      s.get("key_fields", {}).get("report_type") or
                      s.get("key_fields", {}).get("doc_type") or
                      s.get("key_fields", {}).get("table_type"))
                if rt and rt not in ("UNKNOWN", "OTHER"):
                    fields["report_type"] = str(rt)[:50]
            except Exception:
                pass

        elif fext in WITSML_EXTS:
            # WITSML 1.3.1 / 1.4.1 — trajectory, log, mudLog, well, wellbore.
            # Gate: only process files that declare the WITSML namespace to
            # avoid parsing unrelated XML (config files, SVG, RSS, etc.).
            try:
                # Cheap namespace check — read first 500 bytes only.
                _witsml_sig = b"witsml.org/schemas"
                with open(fpath, "rb") as _wf:
                    _head = _wf.read(500)
                if _witsml_sig not in _head:
                    fields["file_category"] = "OTHER"
                    fields["report_type"]   = "XML_OTHER"
                else:
                    from dataview.file_catalog.witsml_catalog import classify_witsml
                    cl = classify_witsml(fpath)
                    fields["file_category"] = cl.get("file_category", "WELL")
                    fields["report_type"]   = cl.get("report_type", "WITSML")
                    fields.update({
                        "uwi":        cl.get("uwi"),
                        "well_name":  cl.get("well_name"),
                        "operator":   cl.get("operator"),
                        "contractor": cl.get("contractor"),
                        "well_field": cl.get("well_field"),
                        "state":      cl.get("state"),
                        "county":     cl.get("county"),
                        "spud_date":  cl.get("spud_date"),
                        "total_depth":cl.get("total_depth"),
                        "confidence": float(cl.get("confidence") or 0),
                    })
                    # Curve names for log objects
                    if cl.get("curve_names"):
                        fields["curve_names"] = cl["curve_names"]
                        fields["n_curves"]    = cl.get("n_curves", 0)

                    # Identity fallback: classify_witsml can return null
                    # identity for object types like trajectory, where the well
                    # name lives in <nameWell> and the well ref in the uidWell
                    # attribute. Read them directly when the classifier missed.
                    if not fields.get("well_name") or not fields.get("uwi"):
                        try:
                            _txt = open(fpath, "r", encoding="utf-8",
                                        errors="replace").read(20000)
                            if not fields.get("well_name"):
                                _m = re.search(
                                    r"<nameWell>\s*([^<]+?)\s*</nameWell>",
                                    _txt, re.IGNORECASE)
                                if _m:
                                    fields["well_name"] = _m.group(1).strip()
                            if not fields.get("uwi"):
                                _m = re.search(r'uidWell\s*=\s*"([^"]+)"',
                                               _txt, re.IGNORECASE)
                                if _m:
                                    fields["uwi"] = _m.group(1).strip()
                        except Exception:
                            pass
            except Exception:
                pass

        elif fext in JSON_LOG_EXTS:
            # OSDU WellLog / Well / WellboreMarkerSet / PressureData /
            # SeismicAcquisitionSurvey and JSON Well Log Format (JSONWLF).
            # Gate: only process files that look like petroleum JSON to
            # avoid parsing unrelated JSON (config, GeoJSON already handled
            # by SHP_EXTS as .geojson, package.json, etc.).
            try:
                import json as _json
                with open(fpath, "r", encoding="utf-8-sig",
                          errors="replace") as _jf:
                    _head_text = _jf.read(512)
                # Must have either an OSDU 'kind' field or known JSONWLF keys
                _looks_petroleum = (
                    '"kind"' in _head_text or
                    '"header"' in _head_text or
                    '"WellLog"' in _head_text or
                    '"wellbore"' in _head_text.lower()
                )
                if not _looks_petroleum:
                    fields["file_category"] = "OTHER"
                    fields["report_type"]   = "JSON_OTHER"
                else:
                    from dataview.file_catalog.json_well_log_catalog import classify_json_well_log
                    cl = classify_json_well_log(fpath)
                    fields["file_category"] = cl.get("file_category", "WELL")
                    fields["report_type"]   = cl.get("report_type", "JSON_LOG")
                    fields.update({
                        "uwi":        cl.get("uwi"),
                        "well_name":  cl.get("well_name"),
                        "operator":   cl.get("operator"),
                        "contractor": cl.get("contractor"),
                        "well_field": cl.get("well_field"),
                        "state":      cl.get("state"),
                        "county":     cl.get("county"),
                        "spud_date":  cl.get("spud_date"),
                        "total_depth":cl.get("total_depth"),
                        "confidence": float(cl.get("confidence") or 0),
                    })
                    # Seismic surveys — route bbox to seis fields
                    if cl.get("file_category") == "SEIS":
                        fields.update({
                            "survey_name":  cl.get("survey_name"),
                            "seis_set_type":cl.get("seis_set_type"),
                            "bbox_min_lat": cl.get("bbox_min_lat"),
                            "bbox_max_lat": cl.get("bbox_max_lat"),
                            "bbox_min_lon": cl.get("bbox_min_lon"),
                            "bbox_max_lon": cl.get("bbox_max_lon"),
                            "epsg_code":    cl.get("epsg_code"),
                        })
                    # Curve names for log objects
                    if cl.get("curve_names"):
                        fields["curve_names"] = cl["curve_names"]
                        fields["n_curves"]    = cl.get("n_curves", 0)
            except Exception:
                pass

    except Exception:
        pass

    # Normalize the UWI to bare digits in ONE place, so every format's UWI is
    # consistent with the bare-14 keys used across the system (dv_well, gold,
    # scout resolution). Source files carry dashed/spaced UWIs; strip them here.
    if fields.get("uwi"):
        fields["uwi"] = _normalize_uwi(fields["uwi"])

    # Clean None/"None"/empty strings
    return {k: (v if v is not None and
                str(v).strip() not in ("","None","nan") else None)
            for k, v in fields.items()}

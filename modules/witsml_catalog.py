"""
modules/witsml_catalog.py
=========================
WITSML 1.3.1 / 1.4.1 file classifier and header extractor.

WITSML (Well Site Markup Language) is an XML standard for petroleum well
data. Files contain one or more WITSML objects — trajectory, log, mudLog,
wellbore, well, tubular, etc. — each with structured metadata.

This module handles the most common WITSML delivery formats:

  trajectory  — directional survey stations (md, incl, azi, tvd)
  log         — wireline / LWD curve data (curve definitions + data rows)
  mudLog      — lithology, gas shows, formation tops

Returns a flat dict compatible with _extract_fields() in page_workbench.py.
The dict shape matches the WELL extractor convention so it writes cleanly
to FILE_WELL_HEADER.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


# ── WITSML XML namespace URIs ─────────────────────────────────────────────────
# WITSML uses versioned namespaces. We strip the namespace prefix for tag
# matching so the extractor works across 1.3.1, 1.4.0, and 1.4.1.1.
_WITSML_NS = {
    "1.3.1":   "http://www.witsml.org/schemas/131",
    "1.4.0":   "http://www.witsml.org/schemas/1series",
    "1.4.1":   "http://www.witsml.org/schemas/1series",
    "1.4.1.1": "http://www.witsml.org/schemas/1series",
}

# Top-level container tags → WITSML object types they hold
# e.g. <trajectorys> holds <trajectory> objects
_CONTAINER_TO_OBJECT = {
    "trajectorys": "trajectory",
    "logs":        "log",
    "mudLogs":     "mudLog",
    "wellbores":   "wellbore",
    "wells":       "well",
    "tubulars":    "tubular",
    "bhaRuns":     "bhaRun",
    "drillReports":"drillReport",
    "rigs":        "rig",
    "fluidsReports": "fluidsReport",
}

# Which WITSML object type maps to which petroleum data category
_OBJECT_CATEGORY = {
    "trajectory":   ("WELL", "DIRECTIONAL_SURVEY"),
    "log":          ("WELL", "WELL_LOG"),
    "mudLog":       ("WELL", "MUD_LOG"),
    "wellbore":     ("WELL", "WELL_HEADER"),
    "well":         ("WELL", "WELL_HEADER"),
    "tubular":      ("WELL", "WELL_HEADER"),
    "bhaRun":       ("WELL", "WELL_HEADER"),
    "drillReport":  ("WELL", "WELL_HEADER"),
    "fluidsReport": ("WELL", "WELL_HEADER"),
}


def _strip_ns(tag: str) -> str:
    """Remove XML namespace URI from a tag: '{http://...}name' → 'name'."""
    return tag.split("}")[-1] if "}" in tag else tag


def _clean(val: Optional[str]) -> Optional[str]:
    """Strip whitespace; return None for empty / sentinel strings."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("", "none", "unknown", "--", "null") else None


def _find_text(element: ET.Element, *tags: str) -> Optional[str]:
    """Search for the first matching tag (case-insensitive local name) in
    the element's immediate children. Returns stripped text or None."""
    tags_lower = [t.lower() for t in tags]
    for child in element:
        if _strip_ns(child.tag).lower() in tags_lower:
            return _clean(child.text)
    return None


def _find_all(element: ET.Element, tag: str) -> list:
    """Return all direct children whose local tag name matches (case-insensitive)."""
    tag_l = tag.lower()
    return [c for c in element if _strip_ns(c.tag).lower() == tag_l]


# ══════════════════════════════════════════════════════════════════════════════
# Object-specific extractors
# ══════════════════════════════════════════════════════════════════════════════

def _extract_trajectory(obj: ET.Element) -> dict:
    """Extract metadata from a WITSML <trajectory> object.

    Captures: well name, wellbore ID, survey tool type, start/end dates,
    first/last station MD and TVD, total station count, depth range.
    Does not load station data — that goes to directional_survey_point
    via a dedicated loader.
    """
    fields: dict = {}

    fields["well_name"]    = _find_text(obj, "nameWell")
    fields["uwi"]          = (obj.get("uidWell") or
                               _find_text(obj, "uidWell"))
    fields["survey_type"]  = _find_text(obj, "typeSurveyTool",
                                         "aziRef", "typeTrajectory")

    # Dates
    fields["spud_date"]    = _find_text(obj, "dTimTrajStart")
    _end                   = _find_text(obj, "dTimTrajEnd")

    # Survey stations — count them and get depth range from first/last
    stations = _find_all(obj, "trajectoryStation")
    fields["n_stations"] = len(stations)

    if stations:
        def _sta_md(sta):
            md_el = next((c for c in sta if _strip_ns(c.tag).lower() == "md"), None)
            try:
                return float(md_el.text) if md_el is not None else None
            except (ValueError, TypeError):
                return None

        mds = [m for m in (_sta_md(s) for s in stations) if m is not None]
        if mds:
            fields["depth_start"] = f"{min(mds):.2f}"
            fields["depth_stop"]  = f"{max(mds):.2f}"
            fields["total_depth"] = max(mds)

    # Common data block — contractor / source
    common = next((c for c in obj if _strip_ns(c.tag).lower() == "commondata"), None)
    if common is not None:
        fields["contractor"] = _find_text(common, "sourceName")

    fields["description"] = (
        f"WITSML Trajectory · {fields.get('n_stations', 0)} stations · "
        f"MD {fields.get('depth_start','?')} – {fields.get('depth_stop','?')} ft · "
        f"Tool: {fields.get('survey_type','unknown')}"
    )
    return fields


def _extract_log(obj: ET.Element) -> dict:
    """Extract metadata from a WITSML <log> object.

    Captures: well name, depth range, curve mnemonics (from logCurveInfo),
    index type, service company, run number. Data rows are not read —
    the mnemonicList in logData provides the curve inventory without
    parsing potentially millions of data points.
    """
    fields: dict = {}

    fields["well_name"]    = _find_text(obj, "nameWell")
    fields["uwi"]          = obj.get("uidWell") or _find_text(obj, "uidWell")
    fields["contractor"]   = _find_text(obj, "serviceCompany")
    fields["index_type"]   = _find_text(obj, "indexType")

    # Depth range
    start = _find_text(obj, "startIndex")
    end   = _find_text(obj, "endIndex")
    if start:
        fields["depth_start"] = start
    if end:
        fields["depth_stop"]  = end
        try:
            fields["total_depth"] = float(end)
        except (ValueError, TypeError):
            pass

    # Curve mnemonics from logCurveInfo elements
    curve_infos = _find_all(obj, "logCurveInfo")
    mnemonics = []
    for ci in curve_infos:
        mn = _find_text(ci, "mnemonic")
        if mn and mn.upper() not in ("DEPT", "DEPTH", "MD", "INDEX"):
            mnemonics.append(mn)

    fields["curve_names"] = mnemonics[:20]
    fields["n_curves"]    = len(mnemonics)

    # Run / pass info
    run = _find_text(obj, "runNumber")
    if run:
        fields["report_type"] = f"WELL_LOG_RUN_{run}"

    fields["description"] = (
        f"WITSML Log · {fields.get('n_curves', 0)} curves · "
        f"MD {start or '?'} – {end or '?'} · "
        f"Curves: {', '.join(mnemonics[:6])}"
        + (" …" if len(mnemonics) > 6 else "")
    )
    return fields


def _extract_mudlog(obj: ET.Element) -> dict:
    """Extract metadata from a WITSML <mudLog> object.

    Captures: well name, mud log company, engineers, depth range, formation
    interval count, gas show summary.
    """
    fields: dict = {}

    fields["well_name"]  = _find_text(obj, "nameWell")
    fields["uwi"]        = obj.get("uidWell") or _find_text(obj, "uidWell")
    fields["contractor"] = _find_text(obj, "mudLogCompany")
    fields["operator"]   = _find_text(obj, "mudLogEngineers")

    start = _find_text(obj, "startMd")
    end   = _find_text(obj, "endMd")
    if start:
        fields["depth_start"] = start
    if end:
        fields["depth_stop"]  = end
        try:
            fields["total_depth"] = float(end)
        except (ValueError, TypeError):
            pass

    # Formation intervals
    intervals = _find_all(obj, "geologyInterval")
    fields["n_intervals"] = len(intervals)

    # Gas show summary — look for chromatograph elements with totGas
    gas_shows = []
    for iv in intervals:
        chrom = next((c for c in iv if _strip_ns(c.tag).lower() == "chromatograph"), None)
        if chrom is not None:
            tg = _find_text(chrom, "totGas")
            top = _find_text(iv, "mdTop")
            if tg and top:
                try:
                    if float(tg) > 500:
                        gas_shows.append(f"{top} ft: {tg} ppm")
                except (ValueError, TypeError):
                    pass

    fields["gas_shows"]  = gas_shows[:5]
    fields["show_count"] = len(gas_shows)

    common = next((c for c in obj if _strip_ns(c.tag).lower() == "commondata"), None)
    if common is not None:
        comment = _find_text(common, "comments")
        if comment:
            fields["description"] = (
                f"WITSML Mud Log · {len(intervals)} formation intervals · "
                f"MD {start or '?'} – {end or '?'} · {comment[:200]}"
            )
            return fields

    fields["description"] = (
        f"WITSML Mud Log · {len(intervals)} formation intervals · "
        f"MD {start or '?'} – {end or '?'}"
        + (f" · {len(gas_shows)} gas show(s)" if gas_shows else "")
    )
    return fields


def _extract_wellbore(obj: ET.Element) -> dict:
    """Extract metadata from a WITSML <well> or <wellbore> object."""
    fields: dict = {}
    fields["well_name"]  = _find_text(obj, "name")
    fields["uwi"]        = obj.get("uid") or obj.get("uidWell")
    fields["operator"]   = _find_text(obj, "operator", "operatorDiv")
    fields["well_field"] = _find_text(obj, "field")
    fields["state"]      = _find_text(obj, "state", "provState")
    fields["county"]     = _find_text(obj, "county")
    fields["contractor"] = _find_text(obj, "contractor")
    fields["spud_date"]  = _find_text(obj, "dTimSpud")

    # Coordinates from wellLocation
    well_loc = next((c for c in obj if _strip_ns(c.tag).lower() == "welllocation"), None)
    if well_loc is not None:
        fields["latitude"]  = _find_text(well_loc, "latitude")
        fields["longitude"] = _find_text(well_loc, "longitude")

    fields["description"] = (
        f"WITSML Well · {fields.get('well_name','unknown')} · "
        f"Operator: {fields.get('operator','?')}"
    )
    return fields


# ── Dispatcher ─────────────────────────────────────────────────────────────────
_OBJECT_EXTRACTORS = {
    "trajectory":   _extract_trajectory,
    "log":          _extract_log,
    "mudlog":       _extract_mudlog,   # matched case-insensitively
    "wellbore":     _extract_wellbore,
    "well":         _extract_wellbore,
}


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def classify_witsml(file_path: str) -> dict:
    """Extract metadata from a WITSML XML file.

    Returns a flat dict with keys matching _extract_fields() in
    page_workbench.py:
        file_category, report_type, object_type, witsml_version,
        n_objects, well_name, uwi, operator, well_field, state, county,
        contractor, spud_date, total_depth, depth_start, depth_stop,
        curve_names, n_curves, n_stations, description, confidence, error

    Handles WITSML 1.3.1, 1.4.0, and 1.4.1.1. A file may contain multiple
    objects of the same type (e.g. multiple trajectories); the first object
    is used for primary field extraction, and n_objects records the total.
    """
    result = {
        "file_category":   "WELL",
        "report_type":     "WITSML",
        "object_type":     None,
        "witsml_version":  None,
        "n_objects":       0,
        "well_name":       None,
        "uwi":             None,
        "operator":        None,
        "well_field":      None,
        "state":           None,
        "county":          None,
        "contractor":      None,
        "spud_date":       None,
        "total_depth":     None,
        "depth_start":     None,
        "depth_stop":      None,
        "curve_names":     [],
        "n_curves":        0,
        "n_stations":      0,
        "description":     "WITSML — no metadata extracted",
        "confidence":      0.0,
        "error":           None,
    }

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
    except ET.ParseError as e:
        result["error"] = f"XML parse error: {e}"
        return result

    # ── Identify version and container ───────────────────────────────────────
    root_local = _strip_ns(root.tag)

    # Version from 'version' attribute on the root container
    version = root.get("version", "")
    if version:
        result["witsml_version"] = version

    # Identify what object type this container holds
    object_type = _CONTAINER_TO_OBJECT.get(root_local)
    if object_type is None:
        # Try to infer from root tag directly (some files omit the container)
        object_type = root_local.lower()

    result["object_type"] = object_type

    # Resolve file_category and report_type
    cat, rtype = _OBJECT_CATEGORY.get(
        object_type, ("WELL", "WITSML"))
    result["file_category"] = cat
    result["report_type"]   = rtype

    # ── Find all objects in the container ────────────────────────────────────
    obj_tag_lower = (object_type or "").lower()
    objects = [c for c in root
               if _strip_ns(c.tag).lower() == obj_tag_lower]

    # Also handle files where the root IS the object (no outer container)
    if not objects and _strip_ns(root.tag).lower() == obj_tag_lower:
        objects = [root]

    result["n_objects"] = len(objects)

    if not objects:
        result["error"] = (
            f"No <{object_type}> objects found in <{root_local}>. "
            "File may use a non-standard structure."
        )
        result["confidence"] = 0.15
        return result

    # ── Extract from the first object ────────────────────────────────────────
    first = objects[0]
    extractor = _OBJECT_EXTRACTORS.get(obj_tag_lower)

    if extractor is not None:
        try:
            obj_fields = extractor(first)
            result.update(obj_fields)
        except Exception as e:
            result["error"] = f"{object_type} extractor: {e}"

    # ── Confidence ────────────────────────────────────────────────────────────
    # Higher if we got well_name or uwi; lower for unknown object types.
    if result.get("well_name") or result.get("uwi"):
        result["confidence"] = 0.90 if extractor is not None else 0.50
    else:
        result["confidence"] = 0.40 if extractor is not None else 0.20

    # Multi-object note
    if len(objects) > 1:
        result["description"] = (
            result.get("description", "") +
            f" [{len(objects)} {object_type} objects in file; "
            "first shown above]"
        )

    return result

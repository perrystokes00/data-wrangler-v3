"""
modules/json_well_log_catalog.py
================================
JSON well log and well header classifier / extractor for two schemas:

  1. OSDU (Open Subsurface Data Universe) — cloud petroleum platform
     standard. Kind strings like:
       osdu:wks:work-product-component--WellLog:1.2.0
       osdu:wks:master-data--Well:1.3.0
       osdu:wks:master-data--Wellbore:1.2.0

  2. JSON Well Log Format (JSONWLF) — open standard from NORCE/NPD,
     increasingly used for LAS replacement. Files have a top-level
     "header" object and a "curves" array.

  3. Generic petroleum JSON — any JSON file that appears to contain
     petroleum well data based on key pattern matching.

Returns a flat dict compatible with _extract_fields() in page_workbench.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


def _clean(val: Any) -> Optional[str]:
    """Stringify, strip, and return None for empty/sentinel values."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("", "none", "null", "unknown", "--") else None


def _safe_float(val: Any) -> Optional[float]:
    """Convert to float or return None."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _extract_osdu_id(id_str: str) -> Optional[str]:
    """Extract the meaningful part from an OSDU ID.

    'osdu:master-data--Organisation:pioneer-natural-resources'
    → 'pioneer-natural-resources'
    """
    if not id_str:
        return None
    parts = str(id_str).split(":")
    if parts:
        return parts[-1].replace("-", " ").title()
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Schema detection
# ══════════════════════════════════════════════════════════════════════════════

def _detect_schema(data: dict) -> str:
    """Classify the JSON structure.

    Returns one of: 'osdu_well_log', 'osdu_well', 'osdu_wellbore',
    'jsonwlf', 'generic', 'unknown'.
    """
    kind = data.get("kind", "")
    if kind:
        kind_lower = kind.lower()
        if "welllog" in kind_lower or "well-log" in kind_lower:
            return "osdu_well_log"
        if "wellboretrajectory" in kind_lower:
            return "osdu_trajectory"
        if "wellboremarkerset" in kind_lower or "marker" in kind_lower:
            return "osdu_marker_set"
        if "wellborepressuredata" in kind_lower or "pressuredata" in kind_lower:
            return "osdu_pressure"
        if "seismicacquisitionsurvey" in kind_lower or "seismicsurvey" in kind_lower:
            return "osdu_seismic"
        if "seismichorizon" in kind_lower:
            return "osdu_horizon"
        if "seismicfault" in kind_lower:
            return "osdu_fault"
        if "wellborecompletion" in kind_lower:
            return "osdu_completion"
        if "wellcoreanalysis" in kind_lower or "coreanalysis" in kind_lower:
            return "osdu_core"
        if "productionvolume" in kind_lower:
            return "osdu_production"
        if "rockfluidorganisation" in kind_lower or "rockfluid" in kind_lower:
            return "osdu_scal"
        if "document" in kind_lower and "osdu" in kind_lower:
            return "osdu_document"
        if "master-data--field:" in kind_lower:
            return "osdu_field"
        if "master-data--reservoir:" in kind_lower:
            return "osdu_reservoir"
        if "master-data--well:" in kind_lower:
            return "osdu_well"
        if "master-data--wellbore:" in kind_lower:
            return "osdu_wellbore"
        if "osdu" in kind_lower:
            return "osdu_generic"

    # JSON Well Log Format (JSONWLF) — has a 'header' + 'curves' structure
    if "header" in data and "curves" in data:
        header = data.get("header", {})
        if isinstance(header, dict) and any(
            k in header for k in ("well", "wellName", "uwi", "api")
        ):
            return "jsonwlf"

    # Generic — check for petroleum-looking keys
    keys_lower = {k.lower() for k in (data.keys() if isinstance(data, dict) else [])}
    petroleum_keys = {"uwi", "api", "well_name", "wellname", "uwi_local",
                      "curves", "logcurves", "formation"}
    if keys_lower & petroleum_keys:
        return "generic"

    return "unknown"


# ══════════════════════════════════════════════════════════════════════════════
# OSDU extractors
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_well_log(d: dict) -> dict:
    """Extract from OSDU WellLog work-product-component."""
    inner = d.get("data", {})
    fields: dict = {}

    # Well log metadata
    fields["well_name"]  = _clean(inner.get("Name") or inner.get("WellName"))
    fields["contractor"] = _clean(
        _extract_osdu_id(inner.get("ServiceCompanyID", "")) or
        inner.get("ServiceCompany")
    )

    # Depth range
    start = _safe_float(inner.get("SamplingStart") or inner.get("TopDepthMeasuredDepth"))
    end   = _safe_float(inner.get("SamplingStop")  or inner.get("BottomDepthMeasuredDepth"))
    unit  = _clean(inner.get("DepthUnit", "ft"))
    if start is not None:
        fields["depth_start"] = f"{start:.2f} {unit}"
    if end is not None:
        fields["depth_stop"]  = f"{end:.2f} {unit}"
        fields["total_depth"] = end

    # Curves
    curves_raw = inner.get("Curves", [])
    if isinstance(curves_raw, list):
        mnemonics = []
        for c in curves_raw:
            if isinstance(c, dict):
                mn = _clean(c.get("Mnemonic") or c.get("CurveID"))
                if mn and mn.upper() not in ("DEPT", "DEPTH", "MD", "INDEX"):
                    mnemonics.append(mn)
        fields["curve_names"] = mnemonics[:20]
        fields["n_curves"]    = len(mnemonics)

    # Logging date
    log_date = _clean(inner.get("LoggingServiceDate") or inner.get("CreationDateTime"))
    if log_date:
        fields["spud_date"] = log_date[:10]  # date part only

    # Wellbore ID — extract UWI from the wellbore reference
    wb_id = _clean(inner.get("WellboreID", ""))
    if wb_id:
        # 'osdu:master-data--Wellbore:42-301-45678-0000-WB01' → '42-301-45678-0000'
        parts = wb_id.split(":")
        if parts:
            raw_id = parts[-1]
            # Strip wellbore suffix (-WB01) to get the well ID
            if "-WB" in raw_id.upper():
                fields["uwi"] = raw_id[:raw_id.upper().rfind("-WB")]
            else:
                fields["uwi"] = raw_id

    n_curves = fields.get("n_curves", 0)
    curves_str = ", ".join(fields.get("curve_names", [])[:6])
    fields["description"] = (
        f"OSDU WellLog · {n_curves} curve(s) · "
        f"MD {start or '?'}–{end or '?'} {unit} · "
        f"Curves: {curves_str}"
        + (" …" if n_curves > 6 else "")
    )
    return fields


def _extract_osdu_well(d: dict) -> dict:
    """Extract from OSDU Well master-data object."""
    inner = d.get("data", {})
    fields: dict = {}

    fields["well_name"] = _clean(inner.get("FacilityName"))
    fields["operator"]  = _clean(
        inner.get("OperatorName") or
        _extract_osdu_id(inner.get("OperatorID", ""))
    )
    fields["well_field"]= _clean(inner.get("Field"))

    # UWI from FacilityNameAliases
    aliases = inner.get("FacilityNameAliases", [])
    for alias in (aliases if isinstance(aliases, list) else []):
        alias_type = str(alias.get("AliasNameTypeID", "")).upper()
        if "UWI" in alias_type or "API" in alias_type:
            fields["uwi"] = _clean(alias.get("AliasName"))
            break
    # Fallback: FacilityID often carries the API number
    if not fields.get("uwi"):
        fields["uwi"] = _clean(inner.get("FacilityID"))

    # Coordinates from SpatialLocation
    spatial = inner.get("SpatialLocation", {})
    if isinstance(spatial, dict):
        asi = spatial.get("AsIngestedCoordinates", {})
        if isinstance(asi, dict):
            fp = asi.get("FirstPoint", {})
            if isinstance(fp, dict):
                fields["latitude"]  = _clean(fp.get("Latitude"))
                fields["longitude"] = _clean(fp.get("Longitude"))
            # Also try FeatureCollection
            if not fields.get("latitude"):
                fc = asi.get("FeatureCollection", {})
                if isinstance(fc, dict):
                    features = fc.get("features", [])
                    if features:
                        geom = features[0].get("geometry", {})
                        coords = geom.get("coordinates", [])
                        if len(coords) >= 2:
                            fields["longitude"] = str(coords[0])
                            fields["latitude"]  = str(coords[1])

    # Dates
    fields["spud_date"]    = _clean(inner.get("SpudDate"))
    fields["rig_release"]  = _clean(inner.get("DrillingCompletion"))
    fields["total_depth"]  = _safe_float(inner.get("DrillersTotalDepth"))

    # Location
    fields["county"]       = _clean(inner.get("County"))
    fields["state"]        = _clean(
        _extract_osdu_id(inner.get("StateProvinceID", "")) or
        inner.get("StateProvince")
    )

    fields["description"] = (
        f"OSDU Well · {fields.get('well_name','unknown')} · "
        f"UWI: {fields.get('uwi','?')} · "
        f"Operator: {fields.get('operator','?')}"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# JSON Well Log Format (JSONWLF) extractor
# ══════════════════════════════════════════════════════════════════════════════

def _extract_jsonwlf(d: dict) -> dict:
    """Extract from JSON Well Log Format (NORCE/NPD standard).

    JSONWLF has a 'header' dict with well metadata and a 'curves' array
    where each entry has 'name', 'description', 'quantity', 'unit'.
    """
    fields: dict = {}
    header = d.get("header", {})
    curves = d.get("curves", [])

    # Well identification
    fields["well_name"] = _clean(
        header.get("well") or header.get("wellName") or header.get("name"))
    fields["uwi"]       = _clean(
        header.get("uwi") or header.get("api") or header.get("wellId"))
    fields["operator"]  = _clean(
        header.get("operator") or header.get("company"))
    fields["well_field"]= _clean(header.get("field"))
    fields["contractor"]= _clean(
        header.get("serviceCompany") or header.get("loggingCompany"))

    # Depth range
    start = _safe_float(header.get("startDepth") or header.get("depthStart"))
    end   = _safe_float(header.get("endDepth")   or header.get("depthEnd") or
                         header.get("stopDepth"))
    unit  = _clean(header.get("depthUnit", "ft"))
    if start is not None:
        fields["depth_start"] = f"{start:.2f} {unit}"
    if end is not None:
        fields["depth_stop"]  = f"{end:.2f} {unit}"
        fields["total_depth"] = end

    # Run date
    fields["spud_date"] = _clean(
        header.get("date") or header.get("logDate") or header.get("runDate"))

    # Curves
    mnemonics = []
    if isinstance(curves, list):
        for c in curves:
            if isinstance(c, dict):
                mn = _clean(c.get("name") or c.get("mnemonic"))
                if mn and mn.upper() not in ("DEPT", "DEPTH", "MD", "INDEX"):
                    mnemonics.append(mn)
    fields["curve_names"] = mnemonics[:20]
    fields["n_curves"]    = len(mnemonics)

    curves_str = ", ".join(mnemonics[:6])
    fields["description"] = (
        f"JSONWLF · {len(mnemonics)} curves · "
        f"MD {start or '?'}–{end or '?'} {unit} · "
        f"Curves: {curves_str}"
        + (" …" if len(mnemonics) > 6 else "")
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# Generic JSON petroleum extractor
# ══════════════════════════════════════════════════════════════════════════════

def _extract_generic(d: dict) -> dict:
    """Best-effort extraction from an unrecognised JSON structure.

    Searches top-level keys for common petroleum field names.
    """
    fields: dict = {}
    d_lower = {k.lower(): v for k, v in d.items()}

    fields["uwi"]       = _clean(
        d_lower.get("uwi") or d_lower.get("api") or d_lower.get("api_number"))
    fields["well_name"] = _clean(
        d_lower.get("well_name") or d_lower.get("wellname") or d_lower.get("name"))
    fields["operator"]  = _clean(
        d_lower.get("operator") or d_lower.get("company") or d_lower.get("operatorname"))
    fields["well_field"]= _clean(d_lower.get("field") or d_lower.get("field_name"))
    fields["state"]     = _clean(d_lower.get("state") or d_lower.get("province_state"))
    fields["county"]    = _clean(d_lower.get("county"))

    fields["description"] = (
        f"Generic JSON · Well: {fields.get('well_name','unknown')} · "
        f"UWI: {fields.get('uwi','?')}"
    )
    return fields




# ══════════════════════════════════════════════════════════════════════════════
# OSDU WellboreMarkerSet — formation tops
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_marker_set(d: dict) -> dict:
    """Extract from OSDU WellboreMarkerSet (formation tops / picks).

    Captures: well name, UWI, interpreter, pick count, depth range,
    formation names list, and the full marker list as structured data.
    The marker list is what makes this format so valuable — each pick
    carries formation name, MD, TVD, sub-sea depth, and quality rating.
    These map directly to dv_well_formation_top.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["well_name"]    = _clean(inner.get("Name"))
    fields["operator"]     = _clean(inner.get("InterpreterName"))
    fields["spud_date"]    = _clean(inner.get("InterpretationDateTime", ""))[:10] or None

    # UWI from WellboreID
    wb_id = _clean(inner.get("WellboreID", ""))
    if wb_id:
        parts = wb_id.split(":")
        raw_id = parts[-1] if parts else ""
        if "-WB" in raw_id.upper():
            fields["uwi"] = raw_id[:raw_id.upper().rfind("-WB")]
        else:
            fields["uwi"] = raw_id

    # Depth range
    start = _safe_float(inner.get("TopDepthMeasuredDepth"))
    end   = _safe_float(inner.get("BottomDepthMeasuredDepth"))
    unit  = _clean(inner.get("DepthUnit", "ft"))
    if start is not None:
        fields["depth_start"] = f"{start:.1f} {unit}"
    if end is not None:
        fields["depth_stop"]  = f"{end:.1f} {unit}"
        fields["total_depth"] = end

    # Markers — formation picks
    markers = inner.get("WellboreMarkers", [])
    if not isinstance(markers, list):
        markers = []

    fields["n_markers"] = len(markers)

    # Extract formation names and depth summary
    formation_names = []
    for m in markers:
        if isinstance(m, dict):
            name = _clean(m.get("MarkerName") or m.get("FormationName"))
            if name:
                formation_names.append(name)

    fields["formation_names"] = formation_names[:15]

    # Full marker list as structured data for downstream loading
    # to dv_well_formation_top — kept in key_fields by file_summarizer
    fields["markers"] = [
        {
            "formation": _clean(m.get("MarkerName") or m.get("FormationName")),
            "md":        _safe_float(m.get("MeasuredDepth")),
            "tvd":       _safe_float(m.get("TrueVerticalDepth")),
            "subsea":    _safe_float(m.get("SubSeaDepth")),
            "quality":   _clean(m.get("MarkerQuality")),
        }
        for m in markers
        if isinstance(m, dict)
    ]

    fields["report_type"]   = "FORMATION_TOPS"
    fields["file_category"] = "WELL"

    top_names = ", ".join(formation_names[:5])
    fields["description"] = (
        f"OSDU MarkerSet · {len(markers)} formation tops · "
        f"MD {start or '?'}–{end or '?'} {unit} · "
        f"Tops: {top_names}"
        + (" …" if len(formation_names) > 5 else "")
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU WellborePressureData — DST / RFT / MDT pressure tests
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_pressure(d: dict) -> dict:
    """Extract from OSDU WellborePressureData (DST, RFT, MDT).

    Captures: well/wellbore ID, test type, test number, test date,
    service company, test intervals (formation, depth), pressure
    measurements (ISIP, FSIP, BHP, reservoir pressure), flow rates,
    and reservoir properties (permeability, skin, temperature).
    Maps to dv_well_dst.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["well_name"]   = _clean(inner.get("Name"))
    fields["contractor"]  = _clean(inner.get("ServiceCompany"))

    # Test type determines report_type
    test_type = _clean(inner.get("PressureDataType", "DST")) or "DST"
    fields["report_type"]   = f"DST_{test_type.upper()}" if test_type != "DST" else "DST_REPORT"
    fields["file_category"] = "WELL"

    # UWI from WellboreID
    wb_id = _clean(inner.get("WellboreID", ""))
    if wb_id:
        parts = wb_id.split(":")
        raw_id = parts[-1] if parts else ""
        if "-WB" in raw_id.upper():
            fields["uwi"] = raw_id[:raw_id.upper().rfind("-WB")]
        else:
            fields["uwi"] = raw_id

    fields["spud_date"]   = _clean(inner.get("TestDate"))
    unit_p = _clean(inner.get("PressureUnit", "psi"))
    unit_d = _clean(inner.get("DepthUnit", "ft"))

    # Test intervals — formation and depth
    intervals = inner.get("TestIntervals", [])
    if isinstance(intervals, list) and intervals:
        iv = intervals[0]
        fields["well_field"]  = _clean(iv.get("FormationName"))
        top  = _safe_float(iv.get("TopMeasuredDepth"))
        base = _safe_float(iv.get("BottomMeasuredDepth"))
        if top is not None:
            fields["depth_start"] = f"{top:.1f} {unit_d}"
        if base is not None:
            fields["depth_stop"]  = f"{base:.1f} {unit_d}"
            fields["total_depth"] = base

    # Pressure measurements — key values
    pressures = {}
    for pm in (inner.get("PressureMeasurements", []) or []):
        if isinstance(pm, dict):
            mtype = _clean(pm.get("MeasurementType", ""))
            val   = _safe_float(pm.get("Pressure"))
            if mtype and val is not None:
                pressures[mtype] = val

    fields["pressures"]       = pressures
    fields["n_pressure_pts"]  = len(pressures)

    # Flow periods
    flow_periods = inner.get("FlowPeriods", []) or []
    fields["n_flow_periods"]  = len(flow_periods)
    if flow_periods and isinstance(flow_periods[-1], dict):
        fp = flow_periods[-1]  # use final flow period for representative rates
        fields["gas_rate_mcfd"]  = _safe_float(fp.get("GasRateMcfd"))
        fields["oil_rate_stbd"]  = _safe_float(fp.get("OilRateStbd"))
        fields["water_rate_bwpd"]= _safe_float(fp.get("WaterRateBwpd"))

    # Reservoir properties
    res = inner.get("ReservoirProperties", {}) or {}
    fields["permeability"]   = _safe_float(res.get("Permeability"))
    fields["skin"]           = _safe_float(res.get("Skin"))
    fields["reservoir_temp"] = _safe_float(res.get("ReservoirTemperature"))
    fields["fluid_type"]     = _clean(res.get("FluidType"))

    res_p = pressures.get("ReservoirPressure") or pressures.get("FSIP")
    fields["description"] = (
        f"OSDU PressureData · {test_type} #{inner.get('TestNumber','')} · "
        f"{fields.get('well_field','?')} · "
        f"Res P: {res_p or '?'} {unit_p} · "
        f"Oil: {fields.get('oil_rate_stbd','?')} STBD · "
        f"Gas: {fields.get('gas_rate_mcfd','?')} Mcfd"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU SeismicAcquisitionSurvey
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_seismic(d: dict) -> dict:
    """Extract from OSDU SeismicAcquisitionSurvey.

    Captures: survey name, type (2D/3D), vintage year, acquisition dates,
    contractor, operator, CRS/EPSG, bounding box, acquisition parameters
    (bin size, fold, sample interval, record length, sweep frequencies),
    inline/crossline counts, and area in km². Maps to FILE_SEIS_HEADER.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["survey_name"]   = _clean(inner.get("FacilityName") or inner.get("Name"))
    fields["file_category"] = "SEIS"
    fields["report_type"]   = "SEISMIC"

    # 2D vs 3D
    stype = _clean(inner.get("SurveyType", "3D")) or "3D"
    fields["seis_set_type"] = "2D" if "2D" in stype.upper() else "3D"

    # Operator / contractor
    fields["operator"]    = _clean(
        inner.get("ClientName") or
        _extract_osdu_id(inner.get("OperatorID", ""))
    )
    fields["contractor"]  = _clean(inner.get("ContractorName"))

    # Dates
    fields["spud_date"]   = _clean(inner.get("AcquisitionStartDate"))
    fields["rig_release"] = _clean(inner.get("AcquisitionEndDate"))

    # CRS
    epsg = inner.get("EPSG")
    if epsg:
        fields["epsg_code"] = int(epsg)

    # Bounding box — try SpatialCoverage first, then SpatialArea polygon
    bbox = inner.get("SpatialCoverage", {}).get("BoundingBox", {})
    if bbox:
        fields["bbox_min_lat"] = _safe_float(bbox.get("MinLatitude"))
        fields["bbox_max_lat"] = _safe_float(bbox.get("MaxLatitude"))
        fields["bbox_min_lon"] = _safe_float(bbox.get("MinLongitude"))
        fields["bbox_max_lon"] = _safe_float(bbox.get("MaxLongitude"))
    else:
        # Try to extract from SpatialArea polygon
        spatial = inner.get("SpatialArea", {})
        coords_all = []
        if spatial.get("type") == "Polygon":
            rings = spatial.get("coordinates", [[]])
            if rings:
                coords_all = rings[0]
        if coords_all:
            lons = [c[0] for c in coords_all if len(c) >= 2]
            lats = [c[1] for c in coords_all if len(c) >= 2]
            if lons and lats:
                fields["bbox_min_lon"] = min(lons)
                fields["bbox_max_lon"] = max(lons)
                fields["bbox_min_lat"] = min(lats)
                fields["bbox_max_lat"] = max(lats)

    # Acquisition parameters
    acq = inner.get("AcquisitionParameters", {}) or {}
    fields["sample_interval"] = _safe_float(acq.get("SampleInterval"))
    fields["trace_count"]     = _safe_float(inner.get("NumberOfShotPoints"))

    # 3D-specific
    if fields["seis_set_type"] == "3D":
        fields["il_min"] = 1
        fields["il_max"] = int(inner.get("NumberOfInlines", 0) or 0)
        fields["xl_min"] = 1
        fields["xl_max"] = int(inner.get("NumberOfCrosslines", 0) or 0)

    # Rich parameter dict for key_fields in file_summarizer
    fields["acq_params"] = {
        "source_type":       _clean(acq.get("SourceType")),
        "bin_size_il":       _safe_float(acq.get("BinSizeInline")),
        "bin_size_xl":       _safe_float(acq.get("BinSizeCrossline")),
        "nominal_fold":      acq.get("NominalFold"),
        "max_offset":        _safe_float(acq.get("MaximumOffset")),
        "record_length_ms":  _safe_float(acq.get("RecordLength")),
        "sweep_min_hz":      _safe_float(acq.get("SweepFrequencyMin")),
        "sweep_max_hz":      _safe_float(acq.get("SweepFrequencyMax")),
        "area_km2":          _safe_float(inner.get("SurveyAreaKm2")),
        "n_inlines":         inner.get("NumberOfInlines"),
        "n_crosslines":      inner.get("NumberOfCrosslines"),
        "processing_co":     _clean(inner.get("ProcessingContractor")),
        "processing_date":   _clean(inner.get("ProcessingCompletionDate")),
    }

    vintage = inner.get("VintageYear", "")
    area    = inner.get("SurveyAreaKm2", "")
    fold    = acq.get("NominalFold", "")
    fields["description"] = (
        f"OSDU SeismicSurvey · {stype} · {fields.get('survey_name','?')} · "
        f"Vintage {vintage} · Contractor: {fields.get('contractor','?')} · "
        f"Area: {area} km² · Fold: {fold}"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU WellboreCompletion
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_completion(d: dict) -> dict:
    inner = d.get("data", {})
    fields: dict = {}
    fields["well_name"]    = _clean(inner.get("Name"))
    fields["operator"]     = _clean(inner.get("OperatorName"))
    fields["contractor"]   = _clean(inner.get("ServiceCompany"))
    fields["report_type"]  = "COMPLETION_REPORT"
    fields["file_category"]= "WELL"
    fac_id = _clean(inner.get("FacilityID", ""))
    wb_id  = _clean(inner.get("WellboreID", ""))
    if fac_id and len(fac_id) >= 10:
        fields["uwi"] = fac_id
    elif wb_id:
        parts = wb_id.split(":")
        raw_id = parts[-1] if parts else ""
        fields["uwi"] = (raw_id[:raw_id.upper().rfind("-WB")]
                         if "-WB" in raw_id.upper() else raw_id)
    fields["spud_date"] = _clean(inner.get("CompletionDate"))
    start = _safe_float(inner.get("TopDepthMeasuredDepth"))
    end   = _safe_float(inner.get("BottomDepthMeasuredDepth"))
    unit  = _clean(inner.get("DepthUnit", "ft"))
    if start is not None:
        fields["depth_start"] = f"{start:.1f} {unit}"
    if end is not None:
        fields["depth_stop"]  = f"{end:.1f} {unit}"
        fields["total_depth"] = end
    n_stages   = inner.get("NumberOfStages")
    n_clusters = inner.get("NumberOfClusters")
    comp_type  = _clean(inner.get("CompletionType", ""))
    lateral_ft = _safe_float(inner.get("LateralLength"))
    tot_fluid  = _safe_float(inner.get("TotalFluidVolume"))
    tot_prop   = _safe_float(inner.get("TotalProppantMass"))
    perfs = inner.get("PerfIntervals", []) or []
    formations = list(dict.fromkeys(
        f.get("Formation", "") for f in perfs
        if isinstance(f, dict) and f.get("Formation")))
    fields["completion_params"] = {
        "completion_type":   comp_type,
        "n_stages":          n_stages,
        "n_clusters":        n_clusters,
        "lateral_ft":        lateral_ft,
        "total_fluid_bbl":   tot_fluid,
        "total_proppant_lb": tot_prop,
        "formations":        formations,
        "tubing_in":         _safe_float(inner.get("TubingSize")),
        "casing_in":         _safe_float(inner.get("CasingSize")),
    }
    if formations:
        fields["well_field"] = formations[0]
    fields["description"] = (
        f"OSDU Completion · {comp_type or 'unknown type'} · "
        f"{n_stages or '?'} stages / {n_clusters or '?'} clusters · "
        + (f"Fluid: {tot_fluid:,.0f} bbl" if tot_fluid else "")
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU WellCoreAnalysis
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_core(d: dict) -> dict:
    inner = d.get("data", {})
    fields: dict = {}
    fields["well_name"]    = _clean(inner.get("Name"))
    fields["contractor"]   = _clean(inner.get("Laboratory"))
    fields["report_type"]  = "CORE_ANALYSIS"
    fields["file_category"]= "WELL"
    fields["well_field"]   = _clean(inner.get("Formation"))
    wb_id = _clean(inner.get("WellboreID", ""))
    if wb_id:
        parts = wb_id.split(":")
        raw_id = parts[-1] if parts else ""
        fields["uwi"] = (raw_id[:raw_id.upper().rfind("-WB")]
                         if "-WB" in raw_id.upper() else raw_id)
    fields["spud_date"] = _clean(inner.get("AnalysisDate"))
    unit  = _clean(inner.get("DepthUnit", "ft"))
    start = _safe_float(inner.get("TopDepthMeasuredDepth"))
    end   = _safe_float(inner.get("BottomDepthMeasuredDepth"))
    ci    = inner.get("CoredInterval", {}) or {}
    if not start:
        start = _safe_float(ci.get("TopMeasuredDepth"))
    if not end:
        end   = _safe_float(ci.get("BottomMeasuredDepth"))
    if start:
        fields["depth_start"] = f"{start:.1f} {unit}"
    if end:
        fields["depth_stop"]  = f"{end:.1f} {unit}"
        fields["total_depth"] = end
    recovery = _safe_float(ci.get("CoreRecovery"))
    plugs = inner.get("CorePlugs", []) or []
    fields["n_plugs"] = len(plugs)
    fields["plugs"] = [
        {
            "plug_no":   p.get("PlugNumber"),
            "md":        _safe_float(p.get("MeasuredDepth")),
            "porosity":  _safe_float(p.get("Porosity")),
            "perm_md":   _safe_float(p.get("Permeability")),
            "grain_den": _safe_float(p.get("GrainDensity")),
            "sw":        _safe_float(p.get("WaterSaturation")),
            "lithology": _clean(p.get("LithologyDescription")),
        }
        for p in plugs if isinstance(p, dict)
    ]
    stats = inner.get("SummaryStatistics", {}) or {}
    fields["core_stats"] = {
        "avg_porosity":  _safe_float(stats.get("AveragePorosity")),
        "avg_perm_md":   _safe_float(stats.get("AveragePermeability")),
        "max_porosity":  _safe_float(stats.get("MaxPorosity")),
        "max_perm_md":   _safe_float(stats.get("MaxPermeability")),
        "min_porosity":  _safe_float(stats.get("MinPorosity")),
        "min_perm_md":   _safe_float(stats.get("MinPermeability")),
        "core_recovery": recovery,
    }
    avg_phi = stats.get("AveragePorosity")
    avg_k   = stats.get("AveragePermeability")
    fields["description"] = (
        f"OSDU CoreAnalysis · {inner.get('AnalysisType','?')} · "
        f"{len(plugs)} plugs · MD {start or '?'}-{end or '?'} {unit} · "
        f"Avg phi: {avg_phi}% · Avg k: {avg_k} md"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU ProductionVolume
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_production(d: dict) -> dict:
    inner = d.get("data", {})
    fields: dict = {}
    fields["well_name"]    = _clean(inner.get("Name"))
    fields["operator"]     = _clean(inner.get("ReportingEntity"))
    fields["report_type"]  = "PRODUCTION"
    fields["file_category"]= "WELL"
    fac_id = _clean(inner.get("FacilityID", ""))
    wb_id  = _clean(inner.get("WellboreID", ""))
    if fac_id and len(fac_id) >= 10:
        fields["uwi"] = fac_id
    elif wb_id:
        parts  = wb_id.split(":")
        raw_id = parts[-1] if parts else ""
        fields["uwi"] = (raw_id[:raw_id.upper().rfind("-WB")]
                         if "-WB" in raw_id.upper() else raw_id)
    period = inner.get("ProductionPeriod", {}) or {}
    start_date = _clean(period.get("StartDate"))
    end_date   = _clean(period.get("EndDate"))
    fields["spud_date"]   = start_date
    fields["rig_release"] = end_date
    cum = inner.get("CumulativeSummary", {}) or {}
    cum_oil   = _safe_float(cum.get("CumulativeOil"))
    cum_gas   = _safe_float(cum.get("CumulativeGas"))
    cum_water = _safe_float(cum.get("CumulativeWater"))
    peak_oil  = _safe_float(cum.get("PeakOilRate"))
    peak_date = _clean(cum.get("PeakOilDate"))
    first_prod= _clean(cum.get("FirstProductionDate"))
    last_prod = _clean(cum.get("LastProductionDate"))
    records   = inner.get("ProductionRecords", []) or []
    fields["n_production_months"] = len(records)
    fields["production_summary"] = {
        "cumulative_oil_stb":   cum_oil,
        "cumulative_gas_mcf":   cum_gas,
        "cumulative_water_bbl": cum_water,
        "peak_oil_rate_stbd":   peak_oil,
        "peak_oil_date":        peak_date,
        "first_production":     first_prod or start_date,
        "last_production":      last_prod  or end_date,
        "total_months":         cum.get("TotalMonths") or len(records),
        "fluid_type":           _clean(inner.get("FluidType")),
        "production_type":      _clean(inner.get("ProductionType")),
    }
    oil_str = f"{cum_oil:,.0f} STB" if cum_oil else "?"
    gas_str = f"{cum_gas:,.0f} Mcf" if cum_gas else "?"
    fields["description"] = (
        f"OSDU Production · {len(records)} months · "
        f"{first_prod or start_date or '?'} to {last_prod or end_date or '?'} · "
        f"Cum oil: {oil_str} · Cum gas: {gas_str}"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU WellboreTrajectory
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_trajectory(d: dict) -> dict:
    """Extract from OSDU WellboreTrajectory WPC.

    Distinct from WITSML trajectory — OSDU version carries summary
    statistics (KOP, landing point, lateral length, max inclination,
    max DLS) and a compact station list. The WITSML extractor handles
    raw fixed-width survey files from the field; this handles the
    OSDU-ingested version with processed/QC'd data.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["well_name"]    = _clean(inner.get("Name"))
    fields["contractor"]   = _clean(inner.get("SurveyInstrumentCompany"))
    fields["survey_type"]  = _clean(inner.get("SurveyToolType") or
                                     inner.get("TrajectoryType"))
    fields["report_type"]  = "DIRECTIONAL_SURVEY"
    fields["file_category"]= "WELL"
    fields["spud_date"]    = _clean(inner.get("AcquisitionDate"))

    # UWI from WellboreID
    wb_id = _clean(inner.get("WellboreID", ""))
    if wb_id:
        parts = wb_id.split(":")
        raw_id = parts[-1] if parts else ""
        fields["uwi"] = (raw_id[:raw_id.upper().rfind("-WB")]
                         if "-WB" in raw_id.upper() else raw_id)

    # Depth range
    start = _safe_float(inner.get("TopDepthMeasuredDepth"))
    end   = _safe_float(inner.get("BottomDepthMeasuredDepth"))
    tvd   = _safe_float(inner.get("TotalVerticalDepth"))
    unit  = _clean(inner.get("DepthUnit", "ft"))
    if start is not None:
        fields["depth_start"] = f"{start:.1f} {unit}"
    if end is not None:
        fields["depth_stop"]  = f"{end:.1f} {unit}"
        fields["total_depth"] = end

    # Survey summary stats
    n_sta    = inner.get("NumberOfStations", 0)
    kop      = _safe_float(inner.get("KickOffPoint"))
    landing  = _safe_float(inner.get("LandingPoint"))
    lateral  = _safe_float(inner.get("LateralLength"))
    max_inc  = _safe_float(inner.get("MaxInclination"))
    max_dls  = _safe_float(inner.get("MaxDogLegSeverity"))

    fields["n_stations"] = n_sta
    fields["survey_params"] = {
        "trajectory_type":  _clean(inner.get("TrajectoryType")),
        "azimuth_reference":_clean(inner.get("AzimuthReference")),
        "kop_ft":           kop,
        "landing_ft":       landing,
        "lateral_length_ft":lateral,
        "tvd_ft":           tvd,
        "max_inclination":  max_inc,
        "max_dls":          max_dls,
        "n_stations":       n_sta,
    }

    fields["description"] = (
        f"OSDU Trajectory · {_clean(inner.get('TrajectoryType','?'))} · "
        f"{n_sta} stations · MD {start or '?'}–{end or '?'} {unit} · "
        f"KOP: {kop or '?'} · Lateral: {lateral or '?'} ft · "
        f"Max inc: {max_inc or '?'}° · Max DLS: {max_dls or '?'}°/100ft"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU Field
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_field(d: dict) -> dict:
    """Extract from OSDU Field master-data.

    Fields are geographic/geological units that group wells and reservoirs.
    Captures: field name, discovery year/well, operator, fluid type, basin,
    production type, bounding polygon, cumulative production summary.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["well_name"]    = _clean(inner.get("FieldName") or inner.get("Name"))
    fields["well_field"]   = fields["well_name"]
    fields["operator"]     = _clean(
        inner.get("OperatorName") or
        _extract_osdu_id(inner.get("OperatorID", "")))
    fields["county"]       = _clean(inner.get("County"))
    fields["state"]        = _clean(
        _extract_osdu_id(inner.get("StateProvinceID", "")) or
        inner.get("StateProvince"))
    fields["report_type"]  = "FIELD"
    fields["file_category"]= "WELL"

    # Bounding box from SpatialLocation polygon
    spatial = inner.get("SpatialLocation", {})
    asi = spatial.get("AsIngestedCoordinates", {})
    fc  = asi.get("FeatureCollection", {})
    features = fc.get("features", [])
    if features:
        geom = features[0].get("geometry", {})
        if geom.get("type") == "Polygon":
            rings = geom.get("coordinates", [[]])
            if rings:
                coords = rings[0]
                lons = [c[0] for c in coords if len(c) >= 2]
                lats = [c[1] for c in coords if len(c) >= 2]
                if lons and lats:
                    fields["bbox_min_lon"] = min(lons)
                    fields["bbox_max_lon"] = max(lons)
                    fields["bbox_min_lat"] = min(lats)
                    fields["bbox_max_lat"] = max(lats)

    disc_year = inner.get("DiscoveryYear")
    fluid     = _clean(inner.get("FluidType"))
    basin     = _clean(inner.get("Basin"))
    n_wells   = inner.get("NumberOfWells")
    cum_oil   = _safe_float(inner.get("CumulativeProductionOil"))
    area_km2  = _safe_float(inner.get("AreaKm2"))

    fields["field_params"] = {
        "discovery_year":     disc_year,
        "discovery_well":     _clean(inner.get("DiscoveryWell")),
        "basin":              basin,
        "sub_basin":          _clean(inner.get("SubBasin")),
        "fluid_type":         fluid,
        "production_type":    _clean(inner.get("ProductionType")),
        "primary_reservoir":  _clean(inner.get("PrimaryReservoir")),
        "field_status":       _clean(inner.get("FieldStatus")),
        "area_km2":           area_km2,
        "n_wells":            n_wells,
        "cum_oil_stb":        cum_oil,
        "cum_gas_mcf":        _safe_float(inner.get("CumulativeProductionGas")),
    }

    fields["description"] = (
        f"OSDU Field · {fields['well_name']} · "
        f"Discovered {disc_year or '?'} · {fluid or '?'} · "
        f"Basin: {basin or '?'} · {n_wells or '?'} wells"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU Reservoir
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_reservoir(d: dict) -> dict:
    """Extract from OSDU Reservoir master-data.

    Reservoirs are stratigraphic/petrophysical units within a field.
    Captures: reservoir name, formation, fluid type, petrophysical
    properties (porosity, perm, net pay, pressure, temperature),
    reserves (OOIP, proved), and recovery factor.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["well_name"]    = _clean(
        inner.get("ReservoirName") or inner.get("Name"))
    fields["well_field"]   = _clean(inner.get("FieldName"))
    fields["state"]        = _clean(
        _extract_osdu_id(inner.get("StateProvinceID", "")))
    fields["report_type"]  = "RESERVOIR"
    fields["file_category"]= "WELL"

    props = inner.get("ReservoirProperties", {}) or {}
    avg_phi  = _safe_float(props.get("AveragePorosity"))
    avg_k    = _safe_float(props.get("AveragePermeability"))
    net_pay  = _safe_float(props.get("AverageNetPay"))
    avg_tvd  = _safe_float(props.get("AverageDepthTVD"))
    init_p   = _safe_float(props.get("InitialReservoirPressure"))
    temp     = _safe_float(props.get("ReservoirTemperature"))
    gor      = _safe_float(props.get("GasOilRatio"))
    api_grav = _safe_float(props.get("OilGravity"))

    if avg_tvd:
        fields["total_depth"] = avg_tvd
        fields["depth_start"] = f"{avg_tvd:.0f} ft (avg TVD)"

    fields["reservoir_params"] = {
        "formation":          _clean(inner.get("Formation")),
        "member":             _clean(inner.get("Member")),
        "age":                _clean(inner.get("Age")),
        "rock_type":          _clean(inner.get("RockType")),
        "reservoir_type":     _clean(inner.get("ReservoirType")),
        "fluid_type":         _clean(inner.get("FluidType")),
        "avg_porosity_pct":   avg_phi,
        "avg_perm_md":        avg_k,
        "avg_net_pay_ft":     net_pay,
        "avg_depth_tvd_ft":   avg_tvd,
        "init_res_pressure":  init_p,
        "reservoir_temp_f":   temp,
        "gor_scf_stb":        gor,
        "api_gravity":        api_grav,
        "water_sat_pct":      _safe_float(props.get("WaterSaturation")),
        "recovery_factor_pct":_safe_float(inner.get("RecoveryFactor")),
        "ooip_stb":           _safe_float(inner.get("OriginalOilInPlace")),
        "proved_reserves_stb":_safe_float(inner.get("ProvedReserves")),
    }

    fields["description"] = (
        f"OSDU Reservoir · {fields['well_name']} · "
        f"Formation: {inner.get('Formation','?')} · "
        f"Phi: {avg_phi or '?'}% · k: {avg_k or '?'} md · "
        f"Net pay: {net_pay or '?'} ft"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU RockFluidOrganisation (SCAL)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_scal(d: dict) -> dict:
    """Extract from OSDU RockFluidOrganisation (Special Core Analysis).

    SCAL data includes relative permeability curves (oil-water, oil-gas),
    capillary pressure measurements (MICP, porous plate, centrifuge), and
    wettability indices. Captures: well, lab, formation, depth interval,
    system types, end-point saturations, and summary petrophysics.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["well_name"]    = _clean(inner.get("Name"))
    fields["contractor"]   = _clean(inner.get("Laboratory"))
    fields["well_field"]   = _clean(inner.get("Formation"))
    fields["spud_date"]    = _clean(inner.get("AnalysisDate"))
    fields["report_type"]  = "SCAL"
    fields["file_category"]= "WELL"

    # UWI from WellboreID
    wb_id = _clean(inner.get("WellboreID", ""))
    if wb_id:
        parts = wb_id.split(":")
        raw_id = parts[-1] if parts else ""
        fields["uwi"] = (raw_id[:raw_id.upper().rfind("-WB")]
                         if "-WB" in raw_id.upper() else raw_id)

    unit  = _clean(inner.get("DepthUnit", "ft"))
    start = _safe_float(inner.get("TopDepthMeasuredDepth"))
    end   = _safe_float(inner.get("BottomDepthMeasuredDepth"))
    if start:
        fields["depth_start"] = f"{start:.1f} {unit}"
    if end:
        fields["depth_stop"]  = f"{end:.1f} {unit}"
        fields["total_depth"] = end

    # Rock-fluid systems summary
    systems = inner.get("RockFluidSystems", []) or []
    system_types = [
        _clean(s.get("SystemType")) for s in systems
        if isinstance(s, dict) and s.get("SystemType")]

    # Capillary pressure
    cap_p = inner.get("CapillaryPressure", {}) or {}
    cap_method = _clean(cap_p.get("Method"))
    entry_p    = _safe_float(cap_p.get("EntryPressure"))

    # Summary stats
    stats = inner.get("SummaryStatistics", {}) or {}

    fields["scal_params"] = {
        "n_systems":          len(systems),
        "system_types":       system_types,
        "cap_pressure_method":cap_method,
        "entry_pressure":     entry_p,
        "entry_pressure_unit":_clean(inner.get("PressureUnit")),
        "avg_porosity_pct":   _safe_float(stats.get("AveragePorosity")),
        "avg_perm_md":        _safe_float(stats.get("AveragePermeability")),
        "n_samples":          stats.get("NumberOfSamples"),
    }

    fields["description"] = (
        f"OSDU SCAL · {fields['contractor'] or '?'} · "
        f"Formation: {inner.get('Formation','?')} · "
        f"MD {start or '?'}–{end or '?'} {unit} · "
        f"Systems: {', '.join(system_types) or '?'} · "
        f"Cap P method: {cap_method or '?'}"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU Document (generic wrapper)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_document(d: dict) -> dict:
    """Extract from OSDU Document WPC.

    Generic document wrapper — covers PDFs, reports, proposals, and any
    file that has been ingested into OSDU without a more specific kind.
    Captures: well name, document type, date, author, file format,
    page count, keywords, and any well/field tags in the Tags block.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["well_name"]    = _clean(inner.get("Name"))
    fields["operator"]     = _clean(
        inner.get("AuthorOrganisation") or inner.get("AuthorName"))
    fields["report_type"]  = _clean(inner.get("DocumentType", "DOCUMENT")).upper()
    fields["file_category"]= "WELL"
    fields["spud_date"]    = _clean(inner.get("DocumentDate"))

    # UWI from WellboreID if present
    wb_id = _clean(inner.get("WellboreID", ""))
    if wb_id:
        parts = wb_id.split(":")
        raw_id = parts[-1] if parts else ""
        fields["uwi"] = (raw_id[:raw_id.upper().rfind("-WB")]
                         if "-WB" in raw_id.upper() else raw_id)

    # Structured tags carry well/field references
    tags = inner.get("Tags", {}) or {}
    if isinstance(tags, dict):
        if not fields.get("well_name") and tags.get("Well"):
            fields["well_name"] = _clean(tags["Well"])
        if tags.get("Field"):
            fields["well_field"] = _clean(tags["Field"])

    kws = inner.get("Keywords", []) or []
    file_fmt   = _clean(inner.get("FileFormat"))
    page_count = inner.get("PageCount")
    size_bytes = inner.get("FileSizeBytes")
    size_mb    = f"{size_bytes/1048576:.1f} MB" if size_bytes else "?"

    fields["doc_params"] = {
        "document_type":    _clean(inner.get("DocumentType")),
        "document_date":    fields["spud_date"],
        "author":           _clean(inner.get("AuthorName")),
        "organisation":     _clean(inner.get("AuthorOrganisation")),
        "review_status":    _clean(inner.get("ReviewStatus")),
        "approval_date":    _clean(inner.get("ApprovalDate")),
        "file_format":      file_fmt,
        "file_size":        size_mb,
        "page_count":       page_count,
        "keywords":         kws[:10],
        "tags":             tags,
    }

    fields["description"] = (
        f"OSDU Document · {inner.get('DocumentType','?')} · "
        f"{fields.get('well_name','?')} · "
        f"Author: {_clean(inner.get('AuthorName','?'))} · "
        f"{file_fmt or '?'} · {page_count or '?'} pages · {size_mb}"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU SeismicHorizon
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_horizon(d: dict) -> dict:
    """Extract from OSDU SeismicHorizon WPC.

    Interpreted seismic horizon surfaces. Captures: horizon name,
    geologic unit, age, interpreter, survey reference, domain type
    (time/depth), node count, inline/crossline ranges, depth/time
    statistics, bounding box, well control, and seismic attributes.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["survey_name"]  = _clean(inner.get("Name"))
    fields["well_name"]    = fields["survey_name"]   # reuse for catalog display
    fields["operator"]     = _clean(inner.get("InterpreterOrganisation"))
    fields["contractor"]   = _clean(inner.get("InterpreterName"))
    fields["spud_date"]    = _clean(inner.get("InterpretationDate"))
    fields["report_type"]  = "SEISMIC_HORIZON"
    fields["file_category"]= "SEIS"
    fields["seis_set_type"]= _clean(inner.get("SurveyType", "3D"))

    # Bounding box
    bbox = (inner.get("SpatialCoverage", {}) or {}).get("BoundingBox", {})
    if bbox:
        fields["bbox_min_lat"] = _safe_float(bbox.get("MinLatitude"))
        fields["bbox_max_lat"] = _safe_float(bbox.get("MaxLatitude"))
        fields["bbox_min_lon"] = _safe_float(bbox.get("MinLongitude"))
        fields["bbox_max_lon"] = _safe_float(bbox.get("MaxLongitude"))

    # Depth stats
    depth_stats = inner.get("DepthStatistics", {}) or {}
    twt_stats   = inner.get("TwoWayTimeStatistics", {}) or {}

    # IL/XL ranges
    il_rng = inner.get("InlineRange", {}) or {}
    xl_rng = inner.get("CrosslineRange", {}) or {}
    fields["il_min"] = il_rng.get("Min")
    fields["il_max"] = il_rng.get("Max")
    fields["xl_min"] = xl_rng.get("Min")
    fields["xl_max"] = xl_rng.get("Max")

    fields["horizon_params"] = {
        "horizon_type":     _clean(inner.get("HorizonType")),
        "geologic_unit":    _clean(inner.get("GeologicUnit")),
        "age":              _clean(inner.get("Age")),
        "domain_type":      _clean(inner.get("DomainType")),
        "depth_unit":       _clean(inner.get("DepthUnit")),
        "n_nodes":          inner.get("NumberOfNodes"),
        "il_range":         f"{il_rng.get('Min')}–{il_rng.get('Max')}",
        "xl_range":         f"{xl_rng.get('Min')}–{xl_rng.get('Max')}",
        "min_depth_ft":     _safe_float(depth_stats.get("MinDepth")),
        "max_depth_ft":     _safe_float(depth_stats.get("MaxDepth")),
        "mean_depth_ft":    _safe_float(depth_stats.get("MeanDepth")),
        "min_twt_ms":       _safe_float(twt_stats.get("MinTWT")),
        "max_twt_ms":       _safe_float(twt_stats.get("MaxTWT")),
        "well_control_pts": inner.get("WellControlPoints"),
        "confidence":       _clean(inner.get("ConfidenceRating")),
        "attributes":       inner.get("SeismicAttributes", []),
        "survey_id":        _clean(inner.get("SeismicSurveyID")),
    }

    fields["description"] = (
        f"OSDU SeismicHorizon · {fields['survey_name']} · "
        f"Unit: {inner.get('GeologicUnit','?')} · "
        f"Depth {depth_stats.get('MinDepth','?')}–{depth_stats.get('MaxDepth','?')} ft · "
        f"Nodes: {inner.get('NumberOfNodes','?'):,}" if inner.get('NumberOfNodes')
        else
        f"OSDU SeismicHorizon · {fields['survey_name']} · "
        f"Unit: {inner.get('GeologicUnit','?')}"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# OSDU SeismicFault
# ══════════════════════════════════════════════════════════════════════════════

def _extract_osdu_fault(d: dict) -> dict:
    """Extract from OSDU SeismicFault WPC.

    Interpreted fault surfaces. Captures: fault name, type (normal/reverse/
    strike-slip), style, interpreter, survey reference, strike/dip/dip-
    direction, max throw, fault length, number of fault sticks, depth
    statistics, bounding box, and offsetted horizons.
    """
    inner = d.get("data", {})
    fields: dict = {}

    fields["survey_name"]  = _clean(inner.get("Name"))
    fields["well_name"]    = fields["survey_name"]
    fields["operator"]     = _clean(inner.get("InterpreterOrganisation"))
    fields["contractor"]   = _clean(inner.get("InterpreterName"))
    fields["spud_date"]    = _clean(inner.get("InterpretationDate"))
    fields["report_type"]  = "SEISMIC_FAULT"
    fields["file_category"]= "SEIS"
    fields["seis_set_type"]= _clean(inner.get("SurveyType", "3D"))

    # Bounding box
    bbox = (inner.get("SpatialCoverage", {}) or {}).get("BoundingBox", {})
    if bbox:
        fields["bbox_min_lat"] = _safe_float(bbox.get("MinLatitude"))
        fields["bbox_max_lat"] = _safe_float(bbox.get("MaxLatitude"))
        fields["bbox_min_lon"] = _safe_float(bbox.get("MinLongitude"))
        fields["bbox_max_lon"] = _safe_float(bbox.get("MaxLongitude"))

    depth_stats = inner.get("DepthStatistics", {}) or {}
    horizons    = inner.get("SeismicHorizonsOffsetted", []) or []

    fields["fault_params"] = {
        "fault_type":       _clean(inner.get("FaultType")),
        "fault_style":      _clean(inner.get("FaultStyle")),
        "domain_type":      _clean(inner.get("DomainType")),
        "strike":           _safe_float(inner.get("Strike")),
        "dip":              _safe_float(inner.get("Dip")),
        "dip_direction":    _clean(inner.get("DipDirection")),
        "max_throw_ft":     _safe_float(inner.get("MaxThrow")),
        "fault_length_km":  _safe_float(inner.get("FaultLength")),
        "n_fault_sticks":   inner.get("NumberOfFaultSticks"),
        "n_fault_nodes":    inner.get("NumberOfFaultNodes"),
        "top_depth_ft":     _safe_float(depth_stats.get("TopDepth")),
        "bottom_depth_ft":  _safe_float(depth_stats.get("BottomDepth")),
        "horizons_cut":     horizons,
        "trap_component":   inner.get("TrapComponent"),
        "confidence":       _clean(inner.get("ConfidenceRating")),
        "survey_id":        _clean(inner.get("SeismicSurveyID")),
    }

    fields["description"] = (
        f"OSDU SeismicFault · {fields['survey_name']} · "
        f"{inner.get('FaultType','?')} · "
        f"Strike: {inner.get('Strike','?')}° · "
        f"Dip: {inner.get('Dip','?')}° · "
        f"Max throw: {inner.get('MaxThrow','?')} ft · "
        f"Length: {inner.get('FaultLength','?')} km"
    )
    return fields


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def classify_json_well_log(file_path: str) -> dict:
    """Extract metadata from a JSON petroleum data file.

    Handles OSDU WellLog, OSDU Well, JSON Well Log Format, and
    generic petroleum JSON. Returns a flat dict with keys matching
    _extract_fields() in page_workbench.py.
    """
    result = {
        "file_category":   "WELL",
        "report_type":     "WELL_LOG",
        "json_schema":     "unknown",
        "well_name":       None,
        "uwi":             None,
        "operator":        None,
        "well_field":      None,
        "state":           None,
        "county":          None,
        "contractor":      None,
        "spud_date":       None,
        "rig_release":     None,
        "total_depth":     None,
        "depth_start":     None,
        "depth_stop":      None,
        "latitude":        None,
        "longitude":       None,
        "curve_names":     [],
        "n_curves":        0,
        "description":     "JSON well log — no metadata extracted",
        "confidence":      0.0,
        "error":           None,
    }

    # ── Parse JSON ────────────────────────────────────────────────────────────
    try:
        text = Path(file_path).read_text(encoding="utf-8-sig", errors="replace")
        data = json.loads(text)
    except json.JSONDecodeError as e:
        result["error"] = f"JSON parse error: {e}"
        return result
    except OSError as e:
        result["error"] = f"File read error: {e}"
        return result

    if not isinstance(data, dict):
        result["error"] = "Top-level JSON is not an object (dict)"
        return result

    # ── Schema detection ─────────────────────────────────────────────────────
    schema = _detect_schema(data)
    result["json_schema"] = schema

    # Resolve report_type and category
    _SEIS_SCHEMAS = {"osdu_seismic", "osdu_horizon", "osdu_fault"}
    _RTYPE_MAP = {
        "osdu_well_log":   ("WELL_LOG",          "WELL"),
        "jsonwlf":         ("WELL_LOG",          "WELL"),
        "osdu_trajectory": ("DIRECTIONAL_SURVEY","WELL"),
        "osdu_marker_set": ("FORMATION_TOPS",    "WELL"),
        "osdu_pressure":   ("DST_REPORT",        "WELL"),
        "osdu_completion": ("COMPLETION_REPORT", "WELL"),
        "osdu_core":       ("CORE_ANALYSIS",     "WELL"),
        "osdu_production": ("PRODUCTION",        "WELL"),
        "osdu_seismic":    ("SEISMIC",           "SEIS"),
        "osdu_horizon":    ("SEISMIC_HORIZON",   "SEIS"),
        "osdu_fault":      ("SEISMIC_FAULT",     "SEIS"),
        "osdu_field":      ("FIELD",             "WELL"),
        "osdu_reservoir":  ("RESERVOIR",         "WELL"),
        "osdu_scal":       ("SCAL",              "WELL"),
        "osdu_document":   ("DOCUMENT",          "WELL"),
    }
    if schema in _RTYPE_MAP:
        result["report_type"], result["file_category"] = _RTYPE_MAP[schema]
    elif "well" in schema:
        result["report_type"]   = "WELL_HEADER"
        result["file_category"] = "WELL"

    # ── Extract fields ────────────────────────────────────────────────────────
    _extractors = {
        "osdu_well_log":   _extract_osdu_well_log,
        "osdu_well":       _extract_osdu_well,
        "osdu_wellbore":   _extract_osdu_well,
        "osdu_generic":    _extract_osdu_well,
        "osdu_trajectory": _extract_osdu_trajectory,
        "osdu_marker_set": _extract_osdu_marker_set,
        "osdu_pressure":   _extract_osdu_pressure,
        "osdu_completion": _extract_osdu_completion,
        "osdu_core":       _extract_osdu_core,
        "osdu_production": _extract_osdu_production,
        "osdu_seismic":    _extract_osdu_seismic,
        "osdu_horizon":    _extract_osdu_horizon,
        "osdu_fault":      _extract_osdu_fault,
        "osdu_field":      _extract_osdu_field,
        "osdu_reservoir":  _extract_osdu_reservoir,
        "osdu_scal":       _extract_osdu_scal,
        "osdu_document":   _extract_osdu_document,
        "jsonwlf":         _extract_jsonwlf,
        "generic":         _extract_generic,
    }
    extractor = _extractors.get(schema)
    if extractor is not None:
        try:
            fields = extractor(data)
            result.update(fields)
        except Exception as e:
            result["error"] = f"{schema} extractor: {e}"

    # ── Confidence ────────────────────────────────────────────────────────────
    # Seismic/spatial/reference schemas have no UWI — score on name instead
    _no_uwi_schemas = {"osdu_seismic", "osdu_horizon", "osdu_fault",
                       "osdu_field", "osdu_reservoir"}
    if schema in _no_uwi_schemas:
        result["confidence"] = (
            0.85 if (result.get("survey_name") or result.get("well_name"))
            else 0.40
        )
    elif result.get("well_name") or result.get("uwi"):
        result["confidence"] = 0.85 if extractor is not None else 0.40
    else:
        result["confidence"] = 0.30

    return result

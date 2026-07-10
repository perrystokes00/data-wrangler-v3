"""
json_well_log_catalog.py
========================
OSDU WKS JSON (and JSON Well Log Format) reader → file_catalog.cat_* mirrors.

OSDU records share one envelope:

    { "kind": "osdu:wks:<group>--<EntityType>:<ver>",
      "acl": {...}, "legal": {...},
      "data": { ...payload, shape varies per EntityType... } }

`kind` is the router: the EntityType (Well, WellboreTrajectory,
WellboreMarkerSet, WellborePressureData, RockFluidOrganisation, Document, …)
selects the handler, which maps `data{}` into the matching cat_* table. The
simplified JSON-Well-Log shape (kind/header/data/curves, no acl/legal) emitted
by make_test_dataset_all.gen_json_log is handled by the same Well/WellLog path.

Public entry points (mirroring witsml_catalog / pdf_survey_catalog):

    classify_osdu(path) -> dict        # identity for the EXTRACT stage
    load_osdu(engine, path, *, uwi=None, inventory_id=None, source_path=None,
              source="OSDU", well_info=None, log=None) -> dict

Well-domain kinds load into cat_*; non-well kinds (Field, Reservoir,
SeismicFault, SeismicHorizon, SeismicAcquisitionSurvey) currently have no
cat_well_* target, so they return note="no_target:<Entity>" — cataloged and
visible, never silently dropped. Scan-stage only: never touches dv_*.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime

try:
    from modules.catalog_capture import capture
except ImportError:
    from catalog_capture import capture

WELL_TARGETS = {
    "Well", "WellLog", "Wellbore", "WellboreTrajectory", "WellboreMarkerSet",
    "WellborePressureData", "RockFluidOrganisation", "Document",
}
NO_TARGET = {
    "Organisation",
}
# Master/reference records — loaded into their own cat_* tables, but they are
# field/reservoir-scoped, not well-scoped, so they carry no well UWI.
MASTER_ENTITIES = {
    "Field", "Reservoir",
}
SEIS_ENTITIES = {
    "SeismicAcquisitionSurvey", "SeismicFault", "SeismicHorizon",
}


# ── helpers ──────────────────────────────────────────────────────────────────
def _uid():
    return uuid.uuid4().hex


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trunc(v, n):
    return None if v is None else str(v)[:n]


def _after_colon(s):
    """Tail of an OSDU id reference (…:StateProvince:TX → 'TX')."""
    return str(s).rsplit(":", 1)[-1] if s else None


def _osdu_uwi(s):
    """Pull a digits-only UWI from a FacilityID or a WellboreID reference.
    'osdu:master-data--Wellbore:42-301-45678-0000-WB01' -> '42301456780000'
    '05-001-10052-0000' -> '05001100520000'."""
    if not s:
        return None
    s = str(s).rsplit(":", 1)[-1]          # strip osdu id prefix if present
    s = re.sub(r"-WB\w+$", "", s, flags=re.I)   # drop wellbore suffix
    d = re.sub(r"\D", "", s)
    return d or None


def _as_frac(v):
    """Percent-or-fraction → fraction (8.9 -> 0.089, 0.28 -> 0.28)."""
    f = _f(v)
    if f is None:
        return None
    return f / 100.0 if f > 1.0 else f


def _osdu_latlon(data):
    """Pull (latitude, longitude) from an OSDU well's nested SpatialLocation.

    Handles both shapes real OSDU records use:
      data.SpatialLocation.AsIngestedCoordinates.FirstPoint.{Latitude,Longitude}
      …or the GeoJSON FeatureCollection → features[0].geometry.coordinates [lon,lat]
    Returns (lat, lon) as floats in range, or (None, None)."""
    sl = (data.get("SpatialLocation") or {})
    aic = (sl.get("AsIngestedCoordinates") or sl.get("Wgs84Coordinates") or {})
    fp = aic.get("FirstPoint") or {}
    lat, lon = _f(fp.get("Latitude")), _f(fp.get("Longitude"))
    if lat is None or lon is None:
        # GeoJSON fallback: coordinates are [lon, lat, (depth)]
        try:
            feat = aic["FeatureCollection"]["features"][0]
            coords = feat["geometry"]["coordinates"]
            lon, lat = _f(coords[0]), _f(coords[1])
        except (KeyError, IndexError, TypeError):
            pass
    if lat is None or lon is None:
        return (None, None)
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return (None, None)
    return (lat, lon)


def _entity(kind):
    if not kind:
        return None
    tail = kind.split("--", 1)[1] if "--" in kind else kind
    return tail.split(":", 1)[0]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _identity(obj):
    """Best-effort {uwi, well_name, operator, field, state} from any record."""
    data = obj.get("data", obj) or {}
    uwi = _osdu_uwi(data.get("WellboreID") or data.get("FacilityID")
                    or data.get("UWI"))
    return {
        "uwi": uwi,
        "well_name": (data.get("FacilityName") or data.get("WellName")
                      or data.get("Name")
                      or (obj.get("header") or {}).get("name")),
        "operator": data.get("OperatorName") or data.get("Operator"),
        "field": data.get("Field") or data.get("FieldName")
        or (data.get("Tags") or {}).get("Field"),
        "state": _after_colon(data.get("StateProvinceID")) or data.get("State"),
    }


# ── classify (EXTRACT stage) ─────────────────────────────────────────────────
def classify_json_well_log(path):
    """Identity for the extract stage. Returns the rich field set the workbench
    JSON branch reads (well_field / contractor / spud_date / SEIS bbox /
    curve_names). Non-well records get no well UWI."""
    base = {"file_category": "WELL", "report_type": "JSON_OTHER",
            "uwi": None, "well_name": None, "operator": None, "contractor": None,
            "well_field": None, "state": None, "county": None,
            "spud_date": None, "total_depth": None, "confidence": 0.0,
            "entity": None}
    try:
        obj = _read(path)
    except Exception:
        return base
    ent = _entity(obj.get("kind"))
    data = obj.get("data") or {}
    ident = _identity(obj)
    base["entity"] = ent
    base["report_type"] = f"OSDU_{ent.upper()}" if ent else "JSON_WELL_LOG"

    if ent in SEIS_ENTITIES:
        # seismic metadata → FILE_SEIS_HEADER; never a well UWI
        bb = (data.get("SpatialCoverage") or {}).get("BoundingBox") or {}
        base.update({
            "file_category": "SEIS",
            "survey_name":   data.get("FacilityName") or data.get("Name"),
            "seis_set_type": data.get("SurveyType"),
            "bbox_min_lat":  _f(bb.get("MinLatitude")),
            "bbox_max_lat":  _f(bb.get("MaxLatitude")),
            "bbox_min_lon":  _f(bb.get("MinLongitude")),
            "bbox_max_lon":  _f(bb.get("MaxLongitude")),
            "epsg_code":     data.get("EPSG"),
        })
        return base

    if ent in NO_TARGET or ent in MASTER_ENTITIES:    # field/reservoir/org
        base["file_category"] = "OTHER"
        base["well_name"]  = ident.get("well_name")
        base["well_field"] = ident.get("field")
        return base

    # well-domain record → resolve identity for FILE_WELL_HEADER
    _lat, _lon = _osdu_latlon(data)
    base.update({
        "uwi":         ident.get("uwi"),
        "well_name":   ident.get("well_name"),
        "operator":    ident.get("operator"),
        "well_field":  ident.get("field"),
        "state":       ident.get("state"),
        "county":      data.get("County"),
        "country":     _after_colon(data.get("CountryID")) or data.get("Country"),
        "latitude":    _lat,
        "longitude":   _lon,
        "spud_date":   data.get("SpudDate"),
        "total_depth": _f(data.get("DrillersTotalDepth")
                          or data.get("TotalDepth")),
        "confidence":  1.0 if ident.get("uwi") else 0.3,
    })
    curves = obj.get("curves") or data.get("Curves") or []
    names = [c.get("name") or c.get("mnemonic") or c.get("Mnemonic")
             for c in curves]
    names = [n for n in names if n]
    if names:
        base["curve_names"] = names
        base["n_curves"] = len(names)
    return base


# backwards-compatible alias
classify_osdu = classify_json_well_log


# ── per-entity handlers (build rows; capture) ────────────────────────────────
def _cap(engine, table, rows, *, uwi, inv, sp, src="OSDU"):
    rows = [r for r in rows if r]
    if not rows:
        return 0
    return capture(engine, table, rows, uwi=uwi, inventory_id=inv,
                   source_path=sp, source=src)


def _h_well(engine, data, obj, *, uwi, inv, sp, now):
    """Well / WellLog → cat_well header (+ cat_log_curve if curves present)."""
    detail = {}
    _lat, _lon = _osdu_latlon(data)
    n = _cap(engine, "cat_well", [{
        "WELL_NAME":        data.get("FacilityName") or data.get("WellName")
        or data.get("Name") or uwi,
        "OPERATOR_NAME":    data.get("OperatorName") or data.get("Operator"),
        "FIELD_NAME":       data.get("Field") or data.get("FieldName"),
        "PROVINCE_STATE":   _after_colon(data.get("StateProvinceID"))
        or data.get("State"),
        "COUNTY":           data.get("County"),
        "COUNTRY":          _after_colon(data.get("CountryID"))
        or data.get("Country"),
        "SURFACE_LATITUDE":  _lat,
        "SURFACE_LONGITUDE": _lon,
        "SPUD_DATE":        data.get("SpudDate"),
        "FINAL_TD":         _f(data.get("DrillersTotalDepth")
                               or data.get("TotalDepth")),
        "ACTIVE_IND":       "Y",
        "ROW_QUALITY":      "FINAL",
        "PPDM_GUID":        str(uuid.uuid4()),
        "ROW_CREATED_BY":   "DataWrangler",
        "ROW_CREATED_DATE": now,
    }], uwi=uwi, inv=inv, sp=sp, src="OSDU_WELL")
    if n:
        detail["cat_well"] = n
    curves = obj.get("curves") or data.get("Curves") or []
    crows = []
    for i, c in enumerate(curves):
        mnem = c.get("name") or c.get("mnemonic") or c.get("Mnemonic")
        if not mnem:
            continue
        crows.append({
            "CURVE_MNEMONIC":  str(mnem)[:64],
            "CURVE_UNIT":      _trunc(c.get("unit") or c.get("Unit"), 32),
            "CURVE_INDEX":     i,
            "IS_INDEX":        "Y" if i == 0 else "N",
            "SOURCE_FORMAT":   "OSDU",
        })
    n = _cap(engine, "cat_log_curve", crows, uwi=uwi, inv=inv, sp=sp,
             src="OSDU")
    if n:
        detail["cat_log_curve"] = n
    return detail


def _h_trajectory(engine, data, *, uwi, inv, sp, now):
    stns = data.get("TrajectoryStations") or []
    mds = [_f(s.get("MeasuredDepth")) for s in stns
           if _f(s.get("MeasuredDepth")) is not None]
    sid = f"OSDU_{_uid()[:12]}"
    _cap(engine, "cat_well_dir_srvy_hdr", [{
        "SURVEY_ID":         sid,
        "SURVEY_TYPE":       _trunc(data.get("SurveyToolType")
                                    or data.get("TrajectoryType") or "OSDU", 40),
        "SURVEY_TOP_DEPTH":  min(mds) if mds else None,
        "SURVEY_BASE_DEPTH": max(mds) if mds else None,
        "DEPTH_OUOM":        _trunc(data.get("DepthUnit") or "ft", 16),
        "ACTIVE_IND":        "Y",
        "ROW_CREATED_BY":    "DataWrangler", "ROW_CREATED_DATE": now,
    }], uwi=uwi, inv=inv, sp=sp)
    sta = []
    for i, s in enumerate(sorted(
            stns, key=lambda x: _f(x.get("MeasuredDepth")) or 0.0), start=1):
        sta.append({
            "SURVEY_ID":   sid,
            "STATION_ID":  f"{sid}_{i:04d}",
            "MD":          _f(s.get("MeasuredDepth")),
            "INCL":        _f(s.get("Inclination")),
            "AZIM":        _f(s.get("Azimuth")),
            "TVD":         _f(s.get("TrueVerticalDepth")),
            "DLS":         _f(s.get("DogLegSeverity")),
            "DEPTH_OUOM":  _trunc(data.get("DepthUnit") or "ft", 16),
            "ACTIVE_IND":  "Y",
            "ROW_CREATED_BY": "DataWrangler", "ROW_CREATED_DATE": now,
        })
    n = _cap(engine, "cat_well_dir_srvy_sta", sta, uwi=uwi, inv=inv, sp=sp)
    return {"cat_well_dir_srvy_sta": n} if n else {}


def _h_marker_set(engine, data, *, uwi, inv, sp, now):
    set_name = _trunc(data.get("Name") or "OSDU Markers", 255)
    out = []
    for m in data.get("WellboreMarkers") or []:
        out.append({
            "strat_unit_id":    _uid(),
            "interp_id":        _uid(),
            "strat_name_set":   set_name,
            "strat_unit_name":  _trunc(m.get("MarkerName")
                                       or m.get("FormationID"), 255),
            "strat_unit_type":  "FORMATION",
            "top_depth":        _f(m.get("MeasuredDepth")),
            "depth_ouom":       _trunc(data.get("DepthUnit") or "ft", 16),
            "active_ind":       "Y",
            "row_created_by":   "DataWrangler", "row_created_date": now,
        })
    n = _cap(engine, "cat_well_formation_top", out, uwi=uwi, inv=inv, sp=sp)
    return {"cat_well_formation_top": n} if n else {}


def _h_pressure(engine, data, *, uwi, inv, sp, now):
    flows = data.get("FlowPeriods") or []
    press = data.get("PressureMeasurements") or []

    def _mx(rows, key):
        vals = [_f(r.get(key)) for r in rows if _f(r.get(key)) is not None]
        return max(vals) if vals else None

    row = {
        "dst_id":               _uid(),
        "dst_num":              data.get("TestNumber") or 1,
        "test_type":            _trunc(data.get("PressureDataType") or "DST", 40),
        "test_date":            data.get("TestDate"),
        "top_depth":            _f(data.get("TopDepthMeasuredDepth")),
        "base_depth":           _f(data.get("BottomDepthMeasuredDepth")),
        "depth_ouom":           _trunc(data.get("DepthUnit") or "ft", 16),
        "test_result":          _trunc(data.get("Description"), 255),
        "max_oil_rate":         _mx(flows, "OilRateStbd"),
        "max_gas_rate":         _mx(flows, "GasRateMcfd"),
        "max_water_rate":       _mx(flows, "WaterRateBwpd"),
        "rate_ouom":            "BBL/D",
        "max_shut_in_pressure": _mx(press, "Pressure"),
        "pressure_ouom":        _trunc(data.get("PressureUnit") or "PSI", 16),
        "active_ind":           "Y",
        "row_created_by":       "DataWrangler", "row_created_date": now,
    }
    n = _cap(engine, "cat_well_dst", [row], uwi=uwi, inv=inv, sp=sp)
    return {"cat_well_dst": n} if n else {}


def _h_scal(engine, data, *, uwi, inv, sp, now):
    """RockFluidOrganisation (SCAL) → cat_well_core header + summary sample."""
    summ = data.get("SummaryStatistics") or {}
    core_id = _uid()
    top = _f(data.get("TopDepthMeasuredDepth"))
    base = _f(data.get("BottomDepthMeasuredDepth"))
    _cap(engine, "cat_well_core", [{
        "core_id":          core_id,
        "core_num":         1,
        "core_type":        "SCAL",
        "top_depth":        top,
        "base_depth":       base,
        "depth_ouom":       _trunc(data.get("DepthUnit") or "ft", 16),
        "active_ind":       "Y",
        "row_created_by":   "DataWrangler", "row_created_date": now,
    }], uwi=uwi, inv=inv, sp=sp)
    n = _cap(engine, "cat_well_core_sample", [{
        "core_id":               core_id,
        "sample_id":             _uid(),
        "sample_type":           "SCAL_SUMMARY",
        "sample_depth":          top,
        "depth_ouom":            _trunc(data.get("DepthUnit") or "ft", 16),
        "porosity_frac":         _as_frac(summ.get("AveragePorosity")),
        "permeability_air_md":   _f(summ.get("AveragePermeability")),
        "active_ind":            "Y",
        "row_created_by":        "DataWrangler", "row_created_date": now,
    }], uwi=uwi, inv=inv, sp=sp)
    return {"cat_well_core_sample": n} if n else {"cat_well_core": 1}


def _h_document(engine, data, *, uwi, inv, sp, now):
    tags = data.get("Tags") or {}
    n = _cap(engine, "cat_well", [{
        "WELL_NAME":        tags.get("Well") or data.get("Name") or uwi,
        "FIELD_NAME":       tags.get("Field"),
        "OPERATOR_NAME":    data.get("AuthorOrganisation"),
        "ACTIVE_IND":       "Y",
        "ROW_QUALITY":      "PRELIM",       # doc-derived stub identity
        "PPDM_GUID":        str(uuid.uuid4()),
        "ROW_CREATED_BY":   "DataWrangler", "ROW_CREATED_DATE": now,
    }], uwi=uwi, inv=inv, sp=sp, src="OSDU_DOC")
    return {"cat_well": n} if n else {}


def _h_field(engine, data, *, uwi, inv, sp, now):
    """OSDU Field (master-data) → cat_field. Field-scoped, no well UWI."""
    n = _cap(engine, "cat_field", [{
        "FIELD_KEY":         _trunc(data.get("FacilityID"), 64),
        "FIELD_NAME":        _trunc(data.get("FieldName"), 255),
        "DESCRIPTION":       _trunc(data.get("Description"), 1000),
        "DISCOVERY_YEAR":    data.get("DiscoveryYear"),
        "DISCOVERY_WELL":    _trunc(data.get("DiscoveryWell"), 255),
        "COUNTRY":           _after_colon(data.get("CountryID")),
        "PROVINCE_STATE":    _after_colon(data.get("StateProvinceID")),
        "COUNTY":            _trunc(data.get("County"), 100),
        "BASIN":             _trunc(data.get("Basin"), 100),
        "SUB_BASIN":         _trunc(data.get("SubBasin"), 100),
        "OPERATOR_NAME":     _trunc(data.get("OperatorName"), 255),
        "FIELD_STATUS":      _trunc(data.get("FieldStatus"), 40),
        "FLUID_TYPE":        _trunc(data.get("FluidType"), 40),
        "PRIMARY_RESERVOIR": _trunc(data.get("PrimaryReservoir"), 100),
        "PRODUCTION_TYPE":   _trunc(data.get("ProductionType"), 40),
        "AREA_KM2":          _f(data.get("AreaKm2")),
        "NUMBER_OF_WELLS":   data.get("NumberOfWells"),
        "CUM_PROD_OIL":      _f(data.get("CumulativeProductionOil")),
        "CUM_PROD_GAS":      _f(data.get("CumulativeProductionGas")),
        "ACTIVE_IND":        "Y",
        "ROW_CREATED_BY":    "DataWrangler", "ROW_CREATED_DATE": now,
    }], uwi=None, inv=inv, sp=sp, src="OSDU_FIELD")
    return {"cat_field": n} if n else {}


def _h_reservoir(engine, data, *, uwi, inv, sp, now):
    """OSDU Reservoir (master-data) → cat_reservoir. Reservoir-scoped, no UWI."""
    p = data.get("ReservoirProperties") or {}
    n = _cap(engine, "cat_reservoir", [{
        "RESERVOIR_KEY":     _trunc(data.get("FacilityID"), 64),
        "RESERVOIR_NAME":    _trunc(data.get("ReservoirName"), 255),
        "DESCRIPTION":       _trunc(data.get("Description"), 1000),
        "FIELD_NAME":        _trunc(data.get("FieldName"), 255),
        "RESERVOIR_TYPE":    _trunc(data.get("ReservoirType"), 40),
        "FLUID_TYPE":        _trunc(data.get("FluidType"), 40),
        "ROCK_TYPE":         _trunc(data.get("RockType"), 100),
        "AGE":               _trunc(data.get("Age"), 60),
        "FORMATION":         _trunc(data.get("Formation"), 100),
        "MEMBER":            _trunc(data.get("Member"), 100),
        "COUNTRY":           _after_colon(data.get("CountryID")),
        "PROVINCE_STATE":    _after_colon(data.get("StateProvinceID")),
        "AVG_POROSITY":      _f(p.get("AveragePorosity")),
        "AVG_PERMEABILITY":  _f(p.get("AveragePermeability")),
        "AVG_NET_PAY":       _f(p.get("AverageNetPay")),
        "AVG_DEPTH_TVD":     _f(p.get("AverageDepthTVD")),
        "INIT_PRESSURE":     _f(p.get("InitialReservoirPressure")),
        "RESERVOIR_TEMP":    _f(p.get("ReservoirTemperature")),
        "GOR":               _f(p.get("GasOilRatio")),
        "OIL_GRAVITY":       _f(p.get("OilGravity")),
        "WATER_SATURATION":  _f(p.get("WaterSaturation")),
        "RECOVERY_FACTOR":   _f(data.get("RecoveryFactor")),
        "OOIP":              _f(data.get("OriginalOilInPlace")),
        "PROVED_RESERVES":   _f(data.get("ProvedReserves")),
        "ACTIVE_IND":        "Y",
        "ROW_CREATED_BY":    "DataWrangler", "ROW_CREATED_DATE": now,
    }], uwi=None, inv=inv, sp=sp, src="OSDU_RESERVOIR")
    return {"cat_reservoir": n} if n else {}


_HANDLERS = {
    "Well": _h_well, "WellLog": _h_well, "Wellbore": _h_well,
    "WellboreTrajectory": _h_trajectory,
    "WellboreMarkerSet": _h_marker_set,
    "WellborePressureData": _h_pressure,
    "RockFluidOrganisation": _h_scal,
    "Document": _h_document,
    "Field": _h_field,
    "Reservoir": _h_reservoir,
}


# ── load (CAPTURE stage) ─────────────────────────────────────────────────────
def load_json_well_log(engine, path, *, uwi=None, inventory_id=None,
                       source_path=None, source="OSDU", well_info=None,
                       log=None):
    say = log or (lambda *_: None)
    res = {"ok": False, "loaded": 0, "errors": [], "rt": "", "note": "",
           "detail": {}}
    try:
        obj = _read(path)
    except Exception as e:
        res["errors"].append(f"json parse: {e}")
        return res

    ent = _entity(obj.get("kind"))
    res["rt"] = f"OSDU_{ent.upper()}" if ent else "JSON_OTHER"
    ident = _identity(obj)
    uwi = (uwi or ident.get("uwi") or "").strip() or None
    spath = source_path or path
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if ent in NO_TARGET or ent in SEIS_ENTITIES:
        res["note"] = f"no_target:{ent}"
        say(f"[JSON] {os.path.basename(path)}: {ent} — no cat_* target")
        return res

    handler = _HANDLERS.get(ent)
    if handler is None:
        res["note"] = f"not_impl:{ent or 'UNKNOWN'}"
        return res
    if ent not in MASTER_ENTITIES and not uwi:
        # well-domain records need a UWI; master records (Field/Reservoir)
        # are keyed on their own FacilityID and don't.
        res["errors"].append(f"{ent}: no UWI resolvable from record")
        return res

    data = obj.get("data") or {}
    try:
        if ent in ("Well", "WellLog", "Wellbore"):
            detail = handler(engine, data, obj, uwi=uwi, inv=inventory_id,
                             sp=spath, now=now)
        else:
            detail = handler(engine, data, uwi=uwi, inv=inventory_id,
                             sp=spath, now=now)
    except Exception as e:
        res["errors"].append(f"{ent} capture: {e}")
        return res

    res["detail"] = detail or {}
    res["loaded"] = sum(int(v) for v in res["detail"].values())
    res["ok"] = res["loaded"] > 0
    if res["loaded"] == 0 and not res["errors"]:
        res["note"] = f"not_impl:{ent}_EMPTY"
    say(f"[JSON] {os.path.basename(path)}: {ent} → {res['loaded']} row(s) "
        f"{res['detail']}")
    return res


# backwards-compatible alias
load_osdu = load_json_well_log

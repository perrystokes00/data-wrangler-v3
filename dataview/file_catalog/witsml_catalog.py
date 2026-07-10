"""
witsml_catalog.py
=================
WITSML 1.3.1.1 / 1.4.1.1 ("1series") reader → file_catalog.cat_* mirrors.

Two public entry points, matching the pattern of pdf_survey_catalog /
shapefile_catalog so the workbench capture path can use it uniformly:

    classify_witsml(path) -> dict
        Lightweight identity for the EXTRACT stage (FILE_WELL_HEADER):
        {file_category, report_type, uwi, well_name, operator, field,
         county, state, country, api}.

    load_witsml(engine, path, *, uwi=None, inventory_id=None,
                source_path=None, source="WITSML", well_info=None, log=None)
        Parse the document and write its content into the cat_* mirrors via
        catalog_capture.capture():
          <well>                         -> cat_well            (header)
          <trajectory>/<trajectoryStation> -> cat_well_dir_srvy_hdr / _sta
          <log>/<logCurveInfo>           -> cat_log_curve       (curve list)
        Returns {ok, loaded, errors:[...], rt, note, detail:{...}} — the same
        shape _load_rows_to_catalog expects from every loader.

The parse is namespace-agnostic (it matches on the element local-name), so the
same code reads 1.3.1.1 and 1.4.1.1 without caring which namespace URI is used.
Promotion into dv_* happens later via promote_catalog — this module is
scan-stage only and never touches dataview.dv_*.
"""
from __future__ import annotations

import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime

# Resilient import: works whether catalog_capture lands in modules/ or root.
try:
    from dataview.file_catalog.catalog_capture import capture
except ImportError:
    from dataview.file_catalog.catalog_capture import capture

WITSML_SIG = "witsml.org/schemas"


# ── namespace-agnostic XML helpers ───────────────────────────────────────────
def _local(tag: str) -> str:
    """Strip any '{ns}' prefix from an element tag → bare local-name."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find(elem, name):
    """First descendant whose local-name == name (case-insensitive), or None."""
    nl = name.lower()
    for e in elem.iter():
        if _local(e.tag).lower() == nl:
            return e
    return None


def _findall_local(elem, name):
    """All descendants whose local-name == name (case-insensitive)."""
    nl = name.lower()
    return [e for e in elem.iter() if _local(e.tag).lower() == nl]


def _child_text(elem, *names):
    """Text of the first DIRECT child matching any of names (local-name)."""
    if elem is None:
        return None
    wanted = {n.lower() for n in names}
    for c in list(elem):
        if _local(c.tag).lower() in wanted:
            t = (c.text or "").strip()
            return t or None
    return None


def _num(v):
    if v is None:
        return None
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _is_witsml(path: str) -> bool:
    """Cheap gate — read the head and confirm the WITSML namespace is declared,
    so an unrelated .xml (config, SVG, RSS) is never force-parsed."""
    try:
        with open(path, "rb") as f:
            return WITSML_SIG.encode() in f.read(2000)
    except OSError:
        return False


# ── pure parser (no DB — unit-testable) ──────────────────────────────────────
def parse_witsml(path: str) -> dict:
    """Read a WITSML file into plain dicts/lists. Pure: no DB, no Streamlit.

    Returns:
        {"well": {...}, "stations": [ {...} ], "curves": [ {...} ],
         "report_type": "WITSML_WELL" | "WITSML_TRAJECTORY" |
                        "WITSML_LOG" | "WITSML_MUDLOG"}
    """
    out = {"well": {}, "stations": [], "curves": [], "report_type": "WITSML_WELL"}
    root = ET.parse(path).getroot()

    well = _find(root, "well")
    if well is not None:
        uid = well.get("uid") or well.get("uidWell")
        out["well"] = {
            "uwi":       uid or _child_text(well, "numAPI", "numGovt"),
            "well_name": _child_text(well, "name"),
            "api":       _child_text(well, "numAPI", "numGovt"),
            "operator":  _child_text(well, "operator", "operatorDiv"),
            "field":     _child_text(well, "field"),
            "county":    _child_text(well, "county"),
            "state":     _child_text(well, "stateProvince", "state"),
            "country":   _child_text(well, "country"),
        }

    # Trajectory stations (1.4: <trajectoryStation>; values carry uom attrs)
    for stn in _findall_local(root, "trajectoryStation"):
        s = {
            "MD":   _num(_child_text(stn, "md")),
            "INC":  _num(_child_text(stn, "incl", "inc")),
            "AZ":   _num(_child_text(stn, "azi", "azim")),
            "TVD":  _num(_child_text(stn, "tvd")),
            "NS":   _num(_child_text(stn, "dispNs", "ns")),
            "EW":   _num(_child_text(stn, "dispEw", "ew")),
            "DLS":  _num(_child_text(stn, "dls")),
        }
        if s["MD"] is not None and (s["INC"] is not None or s["AZ"] is not None
                                    or s["TVD"] is not None):
            out["stations"].append(s)
    out["stations"].sort(key=lambda s: s.get("MD") or 0.0)

    # Log curves (<logCurveInfo> → mnemonic / unit / curveDescription)
    for i, lci in enumerate(_findall_local(root, "logCurveInfo")):
        mnem = _child_text(lci, "mnemonic")
        if not mnem:
            continue
        out["curves"].append({
            "CURVE_MNEMONIC":  mnem[:64],
            "CURVE_LONG_NAME": (_child_text(lci, "curveDescription", "name")
                                or "")[:256] or None,
            "CURVE_UNIT":      (_child_text(lci, "unit") or "")[:32] or None,
            "CURVE_INDEX":     i,
            "IS_INDEX":        "Y" if i == 0 else "N",
            "SOURCE_FORMAT":   "WITSML",
        })

    if out["stations"]:
        out["report_type"] = "WITSML_TRAJECTORY"
    elif out["curves"]:
        out["report_type"] = "WITSML_LOG"
    elif _find(root, "mudLog") is not None:
        out["report_type"] = "WITSML_MUDLOG"
    return out


# ── classify (EXTRACT stage) ─────────────────────────────────────────────────
def classify_witsml(path: str) -> dict:
    """Identity-only read for the extract stage. Never raises on a bad file."""
    base = {"file_category": "WELL", "report_type": "WITSML",
            "uwi": None, "well_name": None, "operator": None, "field": None,
            "county": None, "state": None, "country": None, "api": None}
    if not _is_witsml(path):
        base["file_category"] = "OTHER"
        base["report_type"] = "XML_OTHER"
        return base
    try:
        p = parse_witsml(path)
        w = p.get("well", {})
        base.update({
            "report_type": p.get("report_type", "WITSML"),
            "uwi": w.get("uwi"), "well_name": w.get("well_name"),
            "operator": w.get("operator"), "field": w.get("field"),
            "county": w.get("county"), "state": w.get("state"),
            "country": w.get("country"), "api": w.get("api"),
        })
    except Exception:
        pass
    return base


# ── load (CAPTURE stage) ─────────────────────────────────────────────────────
def load_witsml(engine, path, *, uwi=None, inventory_id=None, source_path=None,
                source="WITSML", well_info=None, log=None) -> dict:
    """Parse the WITSML file and capture its content into the cat_* mirrors."""
    say = log or (lambda *_: None)
    res = {"ok": False, "loaded": 0, "errors": [], "rt": "", "note": "",
           "detail": {}}

    if not _is_witsml(path):
        res["note"] = "not_impl:XML_OTHER"
        return res

    try:
        p = parse_witsml(path)
    except Exception as e:
        res["errors"].append(f"witsml parse: {e}")
        return res

    well = p.get("well", {})
    res["rt"] = p.get("report_type", "WITSML")
    uwi = (uwi or well.get("uwi") or "").strip() or None
    spath = source_path or path
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = 0

    # ── well header → cat_well ───────────────────────────────────────────────
    if uwi:
        try:
            n = capture(engine, "cat_well", [{
                "WELL_NAME":        well.get("well_name") or uwi,
                "OPERATOR_NAME":    well.get("operator"),
                "FIELD_NAME":       well.get("field"),
                "PROVINCE_STATE":   well.get("state"),
                "ACTIVE_IND":       "Y",
                "ROW_QUALITY":      "FINAL",
                "PPDM_GUID":        str(uuid.uuid4()),
                "ROW_CREATED_BY":   "DataWrangler",
                "ROW_CREATED_DATE": now,
            }], uwi=uwi, inventory_id=inventory_id, source_path=spath,
               source="WITSML_HEADER")
            if n:
                res["detail"]["cat_well"] = n
                total += n
        except Exception as e:
            res["errors"].append(f"header capture: {e}")

    # ── trajectory → cat_well_dir_srvy_hdr / _sta ────────────────────────────
    stations = p.get("stations", [])
    if uwi and stations:
        try:
            mds = [s["MD"] for s in stations if s.get("MD") is not None]
            survey_id = f"WITSML_{uuid.uuid4().hex[:12]}"
            capture(engine, "cat_well_dir_srvy_hdr", [{
                "SURVEY_ID":         survey_id,
                "SURVEY_TYPE":       "WITSML",
                "SURVEY_TOP_DEPTH":  min(mds) if mds else None,
                "SURVEY_BASE_DEPTH": max(mds) if mds else None,
                "DEPTH_OUOM":        "FT",
                "ACTIVE_IND":        "Y",
                "ROW_CREATED_BY":    "DataWrangler", "ROW_CREATED_DATE": now,
            }], uwi=uwi, inventory_id=inventory_id, source_path=spath,
               source="WITSML")
            sta = []
            for obs_no, s in enumerate(stations, start=1):
                sta.append({
                    "SURVEY_ID":   survey_id,
                    "STATION_ID":  f"{survey_id}_{obs_no:04d}",
                    "MD":          s.get("MD"),
                    "INCL":        s.get("INC"),
                    "AZIM":        s.get("AZ"),
                    "TVD":         s.get("TVD"),
                    "NS_OFFSET":   s.get("NS"),
                    "EW_OFFSET":   s.get("EW"),
                    "DLS":         s.get("DLS"),
                    "DEPTH_OUOM":  "FT",
                    "ACTIVE_IND":  "Y",
                    "ROW_CREATED_BY": "DataWrangler", "ROW_CREATED_DATE": now,
                })
            n = capture(engine, "cat_well_dir_srvy_sta", sta,
                        uwi=uwi, inventory_id=inventory_id,
                        source_path=spath, source="WITSML")
            if n:
                res["detail"]["cat_well_dir_srvy_sta"] = n
                total += n
        except Exception as e:
            res["errors"].append(f"trajectory capture: {e}")

    # ── log curves → cat_log_curve ───────────────────────────────────────────
    curves = p.get("curves", [])
    if curves:
        try:
            n = capture(engine, "cat_log_curve", curves,
                        uwi=uwi, inventory_id=inventory_id,
                        source_path=spath, source="WITSML")
            if n:
                res["detail"]["cat_log_curve"] = n
                total += n
        except Exception as e:
            res["errors"].append(f"curve capture: {e}")

    res["loaded"] = total
    res["ok"] = total > 0
    if total == 0 and not res["errors"]:
        res["note"] = "not_impl:WITSML_EMPTY"
    say(f"[WITSML] {os.path.basename(path)}: {total} row(s) {res['detail']}")
    return res

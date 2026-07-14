"""
witsml_header_loader.py — extract WITSML 1.4.1 objects into bulk-loader staging CSVs.

Standalone XML parser (no app dependency). Handles the three object types, each to its target:

  log        → dv_well_log / dv_well_log_curve   (well_log.csv + well_log_curve.csv)
  trajectory → dv_well_dir_srvy_hdr / _sta        (srvy_hdr.csv + srvy_sta.csv)
  mudLog     → dv_well_formation_top              (formation_top.csv)

WITSML carries uidWell as the UWI (often a real API), plus nameWell — both captured. Rows still
flow through the review/assign-UWI gate so a blank/invalid uid can be fixed before promote.
"""
import os, csv, glob
import xml.etree.ElementTree as ET

WITSML_NS = "{http://www.witsml.org/schemas/1series}"


def _q(tag):
    return f"{WITSML_NS}{tag}"


def _txt(el, tag, default=""):
    if el is None:
        return default
    c = el.find(_q(tag))
    return (c.text or default).strip() if c is not None and c.text else default


def _detect_type(root):
    """Return ('log'|'trajectory'|'mudlog', object_element) for the first object in the file."""
    tag = root.tag.replace(WITSML_NS, "")
    if tag in ("logs", "log"):
        return "log", root.find(_q("log")) if tag == "logs" else root
    if tag in ("trajectorys", "trajectory"):
        return "trajectory", root.find(_q("trajectory")) if tag == "trajectorys" else root
    if tag in ("mudLogs", "mudLog"):
        return "mudlog", root.find(_q("mudLog")) if tag == "mudLogs" else root
    return "unknown", None


def _obj_identity(obj):
    """uwi (uidWell), well_name, log_id from a WITSML object element."""
    uwi = (obj.get("uidWell") or "").strip()
    well_name = _txt(obj, "nameWell")
    return uwi, well_name


def extract_file(path, source="WITSML"):
    """Parse one WITSML file → dict of {target_kind: [rows]}. Never raises."""
    out = {"log": [], "curve": [], "srvy_hdr": [], "srvy_sta": [], "formation": [], "obj_type": None,
           "uwi": "", "well_name": "", "file": os.path.basename(path)}
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        root = ET.parse(path).getroot()
    except Exception as e:
        out["error"] = str(e)
        return out
    obj_type, obj = _detect_type(root)
    out["obj_type"] = obj_type
    if obj is None:
        return out
    uwi, well_name = _obj_identity(obj)
    out["uwi"], out["well_name"] = uwi, well_name
    fp = os.path.abspath(path)

    if obj_type == "log":
        log_id = f"LOG_{stem}"
        out["log"].append({
            "UWI": uwi, "LOG_ID": log_id, "LOG_TYPE": "WITSML",
            "LOG_DATE": _txt(obj.find(_q("commonData")), "dTimCreation")[:10],
            "RUN_NO": _txt(obj, "runNumber") or "1",
            "TOP_DEPTH": _txt(obj, "startIndex"), "BASE_DEPTH": _txt(obj, "endIndex"),
            "FILE_PATH": fp, "FILE_FORMAT": "WITSML", "WELL_NAME": well_name, "SOURCE": source})
        for lci in obj.findall(_q("logCurveInfo")):
            mnem = _txt(lci, "mnemonic")
            if mnem.upper() in ("DEPT", "DEPTH", "MD", "TVD"):
                continue                                    # index curve, not a log curve
            out["curve"].append({
                "UWI": uwi, "LOG_ID": log_id, "CURVE_NAME": mnem,
                "CURVE_DESCRIPTION": _txt(lci, "curveDescription"), "CURVE_UNIT": _txt(lci, "unit"),
                "MIN_VALUE": _txt(lci, "minIndex"), "MAX_VALUE": _txt(lci, "maxIndex"),
                "SOURCE": source})

    elif obj_type == "trajectory":
        srvy_id = f"SRVY_{stem}"
        out["srvy_hdr"].append({
            "UWI": uwi, "SRVY_ID": srvy_id, "SURVEY_SEQ_NO": "1",
            "SURVEY_TYPE": _txt(obj, "typeTrajectory"), "AZIMUTH_REF": _txt(obj, "aziRef"),
            "WELL_NAME": well_name, "SOURCE": source})
        for st in obj.findall(_q("trajectoryStation")):
            out["srvy_sta"].append({
                "UWI": uwi, "SRVY_ID": srvy_id, "SURVEY_SEQ_NO": "1",
                "MD": _txt(st, "md"), "INCLINATION": _txt(st, "incl"),
                "AZIMUTH": _txt(st, "azi"), "TVDSS": _txt(st, "tvd"), "SOURCE": source})

    elif obj_type == "mudlog":
        for i, gi in enumerate(obj.findall(_q("geologyInterval")), 1):
            lith = gi.find(_q("lithology"))
            out["formation"].append({
                "UWI": uwi, "STRAT_NAME_SET_ID": "WITSML_MUDLOG",
                "STRAT_UNIT_ID": _txt(lith, "type") or _txt(gi, "typeLithology"),
                "INTERP_ID": f"ML_{stem}_{i}", "INTERP_BY": _txt(obj, "mudLogEngineers"),
                "INTERP_DATE": _txt(obj, "dTim")[:10],
                "TOP_MD": _txt(gi, "mdTop"), "BASE_MD": _txt(gi, "mdBottom"), "SOURCE": source})
    return out


# staging-file column shapes per target
_COLS = {
    "log": ["UWI", "LOG_ID", "LOG_TYPE", "LOG_DATE", "RUN_NO", "TOP_DEPTH", "BASE_DEPTH",
            "FILE_PATH", "FILE_FORMAT", "WELL_NAME", "SOURCE"],
    "curve": ["UWI", "LOG_ID", "CURVE_NAME", "CURVE_DESCRIPTION", "CURVE_UNIT",
              "MIN_VALUE", "MAX_VALUE", "SOURCE"],
    "srvy_hdr": ["UWI", "SRVY_ID", "SURVEY_SEQ_NO", "SURVEY_TYPE", "AZIMUTH_REF", "WELL_NAME", "SOURCE"],
    "srvy_sta": ["UWI", "SRVY_ID", "SURVEY_SEQ_NO", "MD", "INCLINATION", "AZIMUTH", "TVDSS", "SOURCE"],
    "formation": ["UWI", "STRAT_NAME_SET_ID", "STRAT_UNIT_ID", "INTERP_ID", "INTERP_BY",
                  "INTERP_DATE", "TOP_MD", "BASE_MD", "SOURCE"],
}
_FILENAME = {"log": "witsml_well_log.csv", "curve": "witsml_well_log_curve.csv",
             "srvy_hdr": "witsml_srvy_hdr.csv", "srvy_sta": "witsml_srvy_sta.csv",
             "formation": "witsml_formation_top.csv"}


def write_staging_csvs(directory, out_dir=None, source="WITSML"):
    """Extract every .xml/.wml WITSML file → one CSV per target kind (only kinds with rows).
    Returns {kind: (path, n_rows)}."""
    out_dir = out_dir or directory
    os.makedirs(out_dir, exist_ok=True)
    agg = {k: [] for k in _COLS}
    for path in sorted(set(glob.glob(os.path.join(directory, "*.xml")) +
                           glob.glob(os.path.join(directory, "*.wml")) +
                           glob.glob(os.path.join(directory, "*.XML")) +
                           glob.glob(os.path.join(directory, "*.WML")))):
        res = extract_file(path, source)
        for k in _COLS:
            agg[k].extend(res.get(k, []))
    written = {}
    for k, rows in agg.items():
        if not rows:
            continue
        p = os.path.join(out_dir, _FILENAME[k])
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=_COLS[k]); w.writeheader(); w.writerows(rows)
        written[k] = (p, len(rows))
    return written


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    for kind, (p, n) in write_staging_csvs(d).items():
        print(f"{kind:10} {n:4} rows -> {p}")

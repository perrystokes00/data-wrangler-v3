"""
las_header_loader.py — extract LAS file headers into bulk-loader staging CSVs.

Reads a directory of LAS 2.0 files and writes two CSVs shaped for dv_well_log and
dv_well_log_curve, so the existing bulk_dir_loader pipeline (map → FK → promote → verify)
can load them with no new plumbing:

  well_log.csv        UWI, LOG_ID, LOG_TYPE, LOG_DATE, RUN_NO, TOP_DEPTH, BASE_DEPTH, SOURCE
  well_log_curve.csv  UWI, LOG_ID, CURVE_NAME, CURVE_UNIT, MIN_VALUE, MAX_VALUE, SOURCE

log_id is derived from the LAS filename (stable, unique per file). min/max per curve are
computed from the ~A data (NULL value excluded). Depth-index curve (first in ~C) is skipped.
"""
import os, csv, glob


def _parse_line(line):
    """LAS mnemonic line 'MNEM.UNIT  VALUE : DESCRIPTION' → (mnem, unit, value, descr)."""
    left, _, descr = line.partition(":")
    left = left.strip()
    mnem, _, rest = left.partition(".")
    mnem = mnem.strip()
    rest = rest.strip()
    parts = rest.split(None, 1)
    if not parts:
        unit, value = "", ""
    elif len(parts) == 1:
        # 'GAPI' alone = unit (curve line, no value); a lone number = value (no unit)
        unit, value = (parts[0], "") if not parts[0].replace(".", "").replace("-", "").isdigit() else ("", parts[0])
    else:
        unit, value = parts[0], parts[1].strip()
    return mnem, unit, value, descr.strip()


def parse_las(path):
    """Parse one LAS file → (well_dict, [curve_dicts], [data_rows])."""
    section = None
    well, curves, data = {}, [], []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("~"):
                u = s[1:2].upper()
                section = {"V": "V", "W": "W", "C": "C", "P": "P", "A": "A", "O": "O"}.get(u)
                continue
            if section in ("W", "P"):                    # merge parameters with well info (RUN, etc.)
                m, unit, val, desc = _parse_line(s)
                well[m.upper()] = {"unit": unit, "value": val, "desc": desc}
            elif section == "C":
                m, unit, val, desc = _parse_line(s)
                import re
                desc = re.sub(r"^\s*\d+\s+", "", desc)   # LAS often prefixes the ordinal: "2  GAMMA RAY"
                curves.append({"mnem": m, "unit": unit, "desc": desc})
            elif section == "A":
                parts = s.split()
                if parts:
                    data.append(parts)
    return well, curves, data


def _wget(well, *keys, default=""):
    for k in keys:
        if k.upper() in well and well[k.upper()]["value"]:
            return well[k.upper()]["value"]
    return default


def extract_directory(directory, source="LAS"):
    """Parse every .las in a directory → (log_rows, curve_rows) as lists of dicts."""
    log_rows, curve_rows = [], []
    for path in sorted(glob.glob(os.path.join(directory, "*.las")) +
                       glob.glob(os.path.join(directory, "*.LAS"))):
        well, curves, data = parse_las(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        log_id = f"LOG_{stem}"
        uwi = _wget(well, "UWI", "API", "WELL")
        null_val = _wget(well, "NULL", default="-999.25")
        try: null_f = float(null_val)
        except ValueError: null_f = -999.25

        log_rows.append({
            "UWI": uwi, "LOG_ID": log_id, "LOG_TYPE": "LAS",
            "LOG_DATE": _wget(well, "DATE", "DATE_LOG"),
            "RUN_NO": _wget(well, "RUN", default="1"),
            "TOP_DEPTH": _wget(well, "STRT"), "BASE_DEPTH": _wget(well, "STOP"),
            "SOURCE": source})

        # per-curve min/max from the data section; column 0 is the depth index → skip as a curve
        for ci, c in enumerate(curves):
            if ci == 0:
                continue                                   # depth index, not a log curve
            vals = []
            for row in data:
                if ci < len(row):
                    try:
                        f = float(row[ci])
                        if f != null_f:
                            vals.append(f)
                    except ValueError:
                        pass
            curve_rows.append({
                "UWI": uwi, "LOG_ID": log_id, "CURVE_NAME": c["mnem"],
                "CURVE_DESCRIPTION": c["desc"], "CURVE_UNIT": c["unit"],
                "MIN_VALUE": (f"{min(vals):.4g}" if vals else ""),
                "MAX_VALUE": (f"{max(vals):.4g}" if vals else ""),
                "SOURCE": source})
    return log_rows, curve_rows


def write_staging_csvs(directory, out_dir=None, source="LAS"):
    """Extract a directory of LAS files → well_log.csv + well_log_curve.csv in out_dir
    (defaults to the LAS directory). Returns (log_csv_path, curve_csv_path, n_logs, n_curves)."""
    out_dir = out_dir or directory
    os.makedirs(out_dir, exist_ok=True)
    log_rows, curve_rows = extract_directory(directory, source)
    log_cols = ["UWI", "LOG_ID", "LOG_TYPE", "LOG_DATE", "RUN_NO", "TOP_DEPTH", "BASE_DEPTH", "SOURCE"]
    curve_cols = ["UWI", "LOG_ID", "CURVE_NAME", "CURVE_DESCRIPTION", "CURVE_UNIT",
                  "MIN_VALUE", "MAX_VALUE", "SOURCE"]
    log_path = os.path.join(out_dir, "well_log.csv")
    curve_path = os.path.join(out_dir, "well_log_curve.csv")
    with open(log_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=log_cols); w.writeheader(); w.writerows(log_rows)
    with open(curve_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=curve_cols); w.writeheader(); w.writerows(curve_rows)
    return log_path, curve_path, len(log_rows), len(curve_rows)


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    lp, cp, nl, nc = write_staging_csvs(d)
    print(f"{nl} logs -> {lp}")
    print(f"{nc} curves -> {cp}")

"""
dlis_header_loader.py — extract DLIS headers + curves into bulk-loader staging CSVs.

Mirrors las_header_loader's output shape so the same pipeline (review → map → promote)
handles DLIS logs:

  well_log.csv        UWI, LOG_ID, LOG_TYPE, LOG_DATE, RUN_NO, TOP_DEPTH, BASE_DEPTH,
                      FILE_PATH, FILE_FORMAT, WELL_NAME, SOURCE
  well_log_curve.csv  UWI, LOG_ID, CURVE_NAME, CURVE_DESCRIPTION, CURVE_UNIT,
                      MIN_VALUE, MAX_VALUE, SOURCE

UWI often absent in DLIS origins → left blank for the review/assign-UWI step. WELL_NAME is
carried so the reviewer can seed a well. Per-curve min/max are read from the frame unless the
file exceeds MAX_SCAN_MB, in which case only mnemonic+unit are emitted (min/max blank).
"""
import os, csv, glob

MAX_SCAN_MB = 60          # above this, skip the frame data read and emit mnemonic+unit only
NULL_SENTINELS = (-999.25, -999.2, -9999.0, -999.0)


def _origin_fields(f):
    """well_name, uwi, field, company, run from the first DLIS origin."""
    wn = uwi = field = company = run = ""
    if f.origins:
        o = f.origins[0]
        wn = str(getattr(o, "well_name", "") or "")
        uwi = str(getattr(o, "api_well", "") or getattr(o, "uwi", "") or getattr(o, "well_id", "") or "")
        field = str(getattr(o, "field_name", "") or "")
        company = str(getattr(o, "company", "") or "")
        run = str(getattr(o, "run_number", "") or getattr(o, "run", "") or "")
    return wn, uwi, field, company, run


def _curve_minmax(frame, want_minmax):
    """{channel_name: (min, max)} from frame data, excluding null sentinels. {} if skipped/failed."""
    if not want_minmax:
        return {}
    import numpy as np
    out = {}
    try:
        data = frame.curves()
        for n in data.dtype.names:
            col = data[n]
            if col.dtype.kind == "f":
                col = col[np.isfinite(col)]
                for s in NULL_SENTINELS:
                    col = col[col != s]
            if len(col):
                out[n] = (float(np.min(col)), float(np.max(col)))
    except Exception:
        return {}
    return out


def extract_file(path, source="DLIS"):
    """Parse one DLIS file → (log_row dict, [curve_row dicts]). Never raises; errors → warning row."""
    import dlisio
    stem = os.path.splitext(os.path.basename(path))[0]
    log_id = f"LOG_{stem}"
    size_mb = os.path.getsize(path) / 1e6 if os.path.exists(path) else 0
    want_minmax = size_mb <= MAX_SCAN_MB

    with dlisio.dlis.load(path) as files:
        f = files[0]
        wn, uwi, field, company, run = _origin_fields(f)
        frame = f.frames[0] if f.frames else None
        # depth range from the index channel if present
        top = base = ""
        mm = _curve_minmax(frame, want_minmax) if frame is not None else {}
        seen = set()
        curve_rows = []
        for ch in (f.channels or []):
            name = str(ch.name)
            if name in seen:                              # DLIS repeats index channels; keep first
                continue
            seen.add(name)
            unit = str(getattr(ch, "units", "") or "")
            desc = str(getattr(ch, "long_name", "") or "")
            lo, hi = mm.get(name, ("", ""))
            # treat the depth index channel as the log depth range, not a curve
            if name.upper() in ("TDEP", "DEPT", "DEPTH", "MD") and lo != "" and top == "":
                top, base = f"{lo:.4g}", f"{hi:.4g}"
                continue
            curve_rows.append({
                "UWI": uwi, "LOG_ID": log_id, "CURVE_NAME": name,
                "CURVE_DESCRIPTION": desc, "CURVE_UNIT": unit,
                "MIN_VALUE": (f"{lo:.4g}" if lo != "" else ""),
                "MAX_VALUE": (f"{hi:.4g}" if hi != "" else ""),
                "SOURCE": source})

        log_row = {
            "UWI": uwi, "LOG_ID": log_id, "LOG_TYPE": "DLIS", "LOG_DATE": "",
            "RUN_NO": run or "1", "TOP_DEPTH": top, "BASE_DEPTH": base,
            "FILE_PATH": os.path.abspath(path), "FILE_FORMAT": "DLIS",
            "WELL_NAME": wn, "SOURCE": source}
    return log_row, curve_rows


def extract_directory(directory, source="DLIS"):
    log_rows, curve_rows = [], []
    for path in sorted(glob.glob(os.path.join(directory, "*.dlis")) +
                       glob.glob(os.path.join(directory, "*.DLIS"))):
        try:
            lr, crs = extract_file(path, source)
            log_rows.append(lr); curve_rows.extend(crs)
        except Exception as e:
            stem = os.path.splitext(os.path.basename(path))[0]
            log_rows.append({"UWI": "", "LOG_ID": f"LOG_{stem}", "LOG_TYPE": "DLIS",
                             "LOG_DATE": "", "RUN_NO": "1", "TOP_DEPTH": "", "BASE_DEPTH": "",
                             "FILE_PATH": os.path.abspath(path), "FILE_FORMAT": "DLIS",
                             "WELL_NAME": f"[extract error: {e}]", "SOURCE": source})
    return log_rows, curve_rows


def write_staging_csvs(directory, out_dir=None, source="DLIS"):
    out_dir = out_dir or directory
    os.makedirs(out_dir, exist_ok=True)
    log_rows, curve_rows = extract_directory(directory, source)
    log_cols = ["UWI", "LOG_ID", "LOG_TYPE", "LOG_DATE", "RUN_NO", "TOP_DEPTH", "BASE_DEPTH",
                "FILE_PATH", "FILE_FORMAT", "WELL_NAME", "SOURCE"]
    curve_cols = ["UWI", "LOG_ID", "CURVE_NAME", "CURVE_DESCRIPTION", "CURVE_UNIT",
                  "MIN_VALUE", "MAX_VALUE", "SOURCE"]
    lp = os.path.join(out_dir, "dlis_well_log.csv")
    cp = os.path.join(out_dir, "dlis_well_log_curve.csv")
    with open(lp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=log_cols); w.writeheader(); w.writerows(log_rows)
    with open(cp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=curve_cols); w.writeheader(); w.writerows(curve_rows)
    return lp, cp, len(log_rows), len(curve_rows)


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    lp, cp, nl, nc = write_staging_csvs(d)
    print(f"{nl} log(s) -> {lp}")
    print(f"{nc} curve(s) -> {cp}")

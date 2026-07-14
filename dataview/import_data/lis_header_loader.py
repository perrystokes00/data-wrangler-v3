"""
lis_header_loader.py — extract LIS headers + curves into bulk-loader staging CSVs.

Standalone (uses dlisio's LIS reader; no dependency on the app's lis_catalog). Emits the same
shape as las_header_loader / dlis_header_loader so the shared review → map → promote path
handles LIS logs. UWI is usually absent from LIS headers → blank for the review/assign-UWI step;
WELL_NAME + OPERATOR carried so the reviewer can seed a well.
"""
import os, csv, glob

MAX_SCAN_MB = 60
NULL_SENTINELS = (-999.25, -999.2, -9999.0, -999.0)


def _wellsite_header(lf):
    """{MNEM: value} from LIS wellsite records (well name, operator, field, date, UWI if any).
    Identity rows look like ('WN  ','UNAL','    ','    ','A/5-1') — short, text value last."""
    hdr = {}
    try:
        for wsd in lf.wellsite_data():
            try:
                rows = wsd.table(simple=True)
            except Exception:
                continue
            for row in rows:
                try:
                    n = len(row)                          # works for tuple/list and numpy void records
                except TypeError:
                    continue
                if n < 2:
                    continue
                first, last = row[0], row[-1]
                # numpy void fields come back as bytes/str; normalize both
                mnem = (first.decode() if isinstance(first, bytes) else str(first)).strip().upper()
                val = "" if last is None else (last.decode() if isinstance(last, bytes) else str(last)).strip()
                if mnem and val and n <= 5 and mnem not in hdr:
                    hdr[mnem] = val
    except Exception:
        pass
    return hdr


def _hget(hdr, *keys):
    for k in keys:
        if k.upper() in hdr:
            return hdr[k.upper()]
    return ""


def extract_file(path, source="LIS"):
    from dlisio import lis
    import numpy as np
    stem = os.path.splitext(os.path.basename(path))[0]
    log_id = f"LOG_{stem}"
    size_mb = os.path.getsize(path) / 1e6 if os.path.exists(path) else 0
    want_minmax = size_mb <= MAX_SCAN_MB

    with lis.load(path) as files:
        lf = files[0]
        hdr = _wellsite_header(lf)
        well_name = _hget(hdr, "WN", "WELL")
        uwi = _hget(hdr, "UWI", "API", "WI")
        operator = _hget(hdr, "CN", "COMP", "OPERATOR")
        field = _hget(hdr, "FN", "FLD", "FIELD")
        date = _hget(hdr, "DATE")

        mm, specs = {}, []
        top = base = ""
        for fmt in lf.data_format_specs():
            specs = fmt.specs
            if want_minmax:
                try:
                    curves = lis.curves(lf, fmt)
                    for n in curves.dtype.names:
                        col = curves[n]
                        if col.dtype.kind == "f":
                            col = col[np.isfinite(col)]
                            for s in NULL_SENTINELS:
                                col = col[col != s]
                        if len(col):
                            mm[str(n).strip()] = (float(np.min(col)), float(np.max(col)))
                except Exception:
                    mm = {}
            break

        curve_rows, seen = [], set()
        for sp in specs:
            name = str(getattr(sp, "mnemonic", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            unit = str(getattr(sp, "units", "") or "").strip()
            lo, hi = mm.get(name, ("", ""))
            if name.upper() in ("DEPT", "DEPTH", "MD", "TDEP") and lo != "" and top == "":
                top, base = f"{lo:.4g}", f"{hi:.4g}"
                continue
            curve_rows.append({
                "UWI": uwi, "LOG_ID": log_id, "CURVE_NAME": name,
                "CURVE_DESCRIPTION": "", "CURVE_UNIT": unit,
                "MIN_VALUE": (f"{lo:.4g}" if lo != "" else ""),
                "MAX_VALUE": (f"{hi:.4g}" if hi != "" else ""),
                "SOURCE": source})

        log_row = {
            "UWI": uwi, "LOG_ID": log_id, "LOG_TYPE": "LIS", "LOG_DATE": date,
            "RUN_NO": "1", "TOP_DEPTH": top, "BASE_DEPTH": base,
            "FILE_PATH": os.path.abspath(path), "FILE_FORMAT": "LIS",
            "WELL_NAME": well_name, "OPERATOR": operator, "SOURCE": source}
    return log_row, curve_rows


def extract_directory(directory, source="LIS"):
    log_rows, curve_rows = [], []
    for path in sorted(glob.glob(os.path.join(directory, "*.lis")) +
                       glob.glob(os.path.join(directory, "*.LIS"))):
        try:
            lr, crs = extract_file(path, source)
            log_rows.append(lr); curve_rows.extend(crs)
        except Exception as e:
            stem = os.path.splitext(os.path.basename(path))[0]
            log_rows.append({"UWI": "", "LOG_ID": f"LOG_{stem}", "LOG_TYPE": "LIS",
                             "LOG_DATE": "", "RUN_NO": "1", "TOP_DEPTH": "", "BASE_DEPTH": "",
                             "FILE_PATH": os.path.abspath(path), "FILE_FORMAT": "LIS",
                             "WELL_NAME": f"[extract error: {e}]", "OPERATOR": "", "SOURCE": source})
    return log_rows, curve_rows


def write_staging_csvs(directory, out_dir=None, source="LIS"):
    out_dir = out_dir or directory
    os.makedirs(out_dir, exist_ok=True)
    log_rows, curve_rows = extract_directory(directory, source)
    log_cols = ["UWI", "LOG_ID", "LOG_TYPE", "LOG_DATE", "RUN_NO", "TOP_DEPTH", "BASE_DEPTH",
                "FILE_PATH", "FILE_FORMAT", "WELL_NAME", "OPERATOR", "SOURCE"]
    curve_cols = ["UWI", "LOG_ID", "CURVE_NAME", "CURVE_DESCRIPTION", "CURVE_UNIT",
                  "MIN_VALUE", "MAX_VALUE", "SOURCE"]
    lp = os.path.join(out_dir, "lis_well_log.csv")
    cp = os.path.join(out_dir, "lis_well_log_curve.csv")
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

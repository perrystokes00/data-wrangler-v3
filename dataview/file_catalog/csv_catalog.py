"""
modules/csv_catalog.py — opt-in CSV / TSV header extractor for the file catalog.

Why opt-in: CSV is too generic to crawl blindly — every export, log dump and
config file is a CSV — so it is deliberately kept out of the default scan set
(see CSV_EXTS in page_workbench / pipeline_run). It runs ONLY when '.csv' or
'.tsv' is hand-entered in the Formats-to-scan box, which is the act that puts
delimited files into scope at all.

Given a delimited text file it: sniffs the delimiter (tab for .tsv, else
csv.Sniffer with a fallback), reads the header plus a bounded sample of rows,
maps columns to canonical well fields by synonym, classifies the table shape
(well header / directional survey / formation tops / checkshot / production /
generic table), and returns the same flat dict the other catalog extractors
emit (uwi, well_name, operator, ... file_category, report_type, confidence).

UWI handling: returns the *raw* UWI string as found. The catalog writer
canonicalizes it to bare-14 at write time (page_workbench._norm_uwi), so a
dashed API ('42-999-00001-00-00') here is fine and still matches dv_well.

Self-contained: stdlib only (csv, re). Never raises into the catalog loop —
any failure returns the empty-ish dict, which the pipeline reads as 'no UWI'.
"""
from __future__ import annotations
import csv
import re

# ── column-name synonyms → canonical field.  keys are normalized (A-Z0-9 only) ──
_SYN = {
    "uwi":         {"UWI", "API", "APINUMBER", "APINO", "APIWELLNUMBER",
                    "API14", "API12", "API10", "WELLAPI", "UWI14",
                    "WELLID", "WELLIDENTIFIER", "APINUM"},
    "well_name":   {"WELLNAME", "WELL", "NAME", "LEASENAME", "LEASEWELL",
                    "WELLLABEL", "COMMONNAME", "WELLNO", "WELLNUMBER"},
    "operator":    {"OPERATOR", "OPERATORNAME", "COMPANY", "CURRENTOPERATOR",
                    "OPER"},
    "well_field":  {"FIELD", "FIELDNAME", "ASSIGNEDFIELD", "POOL"},
    "state":       {"STATE", "STATENAME", "STATECODE", "PROVINCE",
                    "PROVINCESTATE"},
    "county":      {"COUNTY", "COUNTYNAME", "PARISH", "COUNTYPARISH",
                    "BOROUGH"},
    "latitude":    {"LAT", "LATITUDE", "SURFACELATITUDE", "SURFLAT", "YLAT",
                    "WGS84LAT", "LATITUDEDD", "LATDD"},
    "longitude":   {"LON", "LONG", "LONGITUDE", "SURFACELONGITUDE", "SURFLON",
                    "XLON", "WGS84LON", "LONGITUDEDD", "LONGDD"},
    "total_depth": {"TD", "TOTALDEPTH", "DRILLTD", "FINALTD", "MDTD", "TDMD"},
    "spud_date":   {"SPUD", "SPUDDATE", "DATESPUD"},
}

# ── shape-detector marker columns (normalized) ──
_MD   = {"MD", "MEASUREDDEPTH", "DEPTH", "DEPTHMD"}
_INC  = {"INC", "INCL", "INCLINATION", "DEVI", "DEV"}
_AZI  = {"AZI", "AZIM", "AZIMUTH", "AZIMUTHDEG"}
_TVD  = {"TVD", "TRUEVERTICALDEPTH", "TVDSS"}
_FORM = {"FORMATION", "FORMATIONNAME", "STRATUNIT", "MARKER", "PICK",
         "TOPNAME", "ZONE"}
_TWTT = {"TWTT", "TWT", "TWOWAYTIME", "OWT"}
_OIL  = {"OIL", "OILBBL", "OILPROD", "BOPD", "OILVOL"}
_GAS  = {"GAS", "GASMCF", "GASPROD", "MCFD", "GASVOL"}
_WAT  = {"WATER", "WATERBBL", "WTR", "BWPD", "WATERVOL"}

MAX_SAMPLE_ROWS = 200          # enough to classify + grab a representative UWI
SNIFF_BYTES     = 8192


def _norm_key(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _looks_like_uwi(v) -> bool:
    d = _digits(v)
    return 10 <= len(d) <= 16


def _sniff_delim(sample: str, ext: str) -> str:
    if ext == ".tsv":
        return "\t"
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        first = sample.splitlines()[0] if sample else ""
        counts = {d: first.count(d) for d in (",", ";", "\t", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else ","


def classify_csv(fpath: str) -> dict:
    """Extract catalog header fields from a delimited (.csv/.tsv) file."""
    out = {
        "file_category": "OTHER",
        "report_type":   "CSV",
        "uwi": None, "well_name": None, "operator": None,
        "well_field": None, "state": None, "county": None,
        "latitude": None, "longitude": None,
        "total_depth": None, "spud_date": None,
        "confidence": 0.0,
        "n_rows": 0, "n_distinct_uwi": 0,
    }
    try:
        ext = ("." + fpath.rsplit(".", 1)[-1].lower()) if "." in fpath else ""
        with open(fpath, "r", encoding="utf-8-sig", errors="replace") as fh:
            sample = fh.read(SNIFF_BYTES)
            fh.seek(0)
            delim = _sniff_delim(sample, ext)
            reader = csv.reader(fh, delimiter=delim)

            try:
                header = next(reader)
            except StopIteration:
                return out                       # empty file

            norm = [_norm_key(h) for h in header]
            nset = set(norm)

            # header column → canonical field (first match wins)
            colmap: dict[str, int] = {}
            for i, nk in enumerate(norm):
                for field, syns in _SYN.items():
                    if nk in syns and field not in colmap:
                        colmap[field] = i

            has = lambda S: bool(nset & S)
            if has(_MD) and has(_INC) and has(_AZI):
                out["report_type"] = "DIRECTIONAL_SURVEY"
            elif has(_FORM) and (has(_MD) or has(_TVD)):
                out["report_type"] = "FORMATION_TOPS"
            elif has(_TWTT) and has(_MD):
                out["report_type"] = "CHECKSHOT"
            elif has(_OIL) or has(_GAS) or has(_WAT):
                out["report_type"] = "PRODUCTION"
            elif "uwi" in colmap or "well_name" in colmap:
                out["report_type"] = "WELL_HEADER"
            else:
                out["report_type"] = "CSV_TABLE"

            uwi_col = colmap.get("uwi")
            distinct_uwi: set[str] = set()
            first_vals: dict[str, str] = {}
            n = 0
            for row in reader:
                if not row or all((c or "").strip() == "" for c in row):
                    continue
                n += 1
                if uwi_col is not None and uwi_col < len(row):
                    raw = (row[uwi_col] or "").strip()
                    if raw and _looks_like_uwi(raw):
                        distinct_uwi.add(_digits(raw))
                        if not out["uwi"]:
                            out["uwi"] = raw      # raw — writer normalizes
                for field, ci in colmap.items():
                    if field == "uwi" or field in first_vals:
                        continue
                    if ci < len(row):
                        v = (row[ci] or "").strip()
                        if v:
                            first_vals[field] = v
                if n >= MAX_SAMPLE_ROWS:
                    break

            out["n_rows"] = n
            out["n_distinct_uwi"] = len(distinct_uwi)
            for field, v in first_vals.items():
                out[field] = v[:255]

            ident = bool(out["uwi"] or out["well_name"])
            out["file_category"] = "WELL" if ident else "OTHER"
            matched = len(colmap)
            out["confidence"] = round(min(1.0, matched / 6.0), 2) if matched else 0.0
            if out["n_distinct_uwi"] > 1:
                out["multi_well"] = True          # representative UWI = first row
    except Exception:
        return out
    return out

"""
modules/pdf_survey_catalog.py
=============================
Directional survey PDF extraction, classification and PPDM loading.

Supports:
  - Text-based PDFs (pdfplumber)
  - Three common report layouts: Landmark, Baker Hughes, Simple
  - Auto-detects column order regardless of layout
  - Loads to dbo.WELL_DIR_SURVEY + dbo.WELL_DIR_SRVY_STATION

Pipeline:
  1. scan_directory()       → find all PDFs
  2. classify_pdf()         → detect if it's a survey + extract well info
  3. extract_stations()     → parse the station table
  4. validate_stations()    → check continuity, flag anomalies
  5. load_to_ppdm()         → insert into PPDM tables
"""
from __future__ import annotations
import re, uuid
from pathlib import Path
from typing import Optional
import pdfplumber
import pandas as pd
import numpy as np

# ── Report type constants ─────────────────────────────────────────────────────
RT_DIRECTIONAL = "DIRECTIONAL_SURVEY"
RT_MUDLOG      = "MUD_LOG"
RT_FORMATION   = "FORMATION_TOPS"
RT_COMPLETION  = "COMPLETION_REPORT"
RT_UNKNOWN     = "UNKNOWN"

# ── Column name synonyms → canonical name ────────────────────────────────────
COL_SYNONYMS = {
    "MD": [
        "md", "measured depth", "meas depth", "depth ft", "depth",
        "md (ft)", "meas dep", "measdepth", "md_ft", "md ft",
    ],
    "INC": [
        "inc", "incl", "inclination", "incl deg", "inc (deg)",
        "inc (°)", "inclination (deg)", "angle", "inc deg",
    ],
    "AZI": [
        "azi", "azim", "azimuth", "azim deg", "azi (deg)",
        "azimuth (deg)", "azimuth (tn)", "azi (°)", "azim (°)", "azim deg",
    ],
    "TVD": [
        "tvd", "true vert dep", "true vertical depth", "tvd ft",
        "tvd (ft)", "tv depth", "vert depth",
    ],
    "NS": [
        "ns", "n/s", "northing", "n/s (ft)", "ns (ft)", "north/south",
        "ns ft", "n-s", "n/s ft",
    ],
    "EW": [
        "ew", "e/w", "easting", "e/w (ft)", "ew (ft)", "east/west",
        "ew ft", "e-w", "e/w ft",
    ],
    "DLS": [
        "dls", "dog leg", "dogleg", "dog leg sev", "dl sev",
        "dls (deg/100)", "dls deg/100", "dogleg severity",
        "dog leg severity", "dl", "d.l.s",
    ],
    "VSEC": [
        "vsec", "v-sec", "closure dist", "closure distance",
        "vertical section", "v sec", "vsec ft",
    ],
}

# Reverse lookup: synonym → canonical
_SYN_MAP = {}
for canon, syns in COL_SYNONYMS.items():
    for s in syns:
        _SYN_MAP[s.lower().strip()] = canon


def _match_col(name: str) -> Optional[str]:
    """Match a column header string to a canonical column name."""
    cleaned = re.sub(r'[\(\)°\n]', ' ', name).lower().strip()
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Direct match
    if cleaned in _SYN_MAP:
        return _SYN_MAP[cleaned]
    # Partial match
    for syn, canon in _SYN_MAP.items():
        if syn in cleaned or cleaned in syn:
            return canon
    return None


# ── Well info extraction patterns ─────────────────────────────────────────────
INFO_PATTERNS = {
    "uwi": [
        r'(?:UWI|API|API.?NUM|API.?NO)[:\s]+([0-9\-]{10,20})',
        r'([0-9]{2}-[0-9]{3}-[0-9]{5}-[0-9]{2}-[0-9]{2})',
    ],
    "well_name": [
        r'(?:WELL\s+NAME|WELLNAME)[:\s]+([A-Z0-9 #\-/]+?)(?:\n|$)',
        r'(?:WELL)[:\s]+([A-Z0-9 #\-/]+?)(?:\n|$)',
    ],
    "operator": [
        r'(?:OPERATOR|COMPANY)[:\s]+([A-Za-z0-9 &.,]+?)(?:\n|$)',
    ],
    "field": [
        r'(?:FIELD)[:\s]+([A-Za-z0-9 \-]+?)(?:\n|$)',
    ],
    "state": [
        r'(?:STATE)[:\s]+([A-Z]{2,})',
        r'\b(TX|OK|NM|CO|WY|ND|MT|KS|LA|MS|AL|PA|WV|OH)\b',
    ],
    "contractor": [
        r'(?:CONTRACTOR|SERVICE\s+CO)[:\s]+([A-Za-z0-9 &.,]+?)(?:\n|$)',
    ],
    "survey_type": [
        r'(MWD|Magnetic MWD|Gyroscopic|Gyro|Magnetic|Accelerometer)',
    ],
    "total_depth": [
        r'(?:TOTAL DEPTH|TD|MAX DEPTH)[:\s]+([\d,]+)\s*(?:ft|m)',
        r'(?:TOTAL\s+DEPTH)[:\s]+([\d,]+)',
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Scanner
# ══════════════════════════════════════════════════════════════════════════════

def scan_directory(root_path: str) -> list[dict]:
    """Recursively find all PDF files."""
    root  = Path(root_path)
    files = []
    for fp in sorted(root.rglob('*.pdf')):
        files.append({
            "file_id":     uuid.uuid4().hex[:20].upper(),
            "file_path":   str(fp),
            "file_name":   fp.name,
            "file_size_kb":round(fp.stat().st_size/1024, 1),
            "page_count":  0,
            "report_type": RT_UNKNOWN,
            "status":      "PENDING",
        })
    return files


# ══════════════════════════════════════════════════════════════════════════════
# 2. Classifier — detect report type and extract well header
# ══════════════════════════════════════════════════════════════════════════════

def classify_pdf(file_path: str) -> dict:
    """
    Open PDF, detect report type, extract well header information.
    Returns classification dict.
    """
    result = {
        "file_path":    file_path,
        "file_name":    Path(file_path).name,
        "report_type":  RT_UNKNOWN,
        "confidence":   0.0,
        "page_count":   0,
        "well_name":    None,
        "uwi":          None,
        "operator":     None,
        "field":        None,
        "state":        None,
        "contractor":   None,
        "survey_type":  "MWD",
        "total_depth":  None,
        "station_count":0,
        "error":        None,
    }

    try:
        with pdfplumber.open(file_path) as pdf:
            result["page_count"] = len(pdf.pages)

            # Extract text from first page
            text = pdf.pages[0].extract_text() or ""
            text_upper = text.upper()

            # ── Detect report type ────────────────────────────────────────────
            survey_keywords = [
                "DIRECTIONAL SURVEY", "WELLBORE SURVEY",
                "SURVEY REPORT", "MWD", "MEASURED DEPTH",
                "INCLINATION", "AZIMUTH", "TVD", "DOG LEG",
            ]
            # Also catch simple/plain format column headers
            simple_keywords = [
                "INCL DEG", "AZIM DEG", "DEPTH FT",
                "INC (DEG)", "AZI (DEG)", "TVD FT",
                "DOGLEG", "DOG LEG SEV", "DLS",
                "MEASURED DEPTH", "TRUE VERT",
            ]
            score_full   = sum(1 for kw in survey_keywords if kw in text_upper)
            score_simple = sum(1 for kw in simple_keywords  if kw in text_upper)
            score        = score_full

            if score >= 3 or (score >= 1 and score_simple >= 2) or score_simple >= 3:
                result["report_type"] = RT_DIRECTIONAL
                combined = score_full + score_simple
                total    = len(survey_keywords) + len(simple_keywords)
                result["confidence"]  = min(1.0, combined / (total * 0.4))
            elif "MUD LOG" in text_upper or "MUDLOG" in text_upper:
                result["report_type"] = RT_MUDLOG
                result["confidence"]  = 0.8
            elif "FORMATION" in text_upper and "TOPS" in text_upper:
                result["report_type"] = RT_FORMATION
                result["confidence"]  = 0.7
            elif "COMPLETION" in text_upper:
                result["report_type"] = RT_COMPLETION
                result["confidence"]  = 0.6

            # ── Extract well info ─────────────────────────────────────────────
            for field, patterns in INFO_PATTERNS.items():
                for pat in patterns:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        val = m.group(1).strip()
                        if field == "total_depth":
                            val = val.replace(',','')
                        result[field] = val
                        break

            # Count stations if it's a survey
            if result["report_type"] == RT_DIRECTIONAL:
                all_text = "\n".join(
                    p.extract_text() or "" for p in pdf.pages
                )
                # Count rows that look like survey stations
                # (line starting with a number)
                station_rows = re.findall(
                    r'^\s*(\d[\d,]*\.?\d*)\s+\d',
                    all_text, re.MULTILINE
                )
                result["station_count"] = len(station_rows)

    except Exception as e:
        result["error"] = str(e)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 3. Station extractor
# ══════════════════════════════════════════════════════════════════════════════

def extract_stations(file_path: str) -> dict:
    """
    Extract survey station data from a directional survey PDF.
    Returns {"stations": [...], "columns_found": [...], "error": None}
    """
    result = {
        "stations":      [],
        "columns_found": [],
        "col_map":       {},
        "error":         None,
    }

    try:
        with pdfplumber.open(file_path) as pdf:
            all_rows = []
            header_found = False
            col_map = {}

            for page in pdf.pages:
                # Try table extraction first
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        if not table:
                            continue
                        # Find header row
                        for i, row in enumerate(table):
                            if row and not header_found:
                                # Check if this looks like a header
                                matches = sum(
                                    1 for cell in row
                                    if cell and _match_col(str(cell))
                                )
                                if matches >= 3:
                                    # Map column indices to canonical names
                                    col_map = {}
                                    for j, cell in enumerate(row):
                                        if cell:
                                            canon = _match_col(str(cell))
                                            if canon:
                                                col_map[j] = canon
                                    header_found = True
                                    result["col_map"]       = {v:k for k,v in col_map.items()}
                                    result["columns_found"] = list(col_map.values())
                                    continue

                            if header_found and row:
                                # Try to parse as a data row
                                station = _parse_station_row(row, col_map)
                                if station:
                                    all_rows.append(station)

                else:
                    # Fallback: text-based extraction
                    text = page.extract_text() or ""
                    lines = text.split('\n')
                    for line in lines:
                        if not header_found:
                            # Look for header line
                            canon_matches = sum(
                                1 for tok in re.split(r'\s{2,}', line)
                                if _match_col(tok)
                            )
                            if canon_matches >= 3:
                                toks = re.split(r'\s{2,}', line.strip())
                                col_map = {}
                                idx = 0
                                for tok in toks:
                                    canon = _match_col(tok)
                                    if canon:
                                        col_map[idx] = canon
                                    idx += 1
                                header_found = True
                                result["columns_found"] = list(col_map.values())
                                continue
                        else:
                            toks = line.strip().split()
                            station = _parse_token_row(toks, col_map)
                            if station:
                                all_rows.append(station)

            result["stations"] = all_rows

    except Exception as e:
        result["error"] = str(e)

    return result


def _parse_station_row(row: list, col_map: dict) -> Optional[dict]:
    """Parse one table row into a station dict."""
    st = {}
    for j, canon in col_map.items():
        if j < len(row) and row[j] is not None:
            val = str(row[j]).replace(',','').strip()
            try:
                st[canon] = float(val)
            except ValueError:
                pass
    # Must have at least MD and one of INC/AZI
    if "MD" in st and ("INC" in st or "AZI" in st):
        return st
    return None


def _parse_token_row(toks: list, col_map: dict) -> Optional[dict]:
    """Parse whitespace-split tokens into a station dict."""
    if not toks:
        return None
    # First token must be a number (MD)
    try:
        float(toks[0].replace(',',''))
    except ValueError:
        return None

    st = {}
    numeric_toks = []
    for tok in toks:
        try:
            numeric_toks.append(float(tok.replace(',','').replace('+','')))
        except ValueError:
            pass

    # Map by position
    for i, (idx, canon) in enumerate(sorted(col_map.items())):
        if i < len(numeric_toks):
            st[canon] = numeric_toks[i]

    if "MD" in st and ("INC" in st or "AZI" in st):
        return st
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 4. Validation
# ══════════════════════════════════════════════════════════════════════════════

def validate_stations(stations: list[dict]) -> dict:
    """
    Validate station data for common issues.
    Returns {"valid": bool, "warnings": [...], "errors": [...]}
    """
    warnings = []
    errors   = []

    if not stations:
        errors.append("No stations extracted")
        return {"valid": False, "warnings": warnings, "errors": errors}

    mds = [s.get("MD",0) for s in stations]

    # Check MD is monotonically increasing
    for i in range(1, len(mds)):
        if mds[i] <= mds[i-1]:
            errors.append(
                f"MD not increasing at station {i}: "
                f"{mds[i-1]} → {mds[i]}"
            )

    # Check inclination range
    for i, s in enumerate(stations):
        inc = s.get("INC", 0)
        azi = s.get("AZI", 0)
        if inc < 0 or inc > 180:
            errors.append(f"Station {i}: INC={inc} out of range (0-180°)")
        if azi < 0 or azi > 360:
            errors.append(f"Station {i}: AZI={azi} out of range (0-360°)")

    # Check DLS for extreme values
    for i, s in enumerate(stations):
        dls = s.get("DLS", 0)
        if dls > 15:
            warnings.append(
                f"Station {i} MD={s.get('MD','?')}: "
                f"High DLS={dls}°/100ft"
            )

    # Check for gaps
    if len(mds) > 1:
        steps = [mds[i]-mds[i-1] for i in range(1,len(mds))]
        avg_step = sum(steps)/len(steps)
        for i, step in enumerate(steps):
            if step > avg_step * 3:
                warnings.append(
                    f"Large gap between stations {i} and {i+1}: "
                    f"{step:.0f} ft"
                )

    return {
        "valid":    len(errors) == 0,
        "warnings": warnings,
        "errors":   errors,
        "station_count": len(stations),
        "md_range": f"{min(mds):.0f} – {max(mds):.0f} ft",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. PPDM Loader
# ══════════════════════════════════════════════════════════════════════════════

def load_to_ppdm(well_info: dict, stations: list[dict],
                  engine, dialect: str = "mssql",
                  source: str = "PDF_SURVEY",
                  dry_run: bool = False) -> dict:
    """
    Load survey header to WELL_DIR_SURVEY and stations to
    WELL_DIR_SRVY_STATION.
    """
    from sqlalchemy import text
    from modules.catalog_dialect import now_expr

    result = {"loaded": 0, "skipped": 0,
              "survey_id": None, "errors": []}

    if not stations:
        result["errors"].append("No stations to load")
        return result

    uwi     = (well_info.get("uwi") or "").strip()
    if not uwi:
        result["errors"].append("No UWI — cannot load without a well key")
        return result

    now        = now_expr(dialect)
    survey_id  = uuid.uuid4().hex[:40].upper()
    result["survey_id"] = survey_id

    if dry_run:
        result["loaded"] = len(stations)
        return result

    try:
        with engine.begin() as con:
            # Insert survey header
            con.execute(text(f"""
                INSERT INTO dbo.WELL_DIR_SURVEY
                (WELL_DIR_SURVEY_ID, UWI, SURVEY_TYPE,
                 SOURCE, ROW_CREATED_BY, ROW_CREATED_DATE)
                VALUES (:sid, :uwi, :stype, :src, :by, {now})
            """), {
                "sid":   survey_id,
                "uwi":   uwi[:40],
                "stype": (well_info.get("survey_type") or "MWD")[:40],
                "src":   source[:40],
                "by":    "DataWrangler",
            })

            # Insert stations
            for i, st in enumerate(stations):
                station_id = uuid.uuid4().hex[:40].upper()
                con.execute(text(f"""
                    INSERT INTO dbo.WELL_DIR_SRVY_STATION
                    (WELL_DIR_SRVY_STATION_ID, WELL_DIR_SURVEY_ID, UWI,
                     STATION_MD, INCLINATION, AZIMUTH, STATION_TVD,
                     NS_DEVIATION, EW_DEVIATION, DOGLEG_SEVERITY,
                     SOURCE, ROW_CREATED_BY, ROW_CREATED_DATE)
                    VALUES
                    (:stid, :sid, :uwi,
                     :md, :inc, :azi, :tvd,
                     :ns, :ew, :dls,
                     :src, :by, {now})
                """), {
                    "stid": station_id,
                    "sid":  survey_id,
                    "uwi":  uwi[:40],
                    "md":   st.get("MD"),
                    "inc":  st.get("INC"),
                    "azi":  st.get("AZI"),
                    "tvd":  st.get("TVD"),
                    "ns":   st.get("NS"),
                    "ew":   st.get("EW"),
                    "dls":  st.get("DLS"),
                    "src":  source[:40],
                    "by":   "DataWrangler",
                })
            result["loaded"] = len(stations)

    except Exception as e:
        result["errors"].append(str(e))

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 6. Summary
# ══════════════════════════════════════════════════════════════════════════════

def summarize_scan(files: list[dict]) -> dict:
    by_type = {}
    for f in files:
        rt = f.get("report_type", RT_UNKNOWN)
        by_type[rt] = by_type.get(rt, 0) + 1
    return {
        "total_files":    len(files),
        "by_type":        by_type,
        "surveys":        by_type.get(RT_DIRECTIONAL, 0),
        "unknown":        by_type.get(RT_UNKNOWN, 0),
        "ready_to_load":  by_type.get(RT_DIRECTIONAL, 0),
    }

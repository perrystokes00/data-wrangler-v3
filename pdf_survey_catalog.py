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
        "dog leg severity", "dl", "d.l.s", "dls deg 100",
    ],
    "VSEC": [
        "vsec", "v-sec", "closure dist", "closure distance",
        "vertical section", "v sec", "vsec ft",
    ],
}

# Extended patterns for multi-word column headers (Baker Hughes, Landmark etc.)
_TEXT_COL_PATTERNS = [
    (r'Meas\s+Depth',      'MD'),
    (r'Depth\s+ft',        'MD'),
    (r'True\s+Vert\s+Dep', 'TVD'),
    (r'TVD\s+ft',          'TVD'),
    (r'Inclination',       'INC'),
    (r'Incl\s+deg',        'INC'),
    (r'Inc\s+deg',         'INC'),
    (r'Azimuth',           'AZI'),
    (r'Azim\s+deg',        'AZI'),
    (r'Azi\s+deg',         'AZI'),
    (r'Dog\s+Leg\s+Sev',   'DLS'),
    (r'DLS\s+deg',         'DLS'),
    (r'DLS\s*\(',          'DLS'),
    (r'Northing',          'NS'),
    (r'N/S\s+ft',          'NS'),
    (r'Easting',           'EW'),
    (r'E/W\s+ft',          'EW'),
    (r'Closure\s+Dist',    'VSEC'),
    (r'Vert\s+Sect',       'VSEC'),
    (r'MD',            'MD'),
    (r'INC',           'INC'),
    (r'AZI',           'AZI'),
    (r'TVD',           'TVD'),
    (r'NS',            'NS'),
    (r'EW',            'EW'),
    (r'DLS',           'DLS'),
    (r'VSEC',          'VSEC'),
    # Landmark/Halliburton format — columns with units in parens
    (r'\bMD\s*\(',          'MD'),
    (r'\bINC\s*\(',         'INC'),
    (r'\bAZI\s*\(',         'AZI'),
    (r'\bTVD\s*\(',         'TVD'),
    (r'N/S\s*\(',           'NS'),
    (r'E/W\s*\(',           'EW'),
    (r'DLS\s*\(',           'DLS'),
    (r'V-Sec',              'VSEC'),
    (r'V\.Sec',             'VSEC'),
    (r'V\s+Sec',            'VSEC'),
]

# Reverse lookup: synonym → canonical
_SYN_MAP = {}
for canon, syns in COL_SYNONYMS.items():
    for s in syns:
        _SYN_MAP[s.lower().strip()] = canon


def _match_col(name: str) -> Optional[str]:
    """Match a column header string to a canonical column name."""
    # Preserve N/S and E/W before stripping slashes
    preserved = re.sub(r'\b([NE])/([SW])\b', r'\1\2', name, flags=re.IGNORECASE)
    # Strip degree signs (Unicode ° plus asterisk/bullet substitutes from
    # bad PDF encodings), parentheses, slashes within units, newlines
    cleaned = re.sub(r'[()°\*\u00b0\u2022\u00b7/\n]', ' ', preserved).lower().strip()
    # Strip any remaining non-ASCII (encoding artifacts)
    cleaned = re.sub(r'[^\x00-\x7f]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    # Direct match
    if cleaned in _SYN_MAP:
        return _SYN_MAP[cleaned]
    # Partial match
    for syn, canon in _SYN_MAP.items():
        if syn in cleaned or cleaned in syn:
            return canon
    # Last resort — match on first word only
    first = cleaned.split()[0] if cleaned.split() else ""
    if first and first in _SYN_MAP:
        return _SYN_MAP[first]
    return None


# ── Well info extraction patterns ─────────────────────────────────────────────
INFO_PATTERNS = {
    "uwi": [
        r'(?:UWI|API|UWI\s*/\s*API|API.?NUM|API.?NO)[:\s]+([0-9\-]{10,20})',
        r'([0-9]{2}-[0-9]{3}-[0-9]{5}-[0-9]{2}-[0-9]{2})',
    ],
    "well_name": [
        # Stop at newline OR at UWI/API label on same line
        r'(?:WELL\s+NAME|WELLNAME)[:\s]+([A-Za-z0-9 #\-/]+?)(?=\s{2,}|\t|\n|$|(?:UWI|API|Field|State))',
        r'(?:Well\s+Name)[:\s]+([A-Za-z0-9 #\-/]+?)(?=\s{2,}|\t|\n|$|(?:UWI|API|Field|State))',
        r'(?:^WELL)[:\s]+([A-Za-z0-9 #\-/]+?)(?=\s{2,}|\t|\n|$|(?:UWI|API))',
    ],
    "operator": [
        # Stop at newline OR at a known field label on the same line
        r'(?:OPERATOR|COMPANY|OPERATED\s+BY)[:\s]+([A-Za-z0-9 &.,]+?)(?=\s{2,}|\t|\n|\r|$|(?:Survey|UWI|API|Field|State|Well\s+Name|Report))',
        r'Operator[:\s]+([A-Za-z0-9 &.,]+?)(?=\s{2,}|\t|\n|\r|$|(?:Survey|UWI|Field|Well))',
    ],
    "field": [
        r'(?:FIELD|FIELD\s+NAME)[:\s]+([A-Za-z0-9 \-]+?)(?:\n|$)',
        r'Field[:\s]+([A-Za-z0-9 \-]+?)(?:\n|$)',
    ],
    "county": [
        r'(?:COUNTY)[:\s]+([A-Za-z ]+?)(?:\n|$)',
        r'County[:\s]+([A-Za-z ]+?)(?:\n|$)',
    ],
    "state": [
        r'(?:STATE)[:\s]+([A-Z]{2,})',
        r'State[:\s]+([A-Z]{2})',
        r'\b(TX|OK|NM|CO|WY|ND|MT|KS|LA|MS|AL|PA|WV|OH)\b',
    ],
    "contractor": [
        r'(?:CONTRACTOR|SERVICE\s+CO|DRILLING\s+CO)[:\s]+([A-Za-z0-9 &.,]+?)(?:\n|$)',
    ],
    "survey_type": [
        r'(MWD|Magnetic MWD|Gyroscopic|Gyro|Magnetic|Accelerometer)',
    ],
    "latitude": [
        r'(?:LATITUDE|LAT)[:\s]+([0-9.\-]+)',
    ],
    "longitude": [
        r'(?:LONGITUDE|LON|LONG)[:\s]+([0-9.\-]+)',
    ],
    "spud_date": [
        r'(?:SPUD\s+DATE|SPUD)[:\s]+([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})',
    ],
    "rig_release": [
        r'(?:RIG\s+RELEASE|RELEASE\s+DATE)[:\s]+([0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})',
    ],
    "total_depth": [
        r'(?:TOTAL\s+DEPTH|TD|MAX\s+DEPTH)[:\s]+([\d,]+)\s*(?:ft|FT|m|M)',
        r'(?:TOTAL\s+DEPTH)[:\s]+([\d,]+)',
        r'Total\s+Depth[:\s]+([\d,]+)',
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Scanner
# ══════════════════════════════════════════════════════════════════════════════

def scan_directory(root_path: str) -> list[dict]:
    import pdfplumber
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
    import pdfplumber
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

            # Extract text from first 3 pages for classification
            text      = pdf.pages[0].extract_text() or ""
            all_pages = " ".join(
                (p.extract_text() or "") for p in pdf.pages[:3]
            )
            text_upper     = text.upper()
            all_upper      = all_pages.upper()

            # ── Step 1: Check specific/named report types first ───────────────
            # These have distinctive title keywords — check before generic
            # directional keywords which appear in many report types.
            _specific = [
                (RT_EOWR,     ["END OF WELL", "FINAL WELL REPORT",
                                "END-OF-WELL", "WELL COMPLETION REPORT",
                                "ELAPSED DAYS", "AFE COST", "ACTUAL COST"]),
                (RT_MUDLOG,   ["MUD LOG", "MUDLOG", "LITHOLOGY LOG",
                                "GAS UNITS", "MUD WEIGHT"]),
                (RT_SCOUT,    ["SCOUT TICKET", "SCOUT REPORT",
                                "INITIAL PRODUCTION", "IP RATE"]),
                (RT_DDR,      ["DAILY DRILLING REPORT", "DDR",
                                "DAILY REPORT", "24-HOUR", "WEIGHT ON BIT"]),
                (RT_WELL_TEST,["WELL TEST REPORT", "PRODUCTION TEST",
                                "BUILDUP TEST", "DRAWDOWN", "SKIN FACTOR"]),
                (RT_RFT,      ["REPEAT FORMATION TESTER", "RFT", "MDT",
                                "FORMATION PRESSURE", "WIRELINE PRESSURE"]),
                (RT_PETRO,    ["PETROPHYSICAL", "PETROPHYSICAL INTERPRETATION",
                                "PHIE", "NET PAY", "VCL", "ARCHIE",
                                "WATER SATURATION", "LOG INTERPRETATION",
                                "EFFECTIVE POROSITY", "RESISTIVITY"]),
                (RT_CASING,   ["CASING RECORD", "CEMENTING RECORD",
                                "CEMENT JOB", "TOP OF CEMENT", "SLURRY"]),
                (RT_FORMATION,["FORMATION TOPS", "STRATIGRAPHIC TOPS",
                                "TOP PICKS", "FORMATION PICK"]),
                (RT_COMPLETION,["COMPLETION REPORT", "FRAC REPORT",
                                "PERFORATION", "COMPLETION SUMMARY"]),
                ("CORE_PHOTO",  ["CORE IMAGE", "CORE PHOTO", "ANNOTATED FEATURES",
                                 "PLANAR FRACTURE", "SEMI-PLANAR", "CURVIPLANAR",
                                 "UTAH FORGE", "STIMULATION CORE"]),
            ]

            for rt, keywords in _specific:
                hits = sum(1 for kw in keywords if kw in all_upper)
                if hits >= 2:
                    result["report_type"] = rt
                    result["confidence"]  = min(1.0, hits / len(keywords) * 2.5)
                    break

            # ── Step 2: Fall back to directional survey detection ─────────────
            if result["report_type"] == RT_UNKNOWN:
                survey_keywords = [
                    "DIRECTIONAL SURVEY", "WELLBORE SURVEY",
                    "SURVEY REPORT", "MWD", "MEASURED DEPTH",
                    "INCLINATION", "AZIMUTH", "TVD", "DOG LEG",
                ]
                simple_keywords = [
                    "INCL DEG", "AZIM DEG", "DEPTH FT",
                    "INC (DEG)", "AZI (DEG)", "TVD FT",
                    "DOGLEG", "DOG LEG SEV", "DLS",
                    "MEASURED DEPTH", "TRUE VERT",
                ]
                score_full   = sum(1 for kw in survey_keywords if kw in text_upper)
                score_simple = sum(1 for kw in simple_keywords  if kw in text_upper)

                if (score_full >= 3
                        or (score_full >= 1 and score_simple >= 2)
                        or score_simple >= 3):
                    result["report_type"] = RT_DIRECTIONAL
                    combined = score_full + score_simple
                    total    = len(survey_keywords) + len(simple_keywords)
                    result["confidence"] = min(1.0, combined / (total * 0.4))

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

            # ── Count stations if directional survey ──────────────────────────
            if result["report_type"] == RT_DIRECTIONAL:
                all_text = "\n".join(
                    p.extract_text() or "" for p in pdf.pages
                )
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
    import pdfplumber, re
    result = {
        "stations":      [],
        "columns_found": [],
        "col_map":       {},
        "error":         None,
    }
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = ""
            col_positions = []  # for single-cell table format
            for page in pdf.pages:
                # Try table extraction first
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        if not table:
                            continue
                        col_map = {}
                        header_found = False
                        for i, row in enumerate(table):
                            if not row:
                                continue
                            # Single-cell row (Baker Hughes style)
                            if len(row) == 1 and row[0]:
                                cell_text   = str(row[0])
                                header_line = cell_text.split("\n")[0]
                                if not col_positions:
                                    # Try to detect header
                                    found = []
                                    for pat, canon in _TEXT_COL_PATTERNS:
                                        for m in re.finditer(pat, header_line, re.IGNORECASE):
                                            found.append((m.start(), canon))
                                    found.sort()
                                    seen_c, unique_c = set(), []
                                    for pos, canon in found:
                                        if canon not in seen_c:
                                            seen_c.add(canon)
                                            unique_c.append((pos, canon))
                                    if len(unique_c) >= 3:
                                        col_positions = unique_c
                                        result["columns_found"] = [c for _, c in col_positions]
                                        header_found = True
                                else:
                                    # Data row — parse space-separated values
                                    nums = []
                                    for t in cell_text.split():
                                        try:
                                            nums.append(float(t.replace(",","").replace("+","")))
                                        except ValueError:
                                            pass
                                    if len(nums) >= 3:
                                        stn = {canon: nums[i]
                                               for i, (_, canon) in enumerate(col_positions)
                                               if i < len(nums)}
                                        if "MD" in stn:
                                            result["stations"].append(stn)
                                continue
                            if not header_found:
                                matches = sum(1 for cell in row
                                             if cell and _match_col(str(cell)))
                                if matches >= 3:
                                    for j, cell in enumerate(row):
                                        if cell:
                                            canon = _match_col(str(cell))
                                            if canon:
                                                col_map[j] = canon
                                    header_found = True
                                    result["col_map"] = {v: k for k, v in col_map.items()}
                                    result["columns_found"] = list(col_map.values())
                                    continue
                            if header_found:
                                stn = _parse_station_row(row, col_map)
                                if stn:
                                    result["stations"].append(stn)

                # Always accumulate text for fallback parsing
                _pg_text = page.extract_text() or ""
                full_text += _pg_text + "\n"


            # Text-based parsing if tables missed stations (< 3 found)
            if len(result["stations"]) < 5 and full_text:
                lines         = full_text.splitlines()
                col_positions = []
                header_found  = False

                for line in lines:
                    if not line.strip():
                        continue

                    if not header_found:
                        found = []
                        for pat, canon in _TEXT_COL_PATTERNS:
                            for m in re.finditer(pat, line, re.IGNORECASE):
                                found.append((m.start(), canon))
                        found.sort()
                        seen, unique = set(), []
                        for pos, canon in found:
                            if canon not in seen:
                                seen.add(canon)
                                unique.append((pos, canon))
                        if len(unique) >= 3:
                            col_positions = unique
                            header_found  = True
                            result["columns_found"] = [c for _, c in col_positions]
                        continue

                    if not re.match(r"^\s*[+\-]?\d", line):
                        continue

                    nums = []
                    for t in line.split():
                        try:
                            nums.append(float(t.replace(",","").replace("+","")))
                        except ValueError:
                            pass

                    if len(nums) < 3:
                        continue

                    stn = {canon: nums[i]
                           for i, (_, canon) in enumerate(col_positions)
                           if i < len(nums)}

                    if "MD" in stn and ("INC" in stn or "AZI" in stn or "TVD" in stn):
                        existing_mds = {s["MD"] for s in result["stations"]}
                        if stn["MD"] not in existing_mds:
                            result["stations"].append(stn)

        result["stations"].sort(key=lambda s: s.get("MD", 0))

    except Exception as e:
        result["error"] = str(e)

    return result


def _parse_station_row(row: list, col_map: dict) -> Optional[dict]:
    """Parse one table row into a station dict."""
    st = {}
    for j, canon in col_map.items():
        if j < len(row) and row[j] is not None:
            val = str(row[j]).replace(',','').replace('+','').strip()
            try:
                st[canon] = float(val)
            except ValueError:
                pass
    # Must have at least MD and one of INC/AZI/TVD
    if "MD" in st and ("INC" in st or "AZI" in st or "TVD" in st):
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

def _safe_float(v):
    try:
        return float(v) if v not in (None, "", "None") else None
    except Exception:
        return None


def load_to_ppdm(well_info: dict, stations: list[dict],
                  engine, dialect: str = "mssql",
                  source: str = "PDF_SURVEY",
                  dry_run: bool = False) -> dict:
    """
    Load directional survey stations to dataview.dv_well_dir_srvy_sta.
    Columns: uwi, survey_id, station_id, md, incl, azim, tvd,
             ns_offset, ew_offset, surface_latitude, surface_longitude,
             dls, depth_ouom, row_created_by, row_created_date, source
    """
    from sqlalchemy import text

    result = {"loaded": 0, "skipped": 0, "survey_id": None, "errors": []}

    if not stations:
        result["errors"].append("No stations to load")
        return result

    uwi = (well_info.get("uwi") or "").strip()
    if not uwi:
        result["errors"].append("No UWI — cannot load without a well key")
        return result

    survey_id = uuid.uuid4().hex[:32].upper()
    result["survey_id"] = survey_id

    if dry_run:
        result["loaded"] = len(stations)
        return result

    try:
        # ── Header row first (FK requirement) ────────────────────────
        mds   = [_safe_float(s.get("MD")) for s in stations
                 if _safe_float(s.get("MD")) is not None]
        ouom  = "M" if mds and max(mds) < 500 else "FT"
        try:
            with engine.begin() as con:
                con.execute(text("""
                    INSERT INTO dataview.dv_well_dir_srvy_hdr (
                        uwi, survey_id, survey_type,
                        survey_top_depth, survey_base_depth,
                        depth_ouom, active_ind,
                        row_created_by, row_created_date, source
                    ) VALUES (
                        :uwi, :sid, :stype,
                        :top, :base,
                        :ouom, 'Y',
                        :by, GETDATE(), :src
                    )
                """), {
                    "uwi":   uwi[:40],
                    "sid":   survey_id,
                    "stype": (well_info.get("survey_type") or "MWD")[:40],
                    "top":   min(mds) if mds else None,
                    "base":  max(mds) if mds else None,
                    "ouom":  ouom,
                    "by":    "DataWrangler",
                    "src":   source[:40],
                })
        except Exception as hdr_e:
            result["errors"].append(f"Header insert failed: {hdr_e}")
            return result

        # ── Station rows ──────────────────────────────────────────────
        with engine.begin() as con:
            # ── Station rows ──────────────────────────────────────────
            for obs_no, stn in enumerate(stations, start=1):
                station_id = f"{survey_id}_{obs_no:04d}"
                con.execute(text("""
                    INSERT INTO dataview.dv_well_dir_srvy_sta (
                        uwi, survey_id, station_id,
                        md, incl, azim, tvd,
                        ns_offset, ew_offset,
                        dls, depth_ouom,
                        row_created_by, row_created_date, source
                    ) VALUES (
                        :uwi, :sid, :stid,
                        :md, :incl, :azim, :tvd,
                        :ns, :ew,
                        :dls, :ouom,
                        :by, GETDATE(), :src
                    )
                """), {
                    "uwi":  uwi[:40],
                    "sid":  survey_id,
                    "stid": station_id,
                    "md":   _safe_float(stn.get("MD")),
                    "incl": _safe_float(stn.get("INC") or stn.get("INCL")),
                    "azim": _safe_float(stn.get("AZ")  or stn.get("AZIM")),
                    "tvd":  _safe_float(stn.get("TVD")),
                    "ns":   _safe_float(stn.get("NS")),
                    "ew":   _safe_float(stn.get("EW")),
                    "dls":  _safe_float(stn.get("DLS")),
                    "ouom": ouom,
                    "by":   "DataWrangler",
                    "src":  source[:40],
                })
                result["loaded"] += 1

    except Exception as e:
        result["errors"].append(str(e))

    return result


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


# ══════════════════════════════════════════════════════════════════════════════
# Extended report type constants
# ══════════════════════════════════════════════════════════════════════════════
RT_RFT       = "RFT_MDT"
RT_SCOUT     = "SCOUT_TICKET"
RT_DDR       = "DAILY_DRILLING_REPORT"
RT_WELL_TEST = "WELL_TEST"
RT_PETRO     = "PETROPHYSICAL"
RT_EOWR      = "END_OF_WELL"
RT_CASING    = "CASING_CEMENTING"

# PPDM targets for each new type
EXTENDED_PPDM_TARGETS = {
    RT_RFT:       "WELL_TEST + WELL_TEST_RESULT",
    RT_SCOUT:     "WELL + WELL_VERSION",
    RT_DDR:       "WELL_ACTIVITY",
    RT_WELL_TEST: "WELL_TEST + WELL_TEST_RESULT",
    RT_PETRO:     "WELL_LOG_VERSION + WELL_INTERPRETATION",
    RT_EOWR:      "WELL + WELL_VERSION",
    RT_CASING:    "WELL_COMPLETION + WELL_COMPLETION_COMPONENT",
}

# Keyword sets for classification
_EXTENDED_KEYWORDS = {
    RT_RFT: [
        "repeat formation tester", "rft", "mdt", "formation pressure",
        "wireline pressure", "mobility", "fluid gradient", "free water level",
        "modular dynamic tester", "fwl", "owc", "goc", "pressure measurement",
    ],
    RT_SCOUT: [
        "scout ticket", "scout report", "initial production", "ip rate",
        "well scout", "completion information", "perforation", "proppant",
        "choke size", "flowing tubing pressure", "ftp",
    ],
    RT_DDR: [
        "daily drilling report", "ddr", "daily report", "24-hour",
        "drilling parameters", "weight on bit", "wob", "rop",
        "mud properties", "standpipe pressure", "next 24",
        "daily morning report", "operations summary",
    ],
    RT_WELL_TEST: [
        "well test report", "production test", "flow test", "multi-rate",
        "buildup test", "drawdown", "productivity index", "pi test",
        "skin factor", "reservoir pressure", "isochronal",
        "fwhp", "fbhp", "wellhead pressure", "bottomhole pressure",
    ],
    RT_PETRO: [
        "petrophysical", "petrophys", "log interpretation", "well log analysis",
        "porosity", "water saturation", "net pay", "vcl", "clay volume",
        "phie", "effective porosity", "archie", "resistivity",
        "neutron", "density", "gamma ray",
    ],
    RT_EOWR: [
        "end of well", "final well report", "well completion report",
        "elapsed days", "afe", "actual cost", "npt",
        "stratigraphic summary", "well summary", "total depth reached",
    ],
    RT_CASING: [
        "casing record", "cementing record", "cement job", "cbl",
        "cement bond", "centralizer", "float shoe", "displacement",
        "thickening time", "compressive strength", "woc",
        "top of cement", "toc", "slurry",
    ],
}


def extended_classify_pdf(file_path: str) -> dict:
    """
    Extended classifier — detects 7 additional petroleum PDF types
    beyond the base 5 in classify_pdf().

    Returns classification dict with keys:
      report_type, confidence, well_name, uwi, operator,
      page_count, error, + type-specific fields
    """
    import pdfplumber

    result = {
        "file_path":   file_path,
        "file_name":   Path(file_path).name,
        "report_type": RT_UNKNOWN,
        "confidence":  0.0,
        "page_count":  0,
        "well_name":   None,
        "uwi":         None,
        "operator":    None,
        "error":       None,
    }

    try:
        with pdfplumber.open(file_path) as pdf:
            result["page_count"] = len(pdf.pages)
            text = " ".join(
                (p.extract_text() or "") for p in pdf.pages[:3]
            ).lower()

        best_type  = RT_UNKNOWN
        best_score = 0
        best_conf  = 0.0

        for rt, keywords in _EXTENDED_KEYWORDS.items():
            hits  = sum(1 for kw in keywords if kw in text)
            score = hits / len(keywords)
            if hits > best_score:
                best_score = hits
                best_type  = rt
                best_conf  = min(1.0, score * 3.0)

        if best_score >= 2:
            result["report_type"] = best_type
            result["confidence"]  = best_conf

        # Extract well info using same INFO_PATTERNS
        with pdfplumber.open(file_path) as pdf:
            hdr_text = pdf.pages[0].extract_text() or ""
        for field, patterns in INFO_PATTERNS.items():
            for pat in patterns:
                m = re.search(pat, hdr_text, re.IGNORECASE)
                if m:
                    result[field] = m.group(1).strip()
                    break

    except Exception as e:
        result["error"] = str(e)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# Extractors for new types
# ══════════════════════════════════════════════════════════════════════════════

def extract_rft_data(file_path: str) -> dict:
    """Extract RFT/MDT pressure measurements and fluid samples."""
    import pdfplumber
    rows   = []
    samples = []
    result = {"rows": rows, "samples": samples, "error": None}
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table or len(table) < 2:
                        continue
                    hdrs = [str(c).strip().upper() for c in (table[0] or [])]
                    def _ci(keys):
                        return next((i for i,h in enumerate(hdrs)
                                     if any(k in h for k in keys)), None)
                    depth_c = _ci(["DEPTH","MD","TVD"])
                    press_c = _ci(["PRESSURE","PRESS","PSI"])
                    form_c  = _ci(["FORMATION","ZONE","INTERVAL"])
                    fluid_c = _ci(["FLUID","TYPE"])
                    mob_c   = _ci(["MOBIL","MD/CP"])
                    grad_c  = _ci(["GRADIENT","GRAD"])
                    if depth_c is None or press_c is None:
                        continue
                    for row in table[1:]:
                        if not row: continue
                        def _v(i):
                            if i is None or i >= len(row): return None
                            v = re.sub(r'[^\d.\-]','',str(row[i]))
                            try: return float(v)
                            except: return None
                        depth = _v(depth_c)
                        press = _v(press_c)
                        if depth and press:
                            rows.append({
                                "DEPTH_MD":   depth,
                                "PRESSURE":   press,
                                "FORMATION":  str(row[form_c]).strip() if form_c is not None and form_c < len(row) else None,
                                "FLUID_TYPE": str(row[fluid_c]).strip() if fluid_c is not None and fluid_c < len(row) else None,
                                "MOBILITY":   _v(mob_c),
                                "GRADIENT":   _v(grad_c),
                            })
    except Exception as e:
        result["error"] = str(e)
    return result


def extract_scout_ticket(file_path: str) -> dict:
    """Extract well header and IP data from a scout ticket."""
    import pdfplumber
    header = {}
    ip_rows = []
    result = {"header": header, "ip_rows": ip_rows, "error": None}
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        # Header patterns
        patterns = {
            "API":          r'(?:API|UWI)[:\s]+([0-9\-]{10,20})',
            "WELL_NAME":    r'Well\s+Name[:\s]+([A-Z0-9 #\-/]+?)(?:\n|$)',
            "OPERATOR":     r'Operator[:\s]+([A-Za-z0-9 &.,]+?)(?:\n|$)',
            "FIELD":        r'Field[:\s]+([A-Za-z0-9 \-]+?)(?:\n|$)',
            "SPUD_DATE":    r'Spud\s+Date[:\s]+([\d\-/]+)',
            "COMPLETION_DATE": r'Completion\s+Date[:\s]+([\d\-/]+)',
            "TOTAL_DEPTH":  r'Total\s+Depth[:\s]+([\d,]+)\s*ft',
            "TVD":          r'TVD[:\s]+([\d,]+)\s*ft',
            "LATERAL":      r'Lateral[:\s]+([\d,]+)\s*ft',
        }
        for field, pat in patterns.items():
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                header[field] = m.group(1).strip().replace(',','')
        # IP table
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table: continue
                    hdrs = [str(c).strip().upper() for c in (table[0] or [])]
                    if not any("OIL" in h or "FLUID" in h or "BOE" in h for h in hdrs):
                        continue
                    def _ci(keys):
                        return next((i for i,h in enumerate(hdrs)
                                     if any(k in h for k in keys)), None)
                    date_c  = _ci(["DATE","DAY"])
                    oil_c   = _ci(["OIL","BBL"])
                    gas_c   = _ci(["GAS","MCF","MMCF"])
                    water_c = _ci(["WATER","WTR"])
                    for row in table[1:]:
                        if not row: continue
                        def _v(i):
                            if i is None or i >= len(row): return None
                            v = re.sub(r'[^\d.\-]','',str(row[i]))
                            try: return float(v)
                            except: return None
                        ip_rows.append({
                            "DATE":      str(row[date_c]).strip() if date_c is not None else None,
                            "OIL_BOPD":  _v(oil_c),
                            "GAS_MCFD":  _v(gas_c),
                            "WATER_BWPD":_v(water_c),
                        })
    except Exception as e:
        result["error"] = str(e)
    return result


def extract_ddr(file_path: str) -> dict:
    """Extract daily drilling report — operations, parameters, mud props."""
    import pdfplumber
    ops_rows   = []
    param_rows = []
    mud_rows   = []
    result = {"ops": ops_rows, "params": param_rows,
              "mud": mud_rows, "header": {}, "error": None}
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        # Header
        hdr = {}
        for field, pat in [
            ("REPORT_DATE", r'(?:Report\s+Date|Date)[:\s]+([\d\-/]+)'),
            ("REPORT_NO",   r'Report\s+#[:\s]+(\d+)'),
            ("MD_START",    r'Measured\s+Depth.*?start[):\s]+([\d,]+)'),
            ("MD_END",      r'Measured\s+Depth.*?end[):\s]+([\d,]+)'),
            ("PROGRESS",    r'Progress[:\s]+([\d,]+)\s*ft'),
        ]:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                hdr[field] = m.group(1).strip().replace(',','')
        result["header"] = hdr
        # Tables
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table or len(table) < 2: continue
                    hdrs = [str(c or '').strip().upper() for c in table[0]]
                    # Operations table
                    if any("ACTIVITY" in h or "OPERATION" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            ops_rows.append({h: str(v).strip() for h,v in zip(hdrs,row) if v})
                    # Drilling parameters table
                    elif any("WOB" in h or "ROP" in h or "TORQUE" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            param_rows.append({h: str(v).strip() for h,v in zip(hdrs,row) if v})
                    # Mud properties table
                    elif any("MUD" in h or "VISCOSITY" in h or "PH" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            mud_rows.append({h: str(v).strip() for h,v in zip(hdrs,row) if v})
    except Exception as e:
        result["error"] = str(e)
    return result


def extract_well_test(file_path: str) -> dict:
    """Extract production/well test — flow periods and reservoir analysis."""
    import pdfplumber
    flow_rows = []
    analysis  = {}
    result = {"flow_rows": flow_rows, "analysis": analysis,
              "header": {}, "error": None}
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        # Header
        hdr = {}
        for field, pat in [
            ("TEST_DATE",   r'Test\s+Date[:\s]+([\d\-/]+)'),
            ("TEST_TYPE",   r'Test\s+Type[:\s]+([A-Za-z\- ]+?)(?:\n|$)'),
            ("ZONE",        r'Zone[:\s]+([A-Za-z0-9 ]+?)(?:\n|$)'),
            ("PERFS",       r'Perforations[:\s]+([\d,]+ ?[-–] ?[\d,]+\s*ft[^,\n]*)'),
        ]:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                hdr[field] = m.group(1).strip()
        result["header"] = hdr
        # Analysis values
        for field, pat in [
            ("STATIC_PRESSURE",  r'Static\s+Reservoir\s+Pressure[:\s]+([\d,]+)'),
            ("PERMEABILITY",     r'(?:Formation\s+)?Permeability[^:]*[:\s]+([\d.]+)\s*mD'),
            ("SKIN",             r'Skin\s+Factor[^:]*[:\s]+([+-]?[\d.]+)'),
            ("PI",               r'Productivity\s+Index[^:]*[:\s]+([\d.]+)'),
            ("DRAINAGE_RADIUS",  r'Drainage\s+Radius[:\s]+([\d,]+)'),
            ("RESERVOIR_TEMP",   r'Reservoir\s+Temperature[:\s]+([\d.]+)'),
        ]:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                analysis[field] = m.group(1).replace(',','').strip()
        # Flow period table
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table or len(table) < 2: continue
                    hdrs = [str(c or '').strip().upper() for c in table[0]]
                    if not any("FLOW" in h or "PERIOD" in h or "CHOKE" in h
                               or "OIL" in h for h in hdrs):
                        continue
                    for row in table[1:]:
                        if not row: continue
                        r = {}
                        for h, v in zip(hdrs, row):
                            if v:
                                clean = re.sub(r'[^\d.\-]','',str(v))
                                try:
                                    r[h] = float(clean)
                                except:
                                    r[h] = str(v).strip()
                        if r:
                            flow_rows.append(r)
    except Exception as e:
        result["error"] = str(e)
    return result


def extract_petrophysical(file_path: str) -> dict:
    """Extract zone summary and interval analysis from petrophysical report."""
    import pdfplumber
    zones    = []
    interval = []
    result   = {"zones": zones, "interval": interval, "error": None}
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table or len(table) < 2: continue
                    hdrs = [str(c or '').strip().upper() for c in table[0]]
                    # Zone summary
                    if any("NET PAY" in h or "N/G" in h or "PHIE" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            r = {}
                            for h,v in zip(hdrs,row):
                                if v:
                                    clean = re.sub(r'[^\d.\-]','',str(v))
                                    try: r[h] = float(clean)
                                    except: r[h] = str(v).strip()
                            if r: zones.append(r)
                    # Interval detail
                    elif any("GR" in h or "RHOB" in h or "NPHI" in h or "RT" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            r = {}
                            for h,v in zip(hdrs,row):
                                if v:
                                    clean = re.sub(r'[^\d.\-]','',str(v))
                                    try: r[h] = float(clean)
                                    except: r[h] = str(v).strip()
                            if r: interval.append(r)
    except Exception as e:
        result["error"] = str(e)
    return result


def extract_eowr(file_path: str) -> dict:
    """Extract end of well report — summary, stratigraphy, NPT."""
    import pdfplumber
    strat_rows = []
    npt_rows   = []
    summary    = {}
    result     = {"summary": summary, "strat": strat_rows,
                  "npt": npt_rows, "error": None}
    try:
        with pdfplumber.open(file_path) as pdf:
            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        for field, pat in [
            ("SPUD_DATE",     r'Spud\s+Date[:\s]+([\d\-/]+)'),
            ("RIG_RELEASE",   r'Rig\s+Release[:\s]+([\d\-/]+)'),
            ("TOTAL_DEPTH",   r'Total\s+Depth[:\s]+([\d,]+)\s*ft'),
            ("ELAPSED_DAYS",  r'Elapsed\s+Days[:\s]+(\d+)'),
            ("ACTUAL_COST",   r'Actual\s+Cost[:\s]+\$?([\d.,]+)'),
            ("AFE_COST",      r'AFE\s+Cost[:\s]+\$?([\d.,]+)'),
            ("STAGES",        r'Stages\s+completed[:\s]+(\d+)'),
            ("TOTAL_PROPPANT",r'Total\s+proppant[:\s]+([\d,]+)'),
        ]:
            m = re.search(pat, full_text, re.IGNORECASE)
            if m:
                summary[field] = m.group(1).strip().replace(',','')
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table or len(table) < 2: continue
                    hdrs = [str(c or '').strip().upper() for c in table[0]]
                    if any("FORMATION" in h for h in hdrs) and any("TOP" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            r = {h: str(v).strip() for h,v in zip(hdrs,row) if v}
                            if r: strat_rows.append(r)
                    elif any("NPT" in h or "EVENT" in h or "DURATION" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            r = {h: str(v).strip() for h,v in zip(hdrs,row) if v}
                            if r: npt_rows.append(r)
    except Exception as e:
        result["error"] = str(e)
    return result


def extract_casing_cement(file_path: str) -> dict:
    """Extract casing programme and cement job data."""
    import pdfplumber
    casing_rows  = []
    cement_rows  = []
    cbl_rows     = []
    result       = {"casing": casing_rows, "cement": cement_rows,
                    "cbl": cbl_rows, "error": None}
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    if not table or len(table) < 2: continue
                    hdrs = [str(c or '').strip().upper() for c in table[0]]
                    if any("STRING" in h or "CASING" in h for h in hdrs) and any("OD" in h or "WEIGHT" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            r = {h: str(v).strip() for h,v in zip(hdrs,row) if v}
                            if r: casing_rows.append(r)
                    elif any("SLURRY" in h or "SACK" in h or "CEMENT" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            r = {h: str(v).strip() for h,v in zip(hdrs,row) if v}
                            if r: cement_rows.append(r)
                    elif any("CBL" in h or "BOND" in h or "AMPLITUDE" in h for h in hdrs):
                        for row in table[1:]:
                            if not row: continue
                            r = {h: str(v).strip() for h,v in zip(hdrs,row) if v}
                            if r: cbl_rows.append(r)
    except Exception as e:
        result["error"] = str(e)
    return result

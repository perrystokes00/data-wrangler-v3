"""
modules/extract_petro.py
========================
Petrophysical report extractor — handles variable PDF formats.

Extracts:
  1. Well header (UWI, well name, operator, field, state, county)
  2. Zone summary table → dv_well_petro_zone
  3. Interpretation metadata → dv_well_petro_interp
  4. Cutoff criteria → stored as remark on dv_well_petro_interp

Usage:
    from modules.extract_petro import extract_petro, load_petro_zones
    result = extract_petro(file_path)
    load_petro_zones(engine, dialect, result, uwi)
"""
import re
import uuid
from pathlib import Path


# =============================================================================
# Classification keywords
# =============================================================================

PETRO_KEYWORDS = [
    "petrophysical", "petro", "phie", "phi", "sw ", "water saturation",
    "vcl", "clay volume", "net pay", "zone summary", "porosity",
    "interpretation report", "log analysis", "cutoff",
]

def is_petro_report(text: str) -> bool:
    """Return True if text looks like a petrophysical report."""
    t = text.lower()
    hits = sum(1 for kw in PETRO_KEYWORDS if kw in t)
    return hits >= 3


# =============================================================================
# Main extractor
# =============================================================================

def extract_petro(file_path: str) -> dict:
    """
    Extract petrophysical data from a PDF.
    Returns dict with: header, zones, interp_meta, cutoffs, raw_text
    """
    result = {
        "header":      {},
        "zones":       [],
        "interp_meta": {},
        "cutoffs":     [],
        "raw_text":    "",
        "ok":          False,
        "error":       None,
    }

    try:
        import pdfplumber
        text_pages = []
        tables_all = []

        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                pt = page.extract_text() or ""
                text_pages.append(pt)
                tbls = page.extract_tables() or []
                tables_all.extend(tbls)

        full_text = "\n".join(text_pages)
        result["raw_text"] = full_text

        if not is_petro_report(full_text):
            result["error"] = "Not identified as a petrophysical report"
            return result

        result["header"]      = _extract_header(full_text)
        result["zones"]       = _extract_zones(full_text, tables_all)
        result["interp_meta"] = _extract_interp_meta(full_text)
        result["cutoffs"]     = _extract_cutoffs(full_text, tables_all)
        result["ok"]          = True

    except Exception as e:
        result["error"] = str(e)

    return result


# =============================================================================
# Header extraction
# =============================================================================

HEADER_PATTERNS = {
    "uwi": [
        r"UWI\s*/?\s*API[:\s]+([0-9\-]{10,20})",
        r"API[:\s]+([0-9\-]{10,20})",
        r"UWI[:\s]+([0-9\-]{10,20})",
    ],
    "well_name": [
        r"Well\s*Name[:\s]+([^\n\r]{3,50})",
        r"WELL\s*NAME[:\s]+([^\n\r]{3,50})",
        r"Well[:\s]+([A-Z][^\n\r]{3,40})",
    ],
    "operator": [
        r"Operator[:\s]+([^\n\r]{3,60})",
        r"OPERATOR[:\s]+([^\n\r]{3,60})",
        r"Company[:\s]+([^\n\r]{3,60})",
    ],
    "field": [
        r"Field[:\s]+([^\n\r]{2,50})",
        r"FIELD[:\s]+([^\n\r]{2,50})",
    ],
    "state": [
        r"State[:\s]+([A-Z]{2})\b",
        r"STATE[:\s]+([A-Z]{2})\b",
    ],
    "county": [
        r"County[:\s]+([^\n\r]{2,40})",
        r"COUNTY[:\s]+([^\n\r]{2,40})",
    ],
    "interpreter": [
        r"Interpreter[:\s]+([^\n\r]{3,60})",
        r"Interpreted\s+by[:\s]+([^\n\r]{3,60})",
    ],
    "interp_date": [
        r"Date[:\s]+(\d{4}[-/]\d{2}[-/]\d{2})",
        r"Date[:\s]+(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
    ],
    "log_suite": [
        r"Log\s*Suite[:\s]+([^\n\r]{5,100})",
        r"Logs[:\s]+([^\n\r]{5,100})",
    ],
}


def _extract_header(text: str) -> dict:
    header = {}
    for field, patterns in HEADER_PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                val = m.group(1).strip().rstrip(".,;")
                if val:
                    header[field] = val
                    break
    return header


# =============================================================================
# Zone summary extraction
# =============================================================================

# Column name aliases → standard field names
ZONE_COL_MAP = {
    # Depth
    "top":          "top_depth",
    "top (ft md)":  "top_depth",
    "top (ft)":     "top_depth",
    "base":         "base_depth",
    "base (ft md)": "base_depth",
    "base (ft)":    "base_depth",
    # Thickness
    "gross":        "gross_thickness",
    "gross (ft)":   "gross_thickness",
    "gross thickness": "gross_thickness",
    "net pay":      "net_thickness",
    "net pay (ft)": "net_thickness",
    "net (ft)":     "net_thickness",
    # Ratios
    "n/g":          "ng_ratio",
    "net/gross":    "ng_ratio",
    # Porosity
    "avg phie (%)": "phi_net_avg",
    "phie (%)":     "phi_net_avg",
    "avg phie":     "phi_net_avg",
    "phie":         "phi_net_avg",
    "phi":          "phi_total_avg",
    # Saturation
    "avg sw (%)":   "sw_avg",
    "sw (%)":       "sw_avg",
    "avg sw":       "sw_avg",
    "sw":           "sw_avg",
    # Shale volume
    "avg vsh":      "vsh_avg",
    "vsh":          "vsh_avg",
    "vcl":          "vsh_avg",
    # Hydrocarbon pore volume
    "hcpv":         "hcpv",
    "hydrocarbon pore": "hcpv",
    "hc pore":      "hcpv",
    # Permeability
    "perm":         "perm_avg",
    "k (md)":       "perm_avg",
    # Pay classification
    "hydrocarbon pore vo": "hcpv",
}

ZONE_SECTION_HEADERS = [
    "zone summary", "zone analysis", "reservoir summary",
    "interval summary", "formation summary",
]

def _extract_zones(text: str, tables: list) -> list:
    """
    Extract zone rows from tables. Tries to find a zone summary table
    by looking for tables with zone name + depth columns.
    """
    zones = []

    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue

        # Find header row
        header_row = None
        data_start = 0
        for i, row in enumerate(tbl[:4]):
            row_text = " ".join(str(c or "").lower() for c in row)
            if any(kw in row_text for kw in
                   ["zone","top","base","phie","phi","sw","net"]):
                header_row = row
                data_start = i + 1
                break

        if header_row is None:
            continue

        # Map columns
        col_map = {}
        for ci, col in enumerate(header_row):
            if col is None:
                continue
            key = str(col).lower().strip()
            std = ZONE_COL_MAP.get(key)
            if std:
                col_map[ci] = std
            elif "zone" in key or "formation" in key or "interval" in key:
                col_map[ci] = "zone_name"

        if "zone_name" not in col_map.values():
            continue
        if "top_depth" not in col_map.values():
            continue

        # Extract data rows
        for row in tbl[data_start:]:
            if not row or all(c is None or str(c).strip() == "" for c in row):
                continue

            zone = {}
            for ci, std_name in col_map.items():
                if ci < len(row):
                    val = str(row[ci] or "").strip()
                    if val and val.lower() not in ("none","—","-","n/a"):
                        zone[std_name] = val

            if "zone_name" in zone and zone["zone_name"]:
                zones.append(zone)

    # If no table found, try regex from text
    if not zones:
        zones = _extract_zones_regex(text)

    return zones


def _extract_zones_regex(text: str) -> list:
    """Fallback: extract zone data via regex from text."""
    zones = []
    lines = text.split("\n")

    in_zone_section = False
    for line in lines:
        ll = line.lower()

        # Detect zone section start
        if any(h in ll for h in ZONE_SECTION_HEADERS):
            in_zone_section = True
            continue

        # Stop at next major section
        if in_zone_section and re.match(
                r"(detailed|cutoff|interpretation|log suite|appendix)",
                ll.strip(), re.IGNORECASE):
            break

        if not in_zone_section:
            continue

        # Try to parse a data line: ZoneName  7800  8050  250  185  ...
        m = re.match(
            r"([A-Za-z][\w\s]{2,30}?)\s+"
            r"(\d[\d,\.]+)\s+"
            r"(\d[\d,\.]+)\s+"
            r"(\d[\d,\.]+)\s*"
            r"([\d,\.]*)",
            line.strip(),
        )
        if m:
            zones.append({
                "zone_name":      m.group(1).strip(),
                "top_depth":      m.group(2).replace(",",""),
                "base_depth":     m.group(3).replace(",",""),
                "gross_thickness":m.group(4).replace(",",""),
                "net_thickness":  m.group(5).replace(",","") if m.group(5) else None,
            })

    return zones


# =============================================================================
# Interpretation metadata
# =============================================================================

def _extract_interp_meta(text: str) -> dict:
    """Extract interpretation-level metadata."""
    meta = {}

    # Software
    for pat in [
        r"Software[:\s]+([^\n\r]{3,60})",
        r"Petrel|Interactive Petrophysics|IP|Techlog|Elog|Geolog",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            meta["software"] = m.group(0).strip() if "(" not in pat else m.group(1).strip()
            break

    # Depth interval
    m = re.search(
        r"(\d[\d,\.]+)\s*[-–to]+\s*(\d[\d,\.]+)\s*ft\s*(?:MD|TVDSS)?",
        text, re.IGNORECASE)
    if m:
        meta["interp_top"]  = m.group(1).replace(",","")
        meta["interp_base"] = m.group(2).replace(",","")

    return meta


# =============================================================================
# Cutoff extraction
# =============================================================================

CUTOFF_PARAMS = {
    "vcl":  ["vcl","clay volume","shale volume","vsh"],
    "phie": ["phie","phi","porosity","effective porosity"],
    "sw":   ["sw","water saturation","water sat"],
    "rt":   ["rt","resistivity"],
    "perm": ["perm","permeability"],
}

def _extract_cutoffs(text: str, tables: list) -> list:
    """Extract cutoff criteria."""
    cutoffs = []

    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue
        tbl_text = " ".join(
            str(c or "") for row in tbl for c in row).lower()
        if "cutoff" not in tbl_text and "parameter" not in tbl_text:
            continue

        for row in tbl[1:]:
            if not row or len(row) < 2:
                continue
            param = str(row[0] or "").strip()
            value = str(row[1] or "").strip() if len(row) > 1 else ""
            basis = str(row[2] or "").strip() if len(row) > 2 else ""
            if param and value:
                cutoffs.append({
                    "parameter": param,
                    "value":     value,
                    "basis":     basis,
                })

    # Regex fallback
    if not cutoffs:
        for param, aliases in CUTOFF_PARAMS.items():
            for alias in aliases:
                m = re.search(
                    rf"{re.escape(alias)}\s*[:\(<]\s*([<>≤≥]?\s*[\d\.]+\s*%?)",
                    text, re.IGNORECASE)
                if m:
                    cutoffs.append({
                        "parameter": param.upper(),
                        "value":     m.group(1).strip(),
                        "basis":     "",
                    })
                    break

    return cutoffs


# =============================================================================
# Database loaders
# =============================================================================

def load_petro_zones(engine, dialect: str, result: dict,
                     uwi: str, source: str = "PDF_EXTRACT") -> dict:
    """
    Load extracted zones to dv_well_petro_zone.
    Returns {"loaded": n, "errors": [...]}
    """
    from sqlalchemy import text as _t
    from datetime import datetime

    zones  = result.get("zones", [])
    meta   = result.get("interp_meta", {})
    cutoffs= result.get("cutoffs", [])
    header = result.get("header", {})

    loaded = 0
    errors = []

    if not zones:
        return {"loaded": 0, "errors": ["No zones extracted"]}

    # Build cutoff remark string
    cutoff_str = "; ".join(
        f"{c['parameter']} {c['value']}" for c in cutoffs
    ) if cutoffs else None

    for zone in zones:
        try:
            zone_id = uuid.uuid4().hex[:40].upper()

            def _f(key, cast=None):
                v = zone.get(key)
                if v is None or str(v).strip() in ("","None","—"):
                    return None
                try:
                    return cast(str(v).replace(",","").strip()) if cast else str(v).strip()
                except (ValueError, TypeError):
                    return None

            # Convert % values (strip % sign)
            def _pct(key):
                v = zone.get(key)
                if v is None:
                    return None
                try:
                    return float(str(v).replace("%","").replace(",","").strip())
                except (ValueError, TypeError):
                    return None

            with engine.begin() as con:
                con.execute(_t("""
                    INSERT INTO dataview.dv_well_petro_zone (
                        zone_id, uwi, zone_name,
                        top_depth, base_depth,
                        gross_thickness, net_thickness,
                        phi_net_avg, phi_total_avg,
                        sw_avg,
                        vsh_avg,
                        hcpv_ouom,
                        pay_flag,
                        remark,
                        active_ind, source,
                        row_created_by, row_created_date,
                        row_changed_by, row_changed_date
                    ) VALUES (
                        :zid, :uwi, :zname,
                        :top, :base,
                        :gross, :net,
                        :phi_net, :phi_tot,
                        :sw,
                        :vsh,
                        :hcpv,
                        :pay,
                        :remark,
                        'Y', :source,
                        'DataWrangler', GETUTCDATE(),
                        'DataWrangler', GETUTCDATE()
                    )
                """), {
                    "zid":    zone_id,
                    "uwi":    uwi,
                    "zname":  _f("zone_name"),
                    "top":    _f("top_depth",  float),
                    "base":   _f("base_depth", float),
                    "gross":  _f("gross_thickness", float),
                    "net":    _f("net_thickness",   float),
                    "phi_net":_pct("phi_net_avg"),
                    "phi_tot":_pct("phi_total_avg"),
                    "sw":     _pct("sw_avg"),
                    "vsh":    _pct("vsh_avg"),
                    "hcpv":   _f("hcpv", float),
                    "pay":    "Y" if _pct("sw_avg") and
                               _pct("sw_avg") < 65 and
                               _pct("phi_net_avg") and
                               _pct("phi_net_avg") > 4 else "N",
                    "remark": cutoff_str,
                    "source": source,
                })
            loaded += 1

        except Exception as e:
            errors.append(f"{zone.get('zone_name','?')}: {e}")

    # Write interp metadata
    if meta or header.get("interpreter"):
        try:
            iid = uuid.uuid4().hex[:40].upper()
            remark_parts = []
            if header.get("interpreter"):
                remark_parts.append(f"Interpreter: {header['interpreter']}")
            if header.get("log_suite"):
                remark_parts.append(f"Logs: {header['log_suite']}")
            if cutoff_str:
                remark_parts.append(f"Cutoffs: {cutoff_str}")

            with engine.begin() as con:
                con.execute(_t("""
                    INSERT INTO dataview.dv_well_petro_interp (
                        interp_id, uwi,
                        interp_top, interp_base,
                        interp_date,
                        remark,
                        active_ind, source,
                        row_created_by, row_created_date,
                        row_changed_by, row_changed_date
                    ) VALUES (
                        :iid, :uwi,
                        :top, :base,
                        :idate,
                        :remark,
                        'Y', :source,
                        'DataWrangler', GETUTCDATE(),
                        'DataWrangler', GETUTCDATE()
                    )
                """), {
                    "iid":    iid,
                    "uwi":    uwi,
                    "top":    float(meta["interp_top"])  if meta.get("interp_top")  else None,
                    "base":   float(meta["interp_base"]) if meta.get("interp_base") else None,
                    "idate":  header.get("interp_date"),
                    "remark": " | ".join(remark_parts) if remark_parts else None,
                    "source": source,
                })
        except Exception as e:
            errors.append(f"interp_meta: {e}")

    return {"loaded": loaded, "errors": errors}

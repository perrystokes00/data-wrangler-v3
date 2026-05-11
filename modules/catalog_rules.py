"""
modules/catalog_rules.py
========================
Cataloging rules engine for DataView v3.

Responsibilities:
  1. Extract rich header fields from LAS/DLIS/LIS/SEGY/P190 files
  2. Score each file for catalog readiness (0-100)
  3. Match files to existing dv_well records
  4. Bootstrap dv_well records from file headers when no match found
  5. Apply configurable cataloging rules

Catalog readiness score:
  - UWI found in dv_well          +40
  - UWI present in header         +20
  - Well name present             +10
  - Operator present              +10
  - Lat/lon present               +10
  - Key fields complete (depth etc)+10
  ─────────────────────────────────
  100 = fully ready to catalog
   60+ = catalog with review
   40+ = flag for manual UWI entry
   <40 = needs attention

"""
from __future__ import annotations

import re
import hashlib
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from sqlalchemy import text

# ── Constants ─────────────────────────────────────────────────────────────────

# UWI patterns
_UWI_PATTERNS = [
    # Standard 14-digit API: 42-317-12345-00-00
    r'\b(\d{2}-\d{3}-\d{5}-\d{2}-\d{2})\b',
    # Compact 14-digit: 42317123450000
    r'\b(\d{14})\b',
    # 10-digit API: 4231712345
    r'\b(\d{10})\b',
    # Canadian UWI: 100/06-01-001-01W4/0
    r'\b(\d{3}/\d{2}-\d{2}-\d{3}-\d{2}[WE]\d/\d)\b',
]

# Standard LAS well section mnemonics
_LAS_WELL_FIELDS = {
    'WELL': 'well_name',
    'WELLNAME': 'well_name',
    'WELL_NAME': 'well_name',
    'UWI': 'uwi',
    'API': 'uwi',
    'LIC': 'uwi',
    'APINO': 'uwi',
    'OPER': 'operator',
    'COMP': 'operator',
    'OPERATOR': 'operator',
    'COMPANY': 'operator',
    'FLD': 'field',
    'FIELD': 'field',
    'STAT': 'state',
    'PROV': 'state',
    'CNTY': 'county',
    'COUNTY': 'county',
    'CTRY': 'country',
    'LOC': 'location',
    'SRVC': 'contractor',
    'SLAT': 'latitude',
    'SLNG': 'longitude',
    'GDAT': 'datum',
    'STRT': 'start_depth',
    'STOP': 'stop_depth',
    'STEP': 'step',
    'NULL': 'null_value',
    'ELEV': 'kb_elevation',
    'GLEN': 'gl_elevation',
    'EREF': 'elev_ref',
    'DATE': 'log_date',
    'LNUM': 'log_number',
    'HZCS': 'coord_system',
    'LONG': 'longitude',
    'LAT': 'latitude',
}

# Scoring weights
#
# UWI handling is binary-ish:
#   - UWI matches dv_well → +40 (highest single signal of usefulness)
#   - UWI in header but no match → +30 (still valuable identifier)
#   - No UWI at all → 0
#
# The remaining 60 points reward intrinsic document quality, NOT linkage
# to the existing well master. This is the document-centric philosophy:
# a file with rich location metadata is valuable in its own right, even
# if it doesn't tie back to dv_well.
#
# state/county scoring is included even though current extractors don't
# populate those fields for LOG/SEIS/PDF/SHP files. The weights are
# intentional — they signal what extraction SHOULD capture, and the
# scoring will start crediting these fields automatically once
# extract_file_fields() is fixed to populate them.
_SCORE_WEIGHTS = {
    'uwi_in_db':      40,   # UWI in header AND matched in dv_well
    'uwi_in_header':  30,   # UWI in header, dv_well match not required
    'well_name':      10,
    'operator':       10,
    'lat_lon':        20,   # bumped from 10 — location is high-value
    'depth_range':    10,
    'state':           5,   # new — aspirational until extraction populates it
    'county':          5,   # new — aspirational until extraction populates it
}


# ── Header extraction ─────────────────────────────────────────────────────────

def extract_las_fields(file_path: str) -> dict:
    """
    Extract all well section fields from a LAS file.
    Returns dict with standardized field names.
    """
    result = {
        'file_type':   'LAS',
        'uwi':         None,
        'well_name':   None,
        'operator':    None,
        'field':       None,
        'state':       None,
        'county':      None,
        'latitude':    None,
        'longitude':   None,
        'kb_elevation':None,
        'gl_elevation':None,
        'start_depth': None,
        'stop_depth':  None,
        'step':        None,
        'null_value':  None,
        'log_date':    None,
        'contractor':  None,
        'curves':      [],
        'header_text': '',
        'raw_fields':  {},
    }

    try:
        with open(file_path, 'r', errors='replace') as f:
            raw = f.read(50000)  # Read first 50KB — header only

        # Split at data section
        a_idx = raw.upper().find('\n~A')
        header_text = raw[:a_idx].strip() if a_idx > 0 else raw
        result['header_text'] = header_text

        in_well = False
        in_curve = False

        for line in header_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            upper = stripped.upper()

            if upper.startswith('~W'):
                in_well, in_curve = True, False
                continue
            if upper.startswith('~C'):
                in_well, in_curve = False, True
                continue
            if upper.startswith('~'):
                in_well, in_curve = False, False
                continue

            if in_well or in_curve:
                dot   = stripped.find('.')
                colon = stripped.find(':')
                if dot <= 0:
                    continue

                mnem = stripped[:dot].strip().upper()
                rest = stripped[dot+1:]
                sp   = rest.find(' ')
                unit = rest[:sp].strip() if sp > 0 else ''
                val  = rest[sp:colon].strip() if (sp > 0 and colon > sp) else rest[:colon].strip() if colon > 0 else rest.strip()
                desc = stripped[colon+1:].strip() if colon > 0 else ''

                result['raw_fields'][mnem] = {'value': val, 'unit': unit, 'description': desc}

                # Map to standard fields
                std_field = _LAS_WELL_FIELDS.get(mnem)
                if std_field and val and val not in ('.', '', '  '):
                    if std_field == 'uwi' and not result['uwi']:
                        result['uwi'] = _clean_uwi(val)
                    elif std_field in ('start_depth', 'stop_depth', 'step', 'kb_elevation', 'gl_elevation', 'null_value'):
                        try:
                            result[std_field] = float(val.replace(',', ''))
                        except ValueError:
                            result[std_field] = val
                    elif std_field in ('latitude', 'longitude'):
                        try:
                            result[std_field] = float(val.replace(',', ''))
                        except ValueError:
                            pass
                    elif not result.get(std_field):
                        result[std_field] = val.strip()

                # Curves
                if in_curve and mnem and mnem not in ('DEPT', 'DEPTH', 'MD', 'TVD', 'TIME'):
                    result['curves'].append({
                        'mnemonic': mnem,
                        'unit': unit,
                        'description': desc,
                    })

        # Try to find UWI in header text if not found in well section
        if not result['uwi']:
            result['uwi'] = _find_uwi_in_text(header_text)

    except Exception as e:
        result['error'] = str(e)

    return result


def extract_dlis_fields(file_path: str) -> dict:
    """Extract fields from DLIS file."""
    result = {
        'file_type': 'DLIS',
        'uwi': None, 'well_name': None, 'operator': None,
        'field': None, 'curves': [], 'header_text': '',
    }
    try:
        import dlisio
        with dlisio.dlis(file_path) as (f, *tail):
            origins = f.origins
            if origins:
                o = origins[0]
                result['well_name']  = getattr(o, 'well_name', None)
                result['uwi']        = _clean_uwi(getattr(o, 'well_id', '') or '')
                result['operator']   = getattr(o, 'company', None)
                result['field']      = getattr(o, 'field_name', None)
                result['header_text'] = f"Well: {result['well_name']} UWI: {result['uwi']}"
            result['curves'] = [
                {'mnemonic': ch.name, 'unit': str(ch.units or ''), 'description': str(ch.long_name or '')}
                for ch in f.channels
            ]
    except Exception as e:
        result['error'] = str(e)
    return result


def extract_segy_fields(file_path: str) -> dict:
    """Extract fields from SEG-Y file (EBCDIC header only)."""
    result = {
        'file_type': 'SEGY',
        'survey_name': None, 'line_name': None,
        'sample_interval': None, 'samples_per_trace': None,
        'header_text': '',
    }
    try:
        with open(file_path, 'rb') as f:
            ebcdic_bytes = f.read(3200)
            bin_header   = f.read(400)

        # Decode EBCDIC
        try:
            ebcdic_text = ebcdic_bytes.decode('cp037', errors='replace')
        except Exception:
            ebcdic_text = ebcdic_bytes.decode('latin-1', errors='replace')
        result['header_text'] = ebcdic_text

        # Parse binary header for sample interval and samples per trace
        if len(bin_header) >= 22:
            import struct
            si  = struct.unpack('>H', bin_header[16:18])[0]  # µs
            spt = struct.unpack('>H', bin_header[20:22])[0]
            result['sample_interval']    = si
            result['samples_per_trace']  = spt

        # Try to find survey name in EBCDIC text
        for line in ebcdic_text.splitlines():
            l = line.strip()
            if not l:
                continue
            for kw in ('SURVEY', 'LINE', 'PROJECT', 'AREA'):
                if kw in l.upper():
                    result['survey_name'] = l[:100]
                    break
            if result['survey_name']:
                break

    except Exception as e:
        result['error'] = str(e)
    return result


def extract_file_fields(file_path: str) -> dict:
    """
    Universal dispatcher — calls file_summarizer.summarize() for all formats.

    summarize() handles: LAS, DLIS, SEGY, PDF, SHP, GeoJSON,
    Excel, Word, CSV, TSV, P190 — returning a consistent dict with
    uwi, well_name, ppdm_hints, warnings, key_fields, error.

    Normalises the result into the shape score_file() expects.
    """
    from modules.file_summarizer import summarize

    ext = Path(file_path).suffix.lower()

    _LOG_EXTS    = {'.las', '.dlis', '.dlf', '.dis', '.lis'}
    _SEIS_EXTS   = {'.segy', '.sgy', '.seg', '.p190', '.p90', '.p1'}
    _SHP_EXTS    = {'.shp', '.geojson', '.gpkg', '.kml', '.kmz', '.gdb'}
    _OFFICE_EXTS = {'.xlsx', '.xls', '.docx', '.doc', '.csv', '.tsv', '.txt'}

    if ext in _LOG_EXTS:
        file_type = 'LOG'
    elif ext in _SEIS_EXTS:
        file_type = 'SEIS'
    elif ext == '.pdf':
        file_type = 'PDF'
    elif ext in _SHP_EXTS:
        file_type = 'SHP'
    elif ext in _OFFICE_EXTS:
        file_type = 'OFFICE'
    else:
        file_type = 'OTHER'

    try:
        s = summarize(file_path)
    except Exception as e:
        return {
            'file_type': file_type, 'uwi': None, 'well_name': None,
            'operator': None, 'latitude': None, 'longitude': None,
            'start_depth': None, 'stop_depth': None,
            'header_text': '', 'ppdm_hints': [], 'error': str(e),
        }

    kf = s.get('key_fields', {})

    fields = {
        'file_type':   file_type,
        'uwi':         s.get('uwi'),
        'well_name':   s.get('well_name'),
        'operator':    None,
        'latitude':    None,
        'longitude':   None,
        'start_depth': None,
        'stop_depth':  None,
        'header_text': '',
        'ppdm_hints':  s.get('ppdm_hints', []),
        'warnings':    s.get('warnings', []),
        'error':       s.get('error'),
    }

    if file_type == 'LOG':
        # _summarize_las key_fields: curves (int), curve_names, depth_start,
        #   depth_stop, depth_step, null_value, company, field, samples
        # operator/lat/lon not in key_fields — they come from extract_las_fields()
        # which reads raw LAS header directly. summarize() does NOT expose them.
        fields['operator']    = kf.get('company')       # COMP mnemonic
        fields['start_depth'] = kf.get('depth_start')
        fields['stop_depth']  = kf.get('depth_stop')
        fields['curve_count'] = kf.get('curves', 0)     # integer count
        fields['curve_names'] = kf.get('curve_names', [])
        fields['field']       = kf.get('field')
        # lat/lon not available via summarize() for LAS — leave None

    elif file_type == 'SEIS':
        fields['survey_name']       = kf.get('survey_name')
        fields['sample_interval']   = kf.get('sample_interval')
        fields['samples_per_trace'] = kf.get('samples_per_trace')

    elif file_type == 'PDF':
        # _summarize_pdf key_fields: report_type, confidence, operator,
        #   station_count, survey_type, pages, has_tables
        # total_depth is NOT forwarded by _summarize_pdf into key_fields
        fields['report_type']   = kf.get('report_type')
        fields['confidence']    = kf.get('confidence', 0.0)
        fields['operator']      = kf.get('operator')
        fields['station_count'] = kf.get('station_count', 0)
        fields['survey_type']   = kf.get('survey_type')

    elif file_type == 'SHP':
        # _summarize_shp key_fields: feature_count, geometry_type, feature_type,
        #   crs_epsg, attributes, bounds, confidence
        # ppdm_target is in ppdm_hints, column_map is NOT forwarded
        fields['feature_type']  = kf.get('feature_type')
        fields['ppdm_target']   = (s.get('ppdm_hints') or [None])[0]
        fields['geometry_type'] = kf.get('geometry_type')
        fields['feature_count'] = kf.get('feature_count', 0)
        fields['crs']           = (f"EPSG:{kf['crs_epsg']}"
                                   if kf.get('crs_epsg') else None)
        fields['confidence']    = kf.get('confidence', 0.0)
        attrs_lower = [a.lower() for a in kf.get('attributes', [])]
        if any(a in attrs_lower for a in ('uwi', 'api', 'api_no', 'api14')):
            fields['uwi'] = '__SHP_HAS_UWI_COL__'
        if any(a in attrs_lower for a in ('well_name', 'wellname', 'well')):
            fields['well_name'] = '__SHP_HAS_WELL_COL__'

    elif file_type == 'OFFICE':
        fields['ppdm_target'] = ', '.join(s.get('ppdm_hints', []))
        if not fields['uwi']:
            fields['uwi'] = kf.get('uwi')

    return fields


# ── UWI utilities ─────────────────────────────────────────────────────────────

def _clean_uwi(val: str) -> Optional[str]:
    """Clean and validate a UWI/API string."""
    if not val:
        return None
    val = val.strip()
    if val in ('.', '', '  ', 'UNKNOWN', 'N/A'):
        return None
    return val


def _find_uwi_in_text(text: str) -> Optional[str]:
    """Search text for UWI/API patterns."""
    for pat in _UWI_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return _clean_uwi(m.group(1))
    return None


# ── UWI matching ──────────────────────────────────────────────────────────────

def match_uwi(engine, uwi: str) -> Optional[str]:
    """
    Try to match a UWI against dv_well.
    Returns matched uwi or None.
    Tries exact match then normalized (digits only) match.
    """
    if not uwi or not engine:
        return None
    try:
        with engine.connect() as con:
            # Exact match
            row = con.execute(text(
                "SELECT uwi FROM dataview.dv_well WHERE uwi = :u"),
                {"u": uwi}).fetchone()
            if row:
                return row[0]

            # Normalized — digits only
            digits = re.sub(r'\D', '', uwi)
            if len(digits) >= 10:
                row = con.execute(text(
                    "SELECT uwi FROM dataview.dv_well "
                    "WHERE REPLACE(REPLACE(REPLACE(uwi,'-',''),'/',''),' ','') = :d"),
                    {"d": digits}).fetchone()
                if row:
                    return row[0]
    except Exception:
        pass
    return None


# ── Cataloging rules ──────────────────────────────────────────────────────────

def score_file(fields: dict, engine=None) -> dict:
    """
    Score a file for catalog readiness (0-100).
    Dispatches to type-specific logic based on fields['file_type'].

      LOG / SEGY / PDF  → UWI-centric scoring
      SHP               → confidence + feature classification scoring
      OFFICE            → ppdm_hints + UWI presence scoring
      OTHER             → minimal scoring
    """
    file_type = (fields.get('file_type') or 'OTHER').upper()

    if file_type == 'SHP':
        return _score_shapefile(fields)
    if file_type == 'OFFICE':
        return _score_office(fields)

    # ── UWI-centric scoring (LOG, SEIS, PDF, OTHER) ───────────────────────────
    score       = 0
    issues      = []
    recs        = []
    matched_uwi = None

    uwi = fields.get('uwi')
    # Ignore shapefile sentinel values if they somehow leak here
    if uwi and str(uwi).startswith('__SHP_'):
        uwi = None

    if uwi and engine:
        matched_uwi = match_uwi(engine, uwi)
        if matched_uwi:
            score += _SCORE_WEIGHTS['uwi_in_db']
        else:
            score += _SCORE_WEIGHTS['uwi_in_header']
            issues.append(f"UWI '{uwi}' not found in dv_well")
            recs.append("Bootstrap well from header or verify UWI")
    elif uwi:
        score += _SCORE_WEIGHTS['uwi_in_header']
        issues.append("No DB connection — UWI not verified")
    else:
        issues.append("No UWI found in header")
        recs.append("Extract UWI from filename or enter manually")

    wn = fields.get('well_name')
    if wn and not str(wn).startswith('__SHP_'):
        score += _SCORE_WEIGHTS['well_name']
    else:
        issues.append("No well name in header")

    if fields.get('operator'):
        score += _SCORE_WEIGHTS['operator']
    else:
        issues.append("No operator in header")

    if fields.get('latitude') and fields.get('longitude'):
        score += _SCORE_WEIGHTS['lat_lon']
    else:
        issues.append("No coordinates in header")

    # State and county scoring — document-centric signals that don't depend
    # on dv_well. Currently aspirational: extract_file_fields() does not yet
    # populate these for LOG/SEIS/PDF/SHP files. Score will activate
    # automatically once extraction is fixed to fill them in.
    if fields.get('state'):
        score += _SCORE_WEIGHTS['state']
    if fields.get('county'):
        score += _SCORE_WEIGHTS['county']

    sd = fields.get('start_depth')
    ed = fields.get('stop_depth')
    if sd is not None and ed is not None:
        try:
            if float(ed) > float(sd):
                score += _SCORE_WEIGHTS['depth_range']
            else:
                issues.append("Invalid depth range (stop <= start)")
        except (TypeError, ValueError):
            pass
    elif file_type == 'PDF' and ed is not None:
        score += _SCORE_WEIGHTS['depth_range'] // 2

    if file_type == 'PDF' and fields.get('report_type'):
        issues.insert(0, f"Report type: {fields['report_type']}")

    if score >= 80:   readiness = 'READY'
    elif score >= 60: readiness = 'REVIEW'
    elif score >= 40: readiness = 'NEEDS_UWI'
    else:             readiness = 'ATTENTION'

    return {
        'score':           score,
        'readiness':       readiness,
        'matched_uwi':     matched_uwi,
        'issues':          issues,
        'recommendations': recs,
    }


def _score_shapefile(fields: dict) -> dict:
    """
    Score a shapefile based on classification confidence and feature type.
    Shapefiles are not UWI-centric — scoring rewards confident classification
    and known PPDM targets.

    Score bands:
      80-100  READY    — high confidence, known PPDM target
      60-79   REVIEW   — moderate confidence or unknown target
      40-59   NEEDS_UWI — well shapefile with UWI column but unverified
      <40     ATTENTION — low confidence or unclassified
    """
    score   = 0
    issues  = []
    recs    = []

    confidence   = float(fields.get('confidence') or 0.0)
    feature_type = fields.get('feature_type') or 'REVIEW'
    ppdm_target  = fields.get('ppdm_target')
    has_uwi_col  = str(fields.get('uwi') or '').startswith('__SHP_HAS_UWI')
    has_well_col = str(fields.get('well_name') or '').startswith('__SHP_HAS_WELL')
    feat_count   = fields.get('feature_count') or 0
    crs          = fields.get('crs')

    # Confidence → up to 50 pts
    score += int(confidence * 50)

    # Known PPDM target → 20 pts
    if ppdm_target:
        score += 20
    else:
        issues.append("No PPDM target identified")
        recs.append("Classify shapefile feature type manually")

    # UWI column present → 20 pts (well shapefile can be matched)
    if has_uwi_col:
        score += 20
    elif has_well_col:
        score += 10
        issues.append("Well name column found but no UWI — match may be approximate")
    elif feature_type not in ('BOUNDARY', 'REVIEW'):
        issues.append("No UWI or well name column detected")

    # CRS present → 10 pts
    if crs and crs.upper() not in ('NONE', 'UNKNOWN', 'NONE'):
        score += 10
    else:
        issues.append("No CRS / projection defined")
        recs.append("Define CRS before loading to PPDM spatial tables")

    score = min(score, 100)

    # Readiness — well shapefiles without UWI pushed to NEEDS_UWI
    if score >= 80:
        readiness = 'READY'
    elif score >= 60:
        readiness = 'REVIEW'
    elif has_uwi_col or has_well_col:
        readiness = 'NEEDS_UWI'
    else:
        readiness = 'ATTENTION'

    if feat_count > 0:
        issues.insert(0, f"{feat_count:,} features · {fields.get('geometry_type','?')} · {feature_type}")

    return {
        'score':           score,
        'readiness':       readiness,
        'matched_uwi':     None,
        'issues':          issues,
        'recommendations': recs,
    }


def _score_office(fields: dict) -> dict:
    """
    Score an Excel/Word/CSV file based on PPDM hints and UWI presence.

    Score bands:
      80+   READY    — UWI found + known PPDM target
      60-79 REVIEW   — PPDM target identified, no UWI
      40-59 NEEDS_UWI — some structure detected, UWI missing
      <40   ATTENTION — unrecognised structure
    """
    score  = 0
    issues = []
    recs   = []

    ppdm_hints = fields.get('ppdm_hints') or []
    uwi        = fields.get('uwi')
    warnings   = fields.get('warnings') or []

    # PPDM hints → up to 40 pts (10 per hint, max 4)
    hint_score = min(len(ppdm_hints) * 10, 40)
    score += hint_score
    if not ppdm_hints:
        issues.append("No PPDM table mapping detected")
        recs.append("Review column headers and map to PPDM manually")

    # UWI present → 40 pts
    if uwi and not str(uwi).startswith('__SHP_'):
        score += 40
    else:
        issues.append("No UWI column found in data")
        recs.append("Identify UWI/API column for well linkage")

    # No warnings → 20 pts
    if not warnings:
        score += 20
    else:
        for w in warnings[:3]:
            issues.append(w)

    score = min(score, 100)

    if score >= 80:   readiness = 'READY'
    elif score >= 60: readiness = 'REVIEW'
    elif score >= 40: readiness = 'NEEDS_UWI'
    else:             readiness = 'ATTENTION'

    if ppdm_hints:
        issues.insert(0, f"PPDM targets: {', '.join(ppdm_hints)}")

    return {
        'score':           score,
        'readiness':       readiness,
        'matched_uwi':     None,
        'issues':          issues,
        'recommendations': recs,
    }


# ── dv_well bootstrap ─────────────────────────────────────────────────────────

def bootstrap_well(engine, dialect: str, fields: dict,
                   source: str = 'FILE_HEADER',
                   created_by: str = 'DataWrangler') -> tuple[bool, str]:
    """
    Create a dv_well record from file header fields.
    Returns (ok, uwi_or_error).
    Only creates if UWI not already in dv_well.
    """
    uwi = fields.get('uwi')
    if not uwi:
        return False, "No UWI available"

    # Check if already exists
    if match_uwi(engine, uwi):
        return True, uwi  # Already there

    well_name = fields.get('well_name') or ''
    operator  = fields.get('operator') or ''
    lat       = fields.get('latitude')
    lon       = fields.get('longitude')
    final_td  = fields.get('stop_depth')

    # Resolve operator BA ID if possible
    operator_ba_id = None
    if operator and engine:
        try:
            with engine.connect() as con:
                row = con.execute(text(
                    "SELECT ba_id FROM dataview.dv_business_associate "
                    "WHERE ba_name = :n"), {"n": operator}).fetchone()
                if row:
                    operator_ba_id = row[0]
                else:
                    # Create BA record
                    import hashlib
                    ba_id = hashlib.sha1(
                        operator.upper().encode('utf-8')).hexdigest()
                    with engine.begin() as con:
                        con.execute(text("""
                            IF NOT EXISTS (
                                SELECT 1 FROM dataview.dv_business_associate
                                WHERE ba_id = :bid)
                            INSERT INTO dataview.dv_business_associate
                                (ba_id, ba_name, active_ind,
                                 row_created_by, row_created_date, source)
                            VALUES (:bid, :name, 'Y', :by, GETDATE(), :src)
                        """), {"bid": ba_id, "name": operator[:255],
                               "by": created_by, "src": source})
                    operator_ba_id = ba_id
        except Exception:
            pass

    try:
        with engine.begin() as con:
            con.execute(text("""
                INSERT INTO dataview.dv_well (
                    uwi, well_name, surface_latitude, surface_longitude,
                    final_td, operator_ba_id, active_ind, source,
                    row_created_by, row_created_date
                ) VALUES (
                    :uwi, :wn, :lat, :lon,
                    :td, :op, 'Y', :src,
                    :by, GETDATE()
                )
            """), {
                "uwi": uwi[:40],
                "wn":  well_name[:255] if well_name else None,
                "lat": lat,
                "lon": lon,
                "td":  final_td,
                "op":  operator_ba_id,
                "src": source,
                "by":  created_by,
            })
        return True, uwi
    except Exception as e:
        return False, str(e)


# ── Batch header extraction ───────────────────────────────────────────────────

def extract_and_score_inventory(engine, dialect: str,
                                 inventory_ids: list[str] = None,
                                 ext_filter: list[str] = None,
                                 limit: int = 100,
                                 progress_callback=None) -> list[dict]:
    """
    Pull files from GLOBAL_FILE_CATALOG, extract headers, score them.
    Returns list of result dicts.

    ext_filter: e.g. ['.las', '.dlis'] — None means all well log types
    inventory_ids: specific IDs to process — None means pull from DB
    """
    if ext_filter is None:
        ext_filter = ['.las', '.dlis', '.dlf', '.lis', '.segy', '.sgy']

    results = []

    try:
        # Fetch files to process
        if inventory_ids:
            placeholders = ','.join(f':id{i}' for i in range(len(inventory_ids)))
            params = {f'id{i}': v for i, v in enumerate(inventory_ids)}
            sql = f"""
                SELECT TOP {limit} INVENTORY_ID, FILE_PATH, FILE_EXT
                FROM file_catalog.GLOBAL_FILE_CATALOG
                WHERE INVENTORY_ID IN ({placeholders})
            """
        else:
            exts = ','.join(f"'{e}'" for e in ext_filter)
            sql = f"""
                SELECT TOP {limit} INVENTORY_ID, FILE_PATH, FILE_EXT
                FROM file_catalog.GLOBAL_FILE_CATALOG
                WHERE FILE_EXT IN ({exts})
                AND (CATALOG_STATUS IS NULL OR CATALOG_STATUS = 'UNCATALOGED')
                ORDER BY SCAN_DATE DESC
            """
            params = {}

        with engine.connect() as con:
            rows = con.execute(text(sql), params).fetchall()

        total = len(rows)
        for i, (inv_id, file_path, ext) in enumerate(rows):
            if progress_callback:
                progress_callback(i, total, file_path)

            try:
                fields = extract_file_fields(file_path)
                scored = score_file(fields, engine)
                results.append({
                    'inventory_id': inv_id,
                    'file_path':    file_path,
                    'file_ext':     ext,
                    'fields':       fields,
                    'score':        scored['score'],
                    'readiness':    scored['readiness'],
                    'matched_uwi':  scored['matched_uwi'],
                    'issues':       scored['issues'],
                    'recommendations': scored['recommendations'],
                })
            except Exception as e:
                results.append({
                    'inventory_id': inv_id,
                    'file_path':    file_path,
                    'file_ext':     ext,
                    'error':        str(e),
                    'score':        0,
                    'readiness':    'ERROR',
                })

    except Exception as e:
        results.append({'error': str(e)})

    return results


# ── Catalog rules summary ─────────────────────────────────────────────────────

CATALOG_RULES = {
    'LAS': {
        'required_fields':  ['uwi'],
        'recommended_fields': ['well_name', 'operator', 'start_depth', 'stop_depth'],
        'min_curves':       1,
        'min_score':        60,
        'auto_bootstrap':   True,
        'description': 'Well log — LAS format',
    },
    'DLIS': {
        'required_fields':  ['uwi'],
        'recommended_fields': ['well_name', 'operator'],
        'min_curves':       1,
        'min_score':        60,
        'auto_bootstrap':   True,
        'description': 'Well log — DLIS format',
    },
    'LIS': {
        'required_fields':  ['uwi'],
        'recommended_fields': ['well_name'],
        'min_curves':       1,
        'min_score':        40,
        'auto_bootstrap':   True,
        'description': 'Well log — LIS format',
    },
    'SEGY': {
        'required_fields':  ['survey_name'],
        'recommended_fields': ['sample_interval', 'samples_per_trace'],
        'min_curves':       0,
        'min_score':        40,
        'auto_bootstrap':   False,
        'description': 'Seismic — SEG-Y format',
    },
}


def get_rules(file_type: str) -> dict:
    """Return cataloging rules for a file type."""
    return CATALOG_RULES.get(file_type.upper(), {
        'required_fields': [],
        'recommended_fields': [],
        'min_curves': 0,
        'min_score': 40,
        'auto_bootstrap': False,
        'description': 'Unknown format',
    })


# ── Write scores back to GLOBAL_FILE_CATALOG ─────────────────────────────────

def write_score(engine, inventory_id: str, scored: dict,
                fields: dict) -> bool:
    """Write catalog score back to GLOBAL_FILE_CATALOG."""
    try:
        issues_str = "; ".join(scored.get("issues", []))[:2000]
        with engine.begin() as con:
            con.execute(text("""
                UPDATE file_catalog.GLOBAL_FILE_CATALOG SET
                    CATALOG_SCORE     = :score,
                    CATALOG_READINESS = :readiness,
                    MATCHED_UWI       = :uwi,
                    MATCH_METHOD      = :method,
                    CATALOG_ISSUES    = :issues,
                    HEADER_EXTRACTED  = 'Y',
                    UWI               = COALESCE(UWI, :raw_uwi),
                    WELL_NAME         = COALESCE(WELL_NAME, :wn),
                    OPERATOR          = COALESCE(OPERATOR, :op)
                WHERE INVENTORY_ID = :inv_id
            """), {
                "score":     scored.get("score", 0),
                "readiness": scored.get("readiness", "UNKNOWN"),
                "uwi":       scored.get("matched_uwi"),
                "method":    "AUTO",
                "issues":    issues_str,
                "raw_uwi":   fields.get("uwi"),
                "wn":        (fields.get("well_name") or "")[:255],
                "op":        (fields.get("operator") or "")[:255],
                "inv_id":    inventory_id,
            })
        return True
    except Exception:
        return False


def score_inventory_batch(engine, dialect: str,
                          ext_filter: list = None,
                          limit: int = 200,
                          progress_callback=None) -> dict:
    """
    Pull unscored files from inventory, extract headers,
    score them and write results back.
    Returns summary dict.
    """
    if ext_filter is None:
        ext_filter = [".las", ".dlis", ".dlf", ".lis", ".segy", ".sgy"]

    summary = {"total": 0, "scored": 0, "errors": 0,
               "ready": 0, "review": 0, "needs_uwi": 0, "attention": 0}

    try:
        exts = ",".join(f"\'{e}\'" for e in ext_filter)
        with engine.connect() as con:
            rows = con.execute(text(f"""
                SELECT TOP {limit}
                    INVENTORY_ID, FILE_PATH, FILE_EXT
                FROM file_catalog.GLOBAL_FILE_CATALOG
                WHERE FILE_EXT IN ({exts})
                AND (HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED = 'N')
                ORDER BY SCAN_DATE DESC
            """)).fetchall()
    except Exception as e:
        return {"error": str(e)}

    summary["total"] = len(rows)

    for i, (inv_id, file_path, ext) in enumerate(rows):
        if progress_callback:
            progress_callback(i, len(rows), file_path)
        try:
            fields = extract_file_fields(file_path)
            scored = score_file(fields, engine)
            write_score(engine, inv_id, scored, fields)
            summary["scored"] += 1
            r = scored["readiness"].lower()
            if r in summary:
                summary[r] += 1
        except Exception:
            summary["errors"] += 1

    return summary

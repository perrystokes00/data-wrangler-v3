"""
modules/segy_catalog.py

SEG-Y file catalog — parses binary and text headers, extracts survey
metadata, bounding box coordinates, and optionally seeds PPDM SEIS_SET
and SEIS_LINE tables.

Supports SEG-Y revisions 0, 1, and 2.
Requires: segyio (pip install segyio)

No trace data is read — only the 3200-byte EBCDIC text header and
400-byte binary header are parsed, plus the first and last trace headers
for coordinate extraction.
"""

from __future__ import annotations

import hashlib
import re
import struct
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Constants — SEG-Y binary header byte positions (1-based, per SEG-Y rev 1)
# ─────────────────────────────────────────────────────────────────────────────

# Binary header offsets (0-based from start of binary header block)
_BIN_SAMPLE_INTERVAL  = 16   # 2 bytes, microseconds
_BIN_SAMPLE_COUNT     = 20   # 2 bytes
_BIN_DATA_FORMAT      = 24   # 2 bytes
_BIN_SEGY_REVISION    = 300  # 2 bytes (rev 1+)
_BIN_FIXED_LEN_FLAG   = 302  # 2 bytes

_DATA_FORMAT_NAMES = {
    1: "IBM 32-bit float",
    2: "32-bit integer",
    3: "16-bit integer",
    4: "32-bit fixed point with gain",
    5: "IEEE 32-bit float",
    6: "IEEE 64-bit float",
    7: "8-bit signed integer",
    8: "8-bit unsigned integer",
    9: "64-bit signed integer",
    10: "32-bit unsigned integer",
    11: "16-bit unsigned integer",
    12: "8-bit unsigned integer (alt)",
    15: "3-byte integer",
    16: "24-bit integer",
}

# Trace header byte offsets (0-based from start of trace header)
_TR_INLINE      = 188   # 4 bytes — inline number (rev 1)
_TR_CROSSLINE   = 192   # 4 bytes — crossline number (rev 1)
_TR_X_COORD     = 180   # 4 bytes — X coordinate of CDP
_TR_Y_COORD     = 184   # 4 bytes — Y coordinate of CDP
_TR_COORD_SCALE = 70    # 2 bytes — scalar for coordinates
_TR_FIELD_NO    = 8     # 4 bytes — field record number (shot point proxy)

EBCDIC_TABLE = (
    b'\x00\x01\x02\x03\x9c\t\x86\x7f\x97\x8d\x8e\x0b\x0c\r\x0e\x0f'
    b'\x10\x11\x12\x13\x9d\x85\x08\x87\x18\x19\x92\x8f\x1c\x1d\x1e\x1f'
    b'\x80\x81\x82\x83\x84\n\x17\x1b\x88\x89\x8a\x8b\x8c\x05\x06\x07'
    b'\x90\x91\x16\x93\x94\x95\x96\x04\x98\x99\x9a\x9b\x14\x15\x9e\x1a'
    b' \xa0\xe2\xe4\xe0\xe1\xe3\xe5\xe7\xf1\xa2.<(+|'
    b'&\xe9\xea\xeb\xe8\xed\xee\xef\xec\xdf!\x24*);~'
    b'-/\xc2\xc4\xc0\xc1\xc3\xc5\xc7\xd1\xa6,%_>?'
    b'\xf8\xc9\xca\xcb\xc8\xcd\xce\xcf\xcc`:#@\'="'
    b'\xd8abcdefghi\xab\xbb\xf0\xfd\xfe\xb1'
    b'\xb0jklmnopqr\xaa\xba\xe6\xb8\xc6\xa4'
    b'\xb5~stuvwxyz\xa1\xbf\xd0[\xde\xae'
    b'\xac\xa3\xa5\xb7\xa9\xa7\xb6\xbc\xbd\xbe\xdd\xa8\xaf]\xb4\xd7'
    b'{ABCDEFGHI\xad\xf4\xf6\xf2\xf3\xf5'
    b'}JKLMNOPQR\xb9\xfb\xfc\xf9\xfa\xff'
    b'\\\xf7STUVWXYZ\xb2\xd4\xd6\xd2\xd3\xd5'
    b'0123456789\xb3\xdb\xdc\xd9\xda\x9f'
)


def _is_ascii_header(data: bytes) -> bool:
    """
    Detect if the text header is ASCII rather than EBCDIC.
    Modern SEG-Y files sometimes use ASCII despite the standard requiring EBCDIC.
    """
    sample = data[:160]
    if not sample:
        return False
    printable = sum(1 for b in sample if 0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D))
    return printable / len(sample) > 0.6


def _ebcdic_to_ascii(data: bytes) -> str:
    """
    Convert EBCDIC bytes to ASCII string.
    Auto-detects if header is already ASCII and skips conversion.
    """
    if _is_ascii_header(data):
        return data.decode("ascii", errors="replace")
    return bytes(EBCDIC_TABLE[b] for b in data).decode("ascii", errors="replace")


def _make_id(seed: str) -> str:
    normalised = seed.strip().lower().replace("\\", "/").rstrip("/")
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:20].upper()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _read_int16(data: bytes, offset: int) -> int:
    return struct.unpack(">h", data[offset:offset+2])[0]


def _read_int32(data: bytes, offset: int) -> int:
    return struct.unpack(">i", data[offset:offset+4])[0]


def _apply_scalar(value: int, scalar: int) -> float:
    """Apply SEG-Y coordinate scalar to a raw integer coordinate."""
    if scalar == 0:
        scalar = 1
    if scalar < 0:
        return value / abs(scalar)
    return value * scalar


# ─────────────────────────────────────────────────────────────────────────────
# Header parser
# ─────────────────────────────────────────────────────────────────────────────

def detect_survey_name(file_path: str, header_survey: str = "") -> str:
    """
    Detect a survey name from the file header or filename pattern.
    Header takes priority if it contains a meaningful value (3+ chars).
    Falls back to filename pattern matching — strips common line/SP suffixes
    to extract the survey code prefix.
    """
    import re as _re
    from pathlib import Path as _Path

    if header_survey and len(header_survey.strip()) >= 3:
        return header_survey.strip()

    stem = _Path(file_path).stem.upper()
    cleaned = stem
    for p in [
        r'[_\-](?:LINE|LN|L)0*\d+$',
        r'[_\-]0*\d{3,6}$',
        r'[_\-](?:SP|CDP|CMP)0*\d+$',
        r'[_\-](?:SGY|SEGY|SEG|P190|P90)$',
    ]:
        cleaned = _re.sub(p, '', cleaned)
    cleaned = cleaned.strip('_- ')

    if len(cleaned) >= 3 and not cleaned.isdigit():
        return _re.sub(r'[_\-]+', ' ', cleaned).strip()

    m = _re.search(r'(?:^|[_\-])(\d{4})(?:[_\-]|$)', stem)
    if m:
        year = m.group(1)
        if 1960 <= int(year) <= 2030:
            return f"Survey {year}"
    return ""


def parse_segy_header(file_path: str) -> dict:
    """
    Parse SEG-Y file header without reading trace data.

    Returns dict with keys:
      text_header       : list of 40 strings (EBCDIC decoded)
      survey_name       : extracted from text header
      line_name         : extracted from text header
      client_name       : extracted from text header
      sample_interval_us: sample interval in microseconds
      sample_count      : samples per trace
      data_format       : data format string
      segy_revision     : 0, 1, or 2
      trace_count       : estimated from file size
      dimensionality    : '2D' or '3D' (best guess)
      min_inline/max_inline/min_crossline/max_crossline
      min_x/max_x/min_y/max_y  : projected coordinates
      min_lat/max_lat/min_lon/max_lon : geographic (if detected)
      coord_system      : coordinate system description
      acq_date_start    : date string if found in text header
      file_size_kb      : file size
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    result = {
        "text_header":       [],
        "survey_name":       "",
        "line_name":         "",
        "client_name":       "",
        "vessel_name":       "",
        "sample_interval_us": None,
        "sample_count":      None,
        "data_format":       "",
        "segy_revision":     0,
        "trace_count":       None,
        "dimensionality":    "2D",
        "min_inline":        None, "max_inline":    None,
        "min_crossline":     None, "max_crossline": None,
        "min_x":  None, "max_x":  None,
        "min_y":  None, "max_y":  None,
        "min_lat": None, "max_lat": None,
        "min_lon": None, "max_lon": None,
        "coord_system":      "",
        "acq_date_start":    "",
        "acq_date_end":      "",
        "file_size_kb":      round(path.stat().st_size / 1024, 2),
    }

    with open(file_path, "rb") as f:
        # ── Text header (3200 bytes EBCDIC) ──────────────────────────────
        raw_text = f.read(3200)
        if len(raw_text) < 3200:
            raise ValueError("File too small to be a valid SEG-Y file")

        text_lines = []
        for i in range(40):
            line = _ebcdic_to_ascii(raw_text[i*80:(i+1)*80]).rstrip()
            text_lines.append(line)
        result["text_header"] = text_lines

        # Check text header quality — count printable chars
        full_text = "\n".join(text_lines).upper()
        # Auto-detect survey name from header or filename
        if not result["survey_name"]:
            result["survey_name"] = detect_survey_name(
                file_path, result["survey_name"]
            )
        _printable = sum(1 for c in full_text if 32 <= ord(c) <= 126)
        _total     = max(len(full_text), 1)
        result["text_header_readable"] = (_printable / _total) > 0.5

        # Try to use filename as fallback survey/line name if header is garbled
        if not result["text_header_readable"]:
            stem = path.stem  # filename without extension
            result["survey_name"] = stem
            result["line_name"]   = stem

        for line in text_lines:
            lu = line.upper()
            for kw in ("LINE", "LINE NAME", "LINE NO", "2D LINE"):
                if kw in lu:
                    m = re.search(r'(?:LINE(?:\s+(?:NAME|NO\.?)?)?)\s*[:\-]?\s*([A-Z0-9_\-\.]+)',
                                  lu)
                    if m and not result["line_name"]:
                        result["line_name"] = m.group(1).strip()
            for kw in ("SURVEY", "PROJECT", "AREA"):
                if kw in lu:
                    m = re.search(r'(?:SURVEY|PROJECT|AREA)\s*[:\-]?\s*([A-Z0-9_\-\. ]+)',
                                  lu)
                    if m and not result["survey_name"]:
                        result["survey_name"] = m.group(1).strip()[:60]
            for kw in ("CLIENT", "COMPANY", "OPERATOR"):
                if kw in lu:
                    m = re.search(r'(?:CLIENT|COMPANY|OPERATOR)\s*[:\-]?\s*([A-Z0-9_\-\. &]+)',
                                  lu)
                    if m and not result["client_name"]:
                        result["client_name"] = m.group(1).strip()[:60]
            for kw in ("VESSEL", "SHIP", "CREW"):
                if kw in lu:
                    m = re.search(r'(?:VESSEL|SHIP|CREW)\s*[:\-]?\s*([A-Z0-9_\-\. ]+)',
                                  lu)
                    if m and not result["vessel_name"]:
                        result["vessel_name"] = m.group(1).strip()[:60]
            for kw in ("DATE", "ACQUIRED"):
                if kw in lu:
                    m = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})', lu)
                    if m and not result["acq_date_start"]:
                        result["acq_date_start"] = m.group(1)
            for kw in ("3D", "CUBE", "VOLUME", "INLINE", "CROSSLINE"):
                if kw in lu:
                    result["dimensionality"] = "3D"
                    break
            if "CRS" in lu or "COORD" in lu or "PROJECTION" in lu or "UTM" in lu:
                result["coord_system"] = line.strip()[:255]

        # ── Binary header (400 bytes) ─────────────────────────────────────
        bin_hdr = f.read(400)
        if len(bin_hdr) < 400:
            return result

        si = _read_int16(bin_hdr, _BIN_SAMPLE_INTERVAL)
        sc = _read_int16(bin_hdr, _BIN_SAMPLE_COUNT)
        df = _read_int16(bin_hdr, _BIN_DATA_FORMAT)
        result["sample_interval_us"] = si if si > 0 else None
        result["sample_count"]       = sc if sc > 0 else None
        result["data_format"]        = _DATA_FORMAT_NAMES.get(df, f"Code {df}")

        # Additional binary header fields
        try:
            n_data_traces = _read_int16(bin_hdr, 12)   # traces per ensemble
            n_aux_traces  = _read_int16(bin_hdr, 14)   # aux traces per ensemble
            n_samples_orig= _read_int16(bin_hdr, 22)   # samples per trace (orig)
            meas_system   = _read_int16(bin_hdr, 54)   # 1=metres, 2=feet
            result["n_data_traces"]  = n_data_traces if n_data_traces > 0 else None
            result["n_aux_traces"]   = n_aux_traces  if n_aux_traces  > 0 else None
            result["depth_uom"]      = "M" if meas_system == 1 else ("FT" if meas_system == 2 else None)
            # Max depth/time
            if sc and si and sc > 0 and si > 0:
                result["max_depth_ms"] = round(sc * si / 1000.0, 3)
                result["min_depth_ms"] = 0.0
        except Exception:
            pass

        if len(bin_hdr) >= 302:
            rev = _read_int16(bin_hdr, _BIN_SEGY_REVISION)
            result["segy_revision"] = rev if rev in (0, 1, 2, 256, 512) else 0
            # Rev 1 stores revision as 0x0100 = 256
            if result["segy_revision"] == 256:
                result["segy_revision"] = 1
            elif result["segy_revision"] == 512:
                result["segy_revision"] = 2

        # Estimate trace count from file size
        trace_hdr_bytes = 240
        bytes_per_sample = {1: 4, 2: 4, 3: 2, 4: 4, 5: 4,
                            6: 8, 7: 1, 8: 1}.get(df, 4)
        if sc and sc > 0:
            trace_bytes = trace_hdr_bytes + sc * bytes_per_sample
            data_bytes  = path.stat().st_size - 3600
            if data_bytes > 0:
                result["trace_count"] = max(0, data_bytes // trace_bytes)

        # ── Sample trace headers for bounding box ────────────────────────
        # Read up to MAX_SAMPLE_TRACES trace headers, evenly distributed
        # through the file. Only reads the 240-byte trace header, skips
        # the data samples entirely — fast even for large 3D volumes.
        MAX_SAMPLE_TRACES = 1000

        first_tr = f.read(240)
        if len(first_tr) < 240:
            return result

        bps = {1: 4, 2: 4, 3: 2, 4: 4, 5: 4, 6: 8, 7: 1, 8: 1}.get(df, 4)
        trace_bytes = 240 + (sc * bps if sc else 0)

        xs, ys   = [], []
        inlines  = []
        xlines   = []

        def _parse_tr(tr_bytes):
            if len(tr_bytes) < 240:
                return
            scl = _read_int16(tr_bytes, _TR_COORD_SCALE)
            x   = _apply_scalar(_read_int32(tr_bytes, _TR_X_COORD), scl)
            y   = _apply_scalar(_read_int32(tr_bytes, _TR_Y_COORD), scl)
            il  = _read_int32(tr_bytes, _TR_INLINE)
            xl  = _read_int32(tr_bytes, _TR_CROSSLINE)
            if x != 0 or y != 0:
                xs.append(x); ys.append(y)
            if il != 0:
                inlines.append(il)
            if xl != 0:
                xlines.append(xl)

        # Always parse first trace
        _parse_tr(first_tr)

        n_traces = result["trace_count"] or 0
        if n_traces > 1 and trace_bytes > 0:
            # Determine sampling step
            step = max(1, n_traces // MAX_SAMPLE_TRACES)
            sample_indices = list(range(1, n_traces, step))
            # Always include the last trace
            if (n_traces - 1) not in sample_indices:
                sample_indices.append(n_traces - 1)

            for tr_idx in sample_indices:
                tr_offset = 3600 + tr_idx * trace_bytes
                try:
                    f.seek(tr_offset)
                    tr_bytes = f.read(240)
                    _parse_tr(tr_bytes)
                except Exception:
                    break

    # ── Build bounding box from sampled traces ────────────────────────────
    def _looks_geographic(x, y):
        return (-180 <= x <= 180) and (-90 <= y <= 90)

    if xs and ys:
        if _looks_geographic(xs[0], ys[0]):
            result["min_lat"] = round(min(ys), 7)
            result["max_lat"] = round(max(ys), 7)
            result["min_lon"] = round(min(xs), 7)
            result["max_lon"] = round(max(xs), 7)
        else:
            result["min_x"] = round(min(xs), 2)
            result["max_x"] = round(max(xs), 2)
            result["min_y"] = round(min(ys), 2)
            result["max_y"] = round(max(ys), 2)

    if inlines:
        result["dimensionality"]  = "3D"
        result["min_inline"]      = min(inlines)
        result["max_inline"]      = max(inlines)
        result["min_crossline"]   = min(xlines) if xlines else None
        result["max_crossline"]   = max(xlines) if xlines else None

    # Time range from sample count and interval
    if result["sample_count"] and result["sample_interval_us"]:
        result["min_depth_ms"] = 0.0
        result["max_depth_ms"] = round(
            result["sample_count"] * result["sample_interval_us"] / 1000.0, 3
        )
    else:
        result["min_depth_ms"] = None
        result["max_depth_ms"] = None

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Catalog functions
# ─────────────────────────────────────────────────────────────────────────────

def catalog_segy_file(engine,
                      file_path: str,
                      repository_id: str = "",
                      source: str = "SEIS_FILE_CATALOG",
                      seed_ppdm: bool = False,
                      survey_name: str = "") -> dict:
    """
    Parse a SEG-Y file and insert into SEIS_FILE_CATALOG.

    Parameters
    ----------
    engine        : SQLAlchemy engine
    file_path     : full path to .segy / .sgy file
    repository_id : optional FK to WL_REPOSITORY
    source        : SOURCE value for all rows
    seed_ppdm     : if True, create dbo.SEIS_SET and dbo.SEIS_LINE records

    Returns dict: { ok, action, seis_file_id, seeded_ppdm, error }
    """
    from sqlalchemy import text

    result = {
        "ok": False, "action": "", "seis_file_id": "",
        "seeded_ppdm": False, "error": "",
    }

    path = Path(file_path)
    if not path.exists():
        result["error"] = f"File not found: {file_path}"
        return result

    try:
        header = parse_segy_header(file_path)
    except Exception as e:
        result["error"] = f"Parse failed: {e}"
        return result

    # Apply survey name override if provided
    if survey_name.strip():
        header["survey_name"] = survey_name.strip()

    now          = _now_str()
    seis_file_id = _make_id(file_path)
    file_hash    = _sha256_file(file_path)

    # Relative file name
    try:
        if repository_id:
            with engine.connect() as con:
                base = con.execute(text(
                    "SELECT BASE_PATH FROM [las_catalog].[WL_REPOSITORY] "
                    "WHERE REPOSITORY_ID = :id"
                ), {"id": repository_id}).scalar() or ""
            try:
                rel = str(path.relative_to(base))
            except ValueError:
                rel = path.name
        else:
            rel = path.name
    except Exception:
        rel = path.name

    # Check for existing entry
    with engine.connect() as con:
        existing = con.execute(text(
            "SELECT SEIS_FILE_ID FROM [las_catalog].[SEIS_FILE_CATALOG] "
            "WHERE SEIS_FILE_ID = :id"
        ), {"id": seis_file_id}).scalar()

        if not existing and file_hash:
            existing = con.execute(text(
                "SELECT SEIS_FILE_ID FROM [las_catalog].[SEIS_FILE_CATALOG] "
                "WHERE FILE_HASH = :hash"
            ), {"hash": file_hash}).scalar()
            if existing:
                seis_file_id = existing

    if existing:
        with engine.begin() as con:
            con.execute(text("""
                UPDATE [las_catalog].[SEIS_FILE_CATALOG]
                SET LAST_SEEN_DATE = :now, ROW_CHANGED_DATE = :now,
                    ROW_CHANGED_BY = 'DATA_WRANGLER'
                WHERE SEIS_FILE_ID = :id
            """), {"now": now, "id": seis_file_id})
        result.update({"ok": True, "action": "updated",
                       "seis_file_id": seis_file_id})
        return result

    # Optional PPDM seed
    seis_set_id  = None
    seis_line_id = None
    seis_set_subid = None

    if seed_ppdm:
        try:
            seis_set_id, seis_line_id, seis_set_subid = _seed_ppdm_segy(
                engine, header, source, now
            )
            result["seeded_ppdm"] = True
        except Exception as e:
            result["error"] = f"PPDM seed failed (file will still be catalogued): {e}"

    # Build file row
    file_row = {
        "SEIS_FILE_ID":        seis_file_id,
        "REPOSITORY_ID":       repository_id or None,
        "FILE_FORMAT":         "SEGY",
        "FILE_NAME":           rel,
        "FILE_SIZE_KB":        header["file_size_kb"],
        "FILE_HASH":           file_hash,
        "SEIS_SET_ID":         seis_set_id,
        "SEIS_LINE_ID":        seis_line_id,
        "SEIS_SET_SUBID":      seis_set_subid,
        "SURVEY_NAME":         header["survey_name"] or None,
        "LINE_NAME":           header["line_name"] or None,
        "VESSEL_NAME":         header["vessel_name"] or None,
        "CLIENT_NAME":         header["client_name"] or None,
        "DIMENSIONALITY":      header["dimensionality"],
        "SAMPLE_INTERVAL_US":  header["sample_interval_us"],
        "SAMPLE_COUNT":        header["sample_count"],
        "TRACE_COUNT":         header["trace_count"],
        "DATA_FORMAT":         header["data_format"] or None,
        "SEGY_REVISION":       str(header["segy_revision"]),
        "ACQ_DATE_START":      header["acq_date_start"] or None,
        "ACQ_DATE_END":        header["acq_date_end"] or None,
        "MIN_LAT":             header["min_lat"],
        "MAX_LAT":             header["max_lat"],
        "MIN_LON":             header["min_lon"],
        "MAX_LON":             header["max_lon"],
        "MIN_X":               header["min_x"],
        "MAX_X":               header["max_x"],
        "MIN_Y":               header["min_y"],
        "MAX_Y":               header["max_y"],
        "COORD_SYSTEM":        header["coord_system"] or None,
        "MIN_DEPTH_MS":        header.get("min_depth_ms"),
        "MAX_DEPTH_MS":        header.get("max_depth_ms"),
        "MIN_INLINE":          header["min_inline"],
        "MAX_INLINE":          header["max_inline"],
        "MIN_CROSSLINE":       header["min_crossline"],
        "MAX_CROSSLINE":       header["max_crossline"],
        "CATALOG_DATE":        now,
        "LAST_SEEN_DATE":      now,
        "ACTIVE_IND":          "Y",
        "SOURCE":              source,
        "ROW_CREATED_BY":      "DATA_WRANGLER",
        "ROW_CREATED_DATE":    now,
        "ROW_CHANGED_BY":      "DATA_WRANGLER",
        "ROW_CHANGED_DATE":    now,
    }

    cols = ", ".join(f"[{k}]" for k in file_row)
    vals = ", ".join(f":{k}" for k in file_row)
    with engine.begin() as con:
        con.execute(text(
            f"INSERT INTO [las_catalog].[SEIS_FILE_CATALOG] ({cols}) VALUES ({vals})"
        ), file_row)

        # Insert text header lines
        for i, line in enumerate(header["text_header"], 1):
            con.execute(text("""
                INSERT INTO [las_catalog].[SEIS_FILE_HEADER]
                    (SEIS_FILE_ID, LINE_NO, HEADER_TEXT, SOURCE,
                     ROW_CREATED_BY, ROW_CREATED_DATE)
                VALUES (:fid, :ln, :txt, :src, 'DATA_WRANGLER', :now)
            """), {"fid": seis_file_id, "ln": i,
                   "txt": line[:80], "src": source, "now": now})

    result.update({"ok": True, "action": "inserted",
                   "seis_file_id": seis_file_id})
    return result


def _seed_ppdm_segy(engine, header: dict, source: str, now: str):
    """
    Seed dbo.SEIS_SET and dbo.SEIS_LINE from SEG-Y header data.
    Returns (seis_set_id, seis_line_id, seis_set_subid).
    Raises if PPDM tables don't exist.
    """
    from sqlalchemy import text

    # Check PPDM tables exist
    with engine.connect() as con:
        for tbl in ("SEIS_SET", "SEIS_LINE"):
            exists = con.execute(text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = :t"
            ), {"t": tbl}).scalar()
            if not exists:
                raise RuntimeError(
                    f"dbo.{tbl} does not exist. "
                    "Run PPDM 3.9 DDL or disable PPDM seeding."
                )

    survey_name = header["survey_name"] or "UNKNOWN"
    line_name   = header["line_name"]   or "UNKNOWN"
    dim         = header["dimensionality"]

    seis_set_id    = _make_id(f"SEGY|{survey_name}")
    seis_line_id   = _make_id(f"SEGY|{survey_name}|{line_name}")
    seis_set_subid = "PPDM"

    with engine.begin() as con:
        # SEIS_SET
        existing_set = con.execute(text(
            "SELECT SEIS_SET_ID FROM dbo.SEIS_SET WHERE SEIS_SET_ID = :id"
        ), {"id": seis_set_id}).scalar()

        if not existing_set:
            con.execute(text("""
                INSERT INTO dbo.SEIS_SET
                    (SEIS_SET_ID, SEIS_SET_SUBID, SEIS_SET_NAME,
                     SEIS_TYPE, ACTIVE_IND, SOURCE,
                     ROW_CREATED_BY, ROW_CREATED_DATE,
                     ROW_CHANGED_BY, ROW_CHANGED_DATE)
                VALUES
                    (:id, :subid, :name,
                     :stype, 'Y', :src,
                     'DATA_WRANGLER', :now,
                     'DATA_WRANGLER', :now)
            """), {
                "id":    seis_set_id,
                "subid": seis_set_subid,
                "name":  survey_name[:255],
                "stype": "3D" if dim == "3D" else "2D",
                "src":   source,
                "now":   now,
            })

        # SEIS_LINE
        existing_line = con.execute(text(
            "SELECT SEIS_LINE_ID FROM dbo.SEIS_LINE WHERE SEIS_LINE_ID = :id"
        ), {"id": seis_line_id}).scalar()

        if not existing_line:
            con.execute(text("""
                INSERT INTO dbo.SEIS_LINE
                    (SEIS_LINE_ID, SEIS_SET_ID, SEIS_SET_SUBID,
                     SEIS_LINE_NAME, ACTIVE_IND, SOURCE,
                     ROW_CREATED_BY, ROW_CREATED_DATE,
                     ROW_CHANGED_BY, ROW_CHANGED_DATE)
                VALUES
                    (:lid, :sid, :subid,
                     :name, 'Y', :src,
                     'DATA_WRANGLER', :now,
                     'DATA_WRANGLER', :now)
            """), {
                "lid":   seis_line_id,
                "sid":   seis_set_id,
                "subid": seis_set_subid,
                "name":  line_name[:255],
                "src":   source,
                "now":   now,
            })

    return seis_set_id, seis_line_id, seis_set_subid


def catalog_segy_directory(engine,
                            folder: str,
                            repository_id: str = "",
                            source: str = "SEIS_FILE_CATALOG",
                            seed_ppdm: bool = False,
                            max_workers: int = None,
                            progress_callback=None) -> list[dict]:
    """
    Catalog all SEG-Y files in a directory in parallel.
    """
    import concurrent.futures
    import os

    if max_workers is None:
        cores = os.cpu_count() or 4
        max_workers = min(max(cores - 2, 2), 12)

    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {folder}")

    # Collect all common SEG-Y extensions (case-insensitive on Windows,
    # explicit on Linux/Mac)
    _segy_exts = {".segy", ".sgy", ".seg"}
    files = sorted(set(
        f for f in folder_path.iterdir()
        if f.is_file() and f.suffix.lower() in _segy_exts
    ))

    if not files:
        return []

    # Parse headers in parallel, DB inserts sequentially
    total = len(files)
    parse_results = [None] * total

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_idx = {
            ex.submit(parse_segy_header, str(fp)): i
            for i, fp in enumerate(files)
        }
        completed = 0
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            completed += 1
            if progress_callback:
                progress_callback(completed, total * 2,
                                  f"Parsing {files[idx].name}…")
            try:
                parse_results[idx] = {"ok": True, "header": future.result()}
            except Exception as e:
                parse_results[idx] = {"ok": False, "error": str(e)}

    results = []
    for i, (fp, parsed) in enumerate(zip(files, parse_results)):
        if progress_callback:
            progress_callback(total + i + 1, total * 2,
                              f"Cataloguing {fp.name}…")
        if not parsed or not parsed["ok"]:
            results.append({
                "file_name": fp.name, "ok": False,
                "error": parsed["error"] if parsed else "Parse failed",
                "action": ""
            })
            continue
        r = catalog_segy_file(
            engine, str(fp), repository_id,
            source=source, seed_ppdm=seed_ppdm
        )
        r["file_name"] = fp.name
        results.append(r)

    return results


def get_segy_summary(engine) -> dict:
    """Return summary stats for SEG-Y catalog."""
    from sqlalchemy import text
    try:
        with engine.connect() as con:
            row = con.execute(text("""
                SELECT
                    COUNT(*)                        AS file_count,
                    SUM(FILE_SIZE_KB) / 1024.0      AS total_size_mb,
                    COUNT(DISTINCT SURVEY_NAME)     AS survey_count,
                    SUM(CASE WHEN DIMENSIONALITY='3D' THEN 1 ELSE 0 END) AS count_3d,
                    SUM(CASE WHEN DIMENSIONALITY='2D' THEN 1 ELSE 0 END) AS count_2d
                FROM [las_catalog].[SEIS_FILE_CATALOG]
                WHERE FILE_FORMAT = 'SEGY'
            """)).fetchone()
        return {
            "file_count":    row[0] or 0,
            "total_size_mb": round(float(row[1] or 0), 1),
            "survey_count":  row[2] or 0,
            "count_3d":      row[3] or 0,
            "count_2d":      row[4] or 0,
        }
    except Exception:
        return {"file_count": 0, "total_size_mb": 0,
                "survey_count": 0, "count_3d": 0, "count_2d": 0}

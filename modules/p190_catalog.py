"""
modules/p190_catalog.py

P1/90 (UKOAA) seismic positioning file catalog.

Official record layout (Type 1, 80-byte fixed-width ASCII):
  Col 1:     Record type (S/G/Q/A/T/C/V/E/Z for data; H for header; R for receivers)
  Cols 2-13: Line name (A12, left-justified)
  Cols 14-16: Spare
  Col 17:    Vessel ID
  Col 18:    Source ID
  Col 19:    Tailbuoy/Other ID
  Cols 20-25: Point number (A6, right-justified)
  Cols 26-35: Latitude  (I2,I2,F5.2,A1) = DDMMSS.SSN  (10 chars)
  Cols 36-46: Longitude (I3,I2,F5.2,A1) = DDDMMSS.SSE (11 chars)
  Cols 47-55: Easting  (F9.1)
  Cols 56-64: Northing (F9.1)
  Cols 65-70: Water depth (F6.1)
  Cols 71-73: Julian day (I3)
  Cols 74-79: Time HHMMSS (3I2)
  Col 80:    Spare

Header records:
  Col 1:     'H'
  Cols 2-3:  Record type (I2)
  Cols 4-5:  Modifier (I2)
  Cols 6-32: Parameter description (A27)
  Cols 33-80: Parameter data

Key header types:
  H0100: Survey area description
  H0102: Vessel name (cols 33-56)
  H0300: Client name
  H0400: Geophysical contractor
  H1400/H1500: Geodetic datum

Coordinate parsing strategy: use hemisphere letter (N/S/E/W) as anchor,
then apply fixed-width extraction relative to that position. This is robust
to minor variations in how implementors pad the fields.

Reference: UKOAA P1/90 Post Plot Data Exchange Tape, 28 June 1990
"""

from __future__ import annotations
import hashlib, re
from datetime import datetime, timezone
from pathlib import Path


def _make_id(seed: str) -> str:
    n = seed.strip().lower().replace("\\", "/").rstrip("/")
    return hashlib.sha1(n.encode()).hexdigest()[:20].upper()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""): h.update(chunk)
        return h.hexdigest()
    except Exception: return ""


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_lat(line: str, hemi_pos: int) -> float | None:
    """
    Parse latitude using hemisphere char as anchor.
    Format: I2,I2,F5.2,A1 = exactly 10 chars (DDMMSS.SS + N/S).
    hemi_pos is 0-based index of N or S.
    """
    if hemi_pos < 9: return None
    s = line[hemi_pos - 9 : hemi_pos]   # 9 data chars before hemi
    try:
        d   = int(s[0:2])    # degrees  (I2)
        mn  = int(s[2:4])    # minutes  (I2)
        sec = float(s[4:9])  # seconds  (F5.2)
        if 0 <= d <= 90 and 0 <= mn < 60 and 0 <= sec < 60:
            return (1 if line[hemi_pos] == 'N' else -1) * (d + mn/60 + sec/3600)
    except (ValueError, IndexError):
        pass
    return None


def _parse_lon(line: str, hemi_pos: int) -> float | None:
    """
    Parse longitude using hemisphere char as anchor.
    Format: I3,I2,F5.2,A1 = exactly 11 chars (DDDMMSS.SS + E/W).
    hemi_pos is 0-based index of E or W.
    """
    if hemi_pos < 10: return None
    s = line[hemi_pos - 10 : hemi_pos]  # 10 data chars before hemi
    try:
        d   = int(s[0:3])    # degrees  (I3, may have leading space)
        mn  = int(s[3:5])    # minutes  (I2, right-justified, may have leading space)
        sec = float(s[5:10]) # seconds  (F5.2)
        if 0 <= d <= 180 and 0 <= mn < 60 and 0 <= sec < 60:
            return (1 if line[hemi_pos] == 'E' else -1) * (d + mn/60 + sec/3600)
    except (ValueError, IndexError):
        pass
    return None


def _find_coords(line: str) -> tuple[float | None, float | None]:
    """Find lat/lon in a P190 data record by anchoring on hemisphere chars."""
    lat = lon = None
    for i, c in enumerate(line):
        if c in ('N', 'S') and lat is None:
            v = _parse_lat(line, i)
            if v is not None:
                lat = v
                # Longitude field immediately follows lat field (col 36 in spec)
                for j in range(i + 1, min(i + 14, len(line))):
                    if line[j] in ('E', 'W'):
                        v2 = _parse_lon(line, j)
                        if v2 is not None:
                            lon = v2
                            return lat, lon
    return lat, lon


def _safe_float(s: str) -> float | None:
    try:    return float(s.strip())
    except: return None


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


def parse_p190_header(file_path: str, max_data_records: int = 500000) -> dict:
    """
    Parse a P1/90 file and extract catalog metadata.

    Returns dict with survey metadata, bounding box, and shot statistics.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    result = {
        "survey_name":        "",
        "line_name":          "",
        "vessel_name":        "",
        "client_name":        "",
        "contractor_name":    "",
        "nav_system":         "",
        "coord_system":       "",
        "acq_date_start":     "",
        "acq_date_end":       "",
        "first_shot_point":   None,
        "last_shot_point":    None,
        "shot_count":         0,
        "record_count":       0,
        "record_type_counts": {},
        "min_lat": None, "max_lat": None,
        "min_lon": None, "max_lon": None,
        "min_x":   None, "max_x":   None,
        "min_y":   None, "max_y":   None,
        "file_size_kb": round(path.stat().st_size / 1024, 2),
    }

    lats, lons = [], []
    xs,   ys   = [], []
    lines_seen = set()
    data_count = 0

    with open(file_path, "r", encoding="latin-1", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\r\n").ljust(80)
            if not line.strip():
                continue

            rec = line[0].upper()
            result["record_count"] += 1
            result["record_type_counts"][rec] = (
                result["record_type_counts"].get(rec, 0) + 1
            )

            # ── Header records ─────────────────────────────────────────
            if rec == "H":
                h_type = line[1:5].strip()

                # In practice implementors don't always pad the description
                # to 27 chars (cols 6-32). The full content from col 6 onward
                # contains both the label and the value. We strip known labels
                # to isolate the value; fall back to col 33+ for unknown types.
                full = line[5:].rstrip().rstrip("0").strip()

                _LABELS = {
                    "0100": "SURVEY AREA", "0101": "GENERAL SURVEY DETAILS",
                    "0102": "VESSEL DETAILS", "0103": "SOURCE DETAILS",
                    "0104": "STREAMER DETAILS", "0200": "SURVEY DATE",
                    "0201": "TAPE DATE", "0202": "TAPE VERSION",
                    "0300": "CLIENT", "0400": "GEOPHYSICAL CONTACTOR",
                    "0401": "GEOPHYSICAL CONTRACTOR",
                    "0500": "POSITIONING CONTRACTOR",
                    "0600": "POSITIONING PROCESSING",
                    "0700": "POSITIONING SYSTEM",
                    "0800": "SHOTPOINT POSITION",
                    "1000": "CLOCK TIME", "1400": "GEODETIC DATUM SURVEYED",
                    "1401": "TRANSFORMATION PARAMETERS",
                    "1500": "GEODETIC DATUM AS PLOTTED",
                    "1700": "VERTICAL DATUM",
                    "1800": "PROJECTION", "1900": "ZONE",
                    "2200": "CENTRAL MERIDIAN",
                }
                label = _LABELS.get(h_type, "")
                if label and full.upper().startswith(label.upper()):
                    param = full[len(label):].strip()
                else:
                    param = line[32:80].rstrip().rstrip("0").strip() or full

                if h_type == "0100" and param and not result["survey_name"]:
                    result["survey_name"] = param[:60]
                elif h_type == "0101" and param and not result["survey_name"]:
                    result["survey_name"] = param[:60]
                elif h_type.startswith("0102") and not result["vessel_name"]:
                    # Vessel name is up to first digit (IDs follow as integers)
                    import re as _re
                    m = _re.match(r"^([^0-9]+)", param)
                    result["vessel_name"] = m.group(1).strip()[:60] if m else param[:60]
                elif h_type.startswith("0300") and not result["client_name"]:
                    result["client_name"] = param[:60]
                elif h_type.startswith("0400") and not result["contractor_name"]:
                    result["contractor_name"] = param[:60]
                elif h_type.startswith("0700") and not result["nav_system"]:
                    result["nav_system"] = param[:80]
                elif h_type.startswith("0200") and not result["acq_date_start"]:
                    result["acq_date_start"] = param[:30]
                elif h_type in ("1400", "1500") and not result["coord_system"]:
                    result["coord_system"] = param[:80]
                elif h_type.startswith("1800"):
                    result["coord_system"] = (
                        (result["coord_system"] + " " + param).strip()[:80]
                    )

            # ── Data records ────────────────────────────────────────────
            elif rec in ('S', 'V', 'E', 'T', 'A', 'C', 'Q', 'Z', 'G') \
                    and not line.startswith('EOF'):
                if data_count >= max_data_records:
                    continue
                data_count += 1

                # Line name: cols 2-13 (idx 1:13)
                ln = line[1:13].strip()
                if ln:
                    lines_seen.add(ln)
                    if not result["line_name"]:
                        result["line_name"] = ln

                # Find lat/lon using hemisphere char as anchor.
                # In real files the N/S char reliably marks the end of the
                # 10-char lat field. All other fields are offset from there.
                lat = lon = None
                ns_pos = -1
                for ci, ch in enumerate(line):
                    if ch in ('N', 'S') and ci >= 9:
                        v = _parse_lat(line, ci)
                        if v is not None:
                            lat = v
                            ns_pos = ci
                            break

                if ns_pos >= 0:
                    # Lon field follows lat. Scan a small window after N/S
                    # to find E/W (handles optional space between fields).
                    for _j in range(ns_pos + 10, min(ns_pos + 15, len(line))):
                        if line[_j] in ('E', 'W'):
                            _v2 = _parse_lon(line, _j)
                            if _v2 is not None:
                                lon = _v2
                            break

                    # Shot point: 6 chars immediately before lat field
                    sp_start = ns_pos - 15
                    sp_raw = line[sp_start:sp_start+6].strip() if sp_start >= 0 else ""
                    try:
                        sp = float(sp_raw) if sp_raw else None
                    except ValueError:
                        sp = None
                    if sp is not None:
                        if result["first_shot_point"] is None:
                            result["first_shot_point"] = sp
                        result["last_shot_point"] = sp
                        result["shot_count"] += 1

                    # Easting/northing: 9 chars each, starting after lon field
                    e_start = ns_pos + 12  # lon is 11 chars + 1 for ew char
                    e = _safe_float(line[e_start:e_start+9])
                    n_val = _safe_float(line[e_start+9:e_start+18])
                    if e is not None and n_val is not None and abs(e) > 180:
                        xs.append(e)
                        ys.append(n_val)

                if lat is not None and -90 <= lat <= 90:
                    lats.append(lat)
                if lon is not None and -180 <= lon <= 180:
                    lons.append(lon)

    # Auto-detect survey name from header or filename if not found
    if not result["survey_name"]:
        result["survey_name"] = detect_survey_name(
            file_path, result["survey_name"]
        )

    # Bounding boxes
    if lats and lons:
        result["min_lat"] = round(min(lats), 7)
        result["max_lat"] = round(max(lats), 7)
        result["min_lon"] = round(min(lons), 7)
        result["max_lon"] = round(max(lons), 7)
    if xs and ys:
        result["min_x"]   = round(min(xs), 3)
        result["max_x"]   = round(max(xs), 3)
        result["min_y"]   = round(min(ys), 3)
        result["max_y"]   = round(max(ys), 3)

    if len(lines_seen) > 1:
        result["line_name"] = (
            f"{sorted(lines_seen)[0]} … ({len(lines_seen)} lines)"
        )

    return result


# ── Catalog / seed functions (unchanged logic) ─────────────────────────────

def catalog_p190_file(engine, file_path: str, repository_id: str = "",
                      source: str = "SEIS_FILE_CATALOG",
                      seed_ppdm: bool = False) -> dict:
    from sqlalchemy import text
    result = {"ok": False, "action": "", "seis_file_id": "",
              "seeded_ppdm": False, "error": ""}
    path = Path(file_path)
    if not path.exists():
        result["error"] = f"File not found: {file_path}"; return result
    try:
        header = parse_p190_header(file_path)
    except Exception as e:
        result["error"] = f"Parse failed: {e}"; return result

    now          = _now_str()
    seis_file_id = _make_id(file_path)
    file_hash    = _sha256_file(file_path)

    try:
        rel = str(path.absolute())  # default to full path
        if repository_id:
            with engine.connect() as con:
                base = con.execute(text(
                    "SELECT BASE_PATH FROM [las_catalog].[WL_REPOSITORY] "
                    "WHERE REPOSITORY_ID=:id"), {"id": repository_id}).scalar() or ""
            try: rel = str(path.relative_to(base))
            except ValueError: pass  # keep full path
    except Exception: pass

    with engine.connect() as con:
        existing = con.execute(text(
            "SELECT SEIS_FILE_ID FROM [las_catalog].[SEIS_FILE_CATALOG] "
            "WHERE SEIS_FILE_ID=:id"), {"id": seis_file_id}).scalar()
        if not existing and file_hash:
            existing = con.execute(text(
                "SELECT SEIS_FILE_ID FROM [las_catalog].[SEIS_FILE_CATALOG] "
                "WHERE FILE_HASH=:h"), {"h": file_hash}).scalar()
            if existing: seis_file_id = existing

    if existing:
        with engine.begin() as con:
            con.execute(text("""
                UPDATE [las_catalog].[SEIS_FILE_CATALOG]
                SET SURVEY_NAME   = :sv,  LINE_NAME     = :ln,
                    VESSEL_NAME   = :ve,  CLIENT_NAME   = :cl,
                    SHOT_COUNT    = :sh,
                    FIRST_SHOT_POINT = :fsp, LAST_SHOT_POINT = :lsp,
                    MIN_LAT = :mnla, MAX_LAT = :mxla,
                    MIN_LON = :mnlo, MAX_LON = :mxlo,
                    MIN_X   = :mnx,  MAX_X   = :mxx,
                    MIN_Y   = :mny,  MAX_Y   = :mxy,
                    COORD_SYSTEM  = :cs,
                    ROW_CHANGED_DATE = :now,
                    ROW_CHANGED_BY = 'DATA_WRANGLER'
                WHERE SEIS_FILE_ID = :id
            """), {
                "sv": header["survey_name"] or None,
                "ln": header["line_name"]   or None,
                "ve": header["vessel_name"] or None,
                "cl": header["client_name"] or None,
                "sh": header["shot_count"],
                "fsp": header["first_shot_point"],
                "lsp": header["last_shot_point"],
                "mnla": header["min_lat"],  "mxla": header["max_lat"],
                "mnlo": header["min_lon"],  "mxlo": header["max_lon"],
                "mnx":  header["min_x"],    "mxx":  header["max_x"],
                "mny":  header["min_y"],    "mxy":  header["max_y"],
                "cs":   header["coord_system"] or None,
                "now":  now, "id": seis_file_id,
            })
        result.update({"ok": True, "action": "updated",
                       "seis_file_id": seis_file_id}); return result

    set_id = line_id = subid = None
    if seed_ppdm:
        try:
            set_id, line_id, subid = _seed_ppdm_p190(engine, header, source, now)
            result["seeded_ppdm"] = True
        except Exception as e:
            result["error"] = f"PPDM seed failed: {e}"

    row = {
        "SEIS_FILE_ID":     seis_file_id, "REPOSITORY_ID":    repository_id or None,
        "FILE_FORMAT":      "P190",        "FILE_NAME":        rel,
        "FILE_SIZE_KB":     header["file_size_kb"], "FILE_HASH": file_hash,
        "SEIS_SET_ID":      set_id,        "SEIS_LINE_ID":     line_id,
        "SEIS_SET_SUBID":   subid,         "SURVEY_NAME":      header["survey_name"] or None,
        "LINE_NAME":        header["line_name"] or None,
        "VESSEL_NAME":      header["vessel_name"] or None,
        "CLIENT_NAME":      header["client_name"] or None,
        "DIMENSIONALITY":   "2D",          "NAV_SYSTEM":       header["nav_system"] or None,
        "RECORD_COUNT":     header["record_count"],
        "SHOT_COUNT":       header["shot_count"],
        "FIRST_SHOT_POINT": header["first_shot_point"],
        "LAST_SHOT_POINT":  header["last_shot_point"],
        "ACQ_DATE_START":   header["acq_date_start"] or None,
        "ACQ_DATE_END":     header["acq_date_end"] or None,
        "MIN_LAT":  header["min_lat"],  "MAX_LAT":  header["max_lat"],
        "MIN_LON":  header["min_lon"],  "MAX_LON":  header["max_lon"],
        "MIN_X":    header["min_x"],    "MAX_X":    header["max_x"],
        "MIN_Y":    header["min_y"],    "MAX_Y":    header["max_y"],
        "COORD_SYSTEM":     header["coord_system"] or None,
        "CATALOG_DATE":     now,
        "ACTIVE_IND":       "Y", "SOURCE":         source,
        "ROW_CREATED_BY":   "DATA_WRANGLER", "ROW_CREATED_DATE": now,
        "ROW_CHANGED_BY":   "DATA_WRANGLER", "ROW_CHANGED_DATE": now,
    }
    cols = ", ".join(f"[{k}]" for k in row)
    vals = ", ".join(f":{k}" for k in row)
    with engine.begin() as con:
        con.execute(text(
            f"INSERT INTO [las_catalog].[SEIS_FILE_CATALOG] ({cols}) VALUES ({vals})"), row)
        for rt, cnt in header["record_type_counts"].items():
            con.execute(text("""
                INSERT INTO [las_catalog].[SEIS_FILE_HEADER]
                (SEIS_FILE_ID,LINE_NO,HEADER_TEXT,SOURCE,ROW_CREATED_BY,ROW_CREATED_DATE)
                VALUES(:fid,:ln,:txt,:src,'DATA_WRANGLER',:now)"""),
                {"fid": seis_file_id, "ln": ord(rt),
                 "txt": f"Record type '{rt}': {cnt} records",
                 "src": source, "now": now})

    result.update({"ok": True, "action": "inserted",
                   "seis_file_id": seis_file_id}); return result


def _seed_ppdm_p190(engine, header, source, now):
    from sqlalchemy import text
    with engine.connect() as con:
        for t in ("SEIS_SET","SEIS_LINE"):
            if not con.execute(text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=:t"),{"t":t}).scalar():
                raise RuntimeError(f"dbo.{t} does not exist.")
    sv = header["survey_name"] or "UNKNOWN"
    ln = header["line_name"]   or "UNKNOWN"
    sid  = _make_id(f"P190|{sv}")
    lid  = _make_id(f"P190|{sv}|{ln}")
    sub  = "PPDM"
    with engine.begin() as con:
        if not con.execute(text("SELECT SEIS_SET_ID FROM dbo.SEIS_SET WHERE SEIS_SET_ID=:id"),
                           {"id":sid}).scalar():
            con.execute(text("""INSERT INTO dbo.SEIS_SET
                (SEIS_SET_ID,SEIS_SET_SUBID,SEIS_SET_NAME,SEIS_TYPE,ACTIVE_IND,SOURCE,
                 ROW_CREATED_BY,ROW_CREATED_DATE,ROW_CHANGED_BY,ROW_CHANGED_DATE)
                VALUES(:id,:sub,:nm,'2D','Y',:src,'DATA_WRANGLER',:now,'DATA_WRANGLER',:now)"""),
                {"id":sid,"sub":sub,"nm":sv[:255],"src":source,"now":now})
        if not con.execute(text("SELECT SEIS_LINE_ID FROM dbo.SEIS_LINE WHERE SEIS_LINE_ID=:id"),
                           {"id":lid}).scalar():
            con.execute(text("""INSERT INTO dbo.SEIS_LINE
                (SEIS_LINE_ID,SEIS_SET_ID,SEIS_SET_SUBID,SEIS_LINE_NAME,ACTIVE_IND,SOURCE,
                 ROW_CREATED_BY,ROW_CREATED_DATE,ROW_CHANGED_BY,ROW_CHANGED_DATE)
                VALUES(:lid,:sid,:sub,:nm,'Y',:src,'DATA_WRANGLER',:now,'DATA_WRANGLER',:now)"""),
                {"lid":lid,"sid":sid,"sub":sub,"nm":ln[:255],"src":source,"now":now})
    return sid, lid, sub


def catalog_p190_directory(engine, folder: str, repository_id: str = "",
                            source: str = "SEIS_FILE_CATALOG", seed_ppdm: bool = False,
                            max_workers: int = None, progress_callback=None) -> list[dict]:
    import concurrent.futures, os
    if max_workers is None:
        max_workers = min(max((os.cpu_count() or 4) - 2, 2), 12)
    fp = Path(folder)
    if not fp.is_dir(): raise FileNotFoundError(f"Directory not found: {folder}")
    _exts = {".p190", ".p90", ".p1"}
    files = sorted(f for f in fp.iterdir() if f.is_file() and f.suffix.lower() in _exts)
    if not files: return []
    total = len(files)
    parsed = [None] * total
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        fmap = {ex.submit(parse_p190_header, str(f)): i for i, f in enumerate(files)}
        done = 0
        for fut in concurrent.futures.as_completed(fmap):
            idx = fmap[fut]; done += 1
            if progress_callback: progress_callback(done, total*2, f"Parsing {files[idx].name}…")
            try:    parsed[idx] = {"ok": True,  "header": fut.result()}
            except Exception as e: parsed[idx] = {"ok": False, "error": str(e)}
    results = []
    for i, (f, p) in enumerate(zip(files, parsed)):
        if progress_callback: progress_callback(total+i+1, total*2, f"Cataloguing {f.name}…")
        if not p or not p["ok"]:
            results.append({"file_name": f.name, "ok": False,
                             "error": p["error"] if p else "Parse failed", "action": ""})
            continue
        r = catalog_p190_file(engine, str(f), repository_id, source=source, seed_ppdm=seed_ppdm)
        r["file_name"] = f.name; results.append(r)
    return results


def get_p190_summary(engine) -> dict:
    from sqlalchemy import text
    try:
        with engine.connect() as con:
            r = con.execute(text("""
                SELECT COUNT(*), SUM(FILE_SIZE_KB)/1024.0,
                       COUNT(DISTINCT SURVEY_NAME), SUM(SHOT_COUNT)
                FROM [las_catalog].[SEIS_FILE_CATALOG] WHERE FILE_FORMAT='P190'""")).fetchone()
        return {"file_count": r[0] or 0, "total_size_mb": round(float(r[1] or 0),1),
                "survey_count": r[2] or 0, "total_shots": r[3] or 0}
    except Exception:
        return {"file_count":0,"total_size_mb":0,"survey_count":0,"total_shots":0}

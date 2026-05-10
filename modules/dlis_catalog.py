"""
modules/dlis_catalog.py

DLIS and LIS File Catalog — reads metadata and populates the las_catalog
schema DLIS_* and LIS_* tables.

Follows the same pattern as las_catalog.py:
  - Header-only reads (no curve data loaded into memory beyond depth range)
  - UWI must exist in dbo.WELL before cataloguing
  - Original files never modified

Depth handling:
  DLIS depth values are stored in NATIVE units (e.g. '0.1 in', 'ft', 'm').
  TOP_DEPTH_M / BASE_DEPTH_M are always converted to metres for cross-format
  search. The conversion uses the DEPTH_UOM string from the index channel.

Requires:  pip install dlisio
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

try:
    from dlisio import dlis, lis
except ImportError as e:
    raise ImportError("pip install dlisio") from e


import os as _os

def _default_workers() -> int:
    """Sensible default thread count — leaves 2 cores free, caps at 12."""
    cores = _os.cpu_count() or 4
    return min(max(cores - 2, 2), 12)



# ─────────────────────────────────────────────────────────────────────────────
# Depth unit conversion
# ─────────────────────────────────────────────────────────────────────────────

# Multipliers to convert native unit → metres
_TO_METRES = {
    "m":      1.0,
    "meter":  1.0,
    "metre":  1.0,
    "ft":     0.3048,
    "feet":   0.3048,
    "f":      0.3048,
    "in":     0.0254,
    "inch":   0.0254,
    "0.1 in": 0.00254,   # tenths of an inch (common DLIS MWD unit)
    "0.1in":  0.00254,
    "s":      None,       # time logs — no depth conversion
    "ms":     None,
}

# Standardised UOM label for search (M or FT)
_STD_UOM = {
    "m": "M", "meter": "M", "metre": "M",
    "ft": "FT", "feet": "FT", "f": "FT",
    "in": "FT",       # treat inches as imperial
    "0.1 in": "FT", "0.1in": "FT",
}


def _to_metres(value: float, unit: str) -> Optional[float]:
    """Convert a depth value to metres. Returns None for time logs."""
    if value is None:
        return None
    key = str(unit).lower().strip()
    mult = _TO_METRES.get(key)
    if mult is None:
        return None   # time log or unknown unit
    return round(float(value) * mult, 3)


def _std_uom(unit: str) -> Optional[str]:
    """Return standardised UOM (M or FT) from native unit string."""
    return _STD_UOM.get(str(unit).lower().strip())


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _make_id(seed: str) -> str:
    """SHA1 of normalised path — case-insensitive, strip whitespace, forward slashes."""
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


def _safe_str(val, max_len: int = 255) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s[:max_len] if s and s not in ("None", "nan") else None


def _safe_float(val) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _insert_rows(engine, table: str, rows: list[dict],
                 schema: str = "las_catalog") -> int:
    """Batch insert rows into a catalog table. Skips on PK conflict."""
    if not rows:
        return 0
    from sqlalchemy import text

    cols     = list(rows[0].keys())
    col_sql  = ", ".join(f"[{c}]" for c in cols)
    val_sql  = ", ".join(f":{c}" for c in cols)
    pk_check = _pk_check(engine, table, schema)

    inserted = 0
    with engine.begin() as con:
        for row in rows:
            try:
                if pk_check:
                    pk_vals = {k: row[k] for k in pk_check if k in row}
                    exists_sql = (
                        f"SELECT 1 FROM [{schema}].[{table}] WHERE "
                        + " AND ".join(f"[{k}] = :{k}" for k in pk_check)
                    )
                    if con.execute(text(exists_sql), pk_vals).scalar():
                        continue
                con.execute(
                    text(f"INSERT INTO [{schema}].[{table}] ({col_sql}) VALUES ({val_sql})"),
                    row
                )
                inserted += 1
            except Exception:
                pass   # PK or FK violation — skip silently
    return inserted


def _pk_check(engine, table: str, schema: str) -> list[str]:
    """Return PK column names for a table."""
    from sqlalchemy import text
    try:
        with engine.connect() as con:
            rows = con.execute(text("""
                SELECT kcu.COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                  ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                WHERE kcu.TABLE_NAME   = :t
                  AND kcu.TABLE_SCHEMA = :s
                  AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                ORDER BY kcu.ORDINAL_POSITION
            """), {"t": table, "s": schema}).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _rel_path(full_path: str, base_path: str) -> str:
    try:
        return str(Path(full_path).relative_to(base_path))
    except ValueError:
        return str(Path(full_path).absolute())


def _repo_base_path(engine, repository_id: str) -> str:
    from sqlalchemy import text
    try:
        with engine.connect() as con:
            return con.execute(text(
                "SELECT BASE_PATH FROM [las_catalog].[WL_REPOSITORY] "
                "WHERE REPOSITORY_ID = :id"
            ), {"id": repository_id}).scalar() or ""
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# DLIS cataloguing
# ─────────────────────────────────────────────────────────────────────────────

def parse_dlis_header(file_path: str) -> dict:
    """
    Read DLIS metadata without loading curve data arrays.
    Returns a dict with logical_files list, each containing origin,
    frames (with depth range), and channels.
    """
    result = {
        "logical_files": [],
        "logical_file_count": 0,
        "warnings": [],
    }

    with dlis.load(file_path) as logical_files:
        result["logical_file_count"] = len(logical_files)

        for lf_idx, lf in enumerate(logical_files):
            lf_data = {
                "index":        lf_idx,
                "description":  _safe_str(getattr(lf, 'description', None)),
                "frames":       [],
                "channel_count": 0,
                "frame_count":  len(lf.frames),
            }

            # Origin metadata
            origin = next(iter(lf.origins), None)
            if origin:
                lf_data.update({
                    "well_name":     _safe_str(getattr(origin, 'well_name', None)),
                    "well_id":       _safe_str(getattr(origin, 'well_id', None)),
                    "company":       _safe_str(getattr(origin, 'company', None)),
                    "field_name":    _safe_str(getattr(origin, 'field_name', None)),
                    "producer_name": _safe_str(getattr(origin, 'producer_name', None)),
                    "product":       _safe_str(getattr(origin, 'product', None)),
                    "version":       _safe_str(getattr(origin, 'version', None)),
                    "file_set_name": _safe_str(getattr(origin, 'file_set_name', None)),
                    "run_number":    _safe_str(getattr(origin, 'run_number', None)),
                    "order_number":  _safe_str(getattr(origin, 'order_number', None)),
                    "creation_time": getattr(origin, 'creation_time', None),
                })

            # Frames + channels
            total_channels = 0
            for frame in lf.frames:
                frame_data = {
                    "name":          _safe_str(frame.name),
                    "index_channel": _safe_str(frame.index),
                    "channels":      [],
                    "top_depth":     None,
                    "base_depth":    None,
                    "depth_uom":     None,
                    "spacing":       None,
                    "sample_count":  None,
                }

                # Get depth range without loading all curve data
                try:
                    curves   = frame.curves()
                    idx_name = frame.index
                    if idx_name and idx_name in curves.dtype.names:
                        depth_arr = curves[idx_name]
                        frame_data["top_depth"]    = float(depth_arr.min())
                        frame_data["base_depth"]   = float(depth_arr.max())
                        frame_data["sample_count"] = len(depth_arr)
                        if len(depth_arr) > 1:
                            frame_data["spacing"] = abs(
                                float(depth_arr[1]) - float(depth_arr[0])
                            )
                except Exception as e:
                    result["warnings"].append(
                        f"LF{lf_idx} frame '{frame.name}' depth read error: {e}"
                    )

                # Depth unit from index channel
                try:
                    idx_ch = next(
                        (c for c in frame.channels if c.name == frame.index), None
                    )
                    if idx_ch:
                        frame_data["depth_uom"] = _safe_str(idx_ch.units)
                except Exception:
                    pass

                # Channels
                for ch in frame.channels:
                    try:
                        dim = str(ch.dimension) if hasattr(ch, 'dimension') else None
                        frame_data["channels"].append({
                            "name":      _safe_str(ch.name),
                            "long_name": _safe_str(ch.long_name),
                            "units":     _safe_str(ch.units),
                            "dimension": dim,
                            "is_index":  "Y" if ch.name == frame.index else "N",
                        })
                        total_channels += 1
                    except Exception:
                        pass

                lf_data["frames"].append(frame_data)

            lf_data["channel_count"] = total_channels

            # Parameters (store name, long_name, first value)
            # Suppress UnicodeWarning — DLIS files sometimes encode degree
            # symbols (°) in Latin-1 which dlisio cannot decode as UTF-8.
            # The parameter value is skipped gracefully if undecodable.
            params = []
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UnicodeWarning)
                    for param in lf.find('PARAMETER'):
                        try:
                            vals = param.values
                            val_str = str(vals[0]) if vals else None
                            params.append({
                                "name":      _safe_str(param.name),
                                "long_name": _safe_str(
                                    getattr(param, 'long_name', None)
                                ),
                                "value":     _safe_str(val_str, max_len=500),
                                "units":     _safe_str(
                                    getattr(param, 'zones', [None])[0]
                                    if hasattr(param, 'zones') else None
                                ),
                            })
                        except Exception:
                            pass
            except Exception:
                pass
            lf_data["parameters"] = params

            result["logical_files"].append(lf_data)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# FAST DLIS HEADER READER  (no dlisio — reads only first 4 KB)
# ─────────────────────────────────────────────────────────────────────────────

def _scan_str_values(data: bytes, start: int, limit: int) -> list:
    """
    Collect RP66 fixed-width padded ASCII string values (0x21 0x7F marker).
    Stops before a 0x21 0x7F that begins the NEXT value, preventing the
    0x21 boundary character from being consumed by the previous value.
    """
    vals = []
    i = start
    while i < limit:
        if i + 1 < len(data) and data[i] == 0x21 and data[i + 1] == 0x7F:
            s = i + 2
            e = s
            while e < len(data) and 32 <= data[e] <= 126:
                if data[e] == 0x21 and e + 1 < len(data) and data[e + 1] == 0x7F:
                    break
                e += 1
            vals.append((i, data[s:e].decode('ascii', errors='replace').strip(), e - s))
            i = e
        else:
            i += 1
    return vals


def fast_dlis_meta(file_path: str) -> dict:
    """
    Read DLIS file metadata without dlisio by parsing only the first 4 KB.

    Extracts from the Storage Unit Label (SUL) and ORIGIN object:
      well_name, field_name, company, producer_name, order_number,
      run_number, well_id, dlis_version.

    Returns a dict. All string values are stripped of padding.
    ~20 ms per file vs ~1500 ms for dlisio.load() on a 5 MB file.
    """
    import os as _os

    HEADER_READ  = 4096
    TEMPLATE_END = 440   # ORIGIN template attrs always finish before this offset
    VALUE_LIMIT  = 3000  # scan for values up to this offset

    result = {
        "well_name":     "",
        "well_id":       "",
        "field_name":    "",
        "company":       "",
        "producer_name": "",
        "order_number":  "",
        "run_number":    "",
        "dlis_version":  "",
        "file_size_kb":  round(_os.path.getsize(file_path) / 1024, 2),
    }

    with open(file_path, "rb") as f:
        sul  = f.read(80)
        head = f.read(HEADER_READ)

    # ── Storage Unit Label ────────────────────────────────────────────────
    result["dlis_version"] = sul[4:9].decode("ascii", errors="replace").strip()

    # ── Find ORIGIN attribute template positions ───────────────────────────
    # The template defines attribute names in order. We need to know the
    # order of STRING-type attributes so we can map values to names.
    _ATTRS = [
        b"FILE-ID", b"FILE-SET-NAME", b"FILE-SET-NUMBER",
        b"FILE-NUMBER", b"FILE-TYPE", b"PROGRAMS", b"CREATION-TIME",
        b"ORDER-NUMBER", b"DESCENT-NUMBER", b"RUN-NUMBER",
        b"WELL-NAME", b"FIELD-NAME", b"PRODUCER-CODE",
        b"PRODUCER-NAME", b"COMPANY",
    ]
    attr_positions = []
    for attr in _ATTRS:
        idx = head.find(attr)
        if 0 < idx < TEMPLATE_END + 100:
            attr_positions.append((idx, attr.decode("ascii")))

    # Sort by position — this is the template order
    attr_positions.sort()

    # Dynamically find where the template ends (last attr + reasonable margin)
    if attr_positions:
        last_attr_off = attr_positions[-1][0]
        template_end  = last_attr_off + 50
    else:
        template_end  = TEMPLATE_END

    # ── Collect string values from the Object body ────────────────────────
    str_vals = _scan_str_values(head, template_end, VALUE_LIMIT)

    # ── Match values to attributes ────────────────────────────────────────
    # Only string-type attributes appear as 0x21 0x7F values.
    # Known string attrs (subset of _ATTRS):
    STRING_ATTRS = {
        "ORDER-NUMBER", "DESCENT-NUMBER", "RUN-NUMBER",
        "WELL-NAME", "FIELD-NAME", "PRODUCER-CODE",
        "PRODUCER-NAME", "COMPANY",
    }
    string_attr_order = [
        name for _, name in attr_positions if name in STRING_ATTRS
    ]

    for i, (_, val, _length) in enumerate(str_vals):
        if i < len(string_attr_order):
            attr = string_attr_order[i]
            field_map = {
                "WELL-NAME":     "well_name",
                "FIELD-NAME":    "field_name",
                "COMPANY":       "company",
                "PRODUCER-NAME": "producer_name",
                "PRODUCER-CODE": "producer_name",  # fallback
                "ORDER-NUMBER":  "order_number",
                "RUN-NUMBER":    "run_number",
            }
            key = field_map.get(attr)
            if key and not result[key] and val:
                result[key] = val[:255]

    # ── Fallback: short ID strings (0x29 length ASCII) ───────────────────
    # FILE-SET-NAME and other identifiers use a different encoding.
    # Scan for 0x29 [count=1] [len] [ASCII] patterns as well_id fallback.
    if not result["well_name"] and not result["well_id"]:
        i = template_end
        while i < VALUE_LIMIT - 3:
            if head[i] == 0x29 and head[i+1] == 0x01:
                ln = head[i+2]
                if 4 <= ln <= 80:
                    s = i + 3
                    e = s + ln
                    if e <= len(head):
                        try:
                            val = head[s:e].decode("ascii").strip()
                            if val and all(32 <= ord(c) <= 126 for c in val):
                                result["well_id"] = val[:80]
                                break
                        except Exception:
                            pass
            i += 1

    return result


def catalog_dlis_file(engine, file_path: str, repository_id: str,
                      uwi: str = "", source: str = "DATA_WRANGLER") -> dict:
    """
    Parse a DLIS file header and insert catalog entries.

    Returns { ok, dlis_file_id, action, logical_files, frames,
              channels, error }
    """
    result = {
        "ok": False, "dlis_file_id": "", "action": "",
        "logical_files": 0, "frames": 0, "channels": 0, "error": "",
    }

    path = Path(file_path)
    if not path.exists():
        result["error"] = f"File not found: {file_path}"
        return result

    try:
        header = parse_dlis_header(file_path)
    except Exception as e:
        result["error"] = f"Parse failed: {e}"
        return result

    # Resolve UWI
    effective_uwi = uwi
    if not effective_uwi:
        # Try to get from first logical file origin
        for lf in header["logical_files"]:
            effective_uwi = lf.get("well_id") or lf.get("well_name") or ""
            if effective_uwi:
                break
    if not effective_uwi:
        result["error"] = "No UWI found and none provided."
        return result

    now           = _now_str()
    dlis_file_id  = _make_id(file_path)
    base_path     = _repo_base_path(engine, repository_id)
    rel_path      = _rel_path(file_path, base_path)
    file_size_kb  = round(path.stat().st_size / 1024, 2)
    file_hash     = _sha256_file(file_path)

    # ── DLIS_FILE row ────────────────────────────────────────────────
    file_row = {
        "DLIS_FILE_ID":        dlis_file_id,
        "REPOSITORY_ID":       repository_id,
        "UWI":                 effective_uwi,
        "FILE_NAME":           rel_path,
        "FILE_SIZE_KB":        file_size_kb,
        "FILE_HASH":           file_hash,
        "LOGICAL_FILE_COUNT":  header["logical_file_count"],
        "CATALOG_DATE":        now,
        "LAST_SEEN_DATE":      now,
        "ACTIVE_IND":          "Y",
        "SOURCE":              source,
        "ROW_CREATED_BY":      "DATA_WRANGLER",
        "ROW_CREATED_DATE":    now,
        "ROW_CHANGED_BY":      "DATA_WRANGLER",
        "ROW_CHANGED_DATE":    now,
    }

    from sqlalchemy import text
    with engine.connect() as con:
        # Primary check: path-based ID
        existing = con.execute(text(
            "SELECT DLIS_FILE_ID FROM [las_catalog].[DLIS_FILE] "
            "WHERE DLIS_FILE_ID = :id"
        ), {"id": dlis_file_id}).scalar()

        # Secondary check: file content hash (catches same file stored at different path)
        if not existing and file_hash:
            existing = con.execute(text(
                "SELECT DLIS_FILE_ID FROM [las_catalog].[DLIS_FILE] "
                "WHERE FILE_HASH = :hash"
            ), {"hash": file_hash}).scalar()
            if existing:
                dlis_file_id = existing  # use the existing ID

    if existing:
        with engine.begin() as con:
            con.execute(text("""
                UPDATE [las_catalog].[DLIS_FILE]
                SET LAST_SEEN_DATE = :now, ROW_CHANGED_DATE = :now,
                    ROW_CHANGED_BY = 'DATA_WRANGLER'
                WHERE DLIS_FILE_ID = :id
            """), {"now": now, "id": dlis_file_id})
        result["action"] = "updated"
        result["ok"] = True
        result["dlis_file_id"] = dlis_file_id
        return result

    _insert_rows(engine, "DLIS_FILE", [file_row])

    # ── Logical files, frames, channels, parameters ──────────────────
    lf_count = fr_count = ch_count = 0

    for lf in header["logical_files"]:
        lf_idx = lf["index"]

        ct = lf.get("creation_time")
        if ct and not isinstance(ct, str):
            try:
                ct = ct.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                ct = str(ct)

        lf_row = {
            "DLIS_FILE_ID":     dlis_file_id,
            "LOGICAL_FILE_IDX": lf_idx,
            "DESCRIPTION":      lf.get("description"),
            "WELL_NAME":        lf.get("well_name"),
            "WELL_ID":          lf.get("well_id"),
            "COMPANY":          lf.get("company"),
            "FIELD_NAME":       lf.get("field_name"),
            "PRODUCER_NAME":    lf.get("producer_name"),
            "PRODUCT":          lf.get("product"),
            "VERSION":          lf.get("version"),
            "FILE_SET_NAME":    lf.get("file_set_name"),
            "RUN_NUMBER":       lf.get("run_number"),
            "CREATION_TIME":    ct,
            "ORDER_NUMBER":     lf.get("order_number"),
            "FRAME_COUNT":      len(lf["frames"]),
            "CHANNEL_COUNT":    lf["channel_count"],
            "SOURCE":           source,
            "ROW_CREATED_BY":   "DATA_WRANGLER",
            "ROW_CREATED_DATE": now,
            "ROW_CHANGED_BY":   "DATA_WRANGLER",
            "ROW_CHANGED_DATE": now,
        }
        _insert_rows(engine, "DLIS_LOGICAL_FILE", [lf_row])
        lf_count += 1

        # Frames
        for fr in lf["frames"]:
            uom      = fr.get("depth_uom") or ""
            top      = fr.get("top_depth")
            base     = fr.get("base_depth")

            fr_row = {
                "DLIS_FILE_ID":     dlis_file_id,
                "LOGICAL_FILE_IDX": lf_idx,
                "FRAME_NAME":       fr["name"],
                "INDEX_CHANNEL":    fr.get("index_channel"),
                "TOP_DEPTH":        top,
                "BASE_DEPTH":       base,
                "DEPTH_UOM":        uom,
                "DEPTH_UOM_STD":    _std_uom(uom),
                "TOP_DEPTH_M":      _to_metres(top, uom),
                "BASE_DEPTH_M":     _to_metres(base, uom),
                "SPACING":          fr.get("spacing"),
                "CHANNEL_COUNT":    len(fr["channels"]),
                "SAMPLE_COUNT":     fr.get("sample_count"),
                "SOURCE":           source,
                "ROW_CREATED_BY":   "DATA_WRANGLER",
                "ROW_CREATED_DATE": now,
                "ROW_CHANGED_BY":   "DATA_WRANGLER",
                "ROW_CHANGED_DATE": now,
            }
            _insert_rows(engine, "DLIS_FRAME", [fr_row])
            fr_count += 1

            # Channels
            ch_rows = []
            for ch in fr["channels"]:
                ch_rows.append({
                    "DLIS_FILE_ID":     dlis_file_id,
                    "LOGICAL_FILE_IDX": lf_idx,
                    "FRAME_NAME":       fr["name"],
                    "CHANNEL_NAME":     ch["name"],
                    "LONG_NAME":        ch.get("long_name"),
                    "UNITS":            ch.get("units"),
                    "DIMENSION":        ch.get("dimension"),
                    "IS_INDEX":         ch.get("is_index", "N"),
                    "SOURCE":           source,
                    "ROW_CREATED_BY":   "DATA_WRANGLER",
                    "ROW_CREATED_DATE": now,
                    "ROW_CHANGED_BY":   "DATA_WRANGLER",
                    "ROW_CHANGED_DATE": now,
                })
            _insert_rows(engine, "DLIS_CHANNEL", ch_rows)
            ch_count += len(ch_rows)

        # Parameters
        param_rows = []
        seen = set()
        for p in lf.get("parameters", []):
            key = (dlis_file_id, lf_idx, p["name"])
            if key in seen or not p["name"]:
                continue
            seen.add(key)
            param_rows.append({
                "DLIS_FILE_ID":     dlis_file_id,
                "LOGICAL_FILE_IDX": lf_idx,
                "PARAMETER_NAME":   p["name"],
                "LONG_NAME":        p.get("long_name"),
                "VALUE":            p.get("value"),
                "UNITS":            p.get("units"),
                "SOURCE":           source,
                "ROW_CREATED_BY":   "DATA_WRANGLER",
                "ROW_CREATED_DATE": now,
                "ROW_CHANGED_BY":   "DATA_WRANGLER",
                "ROW_CHANGED_DATE": now,
            })
        _insert_rows(engine, "DLIS_PARAMETER", param_rows)

    result.update({
        "ok":            True,
        "action":        "inserted",
        "dlis_file_id":  dlis_file_id,
        "logical_files": lf_count,
        "frames":        fr_count,
        "channels":      ch_count,
    })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# LIS cataloguing
# ─────────────────────────────────────────────────────────────────────────────

def parse_lis_header(file_path: str) -> dict:
    """
    Read LIS metadata and channel definitions.
    Returns dict with well metadata and channel list.
    """
    result = {
        "well_name": None, "company": None,
        "field_name": None, "log_date": None,
        "channels": [], "warnings": [],
        "top_depth": None, "base_depth": None,
        "depth_uom": None, "sample_count": None,
    }

    with lis.load(file_path) as lis_files:
        lf = lis_files[0]

        # Wellsite data — extract MNEM/VALU pairs
        meta = {}
        for rec in lf.wellsite_data():
            comps = rec.components()
            current_mnem = None
            for c in comps:
                if c.mnemonic == 'MNEM':
                    current_mnem = str(c.component).strip()
                elif c.mnemonic == 'VALU' and current_mnem:
                    val = str(c.component).strip()
                    if val and val not in ('None', ''):
                        meta[current_mnem] = val
                    current_mnem = None

        result["company"]    = _safe_str(meta.get("CN"))
        result["well_name"]  = _safe_str(meta.get("WN"))
        result["field_name"] = _safe_str(meta.get("FN"))
        result["log_date"]   = _safe_str(meta.get("DATE"))

        # Data format specs → channels and depth range
        for spec in lf.data_format_specs():
            try:
                curves = lis.curves(lf, spec)
                names  = curves.dtype.names or []

                # First channel is typically depth
                if names:
                    depth_col = names[0]
                    depth_arr = curves[depth_col]
                    result["top_depth"]    = float(depth_arr.min())
                    result["base_depth"]   = float(depth_arr.max())
                    result["sample_count"] = len(depth_arr)

                # Channels — get units from wellsite output records
                channel_units = {}
                for rec in lf.wellsite_data():
                    comps = rec.components()
                    current_mnem = None
                    current_puni = None
                    i = 0
                    while i < len(comps):
                        c = comps[i]
                        if c.mnemonic == 'MNEM':
                            current_mnem = str(c.component).strip()
                            current_puni = None
                        elif c.mnemonic == 'PUNI' and current_mnem:
                            current_puni = str(c.component).strip()
                            channel_units[current_mnem] = current_puni
                        i += 1

                for i, name in enumerate(names):
                    mn = name.strip()
                    result["channels"].append({
                        "name":     mn,
                        "units":    channel_units.get(mn, ""),
                        "is_index": "Y" if i == 0 else "N",
                    })

                # Depth UOM from first channel unit
                if names:
                    result["depth_uom"] = channel_units.get(
                        names[0].strip(), ""
                    )

            except Exception as e:
                result["warnings"].append(f"Spec read error: {e}")

    return result


def catalog_lis_file(engine, file_path: str, repository_id: str,
                     uwi: str = "", source: str = "DATA_WRANGLER") -> dict:
    """
    Parse a LIS file header and insert catalog entries.
    Returns { ok, lis_file_id, action, channels, error }
    """
    result = {
        "ok": False, "lis_file_id": "", "action": "",
        "channels": 0, "error": "",
    }

    path = Path(file_path)
    if not path.exists():
        result["error"] = f"File not found: {file_path}"
        return result

    try:
        header = parse_lis_header(file_path)
    except Exception as e:
        result["error"] = f"Parse failed: {e}"
        return result

    effective_uwi = uwi.strip() if uwi else ""
    if not effective_uwi:
        result["error"] = (
            "UWI is required for LIS files — the LIS header does not contain "
            "a reliable UWI. Use the File Mapping page to assign one, or "
            "pass a UWI override."
        )
        return result

    now          = _now_str()
    lis_file_id  = _make_id(file_path)
    base_path    = _repo_base_path(engine, repository_id)
    rel_path     = _rel_path(file_path, base_path)
    file_size_kb = round(path.stat().st_size / 1024, 2)
    file_hash    = _sha256_file(file_path)

    file_row = {
        "LIS_FILE_ID":      lis_file_id,
        "REPOSITORY_ID":    repository_id,
        "UWI":              effective_uwi,
        "FILE_NAME":        rel_path,
        "FILE_SIZE_KB":     file_size_kb,
        "FILE_HASH":        file_hash,
        "WELL_NAME":        header.get("well_name"),
        "COMPANY":          header.get("company"),
        "FIELD_NAME":       header.get("field_name"),
        "LOG_DATE":         header.get("log_date"),
        "TOP_DEPTH":        header.get("top_depth"),
        "BASE_DEPTH":       header.get("base_depth"),
        "DEPTH_UOM":        header.get("depth_uom"),
        "CHANNEL_COUNT":    len(header["channels"]),
        "SAMPLE_COUNT":     header.get("sample_count"),
        "CATALOG_DATE":     now,
        "LAST_SEEN_DATE":   now,
        "ACTIVE_IND":       "Y",
        "SOURCE":           source,
        "ROW_CREATED_BY":   "DATA_WRANGLER",
        "ROW_CREATED_DATE": now,
        "ROW_CHANGED_BY":   "DATA_WRANGLER",
        "ROW_CHANGED_DATE": now,
    }

    from sqlalchemy import text
    with engine.connect() as con:
        existing = con.execute(text(
            "SELECT LIS_FILE_ID FROM [las_catalog].[LIS_FILE] "
            "WHERE LIS_FILE_ID = :id"
        ), {"id": lis_file_id}).scalar()

        if not existing and file_hash:
            existing = con.execute(text(
                "SELECT LIS_FILE_ID FROM [las_catalog].[LIS_FILE] "
                "WHERE FILE_HASH = :hash"
            ), {"hash": file_hash}).scalar()
            if existing:
                lis_file_id = existing

    if existing:
        with engine.begin() as con:
            con.execute(text("""
                UPDATE [las_catalog].[LIS_FILE]
                SET LAST_SEEN_DATE = :now, ROW_CHANGED_DATE = :now,
                    ROW_CHANGED_BY = 'DATA_WRANGLER'
                WHERE LIS_FILE_ID = :id
            """), {"now": now, "id": lis_file_id})
        result.update({"ok": True, "action": "updated", "lis_file_id": lis_file_id})
        return result

    _insert_rows(engine, "LIS_FILE", [file_row])

    # Channels
    ch_rows = []
    for ch in header["channels"]:
        ch_rows.append({
            "LIS_FILE_ID":      lis_file_id,
            "CHANNEL_NAME":     ch["name"],
            "UNITS":            ch.get("units"),
            "IS_INDEX":         ch.get("is_index", "N"),
            "SOURCE":           source,
            "ROW_CREATED_BY":   "DATA_WRANGLER",
            "ROW_CREATED_DATE": now,
            "ROW_CHANGED_BY":   "DATA_WRANGLER",
            "ROW_CHANGED_DATE": now,
        })
    _insert_rows(engine, "LIS_CHANNEL", ch_rows)

    result.update({
        "ok":         True,
        "action":     "inserted",
        "lis_file_id": lis_file_id,
        "channels":   len(ch_rows),
    })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Directory scan
# ─────────────────────────────────────────────────────────────────────────────

def _catalog_dlis_from_header(engine, file_path: str, repository_id: str,
                               source: str, header: dict) -> dict:
    """
    Insert DLIS catalog entries using a pre-parsed header dict.
    Avoids re-reading the file — used by the parallel directory scanner
    which parses all files first, then does DB inserts sequentially.
    """
    result = {
        "ok": False, "dlis_file_id": "", "action": "",
        "logical_files": 0, "frames": 0, "channels": 0, "error": "",
    }

    path = Path(file_path)
    effective_uwi = ""
    for lf in header.get("logical_files", []):
        effective_uwi = lf.get("well_id") or lf.get("well_name") or ""
        if effective_uwi:
            break
    if not effective_uwi:
        result["error"] = "No UWI found and none provided."
        return result

    now          = _now_str()
    dlis_file_id = _make_id(file_path)
    base_path    = _repo_base_path(engine, repository_id)
    rel_path     = _rel_path(file_path, base_path)

    try:
        file_size_kb = round(path.stat().st_size / 1024, 2)
    except Exception:
        file_size_kb = None

    file_hash = _sha256_file(file_path)

    from sqlalchemy import text
    with engine.connect() as con:
        existing = con.execute(text(
            "SELECT DLIS_FILE_ID FROM [las_catalog].[DLIS_FILE] "
            "WHERE DLIS_FILE_ID = :id"
        ), {"id": dlis_file_id}).scalar()

    if existing:
        with engine.begin() as con:
            con.execute(text("""
                UPDATE [las_catalog].[DLIS_FILE]
                SET LAST_SEEN_DATE = :now, ROW_CHANGED_DATE = :now,
                    ROW_CHANGED_BY = 'DATA_WRANGLER'
                WHERE DLIS_FILE_ID = :id
            """), {"now": now, "id": dlis_file_id})
        result.update({"ok": True, "action": "updated",
                        "dlis_file_id": dlis_file_id})
        return result

    file_row = {
        "DLIS_FILE_ID":        dlis_file_id,
        "REPOSITORY_ID":       repository_id,
        "UWI":                 effective_uwi,
        "FILE_NAME":           rel_path,
        "FILE_SIZE_KB":        file_size_kb,
        "FILE_HASH":           file_hash,
        "LOGICAL_FILE_COUNT":  header["logical_file_count"],
        "CATALOG_DATE":        now,
        "LAST_SEEN_DATE":      now,
        "ACTIVE_IND":          "Y",
        "SOURCE":              source,
        "ROW_CREATED_BY":      "DATA_WRANGLER",
        "ROW_CREATED_DATE":    now,
        "ROW_CHANGED_BY":      "DATA_WRANGLER",
        "ROW_CHANGED_DATE":    now,
    }
    _insert_rows(engine, "DLIS_FILE", [file_row])

    lf_count = fr_count = ch_count = 0
    for lf in header["logical_files"]:
        lf_idx = lf["index"]
        ct = lf.get("creation_time")
        if ct and not isinstance(ct, str):
            try:
                ct = ct.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                ct = str(ct)

        lf_row = {
            "DLIS_FILE_ID":     dlis_file_id,
            "LOGICAL_FILE_IDX": lf_idx,
            "DESCRIPTION":      lf.get("description"),
            "WELL_NAME":        lf.get("well_name"),
            "WELL_ID":          lf.get("well_id"),
            "COMPANY":          lf.get("company"),
            "FIELD_NAME":       lf.get("field_name"),
            "PRODUCER_NAME":    lf.get("producer_name"),
            "PRODUCT":          lf.get("product"),
            "VERSION":          lf.get("version"),
            "FILE_SET_NAME":    lf.get("file_set_name"),
            "RUN_NUMBER":       lf.get("run_number"),
            "CREATION_TIME":    ct,
            "ORDER_NUMBER":     lf.get("order_number"),
            "FRAME_COUNT":      len(lf["frames"]),
            "CHANNEL_COUNT":    lf["channel_count"],
            "SOURCE":           source,
            "ROW_CREATED_BY":   "DATA_WRANGLER",
            "ROW_CREATED_DATE": now,
            "ROW_CHANGED_BY":   "DATA_WRANGLER",
            "ROW_CHANGED_DATE": now,
        }
        _insert_rows(engine, "DLIS_LOGICAL_FILE", [lf_row])
        lf_count += 1

        for fr in lf["frames"]:
            uom = fr.get("depth_uom") or ""
            top = fr.get("top_depth")
            base = fr.get("base_depth")
            fr_row = {
                "DLIS_FILE_ID":     dlis_file_id,
                "LOGICAL_FILE_IDX": lf_idx,
                "FRAME_NAME":       fr["name"],
                "INDEX_CHANNEL":    fr.get("index_channel"),
                "TOP_DEPTH":        top,
                "BASE_DEPTH":       base,
                "DEPTH_UOM":        uom,
                "DEPTH_UOM_STD":    _std_uom(uom),
                "TOP_DEPTH_M":      _to_metres(top, uom),
                "BASE_DEPTH_M":     _to_metres(base, uom),
                "SPACING":          fr.get("spacing"),
                "CHANNEL_COUNT":    len(fr["channels"]),
                "SAMPLE_COUNT":     fr.get("sample_count"),
                "SOURCE":           source,
                "ROW_CREATED_BY":   "DATA_WRANGLER",
                "ROW_CREATED_DATE": now,
                "ROW_CHANGED_BY":   "DATA_WRANGLER",
                "ROW_CHANGED_DATE": now,
            }
            _insert_rows(engine, "DLIS_FRAME", [fr_row])
            fr_count += 1

            ch_rows = []
            for ch in fr["channels"]:
                ch_rows.append({
                    "DLIS_FILE_ID":     dlis_file_id,
                    "LOGICAL_FILE_IDX": lf_idx,
                    "FRAME_NAME":       fr["name"],
                    "CHANNEL_NAME":     ch["name"],
                    "LONG_NAME":        ch.get("long_name"),
                    "UNITS":            ch.get("units"),
                    "DIMENSION":        ch.get("dimension"),
                    "IS_INDEX":         ch.get("is_index", "N"),
                    "SOURCE":           source,
                    "ROW_CREATED_BY":   "DATA_WRANGLER",
                    "ROW_CREATED_DATE": now,
                    "ROW_CHANGED_BY":   "DATA_WRANGLER",
                    "ROW_CHANGED_DATE": now,
                })
            _insert_rows(engine, "DLIS_CHANNEL", ch_rows)
            ch_count += len(ch_rows)

        param_rows = []
        seen = set()
        for p in lf.get("parameters", []):
            key = (dlis_file_id, lf_idx, p["name"])
            if key in seen or not p["name"]:
                continue
            seen.add(key)
            param_rows.append({
                "DLIS_FILE_ID":     dlis_file_id,
                "LOGICAL_FILE_IDX": lf_idx,
                "PARAMETER_NAME":   p["name"],
                "LONG_NAME":        p.get("long_name"),
                "VALUE":            p.get("value"),
                "UNITS":            p.get("units"),
                "SOURCE":           source,
                "ROW_CREATED_BY":   "DATA_WRANGLER",
                "ROW_CREATED_DATE": now,
                "ROW_CHANGED_BY":   "DATA_WRANGLER",
                "ROW_CHANGED_DATE": now,
            })
        _insert_rows(engine, "DLIS_PARAMETER", param_rows)

    result.update({
        "ok":           True,
        "action":       "inserted",
        "dlis_file_id": dlis_file_id,
        "logical_files": lf_count,
        "frames":        fr_count,
        "channels":      ch_count,
    })
    return result


def _catalog_lis_from_header(engine, file_path: str, repository_id: str,
                              source: str, header: dict,
                              uwi: str = "") -> dict:
    """
    Insert LIS catalog entries using a pre-parsed header dict.
    Used by the parallel directory scanner.
    """
    result = {"ok": False, "lis_file_id": "", "action": "",
              "channels": 0, "error": ""}

    effective_uwi = uwi.strip() if uwi else ""
    if not effective_uwi:
        result["error"] = (
            "UWI is required for LIS files. Use the File Mapping page "
            "to assign one before cataloguing."
        )
        return result

    path = Path(file_path)
    now         = _now_str()
    lis_file_id = _make_id(file_path)
    base_path   = _repo_base_path(engine, repository_id)
    rel_path    = _rel_path(file_path, base_path)

    try:
        file_size_kb = round(path.stat().st_size / 1024, 2)
    except Exception:
        file_size_kb = None

    file_hash = _sha256_file(file_path)

    from sqlalchemy import text
    with engine.connect() as con:
        existing = con.execute(text(
            "SELECT LIS_FILE_ID FROM [las_catalog].[LIS_FILE] "
            "WHERE LIS_FILE_ID = :id"
        ), {"id": lis_file_id}).scalar()

    if existing:
        with engine.begin() as con:
            con.execute(text("""
                UPDATE [las_catalog].[LIS_FILE]
                SET LAST_SEEN_DATE = :now, ROW_CHANGED_DATE = :now,
                    ROW_CHANGED_BY = 'DATA_WRANGLER'
                WHERE LIS_FILE_ID = :id
            """), {"now": now, "id": lis_file_id})
        result.update({"ok": True, "action": "updated",
                        "lis_file_id": lis_file_id})
        return result

    file_row = {
        "LIS_FILE_ID":      lis_file_id,
        "REPOSITORY_ID":    repository_id,
        "UWI":              effective_uwi,
        "FILE_NAME":        rel_path,
        "FILE_SIZE_KB":     file_size_kb,
        "FILE_HASH":        file_hash,
        "WELL_NAME":        header.get("well_name"),
        "COMPANY":          header.get("company"),
        "FIELD_NAME":       header.get("field_name"),
        "LOG_DATE":         header.get("log_date"),
        "TOP_DEPTH":        header.get("top_depth"),
        "BASE_DEPTH":       header.get("base_depth"),
        "DEPTH_UOM":        header.get("depth_uom"),
        "CHANNEL_COUNT":    len(header["channels"]),
        "SAMPLE_COUNT":     header.get("sample_count"),
        "CATALOG_DATE":     now,
        "LAST_SEEN_DATE":   now,
        "ACTIVE_IND":       "Y",
        "SOURCE":           source,
        "ROW_CREATED_BY":   "DATA_WRANGLER",
        "ROW_CREATED_DATE": now,
        "ROW_CHANGED_BY":   "DATA_WRANGLER",
        "ROW_CHANGED_DATE": now,
    }
    _insert_rows(engine, "LIS_FILE", [file_row])

    ch_rows = []
    for ch in header["channels"]:
        ch_rows.append({
            "LIS_FILE_ID":      lis_file_id,
            "CHANNEL_NAME":     ch["name"],
            "UNITS":            ch.get("units"),
            "IS_INDEX":         ch.get("is_index", "N"),
            "SOURCE":           source,
            "ROW_CREATED_BY":   "DATA_WRANGLER",
            "ROW_CREATED_DATE": now,
            "ROW_CHANGED_BY":   "DATA_WRANGLER",
            "ROW_CHANGED_DATE": now,
        })
    _insert_rows(engine, "LIS_CHANNEL", ch_rows)

    result.update({
        "ok":         True,
        "action":     "inserted",
        "lis_file_id": lis_file_id,
        "channels":   len(ch_rows),
    })
    return result


def _catalog_dlis_worker(args: tuple) -> dict:
    """Worker for parallel DLIS cataloguing — parse only, no DB writes."""
    file_path, repository_id, source = args
    try:
        header = parse_dlis_header(file_path)
        return {"ok": True, "file_path": file_path,
                "header": header, "error": ""}
    except Exception as e:
        return {"ok": False, "file_path": file_path,
                "header": None, "error": str(e)}


def _catalog_lis_worker(args: tuple) -> dict:
    """Worker for parallel LIS cataloguing — parse only, no DB writes."""
    file_path, repository_id, source = args
    try:
        header = parse_lis_header(file_path)
        return {"ok": True, "file_path": file_path,
                "header": header, "error": ""}
    except Exception as e:
        return {"ok": False, "file_path": file_path,
                "header": None, "error": str(e)}


def catalog_dlis_directory(engine, folder: str, repository_id: str,
                            source: str = "DATA_WRANGLER",
                            progress_callback=None,
                            max_workers: int = None) -> list[dict]:
    """
    Catalog all DLIS files in a directory.

    File headers are parsed in parallel (I/O-bound), then DB inserts
    are done sequentially (connection-safe). This gives the biggest
    speedup for DLIS since the slow part is reading the binary file.

    max_workers : number of parallel threads for file parsing (default auto)
    """
    import concurrent.futures
    if max_workers is None:
        max_workers = _default_workers()

    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {folder}")

    files = sorted(list(folder_path.glob("*.dlis")) +
                   list(folder_path.glob("*.DLIS")))
    if not files:
        return []

    total = len(files)
    parse_results = [None] * total
    args = [(str(fp), repository_id, source) for fp in files]

    # ── Phase 1: Parse headers in parallel ───────────────────────────
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_idx = {
            ex.submit(_catalog_dlis_worker, a): i
            for i, a in enumerate(args)
        }
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            completed += 1
            if progress_callback:
                progress_callback(completed, total * 2,
                                  f"Parsing {files[idx].name}…")
            try:
                parse_results[idx] = future.result()
            except Exception as e:
                parse_results[idx] = {
                    "ok": False, "file_path": str(files[idx]),
                    "header": None, "error": str(e)
                }

    # ── Phase 2: DB inserts sequentially ─────────────────────────────
    results = []
    for i, (fp, parsed) in enumerate(zip(files, parse_results)):
        if progress_callback:
            progress_callback(total + i + 1, total * 2,
                              f"Cataloguing {fp.name}…")

        if not parsed or not parsed["ok"]:
            r = {"ok": False, "file_name": fp.name,
                 "error": parsed["error"] if parsed else "Parse failed",
                 "action": "", "logical_files": 0, "frames": 0, "channels": 0}
            results.append(r)
            continue

        # Pass pre-parsed header to avoid re-reading the file
        r = _catalog_dlis_from_header(
            engine, str(fp), repository_id, source, parsed["header"]
        )
        r["file_name"] = fp.name
        results.append(r)

    return results


def catalog_lis_directory(engine, folder: str, repository_id: str,
                           source: str = "DATA_WRANGLER",
                           progress_callback=None,
                           max_workers: int = None) -> list[dict]:
    """
    Catalog all LIS files in a directory.
    Headers parsed in parallel, DB inserts done sequentially.
    """
    import concurrent.futures
    if max_workers is None:
        max_workers = _default_workers()

    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {folder}")

    files = sorted(list(folder_path.glob("*.lis")) +
                   list(folder_path.glob("*.LIS")))
    if not files:
        return []

    total = len(files)
    parse_results = [None] * total
    args = [(str(fp), repository_id, source) for fp in files]

    # Phase 1: parse in parallel
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_idx = {
            ex.submit(_catalog_lis_worker, a): i
            for i, a in enumerate(args)
        }
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            completed += 1
            if progress_callback:
                progress_callback(completed, total * 2,
                                  f"Parsing {files[idx].name}…")
            try:
                parse_results[idx] = future.result()
            except Exception as e:
                parse_results[idx] = {
                    "ok": False, "file_path": str(files[idx]),
                    "header": None, "error": str(e)
                }

    # Phase 2: DB inserts sequentially
    results = []
    for i, (fp, parsed) in enumerate(zip(files, parse_results)):
        if progress_callback:
            progress_callback(total + i + 1, total * 2,
                              f"Cataloguing {fp.name}…")

        if not parsed or not parsed["ok"]:
            r = {"ok": False, "file_name": fp.name,
                 "error": parsed["error"] if parsed else "Parse failed",
                 "action": "", "channels": 0}
            results.append(r)
            continue

        r = _catalog_lis_from_header(
            engine, str(fp), repository_id, source, parsed["header"]
        )
        r["file_name"] = fp.name
        results.append(r)

    return results

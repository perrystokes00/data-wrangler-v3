"""
gom_dir_srvy_loader.py — BOEM Gulf of America directional survey loader
========================================================================

Reads a BOEM "Azimuth" directional survey export (the directfixed.txt
fixed-width file) and loads it into:
  - dataview_gom.directional_survey_point

One row per survey station. A well's full trajectory is every row
sharing an api_well_number, ordered by survey_point_md.

Architecture
------------
- Pure Python (no Streamlit), so the loader can also run from a terminal
  script or batch job. Mirrors gom_well_loader.py's structure.
- The BOEM Azimuth file is HEADERLESS FIXED-WIDTH — not delimited — so
  this module has its own fixed-width parser (_open_fixed_width_rows)
  rather than reusing the well loader's csv-based opener.
- Reads in chunks (default 5,000 rows) and writes via batched
  executemany MERGE. fast_executemany=True on the engine packs each
  chunk into one round-trip.
- Idempotent: the MERGE targets the natural key
  (api_well_number, survey_point_md), so re-running the same file
  updates rows in place rather than duplicating stations.
- api_well_number is stored RAW. well_id resolution (the join to
  dataview_gom.well) is a SEPARATE follow-up pass, not done here — so
  surveys for APIs not yet in dataview_gom.well still load cleanly.
- Tolerant: per-row parse errors are logged and the row skipped; the
  batch continues. A summary dict reports counts.

Confirmed fixed-width layout (BOEM Azimuth format, 115-char records)
--------------------------------------------------------------------
    Field             Cols (0-idx)   Width
    api_well_number   0  - 12        12
    survey_point_md   12 - 22        10
    incl_ang          22 - 31         9
    azimuth           31 - 41        10
    survey_point_tvd  41 - 50         9
    latitude          50 - 68        18
    longitude         68 - 86        18
    last_update       86 - 115       29   (MM/DD/YYYY, right-padded)

Usage
-----
    from modules.gom_dir_srvy_loader import load_gom_dir_srvy
    stats = load_gom_dir_srvy(
        engine=engine,
        file_path=r"C:\\...\\GOM\\dir_srvy_pts\\directfixed.txt",
        chunk_size=5000,
        progress_callback=lambda done, total, msg: print(f"{done}/{total} {msg}"),
    )
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import text


# ── Fixed-width layout ───────────────────────────────────────────────────────
# (field_name, start_col, end_col) — 0-indexed, end exclusive. Confirmed
# by inspecting real records from directfixed.txt; every record is 115
# chars. Fields are right-justified within their width; we slice then
# strip.
COLSPECS = [
    ("api_well_number",  0,  12),
    ("survey_point_md",  12, 22),
    ("incl_ang",         22, 31),
    ("azimuth",          31, 41),
    ("survey_point_tvd", 41, 50),
    ("latitude",         50, 68),
    ("longitude",        68, 86),
    ("last_update",      86, 115),
]
RECORD_WIDTH = 115


# ── Parsing helpers ──────────────────────────────────────────────────────────
# Same defensive philosophy as gom_well_loader.py: bad input becomes None
# rather than raising. The fixed-width file has its own quirks — values
# like ".00" with no leading zero, occasional short final lines.

def _clean_str(v) -> Optional[str]:
    """Strip whitespace; return None for empty."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _parse_decimal(v, max_value: float = 1e9) -> Optional[float]:
    """Parse a numeric string to float. Returns None for empty or garbage.

    Handles BOEM's bare-point form (".00" meaning 0.00). max_value is a
    sanity cap protecting the DECIMAL columns from overflow.
    """
    s = _clean_str(v)
    if not s:
        return None
    s = s.replace(",", "")
    # ".00" -> "0.00"; "-.5" -> "-0.5"
    if s.startswith("."):
        s = "0" + s
    elif s.startswith("-."):
        s = "-0" + s[1:]
    try:
        n = float(s)
        if abs(n) > max_value:
            return None
        return n
    except (ValueError, TypeError):
        return None


def _parse_coord(v, max_deg: float = 180.0) -> Optional[float]:
    """Parse a latitude or longitude. Must be in [-max_deg, +max_deg].

    BOEM survey coords are NAD27 decimal degrees. Anything outside the
    valid range is garbage from a malformed row.
    """
    n = _parse_decimal(v)
    if n is None:
        return None
    if abs(n) > max_deg:
        return None
    return n


def _parse_date(v) -> Optional[date]:
    """BOEM survey date format: MM/DD/YYYY (zero-padded). Returns date or None.

    Also tolerates M/D/YYYY just in case the export isn't always padded.
    """
    s = _clean_str(v)
    if not s:
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


# ── File reader ──────────────────────────────────────────────────────────────

def _open_fixed_width_rows(file_path: str):
    """Yield (row_iterator, total_row_count) for a BOEM fixed-width file.

    Unlike the well loader's delimited opener there is NO header row —
    the file is pure data. Each yielded row is a dict keyed by the
    COLSPECS field names, values already sliced-and-stripped to strings.

    Returns
    -------
    (row_iter, total) where:
        row_iter : iterable of dict[str, str]
        total    : int line count, for progress reporting
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Cheap first pass: count non-blank lines for the progress bar.
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        total = sum(1 for line in f if line.strip())
    if total < 0:
        total = 0

    def _row_iter():
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            for raw in f:
                line = raw.rstrip("\r\n")
                if not line.strip():
                    continue
                # Slice each field by its fixed column span. A short line
                # (rare, malformed) just yields empty strings for the
                # fields past its end — the parser turns those into None.
                yield {
                    name: line[start:end].strip()
                    for name, start, end in COLSPECS
                }

    return _row_iter(), total


# ── The loader ───────────────────────────────────────────────────────────────

def load_gom_dir_srvy(
    engine,
    file_path: str,
    chunk_size: int = 5000,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Bulk-load BOEM GOM directional survey points.

    Parameters
    ----------
    engine
        SQLAlchemy engine pointing at the DataView database (with
        fast_executemany=True for performance).
    file_path
        Absolute path to the BOEM Azimuth fixed-width file
        (directfixed.txt). Headerless; 115-char records.
    chunk_size
        Rows per batched executemany MERGE. 5000 balances memory against
        round-trip overhead.
    progress_callback
        Optional callable invoked from the main thread as each chunk
        completes. Signature: (rows_done, rows_total, current_status_msg).

    Returns
    -------
    dict with keys:
        total_rows     — rows read from the file
        loaded_points  — survey-point rows written (MERGE insert+update)
        parse_errors   — rows skipped due to unparseable required fields
        error_samples  — up to 10 example error messages
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    stats = {
        "total_rows":    0,
        "loaded_points": 0,
        "parse_errors":  0,
        "error_samples": [],
    }

    row_iter, total_rows = _open_fixed_width_rows(str(p))
    if total_rows <= 0:
        return stats

    point_params: list = []
    rows_processed = 0
    source_filename = p.name

    def _flush(con):
        """Run the MERGE for the current chunk.

        The MERGE targets the natural key (api_well_number,
        survey_point_md) so re-running the same file updates each
        station in place instead of duplicating it. well_id is left
        untouched here — it's resolved by a separate follow-up pass.
        """
        nonlocal point_params
        if point_params:
            con.execute(text("""
                MERGE dataview_gom.directional_survey_point AS tgt
                USING (SELECT
                         :api_well_number  AS api_well_number,
                         :survey_point_md  AS survey_point_md,
                         :incl_ang         AS incl_ang,
                         :azimuth          AS azimuth,
                         :survey_point_tvd AS survey_point_tvd,
                         :latitude         AS latitude,
                         :longitude        AS longitude,
                         :last_update      AS last_update,
                         :source_file      AS source_file) src
                ON  tgt.api_well_number = src.api_well_number
                AND tgt.survey_point_md = src.survey_point_md
                WHEN MATCHED THEN UPDATE SET
                    incl_ang         = src.incl_ang,
                    azimuth          = src.azimuth,
                    survey_point_tvd = src.survey_point_tvd,
                    latitude         = src.latitude,
                    longitude        = src.longitude,
                    last_update      = src.last_update,
                    source_file      = src.source_file,
                    row_changed_date = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT (
                    api_well_number, survey_point_md, incl_ang, azimuth,
                    survey_point_tvd, latitude, longitude, last_update,
                    source_file, loaded_date, row_changed_date
                ) VALUES (
                    src.api_well_number, src.survey_point_md, src.incl_ang,
                    src.azimuth, src.survey_point_tvd, src.latitude,
                    src.longitude, src.last_update, src.source_file,
                    SYSUTCDATETIME(), SYSUTCDATETIME()
                );
            """), point_params)
            stats["loaded_points"] += len(point_params)
        point_params.clear()

    # Stream rows, build the chunk, flush every chunk_size rows. Each
    # chunk is one transaction — a failed chunk rolls back but earlier
    # committed chunks stay.
    for row in row_iter:
        stats["total_rows"] += 1

        try:
            api = _clean_str(row.get("api_well_number"))
            if not api:
                stats["parse_errors"] += 1
                if len(stats["error_samples"]) < 10:
                    stats["error_samples"].append(
                        f"Row {stats['total_rows']}: blank API well number"
                    )
                continue

            md = _parse_decimal(row.get("survey_point_md"))
            if md is None:
                # Without a measured depth the row has no place in the
                # trajectory and can't satisfy the natural key.
                stats["parse_errors"] += 1
                if len(stats["error_samples"]) < 10:
                    stats["error_samples"].append(
                        f"Row {stats['total_rows']} (API {api}): "
                        f"unparseable survey_point_md "
                        f"{row.get('survey_point_md')!r}"
                    )
                continue

            point_params.append({
                "api_well_number":  api,
                "survey_point_md":  md,
                "incl_ang":         _parse_decimal(row.get("incl_ang")),
                "azimuth":          _parse_decimal(row.get("azimuth")),
                "survey_point_tvd": _parse_decimal(row.get("survey_point_tvd")),
                "latitude":         _parse_coord(row.get("latitude"),  max_deg=90),
                "longitude":        _parse_coord(row.get("longitude"), max_deg=180),
                "last_update":      _parse_date(row.get("last_update")),
                "source_file":      source_filename,
            })

        except Exception as e:
            stats["parse_errors"] += 1
            if len(stats["error_samples"]) < 10:
                stats["error_samples"].append(
                    f"Row {stats['total_rows']}: {type(e).__name__}: {e}"
                )
            continue

        rows_processed += 1

        if rows_processed % chunk_size == 0:
            try:
                with engine.begin() as con:
                    _flush(con)
            except Exception as e:
                # Whole chunk rolled back — record as errors so the
                # caller knows to investigate.
                stats["parse_errors"] += len(point_params)
                if len(stats["error_samples"]) < 10:
                    stats["error_samples"].append(
                        f"Chunk near row {rows_processed} failed: "
                        f"{type(e).__name__}: {e}"
                    )
                point_params.clear()

            if progress_callback:
                try:
                    progress_callback(
                        rows_processed, total_rows,
                        f"Loaded {stats['loaded_points']:,} survey points…"
                    )
                except Exception:
                    pass

    # Flush the final partial chunk.
    if point_params:
        try:
            with engine.begin() as con:
                _flush(con)
        except Exception as e:
            stats["parse_errors"] += len(point_params)
            if len(stats["error_samples"]) < 10:
                stats["error_samples"].append(
                    f"Final chunk failed: {type(e).__name__}: {e}"
                )

    if progress_callback:
        try:
            progress_callback(
                rows_processed, total_rows,
                f"Loaded {stats['loaded_points']:,} survey points"
            )
        except Exception:
            pass

    return stats

"""
gom_well_loader.py — BOEM Gulf of America well header bulk loader
==================================================================

Reads a BOEM-format TSV export of well headers and loads it into:
  - dataview.dv_well_identifier  (universal identifier registry)
  - dataview_gom.well            (GOM-specific well attributes)

Each well gets a deterministic UUID derived from the BOEM API Well Number,
so re-running the loader on the same file produces the same well_id values
and MERGE statements update in place (idempotent).

Architecture
------------
- Pure Python (no Streamlit), so the loader can also be invoked from a
  terminal script or batch job in the future.
- Reads in chunks (default 5,000 rows) and writes via batched executemany.
  The fast_executemany=True flag on the engine (set in modules/db.py) packs
  every parameter set into one network round-trip per statement.
- Idempotent: MERGE statements handle both first-load and re-load cases.
- Tolerant: per-row parsing errors are logged and the row is skipped;
  the batch continues. A summary dict reports counts.

Usage
-----
    from modules.gom_well_loader import load_gom_wells
    stats = load_gom_wells(
        engine=engine,
        file_path=r"C:\\path\\to\\boem_gom_wells.tsv",
        chunk_size=5000,
        progress_callback=lambda done, total, msg: print(f"{done}/{total} {msg}"),
    )
"""

from __future__ import annotations

import csv
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import text


# ── Constants ────────────────────────────────────────────────────────────────

# Deterministic well_id namespace. Generated once via uuid.uuid4() and pinned
# here so every machine produces the same well_id for the same BOEM API.
# Don't change this — it would break idempotency across machines.
WELL_ID_NAMESPACE = uuid.UUID("a7e3c4f1-5b29-4d18-9f7a-c3e8b1d6a4f2")

# Expected column order in the BOEM TSV. Source files may differ in whitespace
# but the order must match. We validate by header on load.
EXPECTED_COLUMNS = [
    "API Well Number",
    "Well Name",
    "Well Name Suffix",
    "Bottom Lease Number",
    "Bottom Area",
    "Bottom Block",
    "Region",
    "Company Name",
    "Spud Date",
    "BH Total MD (feet)",
    "True Vertical Depth (feet)",
    "TVD Subsea (feet)",
    "RKB",
    "KOP",
    "Total Depth Date",
    "Status Date",
    "Type Code",
    "Status Code",
    "Casing Cut Code",
    "Water Depth (feet)",
    "Underwater Comp Stub",
    "Surface Lease Number",
    "Surface Latitude*",
    "Surface Longitude*",
    "Bottom Latitude*",
    "Bottom Longitude*",
]


# ── Parsing helpers ──────────────────────────────────────────────────────────
# BOEM data has quirks: leading spaces on names and leases, dates in M-D-YYYY
# format (not zero-padded), occasional empty strings where NULL is meant.
# Each helper is defensive — bad input becomes None rather than raising.

def _clean_str(v) -> Optional[str]:
    """Strip whitespace; return None for empty."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _parse_date(v) -> Optional[date]:
    """BOEM date format: M-D-YYYY or MM-DD-YYYY. Returns date or None."""
    s = _clean_str(v)
    if not s:
        return None
    # Match M-D-YYYY with 1-2 digit month/day
    m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", s)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def _parse_decimal(v, max_value: float = 1e10) -> Optional[float]:
    """Parse a numeric string to float. Returns None for empty or garbage.

    max_value is a sanity cap — values beyond it are treated as None to
    protect downstream DECIMAL columns from overflow.
    """
    s = _clean_str(v)
    if not s:
        return None
    # Strip commas and stray non-numeric chars
    s = s.replace(",", "")
    try:
        n = float(s)
        if abs(n) > max_value:
            return None
        return n
    except (ValueError, TypeError):
        return None


def _parse_coord(v, max_deg: float = 180.0) -> Optional[float]:
    """Parse a latitude or longitude. Must be in [-max_deg, +max_deg].

    BOEM uses decimal degrees in WGS84 (or close). Anything outside the
    valid range is garbage from a malformed row.
    """
    n = _parse_decimal(v)
    if n is None:
        return None
    if abs(n) > max_deg:
        return None
    return n


def _well_id_for_api(api: str) -> uuid.UUID:
    """Deterministic well_id for a given BOEM API number.

    Uses uuid5 over a fixed namespace so the same API always produces the
    same UUID. This is what makes the loader idempotent.
    """
    # Normalize: strip whitespace. BOEM APIs are 12 chars but we preserve
    # whatever the source gave us in the namespace input.
    api_norm = api.strip()
    return uuid.uuid5(WELL_ID_NAMESPACE, f"BOEM:{api_norm}")


# ── The loader ───────────────────────────────────────────────────────────────

def load_gom_wells(
    engine,
    file_path: str,
    chunk_size: int = 5000,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Bulk-load BOEM GOM well headers.

    Parameters
    ----------
    engine
        SQLAlchemy engine pointing at the DataView database (with
        fast_executemany=True for performance).
    file_path
        Absolute path to the BOEM TSV file. First row must be a header
        matching EXPECTED_COLUMNS.
    chunk_size
        Rows per batched executemany call. 5000 is a balance of memory and
        round-trip overhead. Lower for slow networks; higher for big RAM.
    progress_callback
        Optional callable invoked from the main thread as each chunk
        completes. Signature: (rows_done, rows_total, current_status_msg).

    Returns
    -------
    dict with keys:
        total_rows         — rows read from the file
        loaded_identifiers — rows written to dv_well_identifier
        loaded_wells       — rows written to dataview_gom.well
        parse_errors       — rows skipped due to unparseable required fields
        error_samples      — up to 10 example error messages
    """
def _open_rows(file_path: str):
    """Yield (header_list, row_iterator, total_row_count) for any supported format.

    Auto-detects format by extension. Returns:
        header:   list[str] of column names from the first row
        row_iter: iterable of list[str] rows
        total:    int row count (for progress reporting)

    Supported formats:
        .tsv, .txt   — tab-separated text
        .csv         — comma-separated text
        .xlsx, .xls  — Excel (read via pandas/openpyxl)

    Excel values are coerced to strings to match the TSV-style row contract.
    Empty cells become empty strings. Dates ARE converted back to the
    M-D-YYYY string format the parser expects.
    """
    from datetime import datetime as _dt, date as _date

    p = Path(file_path)
    ext = p.suffix.lower()

    if ext in (".xlsx", ".xls"):
        # Excel path. pandas reads everything, then we coerce to row-of-strings.
        # We use openpyxl for .xlsx (most common BOEM export format) and xlrd
        # for legacy .xls files. Both come with pandas.
        try:
            import pandas as pd
        except ImportError:
            raise ImportError(
                "Loading Excel files requires pandas. "
                "It's already a dependency of Data Wrangler."
            )

        # Read the whole sheet. dtype=str keeps numeric API numbers as strings
        # (preserving leading zeros) and prevents pandas from auto-converting
        # dates into Timestamps until we explicitly decide what to do.
        df = pd.read_excel(p, dtype=str, keep_default_na=False)

        # Trim header whitespace (matches the TSV path's behavior).
        header = [str(c).strip() for c in df.columns.tolist()]

        # Convert dataframe to row iterator. Each row is a list of strings.
        # NaN, None, NaT become empty strings — the parser already treats
        # empty strings as None via _clean_str.
        def _row_iter():
            for _, row in df.iterrows():
                yield [
                    "" if v is None or (isinstance(v, float) and v != v)
                    else str(v).strip()
                    for v in row.tolist()
                ]

        return header, _row_iter(), len(df)

    elif ext in (".tsv", ".txt", ".csv"):
        # Text path. Delimiter inferred from extension.
        delim = "," if ext == ".csv" else "\t"

        # Count rows first (cheap) for progress reporting
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            total = sum(1 for _ in f) - 1  # minus header
        if total < 0:
            total = 0

        # Re-open for real reading
        f = p.open("r", encoding="utf-8-sig", newline="")
        reader = csv.reader(f, delimiter=delim)
        header_raw = next(reader, None)
        if not header_raw:
            f.close()
            raise ValueError("File is empty (no header row).")
        header = [c.strip() for c in header_raw]

        def _row_iter():
            try:
                for row in reader:
                    yield row
            finally:
                f.close()

        return header, _row_iter(), total

    else:
        raise ValueError(
            f"Unsupported file extension: {ext}. "
            f"Use .xlsx, .xls, .tsv, .txt, or .csv."
        )


def load_gom_wells(
    engine,
    file_path: str,
    chunk_size: int = 5000,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    """Bulk-load BOEM GOM well headers.

    Parameters
    ----------
    engine
        SQLAlchemy engine pointing at the DataView database (with
        fast_executemany=True for performance).
    file_path
        Absolute path to the BOEM file. Supported formats: .xlsx, .xls,
        .tsv, .txt, .csv. First row must be a header matching EXPECTED_COLUMNS.
    chunk_size
        Rows per batched executemany call. 5000 is a balance of memory and
        round-trip overhead. Lower for slow networks; higher for big RAM.
    progress_callback
        Optional callable invoked from the main thread as each chunk
        completes. Signature: (rows_done, rows_total, current_status_msg).

    Returns
    -------
    dict with keys:
        total_rows         — rows read from the file
        loaded_identifiers — rows written to dv_well_identifier
        loaded_wells       — rows written to dataview_gom.well
        parse_errors       — rows skipped due to unparseable required fields
        error_samples      — up to 10 example error messages
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    stats = {
        "total_rows":         0,
        "loaded_identifiers": 0,
        "loaded_wells":       0,
        "parse_errors":       0,
        "error_samples":      [],
    }

    # Get header, row iterator, and total count via the format-aware opener.
    header, row_iter, total_rows = _open_rows(str(p))
    if total_rows <= 0:
        return stats

    # Validate header. Accept the file if its column NAMES match
    # EXPECTED_COLUMNS exactly (order matters).
    if header != EXPECTED_COLUMNS:
        missing = set(EXPECTED_COLUMNS) - set(header)
        extra   = set(header) - set(EXPECTED_COLUMNS)
        raise ValueError(
            f"Header mismatch.\n"
            f"  Missing columns: {sorted(missing)}\n"
            f"  Extra columns:   {sorted(extra)}\n"
            f"Expected exactly: {EXPECTED_COLUMNS}"
        )

    # Stream rows, build parameter lists in chunks, flush each chunk.
    ident_params: list = []  # for dv_well_identifier
    well_params:  list = []  # for dataview_gom.well

    rows_processed = 0
    source_filename = p.name

    def _flush(con):
        """Run the two MERGE statements for the current chunk."""
        nonlocal ident_params, well_params

        if ident_params:
            con.execute(text("""
                MERGE dataview.dv_well_identifier AS tgt
                USING (SELECT
                         :well_id          AS well_id,
                         :identifier_type  AS identifier_type,
                         :identifier_value AS identifier_value,
                         :source_system    AS source_system,
                         :is_primary       AS is_primary) src
                ON tgt.well_id = src.well_id
                   AND tgt.identifier_type = src.identifier_type
                WHEN MATCHED THEN UPDATE SET
                    identifier_value = src.identifier_value,
                    source_system    = src.source_system,
                    is_primary       = src.is_primary,
                    loaded_date      = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT
                    (well_id, identifier_type, identifier_value,
                     source_system, is_primary, loaded_date)
                VALUES
                    (src.well_id, src.identifier_type, src.identifier_value,
                     src.source_system, src.is_primary, SYSUTCDATETIME());
            """), ident_params)
            stats["loaded_identifiers"] += len(ident_params)

        if well_params:
            con.execute(text("""
                MERGE dataview_gom.well AS tgt
                USING (SELECT :well_id AS well_id) src
                ON tgt.well_id = src.well_id
                WHEN MATCHED THEN UPDATE SET
                    api_well_number        = :api_well_number,
                    well_name              = :well_name,
                    well_name_suffix       = :well_name_suffix,
                    surface_lease_number   = :surface_lease_number,
                    bottom_lease_number    = :bottom_lease_number,
                    bottom_area_code       = :bottom_area_code,
                    bottom_block_number    = :bottom_block_number,
                    region                 = :region,
                    company_name           = :company_name,
                    spud_date              = :spud_date,
                    total_depth_date       = :total_depth_date,
                    status_date            = :status_date,
                    bh_total_md_ft         = :bh_total_md_ft,
                    true_vertical_depth_ft = :true_vertical_depth_ft,
                    tvd_subsea_ft          = :tvd_subsea_ft,
                    rkb_ft                 = :rkb_ft,
                    kop_ft                 = :kop_ft,
                    water_depth_ft         = :water_depth_ft,
                    type_code              = :type_code,
                    status_code            = :status_code,
                    casing_cut_code        = :casing_cut_code,
                    underwater_comp_stub   = :underwater_comp_stub,
                    surface_latitude       = :surface_latitude,
                    surface_longitude      = :surface_longitude,
                    bottom_latitude        = :bottom_latitude,
                    bottom_longitude       = :bottom_longitude,
                    source_file            = :source_file,
                    row_changed_date       = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT (
                    well_id, api_well_number, well_name, well_name_suffix,
                    surface_lease_number, bottom_lease_number,
                    bottom_area_code, bottom_block_number, region,
                    company_name, spud_date, total_depth_date, status_date,
                    bh_total_md_ft, true_vertical_depth_ft, tvd_subsea_ft,
                    rkb_ft, kop_ft, water_depth_ft,
                    type_code, status_code, casing_cut_code,
                    underwater_comp_stub,
                    surface_latitude, surface_longitude,
                    bottom_latitude, bottom_longitude,
                    source_file, loaded_date, row_changed_date
                ) VALUES (
                    :well_id, :api_well_number, :well_name, :well_name_suffix,
                    :surface_lease_number, :bottom_lease_number,
                    :bottom_area_code, :bottom_block_number, :region,
                    :company_name, :spud_date, :total_depth_date, :status_date,
                    :bh_total_md_ft, :true_vertical_depth_ft, :tvd_subsea_ft,
                    :rkb_ft, :kop_ft, :water_depth_ft,
                    :type_code, :status_code, :casing_cut_code,
                    :underwater_comp_stub,
                    :surface_latitude, :surface_longitude,
                    :bottom_latitude, :bottom_longitude,
                    :source_file, SYSUTCDATETIME(), SYSUTCDATETIME()
                );
            """), well_params)
            stats["loaded_wells"] += len(well_params)

        ident_params.clear()
        well_params.clear()

    # Process row-by-row, flushing every chunk_size rows. Each chunk is
    # one transaction — if the chunk MERGE fails, that chunk rolls back
    # but earlier chunks stay committed.
    for row in row_iter:
        stats["total_rows"] += 1

        # Defensive: row may have extra/missing fields (rare but possible)
        if len(row) < len(EXPECTED_COLUMNS):
            stats["parse_errors"] += 1
            if len(stats["error_samples"]) < 10:
                stats["error_samples"].append(
                    f"Row {stats['total_rows']}: only {len(row)} fields, "
                    f"expected {len(EXPECTED_COLUMNS)}"
                )
            continue

        try:
            # Map fields by index since header already validated
            api = _clean_str(row[0])
            if not api:
                stats["parse_errors"] += 1
                if len(stats["error_samples"]) < 10:
                    stats["error_samples"].append(
                        f"Row {stats['total_rows']}: blank API Well Number"
                    )
                continue

            # Deterministic well_id from the API
            well_id = _well_id_for_api(api)
            well_id_str = str(well_id)

            # Build identifier params — one row for API_BOEM, marked primary
            ident_params.append({
                "well_id":          well_id_str,
                "identifier_type":  "API_BOEM",
                "identifier_value": api,
                "source_system":    "BOEM",
                "is_primary":       1,
            })

            # Build well_attribute params — all 25 BOEM columns
            well_params.append({
                "well_id":               well_id_str,
                "api_well_number":       api,
                "well_name":             _clean_str(row[1]),
                "well_name_suffix":      _clean_str(row[2]),
                "bottom_lease_number":   _clean_str(row[3]),
                "bottom_area_code":      _clean_str(row[4]),
                "bottom_block_number":   _clean_str(row[5]),
                "region":                _clean_str(row[6]),
                "company_name":          _clean_str(row[7]),
                "spud_date":             _parse_date(row[8]),
                "bh_total_md_ft":        _parse_decimal(row[9]),
                "true_vertical_depth_ft": _parse_decimal(row[10]),
                "tvd_subsea_ft":         _parse_decimal(row[11]),
                "rkb_ft":                _parse_decimal(row[12]),
                "kop_ft":                _parse_decimal(row[13]),
                "total_depth_date":      _parse_date(row[14]),
                "status_date":           _parse_date(row[15]),
                "type_code":             _clean_str(row[16]),
                "status_code":           _clean_str(row[17]),
                "casing_cut_code":       _clean_str(row[18]),
                "water_depth_ft":        _parse_decimal(row[19]),
                "underwater_comp_stub":  _clean_str(row[20]),
                "surface_lease_number":  _clean_str(row[21]),
                # row[22], row[23] are the low-precision lat/lon — skipped
                # in favor of the high-precision starred values below.
                "surface_latitude":      _parse_coord(row[24], max_deg=90),
                "surface_longitude":     _parse_coord(row[25], max_deg=180),
                # Sample shows the full 26-col layout has bottom lat/lon
                # as the LAST two starred columns. Defensive index check:
                "bottom_latitude":       (_parse_coord(row[26], max_deg=90)
                                          if len(row) > 26 else None),
                "bottom_longitude":      (_parse_coord(row[27], max_deg=180)
                                          if len(row) > 27 else None),
                "source_file":           source_filename,
            })

        except Exception as e:
            stats["parse_errors"] += 1
            if len(stats["error_samples"]) < 10:
                stats["error_samples"].append(
                    f"Row {stats['total_rows']}: {type(e).__name__}: {e}"
                )
            continue

        rows_processed += 1

        # Flush when chunk is full
        if rows_processed % chunk_size == 0:
            try:
                with engine.begin() as con:
                    _flush(con)
            except Exception as e:
                # Whole chunk rolled back. Record as errors so the caller
                # knows something went wrong and can investigate.
                stats["parse_errors"] += len(ident_params)
                if len(stats["error_samples"]) < 10:
                    stats["error_samples"].append(
                        f"Chunk near row {rows_processed} failed: "
                        f"{type(e).__name__}: {e}"
                    )
                ident_params.clear()
                well_params.clear()

            if progress_callback:
                try:
                    progress_callback(
                        rows_processed, total_rows,
                        f"Loaded {stats['loaded_wells']:,} wells…"
                    )
                except Exception:
                    pass

    # Flush the final partial chunk
    if ident_params or well_params:
        try:
            with engine.begin() as con:
                _flush(con)
        except Exception as e:
            stats["parse_errors"] += len(ident_params)
            if len(stats["error_samples"]) < 10:
                stats["error_samples"].append(
                    f"Final chunk failed: {type(e).__name__}: {e}"
                )

    if progress_callback:
        try:
            progress_callback(
                rows_processed, total_rows,
                f"Loaded {stats['loaded_wells']:,} wells"
            )
        except Exception:
            pass

    return stats

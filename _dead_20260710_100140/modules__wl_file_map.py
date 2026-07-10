"""
modules/wl_file_map.py

Well Log File → UWI Mapping

Staging workflow for DLIS / LIS (and LAS) bulk cataloguing:

  1. scan_directory()     — scan folder, extract header well IDs, fuzzy match
  2. import_manifest()    — load a CSV/Excel manifest (filename → UWI)
  3. save_map()           — persist pending rows to WL_FILE_UWI_MAP
  4. load_map()           — load current staging rows for review/editing
  5. confirm_rows()       — mark selected rows as CONFIRMED
  6. catalog_confirmed()  — catalog CONFIRMED rows → DLIS_FILE / LIS_FILE
  7. clear_catalogued()   — remove CATALOGUED rows from staging table

UWI matching strategy (in order):
  1. Header  — well_id / well_name from file header (exact then fuzzy)
  2. Filename — well name extracted from filename (fuzzy against PPDM)
  3. Manual  — user override in the UI grid

Requires: dlisio, lasio, pandas, openpyxl (for Excel manifests)
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _make_id(seed: str) -> str:
    """SHA1 of normalised path — case-insensitive, strip whitespace."""
    normalised = seed.strip().lower().replace("\\", "/").rstrip("/")
    return hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:20].upper()


def _normalise(s: str) -> str:
    """Strip non-alphanumeric chars and lowercase for fuzzy comparison."""
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _fuzzy_score(candidate: str, target: str) -> float:
    """
    Score how well candidate matches target. Returns 0-100.
    Checks exact, containment, and character overlap.
    """
    nc = _normalise(candidate)
    nt = _normalise(target)
    if not nc or not nt:
        return 0.0
    if nc == nt:
        return 100.0
    if nc in nt or nt in nc:
        overlap = min(len(nc), len(nt))
        total   = max(len(nc), len(nt))
        return round(85.0 * overlap / total + 10, 1)
    common = sum(c in nt for c in set(nc))
    return round(70.0 * common / max(len(set(nc)), 1), 1)


def _best_match(search_str: str,
                ppdm_uwis: list[dict],
                threshold: float = 30.0) -> dict:
    """
    Find the best matching UWI from ppdm_uwis for search_str.
    Matches against both UWI and WELL_NAME.
    Returns { UWI, WELL_NAME, score, method } or empty dict if no match.
    """
    best = {"score": 0.0, "UWI": "", "WELL_NAME": "", "method": ""}
    for row in ppdm_uwis:
        for field, method in [(row["UWI"], "UWI"), (row["WELL_NAME"], "NAME")]:
            s = _fuzzy_score(search_str, field)
            if s > best["score"]:
                best = {
                    "score":     s,
                    "UWI":       row["UWI"],
                    "WELL_NAME": row["WELL_NAME"],
                    "method":    method,
                }
    if best["score"] < threshold:
        return {}
    return best


def _extract_header_id(file_path: str, fmt: str) -> str:
    """
    Extract the best available well identifier from a file header.
    Returns empty string if nothing useful found.
    """
    try:
        if fmt == "DLIS":
            # Use fast reader — avoids loading entire file with dlisio
            try:
                from modules.dlis_catalog import fast_dlis_meta
                meta = fast_dlis_meta(file_path)
                for key in ("well_id", "well_name"):
                    v = meta.get(key, "").strip()
                    if v and v not in ("", "None"):
                        return v
            except Exception:
                # Fallback to dlisio if fast reader fails
                from dlisio import dlis
                with dlis.load(file_path) as lfs:
                    lf = lfs[0]
                    orig = next(iter(lf.origins), None)
                    if orig:
                        for attr in ("well_id", "well_name"):
                            v = getattr(orig, attr, None)
                            if v and str(v).strip() not in ("", "None"):
                                return str(v).strip()
        elif fmt == "LIS":
            from dlisio import lis
            with lis.load(file_path) as lfs:
                lf = lfs[0]
                for rec in lf.wellsite_data():
                    comps = rec.components()
                    current = None
                    for c in comps:
                        if c.mnemonic == "MNEM":
                            current = str(c.component).strip()
                        elif c.mnemonic == "VALU" and current in ("WN", "WID"):
                            v = str(c.component).strip()
                            if v and v not in ("None", ""):
                                return v
                            current = None
        elif fmt == "LAS":
            import lasio
            import logging as _log
            _log.getLogger("lasio").setLevel(_log.ERROR)
            las = lasio.read(file_path, ignore_header_errors=True)
            for mnem in ("UWI", "API", "WELL"):
                try:
                    v = las.well[mnem].value
                    if v and str(v).strip():
                        return str(v).strip()
                except KeyError:
                    pass
    except Exception:
        pass
    return ""


def _stem_candidates(filename: str) -> list[str]:
    """
    Extract candidate well identifier strings from a filename.

    Strategy:
    1. Try the full stem first (handles UWI-prefixed renames)
       e.g. '17-031-10035-0000_Chevron_A12a.DLIS' → try '17-031-10035-0000'
    2. Split on separators, try multi-part joined segments
       e.g. 'A12a-CPP-A2' kept intact before splitting further
    3. Individual parts after removing stop words

    Returns candidates longest-first so the fuzzy matcher sees the
    most specific options first.
    """
    STOP = {"combined", "final", "raw", "interp", "processed",
            "composite", "log", "logs", "data", "copy", "las",
            "dlis", "lis", "well", "file", "export", "out"}

    stem = Path(filename).stem
    candidates = []

    # 1. First token before first underscore — often the UWI in renamed files
    #    e.g. '17-031-10035-0000_Chevron_A12a' → '17-031-10035-0000'
    first_token = stem.split("_")[0]
    if len(first_token) >= 4 and first_token.lower() not in STOP:
        candidates.append(first_token)

    # 2. Full stem
    if stem not in candidates and len(stem) >= 4:
        candidates.append(stem)

    # 3. Underscore-separated segments (kept intact — may contain hyphens)
    #    e.g. 'A12a-CPP-A2' is a single segment worth trying whole
    for part in stem.split("_"):
        part = part.strip()
        if len(part) >= 4 and part.lower() not in STOP and part not in candidates:
            candidates.append(part)

    # 4. Individual alpha-numeric tokens
    tokens = re.split(r"[_\-\.\s]+", stem)
    for t in tokens:
        if len(t) >= 3 and t.lower() not in STOP and t not in candidates:
            candidates.append(t)

    # Sort by length descending — longer = more specific
    candidates.sort(key=len, reverse=True)
    return candidates


# ─────────────────────────────────────────────────────────────────────────────
# Directory scan
# ─────────────────────────────────────────────────────────────────────────────

def _scan_single_file(args: tuple) -> dict:
    """
    Worker function for parallel scan — processes one file.
    Accepts a tuple so it works with ProcessPoolExecutor.map().
    """
    fp, fmt, ppdm_uwis, repository_id = args
    now = _now_str()
    map_id = _make_id(str(fp))
    try:
        file_size_kb = round(fp.stat().st_size / 1024, 2)
    except Exception:
        file_size_kb = None

    # Try header first
    header_id = _extract_header_id(str(fp), fmt.upper())
    match_method = ""
    match = {}

    if header_id:
        match = _best_match(header_id, ppdm_uwis)
        if match:
            match_method = f"HEADER/{match['method']}"

    # Fall back to filename
    if not match:
        for candidate in _stem_candidates(fp.name):
            match = _best_match(candidate, ppdm_uwis)
            if match:
                match_method = "FILENAME"
                break

    return {
        "MAP_ID":           map_id,
        "FILE_PATH":        str(fp),
        "FILE_NAME":        fp.name,
        "FILE_FORMAT":      fmt.upper(),
        "REPOSITORY_ID":    repository_id or None,
        "UWI":              match.get("UWI") or None,
        "HEADER_WELL_ID":   header_id or None,
        "MATCH_METHOD":     match_method or None,
        "MATCH_SCORE":      match.get("score") or None,
        "MATCH_WELL_NAME":  match.get("WELL_NAME") or None,
        "STATUS":           "PENDING",
        "FILE_SIZE_KB":     file_size_kb,
        "REMARK":           None,
        "ROW_CREATED_BY":   "DATA_WRANGLER",
        "ROW_CREATED_DATE": now,
        "ROW_CHANGED_BY":   "DATA_WRANGLER",
        "ROW_CHANGED_DATE": now,
    }


def scan_directory(folder: str,
                   fmt: str,
                   ppdm_uwis: list[dict],
                   repository_id: str = "",
                   max_workers: int = None,
                   progress_callback=None) -> pd.DataFrame:
    """
    Scan a directory for files of the given format, extract header well IDs,
    and fuzzy-match against PPDM wells. Files are processed in parallel.

    Parameters
    ----------
    folder            : directory path to scan
    fmt               : 'DLIS', 'LIS', or 'LAS'
    ppdm_uwis         : list of { UWI, WELL_NAME } dicts from PPDM WELL table
    repository_id     : optional — pre-fill REPOSITORY_ID column
    max_workers       : number of parallel threads (default 4)
    progress_callback : optional callable(completed, total, filename)

    Returns
    -------
    DataFrame with columns matching WL_FILE_UWI_MAP
    """
    if max_workers is None:
        max_workers = _default_workers()
    import concurrent.futures

    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {folder}")

    ext_map = {
        "DLIS": ["*.dlis", "*.DLIS", "*.dlf", "*.DLF"],
        "LIS":  ["*.lis",  "*.LIS"],
        "LAS":  ["*.las",  "*.LAS"],
    }
    files = []
    for pattern in ext_map.get(fmt.upper(), []):
        files.extend(folder_path.rglob(pattern))  # recursive — searches subdirectories
    files = sorted(set(files))

    if not files:
        return pd.DataFrame()

    # Build args list for workers
    args = [(fp, fmt, ppdm_uwis, repository_id) for fp in files]
    rows = []
    completed = 0

    # ThreadPoolExecutor is safe for I/O-bound work (file reads).
    # dlisio releases the GIL during C-level reads so threads overlap well.
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scan_single_file, a): a[0] for a in args}
        for future in concurrent.futures.as_completed(futures):
            fp = futures[future]
            completed += 1
            if progress_callback:
                progress_callback(completed, len(files), fp.name)
            try:
                rows.append(future.result())
            except Exception as e:
                # File failed — add an error row
                rows.append({
                    "MAP_ID":           _make_id(str(fp)),
                    "FILE_PATH":        str(fp),
                    "FILE_NAME":        fp.name,
                    "FILE_FORMAT":      fmt.upper(),
                    "REPOSITORY_ID":    repository_id or None,
                    "UWI":              None,
                    "HEADER_WELL_ID":   None,
                    "MATCH_METHOD":     None,
                    "MATCH_SCORE":      None,
                    "MATCH_WELL_NAME":  None,
                    "STATUS":           "PENDING",
                    "FILE_SIZE_KB":     None,
                    "REMARK":           f"Scan error: {e}",
                    "ROW_CREATED_BY":   "DATA_WRANGLER",
                    "ROW_CREATED_DATE": _now_str(),
                    "ROW_CHANGED_BY":   "DATA_WRANGLER",
                    "ROW_CHANGED_DATE": _now_str(),
                })

    # Sort by filename for consistent ordering
    rows.sort(key=lambda r: r["FILE_NAME"])
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Manifest import
# ─────────────────────────────────────────────────────────────────────────────

import os as _os

def _default_workers() -> int:
    """
    Calculate a sensible default thread count for the current machine.
    Leaves 2 cores free for OS/Streamlit/SQL Server.
    Caps at 12 to avoid memory pressure from concurrent large file reads.
    """
    cores = _os.cpu_count() or 4
    return min(max(cores - 2, 2), 12)



# Folders to skip during filesystem crawl
_CRAWL_SKIP_DIRS = {
    # Windows system directories
    "windows", "program files", "program files (x86)",
    "programfiles", "programfiles(x86)",
    "windows.old", "winnt",
    # User profile junk
    "appdata", "application data", "local settings",
    "ntuser.dat", "$windows.~bt", "$windows.~ws",
    # System / hidden
    "system volume information", "$recycle.bin", "$recycler",
    "recycled", ".trash", ".trashes",
    "pagefile.sys", "hiberfil.sys", "swapfile.sys",
    # Common archive/backup patterns
    "archive", "archives", "backup", "backups", "bak", "old",
    "temp", "tmp", "cache", ".cache",
    # Version control / dev
    ".git", ".svn", ".hg", "node_modules", "__pycache__",
    # Package managers / runtimes
    "venv", ".venv", "env", ".env",
    "site-packages", "dist-packages",
    "miniconda", "anaconda", "anaconda3", "miniconda3",
}

_CRAWL_EXTENSIONS = {
    "LAS":  {".las"},
    "DLIS": {".dlis"},
    "LIS":  {".lis"},
    "SEGY": {".segy", ".sgy"},
    "P190": {".p190", ".p90"},
}


def crawl_walk(root: str,
               formats: list[str],
               engine,
               abort_flag: list = None) -> dict:
    """
    Phase 1: Walk the filesystem and return a list of well log files found.
    Fast — no header reading. Skips files already staged or catalogued.

    Returns dict with:
      file_list : list of { FULL_PATH, PARENT, FILE_NAME, FILE_TYPE, SIZE_KB }
      skipped_existing    : already in staging table
      skipped_catalogued  : already in catalog tables
      aborted : bool
    """
    from sqlalchemy import text

    if abort_flag is None:
        abort_flag = [False]

    root_path = Path(root)
    if not root_path.is_dir():
        raise FileNotFoundError(f"Directory not found: {root}")

    target_exts = set()
    fmt_by_ext  = {}
    for fmt in formats:
        for ext in _CRAWL_EXTENSIONS.get(fmt.upper(), set()):
            target_exts.add(ext.lower())
            fmt_by_ext[ext.lower()] = fmt.upper()

    # Get already-staged paths
    try:
        with engine.connect() as con:
            staged = {
                str(r[0]).lower()
                for r in con.execute(text(
                    "SELECT FILE_PATH FROM [las_catalog].[WL_FILE_UWI_MAP]"
                )).fetchall()
            }
    except Exception:
        staged = set()

    # Get already-catalogued paths
    catalogued = set()
    try:
        with engine.connect() as con:
            for tbl in ("LAS_FILE", "DLIS_FILE", "LIS_FILE"):
                rows = con.execute(text(
                    f"SELECT r.BASE_PATH, f.FILE_NAME "
                    f"FROM [las_catalog].[{tbl}] f "
                    f"JOIN [las_catalog].[WL_REPOSITORY] r "
                    f"  ON r.REPOSITORY_ID = f.REPOSITORY_ID"
                )).fetchall()
                for base, fname in rows:
                    catalogued.add(str(Path(str(base)) / str(fname)).lower())
    except Exception:
        pass

    result = {
        "file_list": [],
        "skipped_existing":   0,
        "skipped_catalogued": 0,
        "aborted": False,
    }

    seen_paths = set()  # deduplicate within this crawl

    for dirpath, dirnames, filenames in _os_walk(root_path):
        if abort_flag[0]:
            result["aborted"] = True
            break

        dirnames[:] = [
            d for d in dirnames
            if d.lower() not in _CRAWL_SKIP_DIRS
            and not d.startswith('.')
        ]

        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext not in target_exts:
                continue

            fp      = Path(dirpath) / fname
            fp_str  = str(fp)
            fp_lower = fp_str.lower()

            # Skip duplicates within this crawl
            if fp_lower in seen_paths:
                continue
            seen_paths.add(fp_lower)

            if fp_lower in staged:
                result["skipped_existing"] += 1
                continue
            if fp_lower in catalogued:
                result["skipped_catalogued"] += 1
                continue

            try:
                size_kb = round(fp.stat().st_size / 1024, 2)
            except Exception:
                size_kb = None

            result["file_list"].append({
                "FULL_PATH": fp_str,
                "PARENT":    str(fp.parent),
                "FILE_NAME": fp.name,
                "FILE_TYPE": fmt_by_ext[ext],
                "SIZE_KB":   size_kb,
            })

    return result


def crawl_process(file_list: list[dict],
                  engine,
                  ppdm_uwis: list[dict],
                  repository_id: str = "",
                  max_workers: int = None,
                  progress_callback=None,
                  abort_flag: list = None) -> dict:
    """
    Phase 2: Extract headers and fuzzy-match UWIs for selected files,
    then save to WL_FILE_UWI_MAP staging table.

    file_list : subset of rows from crawl_walk() result["file_list"]
    Returns dict with: saved, errors, aborted
    """
    import concurrent.futures

    if max_workers is None:
        max_workers = _default_workers()
    if abort_flag is None:
        abort_flag = [False]

    result = {"saved": 0, "errors": 0, "aborted": False, "error_details": []}

    if not file_list:
        return result

    BATCH = 50
    total = len(file_list)

    for batch_start in range(0, total, BATCH):
        if abort_flag[0]:
            result["aborted"] = True
            break

        batch = file_list[batch_start:batch_start + BATCH]
        args  = [
            (Path(row["FULL_PATH"]), row["FILE_TYPE"], ppdm_uwis, repository_id)
            for row in batch
        ]

        rows = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_scan_single_file, a): a for a in args}
            for future in concurrent.futures.as_completed(futures):
                if abort_flag[0]:
                    ex.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    rows.append(future.result())
                except Exception as e:
                    result["errors"] += 1
                    result["error_details"].append(str(e))

        if rows:
            try:
                saved = save_map(engine, pd.DataFrame(rows))
                result["saved"] += saved
            except Exception as e:
                result["errors"] += len(rows)
                result["error_details"].append(f"DB insert failed: {e}")

        if progress_callback:
            progress_callback(
                min(batch_start + BATCH, total),
                total,
                result["saved"],
            )

    return result


def _os_walk(root_path: Path):
    """Fallback os.walk wrapper returning (Path, list, list) tuples."""
    import os
    for dirpath, dirnames, filenames in os.walk(str(root_path)):
        yield Path(dirpath), dirnames, filenames


def import_manifest(manifest_path: str,
                    filename_col: str,
                    uwi_col: str,
                    folder: str,
                    fmt: str,
                    repository_id: str = "") -> pd.DataFrame:
    """
    Load a CSV or Excel manifest that maps filenames to UWIs.

    Parameters
    ----------
    manifest_path : path to the CSV or Excel file
    filename_col  : column name containing filenames
    uwi_col       : column name containing UWIs
    folder        : base directory where the files live
    fmt           : 'DLIS', 'LIS', or 'LAS'
    repository_id : optional pre-fill

    Returns
    -------
    DataFrame with WL_FILE_UWI_MAP columns
    """
    mp = Path(manifest_path)
    if mp.suffix.lower() in (".xlsx", ".xls"):
        manifest_df = pd.read_excel(manifest_path)
    else:
        manifest_df = pd.read_csv(manifest_path)

    if filename_col not in manifest_df.columns:
        raise ValueError(f"Column '{filename_col}' not found in manifest")
    if uwi_col not in manifest_df.columns:
        raise ValueError(f"Column '{uwi_col}' not found in manifest")

    folder_path = Path(folder)
    rows = []
    now = _now_str()

    for _, mrow in manifest_df.iterrows():
        fname = str(mrow[filename_col]).strip()
        uwi   = str(mrow[uwi_col]).strip()
        if not fname or not uwi or uwi.lower() == "nan":
            continue

        fp = folder_path / fname
        map_id = _make_id(str(fp))

        rows.append({
            "MAP_ID":          map_id,
            "FILE_PATH":       str(fp),
            "FILE_NAME":       fname,
            "FILE_FORMAT":     fmt.upper(),
            "REPOSITORY_ID":   repository_id or None,
            "UWI":             uwi,
            "HEADER_WELL_ID":  None,
            "MATCH_METHOD":    "MANIFEST",
            "MATCH_SCORE":     100.0,
            "MATCH_WELL_NAME": None,
            "STATUS":          "CONFIRMED",   # manifest = high confidence
            "FILE_SIZE_KB":    round(fp.stat().st_size / 1024, 2) if fp.exists() else None,
            "REMARK":          None,
            "ROW_CREATED_BY":  "DATA_WRANGLER",
            "ROW_CREATED_DATE": now,
            "ROW_CHANGED_BY":  "DATA_WRANGLER",
            "ROW_CHANGED_DATE": now,
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Database operations
# ─────────────────────────────────────────────────────────────────────────────

def save_map(engine, df: pd.DataFrame) -> int:
    """
    Upsert staging rows to WL_FILE_UWI_MAP.
    Existing rows (same MAP_ID) are updated; new rows inserted.
    Returns count of rows saved.
    """
    from sqlalchemy import text
    import math

    if df.empty:
        return 0

    # Ensure table exists before inserting
    ensure_map_table(engine)

    def _clean(v):
        """Convert NaN/inf to None so SQL Server accepts the value."""
        if v is None:
            return None
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        # pandas NA types
        try:
            import pandas as _pd
            if _pd.isna(v):
                return None
        except Exception:
            pass
        return v

    now = _now_str()
    saved = 0

    with engine.begin() as con:
        for _, row in df.iterrows():
            exists = con.execute(text(
                "SELECT 1 FROM [las_catalog].[WL_FILE_UWI_MAP] "
                "WHERE MAP_ID = :id"
            ), {"id": row["MAP_ID"]}).scalar()

            if exists:
                con.execute(text("""
                    UPDATE [las_catalog].[WL_FILE_UWI_MAP]
                    SET UWI              = :uwi,
                        MATCH_METHOD     = :method,
                        MATCH_SCORE      = :score,
                        MATCH_WELL_NAME  = :wn,
                        STATUS           = :status,
                        REMARK           = :remark,
                        REPOSITORY_ID    = :repo,
                        ROW_CHANGED_BY   = 'DATA_WRANGLER',
                        ROW_CHANGED_DATE = :now
                    WHERE MAP_ID = :id
                """), {
                    "uwi":    _clean(row.get("UWI")),
                    "method": _clean(row.get("MATCH_METHOD")),
                    "score":  _clean(row.get("MATCH_SCORE")),
                    "wn":     _clean(row.get("MATCH_WELL_NAME")),
                    "status": _clean(row.get("STATUS", "PENDING")),
                    "remark": _clean(row.get("REMARK")),
                    "repo":   _clean(row.get("REPOSITORY_ID")),
                    "now":    now,
                    "id":     row["MAP_ID"],
                })
            else:
                cols = list(row.index)
                col_sql = ", ".join(f"[{c}]" for c in cols)
                val_sql = ", ".join(f":{c}" for c in cols)
                clean_row = {c: _clean(row[c]) for c in cols}
                con.execute(
                    text(f"INSERT INTO [las_catalog].[WL_FILE_UWI_MAP] "
                         f"({col_sql}) VALUES ({val_sql})"),
                    clean_row
                )
            saved += 1

    return saved


def load_map(engine,
             fmt: str = "",
             status: str = "",
             since: str = "") -> pd.DataFrame:
    """
    Load staging rows from WL_FILE_UWI_MAP for review.
    Optionally filter by FILE_FORMAT, STATUS, and/or ROW_CREATED_DATE >= since.
    """
    from sqlalchemy import text
    where = ["1=1"]
    params = {}
    if fmt:
        where.append("FILE_FORMAT = :fmt")
        params["fmt"] = fmt.upper()
    if status:
        where.append("STATUS = :status")
        params["status"] = status.upper()
    if since:
        where.append("ROW_CREATED_DATE >= :since")
        params["since"] = since

    with engine.connect() as con:
        rows = con.execute(text(
            f"SELECT MAP_ID, FILE_NAME, FILE_FORMAT, UWI, HEADER_WELL_ID, "
            f"MATCH_METHOD, MATCH_SCORE, MATCH_WELL_NAME, STATUS, "
            f"FILE_SIZE_KB, REMARK, FILE_PATH, REPOSITORY_ID, "
            f"CONVERT(NVARCHAR(19), ROW_CREATED_DATE, 120) AS CREATED_DATE "
            f"FROM [las_catalog].[WL_FILE_UWI_MAP] "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY ROW_CREATED_DATE DESC, FILE_FORMAT, FILE_NAME"
        ), params).fetchall()

    return pd.DataFrame(rows, columns=[
        "MAP_ID", "FILE_NAME", "FILE_FORMAT", "UWI", "HEADER_WELL_ID",
        "MATCH_METHOD", "MATCH_SCORE", "MATCH_WELL_NAME", "STATUS",
        "FILE_SIZE_KB", "REMARK", "FILE_PATH", "REPOSITORY_ID", "CREATED_DATE",
    ])


def update_uwi(engine, map_id: str, uwi: str,
               well_name: str = "") -> None:
    """Update the UWI assignment for a single staging row."""
    from sqlalchemy import text
    with engine.begin() as con:
        con.execute(text("""
            UPDATE [las_catalog].[WL_FILE_UWI_MAP]
            SET UWI              = :uwi,
                MATCH_WELL_NAME  = :wn,
                MATCH_METHOD     = 'MANUAL',
                MATCH_SCORE      = 100,
                STATUS           = 'CONFIRMED',
                ROW_CHANGED_BY   = 'DATA_WRANGLER',
                ROW_CHANGED_DATE = :now
            WHERE MAP_ID = :id
        """), {"uwi": uwi, "wn": well_name, "now": _now_str(), "id": map_id})


def confirm_rows(engine, map_ids: list[str]) -> int:
    """Mark selected rows as CONFIRMED."""
    from sqlalchemy import text
    if not map_ids:
        return 0
    now = _now_str()
    updated = 0
    with engine.begin() as con:
        for mid in map_ids:
            con.execute(text("""
                UPDATE [las_catalog].[WL_FILE_UWI_MAP]
                SET STATUS = 'CONFIRMED',
                    ROW_CHANGED_BY = 'DATA_WRANGLER',
                    ROW_CHANGED_DATE = :now
                WHERE MAP_ID = :id AND UWI IS NOT NULL
            """), {"now": now, "id": mid})
            updated += 1
    return updated


def catalog_confirmed(engine, source: str = "DATA_WRANGLER",
                      progress_callback=None) -> dict:
    """
    Catalog all CONFIRMED rows in WL_FILE_UWI_MAP.
    Calls the appropriate catalog function for each format.
    Marks successfully catalogued rows as CATALOGUED.

    progress_callback : optional callable(completed, total, filename)

    Returns { catalogued, skipped, errors, details }
    """
    from modules.dlis_catalog import catalog_dlis_file, catalog_lis_file
    from modules.las_catalog import catalog_file as catalog_las_file
    from sqlalchemy import text

    result = {
        "catalogued": 0, "skipped": 0, "errors": 0, "details": []
    }

    df = load_map(engine, status="CONFIRMED")
    if df.empty:
        return result

    now   = _now_str()
    total = len(df)

    for i, (_, row) in enumerate(df.iterrows()):
        if progress_callback:
            progress_callback(i, total, str(row["FILE_NAME"]))

        detail = {
            "file":   row["FILE_NAME"],
            "format": row["FILE_FORMAT"],
            "uwi":    row["UWI"],
            "status": "",
            "error":  "",
        }

        if not row["UWI"] or not row["REPOSITORY_ID"]:
            detail["status"] = "skipped"
            detail["error"]  = "Missing UWI or REPOSITORY_ID"
            result["skipped"] += 1
            result["details"].append(detail)
            continue

        try:
            fmt = str(row["FILE_FORMAT"]).upper()
            if fmt == "DLIS":
                r = catalog_dlis_file(
                    engine, row["FILE_PATH"], row["REPOSITORY_ID"],
                    uwi=row["UWI"], source=source
                )
            elif fmt == "LIS":
                r = catalog_lis_file(
                    engine, row["FILE_PATH"], row["REPOSITORY_ID"],
                    uwi=row["UWI"], source=source
                )
            else:  # LAS
                r = catalog_las_file(
                    engine, row["FILE_PATH"], row["REPOSITORY_ID"],
                    uwi=row["UWI"], source=source
                )

            if r["ok"]:
                with engine.begin() as con:
                    con.execute(text("""
                        UPDATE [las_catalog].[WL_FILE_UWI_MAP]
                        SET STATUS = 'CATALOGUED',
                            ROW_CHANGED_BY = 'DATA_WRANGLER',
                            ROW_CHANGED_DATE = :now
                        WHERE MAP_ID = :id
                    """), {"now": now, "id": row["MAP_ID"]})
                detail["status"] = r["action"]
                result["catalogued"] += 1
            else:
                detail["status"] = "error"
                detail["error"]  = r["error"]
                result["errors"] += 1

        except Exception as e:
            detail["status"] = "error"
            detail["error"]  = str(e)
            result["errors"] += 1

        result["details"].append(detail)

    if progress_callback:
        progress_callback(total, total, "Done")
    return result


def clear_catalogued(engine) -> int:
    """Remove all CATALOGUED rows from the staging table."""
    from sqlalchemy import text
    with engine.begin() as con:
        result = con.execute(text(
            "DELETE FROM [las_catalog].[WL_FILE_UWI_MAP] "
            "WHERE STATUS = 'CATALOGUED'"
        ))
        return result.rowcount


def skip_rows(engine, map_ids: list[str]) -> int:
    """Mark selected rows as SKIPPED."""
    from sqlalchemy import text
    if not map_ids:
        return 0
    now = _now_str()
    with engine.begin() as con:
        for mid in map_ids:
            con.execute(text("""
                UPDATE [las_catalog].[WL_FILE_UWI_MAP]
                SET STATUS = 'SKIPPED',
                    ROW_CHANGED_BY = 'DATA_WRANGLER',
                    ROW_CHANGED_DATE = :now
                WHERE MAP_ID = :id
            """), {"now": now, "id": mid})
    return len(map_ids)


def preview_rename(engine, map_ids: list[str] = None) -> pd.DataFrame:
    """
    Preview what files would be renamed — shows old name and proposed new name.
    Only includes CONFIRMED rows that have a UWI assigned.
    If map_ids is provided, only preview those rows.

    Returns DataFrame with columns:
      MAP_ID, FILE_PATH, FILE_NAME, NEW_FILE_NAME, UWI, MATCH_WELL_NAME
    """
    from sqlalchemy import text

    where = ["STATUS = 'CONFIRMED'", "UWI IS NOT NULL"]
    params = {}

    if map_ids:
        placeholders = ", ".join(f":id{i}" for i in range(len(map_ids)))
        where.append(f"MAP_ID IN ({placeholders})")
        for i, mid in enumerate(map_ids):
            params[f"id{i}"] = mid

    with engine.connect() as con:
        rows = con.execute(text(
            f"SELECT MAP_ID, FILE_PATH, FILE_NAME, UWI, MATCH_WELL_NAME "
            f"FROM [las_catalog].[WL_FILE_UWI_MAP] "
            f"WHERE {' AND '.join(where)} "
            f"ORDER BY FILE_NAME"
        ), params).fetchall()

    records = []
    for row in rows:
        map_id, file_path, file_name, uwi, well_name = row
        new_name = _build_new_filename(file_name, uwi)
        already_prefixed = file_name.startswith(uwi)
        records.append({
            "MAP_ID":          map_id,
            "FILE_PATH":       file_path,
            "FILE_NAME":       file_name,
            "NEW_FILE_NAME":   new_name,
            "UWI":             uwi,
            "MATCH_WELL_NAME": well_name,
            "ALREADY_RENAMED": already_prefixed,
        })

    return pd.DataFrame(records)


def rename_files(engine, map_ids: list[str] = None,
                 dry_run: bool = False) -> dict:
    """
    Rename CONFIRMED files by prepending the UWI to the filename.
    e.g. Chevron_A12a.DLIS → 17-031-10035-0000_Chevron_A12a.DLIS

    Rules:
    - Only renames files that don't already start with the UWI
    - Renames in place (same directory)
    - Updates FILE_PATH and FILE_NAME in WL_FILE_UWI_MAP
    - If dry_run=True, returns what would happen without doing it

    Returns { renamed, skipped, errors, details }
    """
    import os
    from sqlalchemy import text

    preview_df = preview_rename(engine, map_ids)
    result = {"renamed": 0, "skipped": 0, "errors": 0, "details": []}

    if preview_df.empty:
        return result

    now = _now_str()

    for _, row in preview_df.iterrows():
        detail = {
            "old_name": row["FILE_NAME"],
            "new_name": row["NEW_FILE_NAME"],
            "uwi":      row["UWI"],
            "status":   "",
            "error":    "",
        }

        if row["ALREADY_RENAMED"]:
            detail["status"] = "skipped — already prefixed"
            result["skipped"] += 1
            result["details"].append(detail)
            continue

        old_path = Path(row["FILE_PATH"])
        new_path = old_path.parent / row["NEW_FILE_NAME"]

        if dry_run:
            detail["status"] = "would rename"
            result["renamed"] += 1
            result["details"].append(detail)
            continue

        if not old_path.exists():
            detail["status"] = "error"
            detail["error"]  = "Source file not found"
            result["errors"] += 1
            result["details"].append(detail)
            continue

        if new_path.exists():
            detail["status"] = "error"
            detail["error"]  = f"Target already exists: {new_path.name}"
            result["errors"] += 1
            result["details"].append(detail)
            continue

        try:
            os.rename(str(old_path), str(new_path))

            # Update staging table
            with engine.begin() as con:
                con.execute(text("""
                    UPDATE [las_catalog].[WL_FILE_UWI_MAP]
                    SET FILE_PATH        = :new_path,
                        FILE_NAME        = :new_name,
                        MATCH_METHOD     = COALESCE(MATCH_METHOD, '') + '+RENAMED',
                        ROW_CHANGED_BY   = 'DATA_WRANGLER',
                        ROW_CHANGED_DATE = :now
                    WHERE MAP_ID = :id
                """), {
                    "new_path": str(new_path),
                    "new_name": row["NEW_FILE_NAME"],
                    "now":      now,
                    "id":       row["MAP_ID"],
                })

            detail["status"] = "renamed"
            result["renamed"] += 1

        except Exception as e:
            detail["status"] = "error"
            detail["error"]  = str(e)
            result["errors"] += 1

        result["details"].append(detail)

    return result


def _build_new_filename(original_name: str, uwi: str) -> str:
    """
    Construct the new filename by prepending UWI.
    Sanitises UWI for use in a filename (replaces / with -).
    e.g. ('Chevron_A12a.DLIS', '17-031-10035-0000') →
         '17-031-10035-0000_Chevron_A12a.DLIS'
    """
    safe_uwi = uwi.replace("/", "-").replace("\\", "-").strip()
    p = Path(original_name)
    return f"{safe_uwi}_{p.name}"


def ensure_map_table(engine) -> bool:
    """Create WL_FILE_UWI_MAP if it doesn't exist. Returns True if created."""
    from sqlalchemy import text
    with engine.connect() as con:
        exists = con.execute(text(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = 'las_catalog' "
            "AND TABLE_NAME = 'WL_FILE_UWI_MAP'"
        )).scalar()
    if exists:
        return False

    with engine.begin() as con:
        con.execute(text("""
            CREATE TABLE [las_catalog].[WL_FILE_UWI_MAP] (
                [MAP_ID]           NVARCHAR(40)   NOT NULL,
                [FILE_PATH]        NVARCHAR(500)  NOT NULL,
                [FILE_NAME]        NVARCHAR(255)  NOT NULL,
                [FILE_FORMAT]      NVARCHAR(10)   NOT NULL,
                [REPOSITORY_ID]    NVARCHAR(40)   NULL,
                [UWI]              NVARCHAR(40)   NULL,
                [HEADER_WELL_ID]   NVARCHAR(255)  NULL,
                [MATCH_METHOD]     NVARCHAR(20)   NULL,
                [MATCH_SCORE]      NUMERIC(5,1)   NULL,
                [MATCH_WELL_NAME]  NVARCHAR(255)  NULL,
                [STATUS]           NVARCHAR(20)   NOT NULL DEFAULT 'PENDING',
                [FILE_SIZE_KB]     NUMERIC(15,2)  NULL,
                [REMARK]           NVARCHAR(2000) NULL,
                [ROW_CREATED_BY]   NVARCHAR(30)   NULL,
                [ROW_CREATED_DATE] DATETIME2      NULL,
                [ROW_CHANGED_BY]   NVARCHAR(30)   NULL,
                [ROW_CHANGED_DATE] DATETIME2      NULL,
                CONSTRAINT [WLMAP_PK] PRIMARY KEY ([MAP_ID]),
                CONSTRAINT [WLMAP_REP_FK] FOREIGN KEY ([REPOSITORY_ID])
                    REFERENCES [las_catalog].[WL_REPOSITORY] ([REPOSITORY_ID])
            )
        """))
        con.execute(text(
            "CREATE INDEX [WLMAP_STATUS_IDX] "
            "ON [las_catalog].[WL_FILE_UWI_MAP] ([STATUS], [FILE_FORMAT])"
        ))
    return True

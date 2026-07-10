"""
curve_registry.py
==================
Build a *log-curve registry* — the inventory of curves/channels in each
well-log file (mnemonic, unit, description, depth interval, sample count) —
and persist it to ``file_catalog.cat_log_curve``.

Design notes
------------
* This stores **metadata only**.  Bulk curve samples are never loaded; the
  vaulted file on disk remains the authoritative source of curve data.  The
  registry answers "which curves, what units, over what depth interval" for
  search, QC and exporter selection.
* The actual format reading is delegated to the proven parsers already in the
  project — ``las_catalog.parse_las_header`` for LAS and
  ``dlis_catalog.parse_dlis_header`` / ``parse_lis_header`` for the binary
  formats — so all ``lasio`` / ``dlisio`` calls live in one place.
* One row per curve (LAS), per channel-per-frame (DLIS), or per channel (LIS).

Public API
----------
    extract_curves(fpath, fext)            -> list[dict]   (parse only)
    write_registry(engine, inventory_id, rows) -> int      (delete+insert)
    ensure_table(engine)                   -> None
    CAT_LOG_CURVE_DDL                      -> str          (standalone DDL)
"""

from __future__ import annotations

LAS_EXTS  = {".las"}
DLIS_EXTS = {".dlis", ".dlf", ".dis"}
LIS_EXTS  = {".lis"}
LOG_EXTS  = LAS_EXTS | DLIS_EXTS | LIS_EXTS


# ── table DDL ───────────────────────────────────────────────────────────────
CAT_LOG_CURVE_DDL = """
IF NOT EXISTS (SELECT 1 FROM sys.tables t
               JOIN sys.schemas s ON s.schema_id = t.schema_id
               WHERE s.name = 'file_catalog' AND t.name = 'cat_log_curve')
BEGIN
    CREATE TABLE file_catalog.cat_log_curve (
        CURVE_ROW_ID    BIGINT IDENTITY(1,1) NOT NULL
                        CONSTRAINT PK_cat_log_curve PRIMARY KEY,
        INVENTORY_ID    VARCHAR(40)   NOT NULL,
        UWI             VARCHAR(64)   NULL,
        UWI14           VARCHAR(14)   NULL,
        SOURCE_FORMAT   VARCHAR(8)    NULL,   -- LAS / DLIS / LIS
        LOGICAL_FILE    INT           NULL,   -- DLIS logical-file ordinal
        FRAME_NAME      VARCHAR(128)  NULL,   -- DLIS frame name
        CURVE_INDEX     INT           NULL,   -- ordinal within file/frame
        CURVE_MNEMONIC  VARCHAR(64)   NOT NULL,
        CURVE_LONG_NAME VARCHAR(256)  NULL,
        CURVE_UNIT      VARCHAR(32)   NULL,
        API_CODE        VARCHAR(32)   NULL,   -- LAS curve API code, if present
        CURVE_DIMENSION VARCHAR(32)   NULL,   -- DLIS dimension, e.g. '[1]'
        IS_INDEX        CHAR(1)       NULL,   -- Y/N  (depth/index curve)
        DEPTH_UOM       VARCHAR(16)   NULL,
        DEPTH_START     FLOAT         NULL,
        DEPTH_STOP      FLOAT         NULL,
        DEPTH_STEP      FLOAT         NULL,
        SAMPLE_COUNT    INT           NULL,
        NULL_VALUE      FLOAT         NULL,
        CREATED_AT      DATETIME2     NOT NULL
                        CONSTRAINT DF_cat_log_curve_created DEFAULT SYSUTCDATETIME()
    );
    CREATE INDEX IX_cat_log_curve_inv   ON file_catalog.cat_log_curve(INVENTORY_ID);
    CREATE INDEX IX_cat_log_curve_uwi14 ON file_catalog.cat_log_curve(UWI14);
    CREATE INDEX IX_cat_log_curve_mnem  ON file_catalog.cat_log_curve(CURVE_MNEMONIC);
END
"""

_INSERT_SQL = """
INSERT INTO file_catalog.cat_log_curve
    (INVENTORY_ID, UWI, UWI14, SOURCE_FORMAT, LOGICAL_FILE, FRAME_NAME,
     CURVE_INDEX, CURVE_MNEMONIC, CURVE_LONG_NAME, CURVE_UNIT, API_CODE,
     CURVE_DIMENSION, IS_INDEX, DEPTH_UOM, DEPTH_START, DEPTH_STOP,
     DEPTH_STEP, SAMPLE_COUNT, NULL_VALUE)
VALUES
    (:inv, :uwi, :uwi14, :fmt, :lf, :frame,
     :idx, :mnem, :long, :unit, :api,
     :dim, :isidx, :duom, :dstart, :dstop,
     :dstep, :scount, :nullv)
"""


# ── helpers ─────────────────────────────────────────────────────────────────
def _s(v, maxlen=None):
    """Trimmed string or None."""
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    return s[:maxlen] if maxlen else s


def _f(v):
    """Float or None (tolerant)."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # guard against NaN / inf leaking into FLOAT columns
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _i(v):
    """Int or None (tolerant)."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def _row(**kw):
    """Normalised registry row with all keys present."""
    return {
        "source_format": kw.get("source_format"),
        "logical_file":  _i(kw.get("logical_file")),
        "frame_name":    _s(kw.get("frame_name"), 128),
        "curve_index":   _i(kw.get("curve_index")),
        "mnemonic":      _s(kw.get("mnemonic"), 64),
        "long_name":     _s(kw.get("long_name"), 256),
        "unit":          _s(kw.get("unit"), 32),
        "api_code":      _s(kw.get("api_code"), 32),
        "dimension":     _s(kw.get("dimension"), 32),
        "is_index":      (kw.get("is_index") or "N")[:1].upper(),
        "depth_uom":     _s(kw.get("depth_uom"), 16),
        "depth_start":   _f(kw.get("depth_start")),
        "depth_stop":    _f(kw.get("depth_stop")),
        "depth_step":    _f(kw.get("depth_step")),
        "sample_count":  _i(kw.get("sample_count")),
        "null_value":    _f(kw.get("null_value")),
    }


# ── per-format extraction (reuses the project's proven parsers) ──────────────
def _from_las(fpath):
    from modules.las_catalog import parse_las_header
    h = parse_las_header(fpath)
    rows = []
    for i, c in enumerate(h.get("curves") or []):
        rows.append(_row(
            source_format="LAS",
            curve_index=i,
            mnemonic=c.get("mnemonic"),
            long_name=c.get("description"),
            unit=c.get("unit"),
            api_code=c.get("api_code"),
            is_index="Y" if c.get("type") == "DEPT" else "N",
            depth_uom=h.get("depth_uom"),
            depth_start=h.get("top_depth"),
            depth_stop=h.get("base_depth"),
            depth_step=h.get("depth_step"),
            sample_count=h.get("sample_count"),
            null_value=h.get("null_value"),
        ))
    return rows


def _from_dlis(fpath):
    from modules.dlis_catalog import parse_dlis_header
    h = parse_dlis_header(fpath)             # full parse (need channels)
    rows = []
    for lf in h.get("logical_files") or []:
        lf_idx = lf.get("index")
        for fr in lf.get("frames") or []:
            for i, ch in enumerate(fr.get("channels") or []):
                rows.append(_row(
                    source_format="DLIS",
                    logical_file=lf_idx,
                    frame_name=fr.get("name"),
                    curve_index=i,
                    mnemonic=ch.get("name"),
                    long_name=ch.get("long_name"),
                    unit=ch.get("units"),
                    dimension=ch.get("dimension"),
                    is_index=ch.get("is_index") or "N",
                    depth_uom=fr.get("depth_uom"),
                    depth_start=fr.get("top_depth"),
                    depth_stop=fr.get("base_depth"),
                    depth_step=fr.get("spacing"),
                    sample_count=fr.get("sample_count"),
                ))
    return rows


def _from_lis(fpath):
    from modules.dlis_catalog import parse_lis_header
    h = parse_lis_header(fpath)
    rows = []
    for i, ch in enumerate(h.get("channels") or []):
        rows.append(_row(
            source_format="LIS",
            curve_index=i,
            mnemonic=ch.get("name"),
            unit=ch.get("units"),
            is_index=ch.get("is_index") or "N",
            depth_uom=h.get("depth_uom"),
            depth_start=h.get("top_depth"),
            depth_stop=h.get("base_depth"),
            sample_count=h.get("sample_count"),
        ))
    return rows


def extract_curves(fpath, fext):
    """Return a list of registry-row dicts for one log file.

    Empty list for unsupported extensions or unreadable files.  Never raises —
    a parse failure yields ``[]`` so the batch promote keeps moving (the file
    still vaults; only its curve registry is skipped).
    """
    fext = (fext or "").lower()
    try:
        if fext in LAS_EXTS:
            return _from_las(fpath)
        if fext in DLIS_EXTS:
            return _from_dlis(fpath)
        if fext in LIS_EXTS:
            return _from_lis(fpath)
    except Exception:
        return []
    return []


# ── persistence ─────────────────────────────────────────────────────────────
def ensure_table(engine):
    """Create file_catalog.cat_log_curve (+ indexes) if it does not exist."""
    from sqlalchemy import text
    with engine.begin() as con:
        con.execute(text(CAT_LOG_CURVE_DDL))


def write_registry(engine, inventory_id, rows):
    """Replace the curve registry for one file (delete-then-insert, idempotent).

    The file's UWI / UWI14 are read from FILE_WELL_HEADER so the registry
    carries the *resolved* identity (matching what triage produced), not the
    raw value embedded in the log.  Returns the number of curve rows written.
    """
    if not inventory_id:
        return 0
    from sqlalchemy import text
    ensure_table(engine)

    with engine.begin() as con:
        idr = con.execute(text(
            "SELECT TOP 1 UWI, UWI14 FROM file_catalog.FILE_WELL_HEADER "
            "WHERE INVENTORY_ID = :i"), {"i": inventory_id}).fetchone()
        uwi   = idr[0] if idr else None
        uwi14 = idr[1] if idr else None

        # idempotent: clear any prior registry for this file first
        con.execute(text("DELETE FROM file_catalog.cat_log_curve "
                         "WHERE INVENTORY_ID = :i"), {"i": inventory_id})

        rows = [r for r in (rows or []) if r.get("mnemonic")]
        if not rows:
            return 0

        params = [{
            "inv":    inventory_id,
            "uwi":    uwi,
            "uwi14":  uwi14,
            "fmt":    r.get("source_format"),
            "lf":     r.get("logical_file"),
            "frame":  r.get("frame_name"),
            "idx":    r.get("curve_index"),
            "mnem":   r.get("mnemonic"),
            "long":   r.get("long_name"),
            "unit":   r.get("unit"),
            "api":    r.get("api_code"),
            "dim":    r.get("dimension"),
            "isidx":  r.get("is_index"),
            "duom":   r.get("depth_uom"),
            "dstart": r.get("depth_start"),
            "dstop":  r.get("depth_stop"),
            "dstep":  r.get("depth_step"),
            "scount": r.get("sample_count"),
            "nullv":  r.get("null_value"),
        } for r in rows]

        con.execute(text(_INSERT_SQL), params)   # executemany
    return len(rows)

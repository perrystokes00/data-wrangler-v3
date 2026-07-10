"""
modules/h3_grids.py
===================
H3 hexagonal indexing for DataView v3 (SQL Server Express).

Two layers:

  Layer A — per-well assignment
      Compute h3_r4..h3_r7 (+ h3_coord_hash) for each well from
      surface_latitude / surface_longitude and write them onto dv_well.
      Used both inline at promote time and as a standalone backfill.

  Layer B — density grids
      Aggregate wells by H3 cell (GROUP BY h3_rN) and emit a GeoJSON
      FeatureCollection of hexagon polygons + counts for the well map.

SQL Server has no native H3, so cells are computed in Python via the
`h3` package. This module is version-agnostic: it works against either
the h3 v4 API (latlng_to_cell / cell_to_boundary) or the legacy v3 API
(geo_to_h3 / h3_to_geo_boundary).

Backfill writes follow the documented SQL-Express lesson: NEVER per-row
UPDATE loops. Computed values land in a staging table, then a single
set-based UPDATE ... FROM ... JOIN applies them.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

import pandas as pd
from sqlalchemy import text

# Resolutions we materialize. Mirrors the dv_well columns h3_r4..h3_r7.
RESOLUTIONS = (4, 5, 6, 7)
H3_COLUMNS = tuple(f"h3_r{r}" for r in RESOLUTIONS)   # ('h3_r4', ... 'h3_r7')
COORD_HASH_COLUMN = "h3_coord_hash"


# ─────────────────────────────────────────────────────────────────────────
# h3 version compat shim
# ─────────────────────────────────────────────────────────────────────────
def _bind_h3():
    """Return (latlng_to_cell, cell_to_boundary_lnglat) bound to whichever
    h3 API is installed. cell_to_boundary_lnglat always yields a CLOSED ring
    of [lng, lat] pairs (GeoJSON order)."""
    import h3

    if hasattr(h3, "latlng_to_cell"):          # h3 v4
        def to_cell(lat, lng, res):
            return h3.latlng_to_cell(lat, lng, res)

        def to_ring(cell):
            # v4 returns (lat, lng) tuples; swap to (lng, lat) for GeoJSON
            ring = [[lng, lat] for (lat, lng) in h3.cell_to_boundary(cell)]
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])           # close the polygon
            return ring

    elif hasattr(h3, "geo_to_h3"):             # h3 v3
        def to_cell(lat, lng, res):
            return h3.geo_to_h3(lat, lng, res)

        def to_ring(cell):
            # v3 with geo_json=True already returns (lng, lat) and closes
            ring = [list(p) for p in h3.h3_to_geo_boundary(cell, geo_json=True)]
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            return ring
    else:
        raise ImportError(
            "h3 package present but neither v4 (latlng_to_cell) nor "
            "v3 (geo_to_h3) API found.")

    return to_cell, to_ring


# ─────────────────────────────────────────────────────────────────────────
# coordinate hash — matches the WranglerView formula exactly
#   SHA256(f"{lat}|{lon}").hexdigest().upper()  using Python's default float repr
# ─────────────────────────────────────────────────────────────────────────
def coord_hash(lat, lon) -> Optional[str]:
    if lat is None or lon is None:
        return None
    try:
        key = f"{float(lat)}|{float(lon)}"
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(key.encode("utf-8")).hexdigest().upper()


def _valid_lat_lon(lat, lon) -> bool:
    try:
        lat = float(lat); lon = float(lon)
    except (TypeError, ValueError):
        return False
    if lat != lat or lon != lon:               # NaN
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def compute_h3_row(lat, lon, to_cell=None) -> dict:
    """Return {h3_r4:.., h3_r5:.., h3_r6:.., h3_r7:.., h3_coord_hash:..}
    for one coordinate pair. All-None if lat/lon are missing/invalid."""
    if to_cell is None:
        to_cell, _ = _bind_h3()
    if not _valid_lat_lon(lat, lon):
        return {c: None for c in H3_COLUMNS} | {COORD_HASH_COLUMN: None}
    lat = float(lat); lon = float(lon)
    out = {f"h3_r{r}": to_cell(lat, lon, r) for r in RESOLUTIONS}
    out[COORD_HASH_COLUMN] = coord_hash(lat, lon)
    return out


# ─────────────────────────────────────────────────────────────────────────
# Layer A — backfill dv_well.h3_* from surface coordinates
# ─────────────────────────────────────────────────────────────────────────
def backfill_h3(engine,
                schema: str = "dataview",
                table: str = "dv_well",
                lat_col: str = "surface_latitude",
                lon_col: str = "surface_longitude",
                key_col: str = "uwi",
                stg_schema: str = "stg",
                only_missing: bool = True,
                chunksize: int = 1000) -> dict:
    """Compute H3 cells for wells and apply them with a single set-based
    UPDATE ... JOIN (no per-row loop).

    only_missing=True  -> only wells where h3_r5 IS NULL (and coords present)
    only_missing=False -> recompute all wells that have coordinates

    Returns {'candidates': n, 'updated': n}.
    """
    to_cell, _ = _bind_h3()

    where_missing = f"AND t.h3_r5 IS NULL" if only_missing else ""
    sel = text(
        f"SELECT t.[{key_col}] AS k, t.[{lat_col}] AS lat, t.[{lon_col}] AS lon "
        f"FROM [{schema}].[{table}] t "
        f"WHERE t.[{lat_col}] IS NOT NULL AND t.[{lon_col}] IS NOT NULL "
        f"{where_missing}")

    with engine.connect() as conn:
        df = pd.read_sql(sel, conn)

    if df.empty:
        return {"candidates": 0, "updated": 0}

    # Compute in Python (h3 v4 base API is scalar; loop is fine at this scale)
    recs = []
    for k, lat, lon in zip(df["k"], df["lat"], df["lon"]):
        row = compute_h3_row(lat, lon, to_cell=to_cell)
        row[key_col] = k
        recs.append(row)
    stage_df = pd.DataFrame.from_records(recs)

    stg_table = f"{table}_h3_stage"
    cols = list(H3_COLUMNS) + [COORD_HASH_COLUMN]
    set_clause = ", ".join(f"t.[{c}] = s.[{c}]" for c in cols)

    # Stage, then one set-based UPDATE...JOIN.
    stage_df.to_sql(stg_table, engine, schema=stg_schema,
                    if_exists="replace", index=False, chunksize=chunksize)

    with engine.begin() as conn:
        result = conn.execute(text(
            f"UPDATE t SET {set_clause} "
            f"FROM [{schema}].[{table}] t "
            f"JOIN [{stg_schema}].[{stg_table}] s "
            f"  ON t.[{key_col}] = s.[{key_col}]"))
        updated = result.rowcount
        conn.execute(text(f"DROP TABLE [{stg_schema}].[{stg_table}]"))

    return {"candidates": len(stage_df), "updated": int(updated)}


# ─────────────────────────────────────────────────────────────────────────
# Layer B — density grid as GeoJSON
# ─────────────────────────────────────────────────────────────────────────
def fetch_cell_counts(engine, resolution: int,
                      schema: str = "dataview",
                      table: str = "dv_well",
                      where: Optional[str] = None) -> pd.DataFrame:
    """Return DataFrame[cell, n] of well counts per H3 cell at `resolution`.
    `where` is an optional extra predicate (without the WHERE keyword),
    e.g. \"source = 'KGS'\"."""
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution must be one of {RESOLUTIONS}")
    col = f"h3_r{resolution}"
    extra = f"AND ({where})" if where else ""
    sql = text(
        f"SELECT [{col}] AS cell, COUNT(*) AS n "
        f"FROM [{schema}].[{table}] "
        f"WHERE [{col}] IS NOT NULL {extra} "
        f"GROUP BY [{col}]")
    with engine.connect() as conn:
        return pd.read_sql(sql, conn)


def cell_counts_to_geojson(counts: pd.DataFrame, to_ring=None) -> dict:
    """Turn a DataFrame[cell, n] into a GeoJSON FeatureCollection of
    hexagon polygons with a `count` property."""
    if to_ring is None:
        _, to_ring = _bind_h3()
    features = []
    for cell, n in zip(counts["cell"], counts["n"]):
        if cell is None or pd.isna(cell):
            continue
        cell = str(cell)
        features.append({
            "type": "Feature",
            "properties": {"h3": cell, "count": int(n)},
            "geometry": {"type": "Polygon", "coordinates": [to_ring(cell)]},
        })
    return {"type": "FeatureCollection", "features": features}


def build_density_grid(engine, resolution: int,
                       schema: str = "dataview",
                       table: str = "dv_well",
                       where: Optional[str] = None) -> dict:
    """One-call density grid: aggregate + GeoJSON for the given resolution."""
    counts = fetch_cell_counts(engine, resolution, schema, table, where)
    return cell_counts_to_geojson(counts)


def write_grid_geojson(engine, path: str, resolution: int, **kw) -> int:
    """Build a density grid and write it to `path`. Returns feature count."""
    fc = build_density_grid(engine, resolution, **kw)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh)
    return len(fc["features"])


# ─────────────────────────────────────────────────────────────────────────
# DDL helper (idempotent) — add the H3 columns + GROUP BY indexes if missing
# ─────────────────────────────────────────────────────────────────────────
def has_coord_columns(engine, schema: str = "dataview", table: str = "dv_well",
                      lat_col: str = "surface_latitude",
                      lon_col: str = "surface_longitude") -> bool:
    """True only if `table` has BOTH coordinate columns. Use this to gate the
    auto-population so it never adds H3 columns to non-well tables in other
    projects/databases."""
    with engine.connect() as conn:
        n = conn.execute(text(
            "SELECT COUNT(*) FROM sys.columns "
            "WHERE object_id = OBJECT_ID(:o) AND name IN (:lat, :lon)"),
            {"o": f"{schema}.{table}", "lat": lat_col, "lon": lon_col}).scalar()
    return (n or 0) >= 2


def ensure_h3_columns(engine, schema: str = "dataview",
                      table: str = "dv_well") -> list:
    """Add h3_r4..h3_r7 (VARCHAR(16)) + h3_coord_hash (CHAR(64)) and indexes
    on h3_r5/h3_r6 if they don't already exist. Returns the list of objects
    actually created."""
    created = []
    coldefs = [(c, "VARCHAR(16) NULL") for c in H3_COLUMNS]
    coldefs.append((COORD_HASH_COLUMN, "CHAR(64) NULL"))
    with engine.begin() as conn:
        for col, decl in coldefs:
            exists = conn.execute(text(
                "SELECT 1 FROM sys.columns "
                "WHERE object_id = OBJECT_ID(:o) AND name = :c"),
                {"o": f"{schema}.{table}", "c": col}).fetchone()
            if not exists:
                conn.execute(text(
                    f"ALTER TABLE [{schema}].[{table}] ADD [{col}] {decl}"))
                created.append(col)
        for res in (5, 6):
            idx = f"IX_{table}_h3_r{res}"
            has_idx = conn.execute(text(
                "SELECT 1 FROM sys.indexes WHERE name = :n "
                "AND object_id = OBJECT_ID(:o)"),
                {"n": idx, "o": f"{schema}.{table}"}).fetchone()
            if not has_idx:
                conn.execute(text(
                    f"CREATE NONCLUSTERED INDEX [{idx}] "
                    f"ON [{schema}].[{table}] ([h3_r{res}])"))
                created.append(idx)
    return created

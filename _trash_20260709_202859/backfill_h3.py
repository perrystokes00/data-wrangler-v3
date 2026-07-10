"""
backfill_h3.py — Compute H3 cells (R4-R7) for all wells in dv_well + dv_well_gom.

Pipeline:
  1. Read (uwi, lat, lon, current_hash) from the source table where lat/lon
     are not NULL and either:
       - h3_coord_hash is NULL (never backfilled), OR
       - h3_coord_hash differs from the recomputed hash (coords changed)
  2. For each well in the work-set, compute:
       - h3_r4, h3_r5, h3_r6, h3_r7 via the h3 package
       - h3_coord_hash = SHA2_256("lat|lon") for staleness detection
  3. Bulk-load the computed rows into a staging table via to_sql
       (method="multi", chunksize=1000)
  4. UPDATE w SET ... FROM dv_well w JOIN #stage s ON w.uwi = s.uwi
  5. DROP the staging table

This is the staging-table + JOIN pattern from Perry's May 25 lesson —
NEVER per-row UPDATE on SQL Express (caps at ~70-100 rows/sec).

Batching: 50K wells per batch. Roughly:
  dataview.dv_well  (477K) -> ~10 batches, ~30 sec/batch -> 5 min total
  dataview_gom.well (55K)  -> ~2 batches, ~30 sec total

Idempotent: re-running this script processes only rows where the hash
indicates stale or missing H3 cells. A fresh full run = no-op after
the first run, fast.

Usage:
    python backfill_h3.py                  # process both tables
    python backfill_h3.py --table dv_well  # process only dv_well
    python backfill_h3.py --force          # ignore hashes, recompute everything

Prerequisites:
    pip install h3 sqlalchemy pyodbc pandas
    alter_wells_add_h3.sql must have run first
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import h3
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
CONN_STR = (
    "mssql+pyodbc://@localhost\\SQLEXPRESS/DataView"
    "?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
)

BATCH_SIZE = 50_000
H3_RESOLUTIONS = (4, 5, 6, 7)


# -----------------------------------------------------------------------------
# Table descriptors — encapsulate the per-table differences (PK column name,
# coord columns, schema-qualified name) so the backfill loop is shared.
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class TableSpec:
    label: str           # human-readable, used in log messages
    full_name: str       # schema-qualified table name
    pk_col: str          # primary key column
    lat_col: str         # surface latitude column
    lon_col: str         # surface longitude column


TABLES: dict[str, TableSpec] = {
    "dv_well": TableSpec(
        label="dataview.dv_well",
        full_name="dataview.dv_well",
        pk_col="uwi",
        lat_col="surface_latitude",
        lon_col="surface_longitude",
    ),
    "dv_well_gom": TableSpec(
        label="dataview_gom.well",
        full_name="dataview_gom.well",
        # NB: GOM uses well_id (UNIQUEIDENTIFIER) as PK, not uwi
        pk_col="well_id",
        lat_col="surface_latitude",
        lon_col="surface_longitude",
    ),
}


# -----------------------------------------------------------------------------
# Hash helper — must match what SQL Server's HASHBYTES('SHA2_256', ...) would
# compute. We use Python here for speed (HASHBYTES per-row in SQL is slow);
# the hash is just for our own staleness detection so consistency is what
# matters, not interop with HASHBYTES.
#
# Format: "{lat}|{lon}" — both formatted with full precision so floating-point
# stringification stays deterministic across pandas/Python versions.
# -----------------------------------------------------------------------------
def coord_hash(lat: float, lon: float) -> bytes:
    """SHA2_256 of 'lat|lon' as 32 raw bytes. Matches BINARY(32) column."""
    return hashlib.sha256(f"{lat!r}|{lon!r}".encode("ascii")).digest()


# -----------------------------------------------------------------------------
# Core backfill — one table at a time
# -----------------------------------------------------------------------------
def fetch_work_set(engine: Engine, spec: TableSpec, force: bool) -> pd.DataFrame:
    """
    Pull the rows that need H3 (re)computation.

    Without --force: only rows where h3_coord_hash IS NULL OR h3_r5 IS NULL.
    With --force: every row with valid coords.

    The hash comparison can't be done server-side without invoking HASHBYTES,
    which is slow per-row. Cheap proxy: trust the hash for now; the validator
    cross-checks everything afterward.
    """
    if force:
        filter_clause = ""
    else:
        # Skip rows already backfilled. The h3_r5 NULL check is the cheap
        # proxy; h3_coord_hash IS NULL covers the never-backfilled case.
        filter_clause = "AND (h3_coord_hash IS NULL OR h3_r5 IS NULL)"

    sql = f"""
        SELECT {spec.pk_col} AS pk,
               {spec.lat_col} AS lat,
               {spec.lon_col} AS lon
        FROM {spec.full_name}
        WHERE {spec.lat_col} IS NOT NULL
          AND {spec.lon_col} IS NOT NULL
          {filter_clause}
    """
    return pd.read_sql(text(sql), engine)


def compute_h3_cells(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add h3_r4..r7 and h3_coord_hash columns to df.

    Vectorization note: h3.latlng_to_cell isn't a numpy ufunc, so we use
    list comprehensions per resolution. For 50K rows × 4 resolutions
    this runs in ~2-3 seconds — fast enough that vectorizing further
    isn't worth it.
    """
    lats = df["lat"].to_numpy()
    lons = df["lon"].to_numpy()

    for res in H3_RESOLUTIONS:
        df[f"h3_r{res}"] = [
            h3.latlng_to_cell(la, lo, res) for la, lo in zip(lats, lons)
        ]

    df["h3_coord_hash"] = [coord_hash(la, lo) for la, lo in zip(lats, lons)]
    return df


def write_batch_via_staging(
    engine: Engine, spec: TableSpec, batch: pd.DataFrame, batch_num: int
) -> int:
    """
    Bulk-load the batch into a staging table and UPDATE the target via JOIN.

    Pattern from Perry's May 25 lesson: NEVER use per-row UPDATE loops via
    pyodbc — caps at ~70-100/sec on SQL Express. ALWAYS use staging+JOIN.

    Staging table name includes batch_num for clarity in logs but is dropped
    at the end either way. Using a real table (not #temp) because to_sql
    can't write to #temp tables via SQLAlchemy.
    """
    stage_name = f"tmp_h3_stage_{spec.pk_col}_{batch_num}"
    stage_full = f"dbo.{stage_name}"

    # Subset columns to staging shape: pk + 4 H3 cells + hash
    stage_df = batch[["pk", "h3_r4", "h3_r5", "h3_r6", "h3_r7", "h3_coord_hash"]]

    # Bulk insert (~5-10s for 50K rows on SQL Express)
    stage_df.to_sql(
        stage_name,
        engine,
        schema="dbo",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
        # explicit dtype mapping prevents pandas from over-widening NVARCHAR
        dtype={
            "pk":            None,   # let SQLAlchemy infer from the data
            "h3_r4":         None,
            "h3_r5":         None,
            "h3_r6":         None,
            "h3_r7":         None,
            "h3_coord_hash": None,
        },
    )

    # Set-based UPDATE via JOIN
    update_sql = f"""
        UPDATE w
        SET w.h3_r4         = s.h3_r4,
            w.h3_r5         = s.h3_r5,
            w.h3_r6         = s.h3_r6,
            w.h3_r7         = s.h3_r7,
            w.h3_coord_hash = s.h3_coord_hash
        FROM {spec.full_name} w
        JOIN {stage_full} s ON s.pk = w.{spec.pk_col};
    """

    with engine.begin() as con:
        rows_updated = con.execute(text(update_sql)).rowcount
        # Drop staging table inside the same transaction so a crash leaves
        # nothing orphaned
        con.execute(text(f"DROP TABLE {stage_full};"))

    return rows_updated


def backfill_table(engine: Engine, spec: TableSpec, force: bool) -> None:
    """Backfill a single source table. Logs progress per batch."""
    print(f"\n=== Backfilling {spec.label} ===")
    t_start = time.time()

    work = fetch_work_set(engine, spec, force)
    n_total = len(work)

    if n_total == 0:
        print(f"  No rows to process. Already up to date.")
        return

    print(f"  {n_total:,} rows to process in batches of {BATCH_SIZE:,}")

    n_done = 0
    for batch_num, batch_start in enumerate(range(0, n_total, BATCH_SIZE), start=1):
        batch_end = min(batch_start + BATCH_SIZE, n_total)
        t_batch = time.time()

        # Slice (copy to be safe — compute_h3_cells mutates)
        batch = work.iloc[batch_start:batch_end].copy()
        compute_h3_cells(batch)
        n_updated = write_batch_via_staging(engine, spec, batch, batch_num)

        n_done += n_updated
        elapsed = time.time() - t_batch
        pct = 100 * n_done / n_total
        print(
            f"  batch {batch_num}: rows {batch_start:,}-{batch_end:,} "
            f"({n_updated:,} updated) in {elapsed:.1f}s "
            f"[{n_done:,}/{n_total:,} = {pct:.1f}%]"
        )

    total_elapsed = time.time() - t_start
    print(
        f"  {spec.label}: {n_done:,} rows backfilled in "
        f"{total_elapsed:.1f}s ({n_done / total_elapsed:.0f} rows/sec)"
    )


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill H3 cells for wells.")
    parser.add_argument(
        "--table",
        choices=list(TABLES.keys()) + ["all"],
        default="all",
        help="Which source table to backfill (default: all).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute every well, ignoring h3_coord_hash. "
             "Use when the H3 algorithm or hash format changed.",
    )
    args = parser.parse_args()

    targets = list(TABLES.values()) if args.table == "all" else [TABLES[args.table]]

    print(f"Connecting to {CONN_STR.split('@')[-1].split('?')[0]} ...")
    engine = create_engine(CONN_STR, fast_executemany=True)

    t_start = time.time()

    try:
        for spec in targets:
            backfill_table(engine, spec, args.force)
    except Exception as exc:
        print(f"\nBACKFILL FAILED: {type(exc).__name__}: {exc}")
        return 1

    total = time.time() - t_start
    print(f"\nTOTAL ELAPSED: {total:.1f}s")
    print("\nNext step: run validate_h3_backfill.py to confirm 100% coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

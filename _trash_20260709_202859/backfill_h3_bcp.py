"""
backfill_h3_bcp.py — Compute H3 cells for all wells via BCP bypass.

Replaces backfill_h3.py, which hung on a 477K-row pyodbc SELECT
(ASYNC_NETWORK_IO wait, 41 minutes elapsed at 2.86s CPU — pyodbc
was the bottleneck, not SQL Server).

This version routes around pyodbc for the bulk transfers:

    1. BCP OUT     : SQL Server → CSV         (native, no pyodbc)
    2. Python H3   : CSV → CSV with cells     (pandas + h3, no DB)
    3. BCP IN      : CSV → staging table      (native, no pyodbc)
    4. UPDATE JOIN : staging → target table   (set-based SQL, small pyodbc call)
    5. Cleanup     : drop staging, remove CSVs

The pyodbc surface shrinks from "fetch 477K rows" (hangs) to
"execute one UPDATE statement" (instant). BCP carries the bulk
load in both directions.

Per Perry's session config:
  - Working dir: %LOCALAPPDATA%/Temp/dw_h3_backfill (auto-cleaned at end)
  - Idempotent: skips wells where h3_coord_hash is already populated
  - bcp.exe assumed on PATH (default for SQL Server installs)

Usage:
    python backfill_h3_bcp.py                  # both source tables
    python backfill_h3_bcp.py --table dv_well  # only dataview.dv_well
    python backfill_h3_bcp.py --force          # ignore existing hashes
    python backfill_h3_bcp.py --keep-temp      # don't delete CSVs at end
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import h3
import pandas as pd
from sqlalchemy import create_engine, text


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
CONN_STR = (
    "mssql+pyodbc://@localhost\\SQLEXPRESS/DataView"
    "?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
)

# BCP authentication: -T (trusted/Windows), -S (server), -d (database).
# These match SSMS's connection. If you connect to SQL Server differently
# (named instance, different machine, SQL auth), update these.
BCP_SERVER = r"localhost\SQLEXPRESS"
BCP_DATABASE = "DataView"

# Where the intermediate CSVs live. %LOCALAPPDATA%\Temp gets cleaned by
# Windows storage maintenance routines automatically.
WORK_DIR = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "dw_h3_backfill"

# Field separator for CSV files. Pipe is safer than comma because well
# names contain commas; pipe doesn't appear in our data shape.
FIELD_SEP = "|"

H3_RESOLUTIONS = (4, 5, 6, 7)


# -----------------------------------------------------------------------------
# Table descriptors — encapsulate per-table differences
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class TableSpec:
    key: str             # arg-friendly short name
    label: str           # human-readable for logging
    full_name: str       # schema-qualified
    pk_col: str          # primary key column name in target
    pk_type_sql: str     # SQL type for the pk column in the staging table
    lat_col: str
    lon_col: str


TABLES: dict[str, TableSpec] = {
    "dv_well": TableSpec(
        key="dv_well",
        label="dataview.dv_well",
        full_name="dataview.dv_well",
        pk_col="uwi",
        pk_type_sql="NVARCHAR(50)",
        lat_col="surface_latitude",
        lon_col="surface_longitude",
    ),
    "dv_well_gom": TableSpec(
        key="dv_well_gom",
        label="dataview_gom.well",
        full_name="dataview_gom.well",
        pk_col="well_id",
        # GOM uses UNIQUEIDENTIFIER. BCP writes/reads UUIDs as their
        # standard 36-char string form (8-4-4-4-12); store the same way
        # in staging.
        pk_type_sql="UNIQUEIDENTIFIER",
        lat_col="surface_latitude",
        lon_col="surface_longitude",
    ),
}


# -----------------------------------------------------------------------------
# Hash helper — must match validate_h3_backfill.py
# -----------------------------------------------------------------------------
def coord_hash_hex(lat: float, lon: float) -> str:
    """
    SHA2_256 of 'lat|lon' as bare 64-char hex string for BCP/SQL import.

    BCP -c (character mode) reads strings verbatim. For a BINARY(32)
    target column, BCP expects the bare hex form (64 hex chars), NOT
    the 0x-prefixed literal form. The 0x prefix works in INSERT/SELECT
    contexts but causes BCP to fail per-row silently. Bare hex is what
    BCP's binary parser expects.
    """
    raw = hashlib.sha256(f"{lat!r}|{lon!r}".encode("ascii")).digest()
    return raw.hex()


# -----------------------------------------------------------------------------
# BCP wrappers — capture stdout, raise on non-zero exit
# -----------------------------------------------------------------------------
def bcp_check_available() -> str:
    """Return the path to bcp.exe, or raise if not found."""
    found = shutil.which("bcp")
    if not found:
        raise RuntimeError(
            "bcp.exe not found on PATH. "
            "Install SQL Server Command Line Tools or add the BCP "
            "executable directory to PATH (e.g. "
            r"'C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\xxx\Tools\Binn')."
        )
    return found


def bcp_out_query(query: str, out_path: Path) -> int:
    """
    Run `bcp queryout`. Returns the row count BCP reports.

    Character mode (-c) with pipe separator (-t|). Native mode (-n) would
    be faster but harder to compose with Python — we'd have to mirror
    SQL Server's binary representation.

    -T = trusted (Windows) auth
    -S = server\\instance
    -d = database
    -q = quoted identifiers (required if schema/table names need quoting)
    """
    cmd = [
        "bcp",
        query,
        "queryout",
        str(out_path),
        "-c",                   # character mode
        f"-t{FIELD_SEP}",
        "-T",                   # trusted auth
        f"-S{BCP_SERVER}",
        f"-d{BCP_DATABASE}",
        "-q",
    ]
    return _run_bcp(cmd, "BCP OUT")


def bcp_in_table(table_name: str, in_path: Path) -> int:
    """
    Run `bcp in` into the specified staging table.

    -b 50000 sets batch size; BCP commits each batch. Smaller batches
    mean less rollback risk if something goes wrong mid-import; 50K
    matches our nominal compute batch size.

    -h "TABLOCK" requests a table lock, much faster than row locks
    on bulk imports.

    -C 65001 sets the code page to UTF-8. Even though our data is
    pure ASCII, being explicit avoids ANSI/UTF surprises.

    NOTE on row terminator: we DON'T pass -r explicitly. BCP -c on
    Windows handles CRLF natively as the default row terminator.
    Passing -r "\r\n" via subprocess on PowerShell/Windows causes
    shell-escaping issues — BCP receives literal backslash-r-backslash-n
    instead of the control chars, then can't find a row terminator
    and reports "Unexpected EOF" on every row.
    """
    cmd = [
        "bcp",
        table_name,
        "in",
        str(in_path),
        "-c",
        f"-t{FIELD_SEP}",
        "-C", "65001",
        "-T",
        f"-S{BCP_SERVER}",
        f"-d{BCP_DATABASE}",
        "-b", "50000",
        "-h", "TABLOCK",
    ]
    return _run_bcp(cmd, "BCP IN")


def _run_bcp(cmd: list[str], label: str) -> int:
    """Run a BCP command, raise on failure, return rows-copied count."""
    print(f"  [{label}] {' '.join(cmd[:3])} ...")
    t0 = time.time()
    # capture_output keeps the BCP banner out of our terminal until we
    # need it; on failure we'll print it.
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"  [{label}] FAILED (exit {result.returncode}, {elapsed:.1f}s)")
        if result.stdout:
            print("  --- BCP stdout ---")
            print(result.stdout)
        if result.stderr:
            print("  --- BCP stderr ---")
            print(result.stderr)
        raise RuntimeError(f"{label} failed")

    # BCP prints e.g. "477108 rows copied." — parse the count
    rows_copied = 0
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.endswith("rows copied.") or line.endswith("row copied."):
            # "477108 rows copied." → 477108
            rows_copied = int(line.split()[0].replace(",", ""))
            break

    # If 0 rows on a BCP IN, something went wrong silently — dump stdout
    # so the operator can see the error message BCP wrote.
    if rows_copied == 0 and "in" in cmd:
        print(f"  [{label}] WARNING: 0 rows copied — dumping full BCP output:")
        print("  --- BCP stdout ---")
        for line in result.stdout.splitlines():
            print(f"  | {line}")
        if result.stderr:
            print("  --- BCP stderr ---")
            for line in result.stderr.splitlines():
                print(f"  | {line}")

    print(f"  [{label}] OK ({rows_copied:,} rows, {elapsed:.1f}s)")
    return rows_copied


# -----------------------------------------------------------------------------
# Per-table pipeline
# -----------------------------------------------------------------------------
def backfill_one_table(spec: TableSpec, engine, force: bool) -> None:
    print(f"\n=== Backfilling {spec.label} ===")
    t_start = time.time()

    # Per-table working files. Including the table key in the filename
    # keeps the two tables' files from clobbering each other.
    src_csv = WORK_DIR / f"{spec.key}_source.csv"
    cells_csv = WORK_DIR / f"{spec.key}_cells.csv"
    stage_table = f"dbo.tmp_h3_stage_{spec.key}"

    # --- Phase 0: ensure staging table exists with the right shape ---
    # Drop-then-create instead of CREATE-IF-NOT-EXISTS so a leftover from
    # a previous failed run doesn't have stale rows.
    print("  [Phase 0] Reset staging table")
    with engine.begin() as con:
        con.execute(text(f"""
            IF OBJECT_ID('{stage_table}', 'U') IS NOT NULL
                DROP TABLE {stage_table};
        """))
        con.execute(text(f"""
            CREATE TABLE {stage_table} (
                pk            {spec.pk_type_sql}  NOT NULL,
                h3_r4         NVARCHAR(15)        NOT NULL,
                h3_r5         NVARCHAR(15)        NOT NULL,
                h3_r6         NVARCHAR(15)        NOT NULL,
                h3_r7         NVARCHAR(15)        NOT NULL,
                -- 64-char hex string (no 0x prefix). BCP -c can't import
                -- text-hex directly into BINARY without a format file, so
                -- we land it as NVARCHAR and convert to BINARY in the
                -- UPDATE via CONVERT(BINARY(32), value, 2).
                h3_coord_hash NVARCHAR(64)        NOT NULL
            );
        """))

    # --- Phase 1: BCP OUT (pk, lat, lon) for rows needing backfill ---
    # The WHERE clause encodes the idempotent skip: only export rows where
    # the hash is missing (never backfilled) OR --force was passed.
    if force:
        filter_clause = ""
    else:
        filter_clause = "AND h3_coord_hash IS NULL"

    out_query = (
        f"SELECT CAST({spec.pk_col} AS NVARCHAR(50)) AS pk, "
        f"{spec.lat_col} AS lat, {spec.lon_col} AS lon "
        f"FROM {spec.full_name} "
        f"WHERE {spec.lat_col} IS NOT NULL "
        f"AND {spec.lon_col} IS NOT NULL "
        f"{filter_clause}"
    )

    print("  [Phase 1] BCP OUT source rows")
    n_source = bcp_out_query(out_query, src_csv)

    if n_source == 0:
        print("  No rows to process — already up to date.")
        # Cleanup the staging table since we won't use it
        with engine.begin() as con:
            con.execute(text(f"DROP TABLE {stage_table};"))
        return

    # --- Phase 2: compute H3 cells in Python ---
    print(f"  [Phase 2] Computing H3 cells for {n_source:,} wells")
    t_compute = time.time()

    # Stream rows in/out so we never hold the full 477K dataset in memory
    # at once — keeps memory bounded and lets us start writing while
    # still reading.
    with src_csv.open("r", encoding="utf-8", newline="") as fin, \
         cells_csv.open("w", encoding="utf-8", newline="") as fout:

        reader = csv.reader(fin, delimiter=FIELD_SEP)
        writer = csv.writer(fout, delimiter=FIELD_SEP, lineterminator="\r\n")

        # Source has 3 columns: pk, lat, lon. No header (bcp doesn't
        # write one by default in character mode).
        n_written = 0
        for row in reader:
            if len(row) < 3:
                continue
            pk, lat_s, lon_s = row[0], row[1], row[2]
            lat, lon = float(lat_s), float(lon_s)
            cells = [h3.latlng_to_cell(lat, lon, r) for r in H3_RESOLUTIONS]
            h_hex = coord_hash_hex(lat, lon)
            writer.writerow([pk, *cells, h_hex])
            n_written += 1

    elapsed_compute = time.time() - t_compute
    rate = n_written / elapsed_compute if elapsed_compute > 0 else 0
    print(f"  [Phase 2] OK ({n_written:,} rows, {elapsed_compute:.1f}s, "
          f"{rate:.0f} rows/sec)")

    # --- Phase 3: BCP IN the computed CSV into staging ---
    print("  [Phase 3] BCP IN computed cells")
    n_imported = bcp_in_table(stage_table, cells_csv)
    if n_imported != n_written:
        raise RuntimeError(
            f"Row count mismatch after BCP IN: wrote {n_written:,}, "
            f"imported {n_imported:,}"
        )

    # --- Phase 4: UPDATE target via JOIN ---
    print("  [Phase 4] UPDATE target via JOIN")
    t_update = time.time()
    update_sql = f"""
        UPDATE w
        SET w.h3_r4         = s.h3_r4,
            w.h3_r5         = s.h3_r5,
            w.h3_r6         = s.h3_r6,
            w.h3_r7         = s.h3_r7,
            -- style=2 reads the hex string WITHOUT a 0x prefix
            -- (style=1 expects the 0x prefix). Matches what
            -- coord_hash_hex() writes.
            w.h3_coord_hash = CONVERT(BINARY(32), s.h3_coord_hash, 2)
        FROM {spec.full_name} w
        JOIN {stage_table} s ON s.pk = CAST(w.{spec.pk_col} AS NVARCHAR(50));
    """
    with engine.begin() as con:
        result = con.execute(text(update_sql))
        n_updated = result.rowcount
    elapsed_update = time.time() - t_update
    print(f"  [Phase 4] OK ({n_updated:,} rows updated, {elapsed_update:.1f}s)")

    # --- Phase 5: drop staging table ---
    print("  [Phase 5] Drop staging table")
    with engine.begin() as con:
        con.execute(text(f"DROP TABLE {stage_table};"))

    total = time.time() - t_start
    print(f"  {spec.label}: complete in {total:.1f}s")


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="BCP-based H3 backfill.")
    parser.add_argument("--table",
                        choices=list(TABLES.keys()) + ["all"],
                        default="all")
    parser.add_argument("--force", action="store_true",
                        help="Recompute all wells (ignore h3_coord_hash).")
    parser.add_argument("--keep-temp", action="store_true",
                        help="Don't delete intermediate CSVs (debug aid).")
    args = parser.parse_args()

    # Sanity checks before doing real work
    bcp_path = bcp_check_available()
    print(f"BCP : {bcp_path}")
    print(f"Conn: {BCP_SERVER}/{BCP_DATABASE}")

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Work: {WORK_DIR}")

    targets = (list(TABLES.values()) if args.table == "all"
               else [TABLES[args.table]])

    engine = create_engine(CONN_STR)

    t_global = time.time()
    try:
        for spec in targets:
            backfill_one_table(spec, engine, args.force)
    except Exception as exc:
        print(f"\nBACKFILL FAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        # Best-effort cleanup of intermediate CSVs
        if not args.keep_temp:
            try:
                shutil.rmtree(WORK_DIR)
                print(f"\nCleaned up {WORK_DIR}")
            except Exception as exc:
                print(f"\nWarning: couldn't clean {WORK_DIR}: {exc}")

    print(f"\nTOTAL ELAPSED: {time.time() - t_global:.1f}s")
    print("Next step: python validate_h3_backfill.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

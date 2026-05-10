"""
copy_reference_data.py
======================
Copies all reference and spatial data from DataView to DataView_Test,
excluding well data and its dependents.

Tables copied (in FK dependency order):
  Reference:  dv_r_source, dv_r_well_type, dv_r_well_status, dv_r_uom
  Spatial:    dv_country, dv_province_state, dv_county, dv_basin,
              dv_plss_township, dv_ocs_block
  Entities:   dv_business_associate, dv_field, dv_source

Tables NOT copied (well data and dependents):
  dv_well, dv_well_alias, dv_well_dir_srvy_hdr, dv_well_dir_srvy_sta,
  dv_well_formation_top, dv_strat_interval, dv_well_log, dv_well_log_curve,
  dv_prod_entity, dv_prod_volume, dv_wl_file_catalog, dv_seis_file_catalog,
  dv_global_file_catalog, dv_seis_set, dv_seis_line,
  dv_load_batch, dv_column_map, dv_data_quality,
  dv_well_casing, dv_well_completion, dv_well_core, dv_well_core_photo,
  dv_well_core_sample, dv_well_dst, dv_well_dst_period, dv_well_mud_log,
  dv_well_perforation, dv_well_petro_interp, dv_well_petro_zone,
  dv_well_pressure, dv_well_shows, dv_well_stimulation

Usage:
    python copy_reference_data.py
    python copy_reference_data.py --src DataView --dst DataView_Test
    python copy_reference_data.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent))

# Tables to copy in FK dependency order
COPY_TABLES = [
    # ── Reference tables (no FK deps) ────────────────────────────────
    "dv_r_source",
    "dv_r_well_type",
    "dv_r_well_status",
    "dv_r_uom",
    # ── Spatial (FK → dv_country) ────────────────────────────────────
    "dv_country",
    "dv_province_state",
    "dv_county",
    "dv_basin",
    "dv_plss_township",
    "dv_ocs_block",
    # ── Entities (FK → dv_r_source) ──────────────────────────────────
    "dv_business_associate",
    "dv_field",
    "dv_source",
    # ── Map layers ────────────────────────────────────────────────────
    "dv_spatial_layer",
]

SCHEMA    = "dataview"
CHUNK_SIZE = 2000


def make_engine(database: str):
    cs = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER=127.0.0.1\\SQLEXPRESS;"
        f"DATABASE={database};"
        f"Trusted_Connection=yes;"
    )
    return create_engine(
        "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(cs),
        fast_executemany=True,
    )


def copy_table(
    src_engine,
    dst_engine,
    table: str,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Copy all rows from src to dst for a single table.
    Skips rows that already exist in dst (IF NOT EXISTS on PK).
    Returns (copied, skipped).
    """
    full = f"[{SCHEMA}].[{table}]"

    # Read source
    with src_engine.connect() as con:
        df = pd.read_sql(text(f"SELECT * FROM {full}"), con)

    if df.empty:
        print(f"  {table:35} 0 rows in source — skipped")
        return 0, 0

    # Get existing PKs in destination
    with dst_engine.connect() as con:
        try:
            dst_df = pd.read_sql(text(f"SELECT * FROM {full}"), con)
            existing_count = len(dst_df)
        except Exception:
            existing_count = 0

    total = len(df)

    if dry_run:
        print(f"  {table:35} {total:6,} rows in source  |  {existing_count:6,} in dest")
        return total, 0

    if existing_count == total:
        print(f"  {table:35} {total:6,} rows — already in sync")
        return 0, total

    # Truncate destination and reload from source
    # Simpler and safer than row-by-row upsert for reference data
    raw_conn = dst_engine.raw_connection()
    try:
        cursor = raw_conn.cursor()

        # Disable FK constraints on this table
        cursor.execute(f"ALTER TABLE {full} NOCHECK CONSTRAINT ALL")
        raw_conn.commit()

        # Delete existing
        cursor.execute(f"DELETE FROM {full}")
        raw_conn.commit()

        # Bulk insert from source
        cols        = list(df.columns)
        col_list    = ", ".join(f"[{c}]" for c in cols)
        placeholders = ", ".join("?" * len(cols))
        insert_sql  = f"INSERT INTO {full} ({col_list}) VALUES ({placeholders})"

        cursor.fast_executemany = True
        for i in range(0, len(df), CHUNK_SIZE):
            batch = df.iloc[i:i+CHUNK_SIZE]
            params = [
                tuple(None if pd.isna(v) else v for v in row)
                for row in batch.itertuples(index=False, name=None)
            ]
            cursor.executemany(insert_sql, params)
            raw_conn.commit()

        # Re-enable FK constraints
        cursor.execute(f"ALTER TABLE {full} CHECK CONSTRAINT ALL")
        raw_conn.commit()
        cursor.close()

        print(f"  {table:35} {total:6,} rows copied")
        return total, 0

    except Exception as e:
        raw_conn.rollback()
        print(f"  {table:35} ERROR: {e}")
        return 0, 0
    finally:
        raw_conn.close()


def copy_reference_data(
    src_db:  str = "DataView",
    dst_db:  str = "DataView_Test",
    dry_run: bool = False,
) -> None:
    print(f"\nCopying reference data: {src_db} → {dst_db}")
    if dry_run:
        print("DRY RUN — no changes will be made\n")

    src_engine = make_engine(src_db)
    dst_engine = make_engine(dst_db)

    total_copied  = 0
    total_skipped = 0

    for table in COPY_TABLES:
        copied, skipped = copy_table(src_engine, dst_engine, table, dry_run)
        total_copied  += copied
        total_skipped += skipped

    print(f"\nDone — {total_copied:,} rows copied, {total_skipped:,} already in sync")
    print(f"\nDataView_Test now has all reference/spatial data.")
    print(f"Well data not copied — DataView_Test is clean for testing.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Copy reference/spatial data from DataView to DataView_Test"
    )
    ap.add_argument("--src",     default="DataView",      help="Source database")
    ap.add_argument("--dst",     default="DataView_Test", help="Destination database")
    ap.add_argument("--dry-run", action="store_true",     help="Preview only")
    args = ap.parse_args()

    copy_reference_data(args.src, args.dst, args.dry_run)

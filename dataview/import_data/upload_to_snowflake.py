"""
upload_to_snowflake.py
======================
Uploads the BCP-exported CSV files to Snowflake via PUT + COPY INTO.
Run export_for_snowflake.bat first to generate the CSVs.

Usage:
    python upload_to_snowflake.py
    python upload_to_snowflake.py --source tx
"""
from __future__ import annotations
import argparse, os, sys, time
from pathlib import Path

try:
    import snowflake.connector
except ImportError:
    sys.exit("pip install snowflake-connector-python")


CSV_DIR = Path(r"C:\Bulk\snowflake_export")

SOURCES = {
    "tx":   ("Texas RRC",      "raw_tx_well.csv",    "RAW_TX",   "WELL"),
    "ks":   ("Kansas KGS",     "raw_ks_well.csv",    "RAW_KS",   "WELL"),
    "nd":   ("North Dakota",   "raw_nd_well.csv",    "RAW_ND",   "WELL"),
    "osdu": ("OSDU",           "raw_osdu_well.csv",  "RAW_OSDU", "WELL"),
    "gom":  ("BOEM GOM",       "raw_boem_well.csv",  "RAW_BOEM", "WELL"),
    "ok":   ("Oklahoma OCC",   "raw_ok_well.csv",    "RAW_OK",   "WELL"),
}


def upload_source(conn, label, csv_path, schema, table):
    """PUT a CSV file to Snowflake stage, then COPY INTO table."""
    cur = conn.cursor()
    t0 = time.time()

    size_mb = csv_path.stat().st_size / (1024 * 1024)
    print(f"\n── {label} ({size_mb:.1f} MB) ──────────────────────────")

    # Read header to get column names
    with open(csv_path, "r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    print(f"  Columns: {len(header)}")

    # Create schema + stage
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    cur.execute(f"USE SCHEMA {schema}")
    cur.execute(f"CREATE STAGE IF NOT EXISTS {schema}.LOAD_STAGE")

    # Drop and recreate table from header
    cur.execute(f"DROP TABLE IF EXISTS {schema}.{table}")
    cols_ddl = ", ".join(f'"{c.upper().strip()}" VARCHAR' for c in header)
    cur.execute(f"CREATE TABLE {schema}.{table} ({cols_ddl})")
    print(f"  Created {schema}.{table}")

    # PUT — upload to stage
    local_path = str(csv_path).replace("\\", "/")
    print(f"  Uploading…", end=" ", flush=True)
    cur.execute(f"PUT 'file://{local_path}' @{schema}.LOAD_STAGE AUTO_COMPRESS=TRUE OVERWRITE=TRUE")
    print(f"done ({time.time() - t0:.1f}s)")

    # COPY INTO
    t1 = time.time()
    fname = csv_path.name
    print(f"  Loading…", end=" ", flush=True)
    cur.execute(f"""
        COPY INTO {schema}.{table}
        FROM @{schema}.LOAD_STAGE/{fname}.gz
        FILE_FORMAT = (
            TYPE = 'CSV'
            FIELD_DELIMITER = ','
            SKIP_HEADER = 0
            FIELD_OPTIONALLY_ENCLOSED_BY = NONE
            NULL_IF = ('')
            EMPTY_FIELD_AS_NULL = TRUE
        )
        ON_ERROR = 'CONTINUE'
    """)
    print(f"done ({time.time() - t1:.1f}s)")

    # Verify
    cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
    n = cur.fetchone()[0]
    print(f"  Loaded: {n:,} rows ({time.time() - t0:.1f}s total)")

    # Clean up stage
    cur.execute(f"REMOVE @{schema}.LOAD_STAGE/{fname}.gz")
    cur.close()
    return n


def main():
    ap = argparse.ArgumentParser(description="Upload CSVs to Snowflake")
    ap.add_argument("--source", default="all",
                    choices=["all", "tx", "ks", "nd", "osdu", "gom", "ok"])
    args = ap.parse_args()

    print("WranglerView — Upload to Snowflake")
    print(f"  CSV dir: {CSV_DIR}")

    # Check CSVs exist
    for key, (label, fname, schema, table) in SOURCES.items():
        if args.source not in ("all", key):
            continue
        p = CSV_DIR / fname
        if not p.exists():
            print(f"\n  MISSING: {p}")
            print(f"  Run export_for_snowflake.bat first")
            return

    # Connect
    print(f"\n  Connecting to Snowflake…", end=" ", flush=True)
    try:
        conn = snowflake.connector.connect(
            account=os.environ.get("SNOWFLAKE_ACCOUNT", "YDWXNCV-VL88062"),
            user=os.environ.get("SNOWFLAKE_USER", "PMSTOKES00"),
            password=os.environ.get("SNOWFLAKE_PASSWORD", ""),
            database="WELL_FEDERATION",
            warehouse="WV_WH",
            role="ACCOUNTADMIN",
        )
        print("OK")
    except Exception as e:
        print(f"FAILED: {e}")
        return

    t0 = time.time()
    total = 0

    for key, (label, fname, schema, table) in SOURCES.items():
        if args.source not in ("all", key):
            continue
        csv_path = CSV_DIR / fname
        try:
            n = upload_source(conn, label, csv_path, schema, table)
            total += n
        except Exception as e:
            print(f"  ERROR: {e}")

    # Verification
    print(f"\n── Summary ─────────────────────────────────────────")
    cur = conn.cursor()
    for key, (label, fname, schema, table) in SOURCES.items():
        try:
            cur.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
            n = cur.fetchone()[0]
            print(f"  {label:20s} {schema}.{table:15s} {n:>10,}")
        except Exception:
            print(f"  {label:20s} {schema}.{table:15s}      (empty)")
    cur.close()
    conn.close()

    print(f"\n  Total: {total:,} rows in {time.time() - t0:.1f}s")
    print("  Done!")


if __name__ == "__main__":
    main()

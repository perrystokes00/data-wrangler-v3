"""
setup_dataview.py
=================
One-time setup script for the DataView schema on an existing SQL Server instance.

  • Reads connection settings from .env (same format as Data Wrangler v2/v3)
  • Creates the 'dataview' schema if it does not exist
  • Runs dv_schema_ddl.sql  (32 tables, 46 indexes)
  • Seeds reference tables  (dv_r_source, dv_r_well_type, dv_r_well_status, dv_r_uom)
  • Prints a table-count summary on completion

Usage (from the v3 project root with the venv active):
    python setup_dataview.py

    # Or override the server / database without editing .env:
    python setup_dataview.py --server MYPC\\SQLEXPRESS --database DataView

    # Preview only — show what would be created without touching the DB:
    python setup_dataview.py --dry-run

Requirements (already in v2 venv):
    pip install sqlalchemy pyodbc python-dotenv
"""
from __future__ import annotations

import argparse
import os
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional dotenv — same pattern as the rest of the app
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # No dotenv installed — rely on env vars or CLI args

# ---------------------------------------------------------------------------
# SQLAlchemy
# ---------------------------------------------------------------------------
try:
    from sqlalchemy import create_engine, text
    HAS_SQLA = True
except ImportError:
    HAS_SQLA = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT    = Path(__file__).parent
DDL_FILE = ROOT / "schema_registry" / "dv_schema_ddl.sql"

# Fallback: look in same directory as this script
if not DDL_FILE.exists():
    DDL_FILE = ROOT / "dv_schema_ddl.sql"


# =============================================================================
# CONNECTION
# =============================================================================

def _build_engine(args):
    """
    Build a SQLAlchemy engine from CLI args + .env, mirroring the v2 DBConfig
    pattern so the same ODBC driver and fast_executemany settings apply.
    """
    if not HAS_SQLA:
        _die("sqlalchemy is not installed.  Run:  pip install sqlalchemy pyodbc")

    import pyodbc  # noqa: F401 — ensure driver available

    server   = args.server   or os.getenv("DB_SERVER", "")
    database = args.database or os.getenv("DB_NAME",   "PPDM39")
    windows  = args.windows_auth or (os.getenv("DB_WINDOWS_AUTH", "0") == "1")
    username = args.username or os.getenv("DB_USERNAME", "")
    password = args.password or os.getenv("DB_PASSWORD", "")
    driver   = args.driver   or os.getenv("DB_DRIVER",
                                           "ODBC Driver 17 for SQL Server")

    if not server:
        _die(
            "No SQL Server specified.\n"
            "  Set DB_SERVER in .env  OR  pass --server MYSERVER\\\\INSTANCE"
        )

    if windows:
        odbc = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            "Trusted_Connection=yes;"
        )
    else:
        if not username:
            _die("SQL auth requires --username (or DB_USERNAME in .env)")
        odbc = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={database};"
            f"UID={username};"
            f"PWD={password};"
        )

    def _creator():
        return pyodbc.connect(odbc)

    engine = create_engine(
        "mssql+pyodbc://",
        creator=_creator,
        fast_executemany=True,
        pool_pre_ping=False,
        pool_size=3,
        max_overflow=5,
        pool_timeout=30,
    )
    return engine, server, database


def _test_connection(engine, server, database):
    with engine.connect() as con:
        row = con.execute(text("SELECT @@VERSION AS v")).fetchone()
        version = str(row[0]).split("\n")[0] if row else "Unknown"
    print(f"  Server   : {server}")
    print(f"  Database : {database}")
    print(f"  Version  : {version}")
    return version


# =============================================================================
# DDL RUNNER
# =============================================================================

def _split_batches(sql: str) -> list[str]:
    """
    Split a SQL script on GO statements (SQL Server batch separator).
    Strips blank batches and leading/trailing whitespace.
    """
    batches = []
    current: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.upper() == "GO":
            batch = "\n".join(current).strip()
            if batch:
                batches.append(batch)
            current = []
        else:
            current.append(line)
    # Trailing batch with no final GO
    batch = "\n".join(current).strip()
    if batch:
        batches.append(batch)
    return batches


def _run_ddl(engine, ddl_path: Path, dry_run: bool) -> int:
    """Execute the DDL file batch by batch.  Returns number of batches run."""
    if not ddl_path.exists():
        _die(f"DDL file not found: {ddl_path}\n"
             f"Expected at: {ddl_path.resolve()}")

    sql = ddl_path.read_text(encoding="utf-8")
    batches = _split_batches(sql)

    print(f"\n  DDL file  : {ddl_path.name}")
    print(f"  Batches   : {len(batches)}")

    if dry_run:
        print("\n  [DRY RUN] — no changes made to the database.")
        for i, b in enumerate(batches, 1):
            preview = b[:80].replace("\n", " ")
            print(f"    batch {i:02d}: {preview}…")
        return 0

    run = 0
    with engine.begin() as con:
        for i, batch in enumerate(batches, 1):
            try:
                con.execute(text(batch))
                run += 1
            except Exception as exc:
                # Surface errors but keep going — DROP IF EXISTS on missing
                # tables produces harmless errors we can skip
                msg = str(exc).splitlines()[0]
                # Ignore "object does not exist" class errors from DROP
                if any(k in msg for k in ["Cannot drop", "does not exist",
                                           "3701", "3706"]):
                    continue
                print(f"\n  WARNING  batch {i}: {msg}")
    return run


# =============================================================================
# REFERENCE TABLE SEEDING
# =============================================================================

_SEED_R_SOURCE = [
    ("DATAVIEW",  "DataView",     "DataView v3 internal source"),
    ("MANUAL",    "Manual",       "Manually entered data"),
    ("IMPORT",    "Import",       "Bulk import via pipeline"),
    ("TIGER",     "Census TIGER", "US Census Bureau TIGER/Line"),
    ("GADM",      "GADM",         "Global Administrative Areas"),
    ("BLM_PLSS",  "BLM PLSS",     "Bureau of Land Management PLSS"),
    ("BOEM",      "BOEM",         "Bureau of Ocean Energy Management"),
    ("NRCAN",     "NRCan",        "Natural Resources Canada"),
    ("PPDM",      "PPDM",         "Professional Petroleum Data Management Assoc."),
]

_SEED_R_WELL_TYPE = [
    ("ABANDONMENT",         "Abandonment well"),
    ("CBM",                 "Coal bed methane"),
    ("CLASS_I_INJECTION",   "Class I injection"),
    ("CLASS_II_INJECTION",  "Class II injection"),
    ("CORE_HOLE",           "Core hole"),
    ("DISPOSAL",            "Disposal / SWD"),
    ("DEVELOPMENT",         "Development well"),
    ("EXPLORATORY",         "Exploratory / wildcat"),
    ("GAS",                 "Gas well"),
    ("GAS_STORAGE",         "Gas storage"),
    ("GEOTHERMAL",          "Geothermal"),
    ("HORIZONTAL",          "Horizontal"),
    ("MONITORING",          "Monitoring / observation"),
    ("OIL",                 "Oil well"),
    ("OIL_GAS",             "Oil and gas"),
    ("SERVICE",             "Service well"),
    ("STRATIGRAPHIC",       "Stratigraphic test"),
    ("UNKNOWN",             "Unknown"),
    ("WATER_SOURCE",        "Water source"),
]

_SEED_R_WELL_STATUS = [
    ("ABANDONED",           "Abandoned"),
    ("ACTIVE",              "Active / producing"),
    ("COMPLETED",           "Completed"),
    ("DRILLING",            "Drilling"),
    ("DRY_HOLE",            "Dry hole"),
    ("INJECTING",           "Injecting"),
    ("MONITORING",          "Monitoring"),
    ("PERMITTED",           "Permitted / proposed"),
    ("SHUT_IN",             "Shut in"),
    ("SUSPENDED",           "Suspended"),
    ("UNKNOWN",             "Unknown"),
]

_SEED_R_UOM = [
    # Length
    ("M",    "m",     "Metre",               "LENGTH",    1.0,         "M"),
    ("FT",   "ft",    "Foot",                "LENGTH",    0.3048,      "M"),
    ("KM",   "km",    "Kilometre",           "LENGTH",    1000.0,      "M"),
    ("MI",   "mi",    "Mile (statute)",      "LENGTH",    1609.344,    "M"),
    # Depth
    ("FTSS", "ftss",  "Feet sub-sea",        "LENGTH",    0.3048,      "M"),
    ("MSS",  "mss",   "Metres sub-sea",      "LENGTH",    1.0,         "M"),
    # Pressure
    ("KPA",  "kPa",   "Kilopascal",          "PRESSURE",  1.0,         "KPA"),
    ("PSI",  "psi",   "Pounds per sq inch",  "PRESSURE",  6.89476,     "KPA"),
    ("BAR",  "bar",   "Bar",                 "PRESSURE",  100.0,       "KPA"),
    ("MPA",  "MPa",   "Megapascal",          "PRESSURE",  1000.0,      "KPA"),
    # Volume — oil/condensate
    ("BBL",  "bbl",   "Barrel (oil)",        "VOLUME",    0.158987,    "M3"),
    ("M3",   "m3",    "Cubic metre",         "VOLUME",    1.0,         "M3"),
    # Volume — gas
    ("MCF",  "Mcf",   "Thousand cubic feet", "VOLUME_GAS",28.3168,     "M3"),
    ("MMCF", "MMcf",  "Million cubic feet",  "VOLUME_GAS",28316.8,     "M3"),
    ("BCF",  "Bcf",   "Billion cubic feet",  "VOLUME_GAS",28316846.6,  "M3"),
    ("E3M3", "E3m3",  "Thousand cubic m",    "VOLUME_GAS",1000.0,      "M3"),
    # Rate
    ("BOPD", "bopd",  "Barrels oil/day",     "RATE",      None,        None),
    ("BWPD", "bwpd",  "Barrels water/day",   "RATE",      None,        None),
    ("MCFD", "Mcfd",  "Mcf per day",         "RATE",      None,        None),
    # Temperature
    ("DEGC", "°C",    "Degrees Celsius",     "TEMP",      1.0,         "DEGC"),
    ("DEGF", "°F",    "Degrees Fahrenheit",  "TEMP",      None,        "DEGC"),
    ("DEGK", "K",     "Kelvin",              "TEMP",      1.0,         "DEGK"),
    # Time
    ("MS",   "ms",    "Millisecond",         "TIME",      0.001,       "S"),
    ("S",    "s",     "Second",              "TIME",      1.0,         "S"),
    # Permeability
    ("MD",   "mD",    "Millidarcy",          "PERM",      1.0,         "MD"),
    # Angle
    ("DEG",  "deg",   "Degree",              "ANGLE",     1.0,         "DEG"),
    # Unitless
    ("FRAC", "frac",  "Fraction (0–1)",      "UNITLESS",  1.0,         "FRAC"),
    ("PCT",  "pct",   "Percent",             "UNITLESS",  0.01,        "FRAC"),
    ("GAPI", "gAPI",  "API gamma-ray unit",  "LOG",       1.0,         "GAPI"),
    ("OHMM", "ohm.m", "Ohm-metre",           "LOG",       1.0,         "OHMM"),
    ("G_CC", "g/cc",  "Grams per cubic cm",  "DENSITY",   1000.0,      "KG_M3"),
    ("US_FT","us/ft", "Microseconds/foot",   "SLOWNESS",  1.0,         "US_FT"),
]


def _seed_references(engine, dry_run: bool):
    """Insert reference rows using MERGE (upsert) — safe to re-run."""
    if dry_run:
        print("\n  [DRY RUN] — reference seed skipped.")
        return

    print("\n  Seeding reference tables …")

    with engine.begin() as con:

        # ── dv_r_source ────────────────────────────────────────────────
        for source, short_name, long_name in _SEED_R_SOURCE:
            con.execute(text("""
                MERGE dataview.dv_r_source AS tgt
                USING (SELECT :source AS source) AS src
                ON tgt.source = src.source
                WHEN NOT MATCHED THEN
                    INSERT (source, short_name, long_name, active_ind,
                            row_created_by)
                    VALUES (:source, :short_name, :long_name, 'Y', 'SYSTEM');
            """), {"source": source, "short_name": short_name,
                   "long_name": long_name})
        print(f"    dv_r_source      : {len(_SEED_R_SOURCE)} rows")

        # ── dv_r_well_type ─────────────────────────────────────────────
        for well_type, long_name in _SEED_R_WELL_TYPE:
            con.execute(text("""
                MERGE dataview.dv_r_well_type AS tgt
                USING (SELECT :well_type AS well_type) AS src
                ON tgt.well_type = src.well_type
                WHEN NOT MATCHED THEN
                    INSERT (well_type, long_name, active_ind, row_created_by)
                    VALUES (:well_type, :long_name, 'Y', 'SYSTEM');
            """), {"well_type": well_type, "long_name": long_name})
        print(f"    dv_r_well_type   : {len(_SEED_R_WELL_TYPE)} rows")

        # ── dv_r_well_status ───────────────────────────────────────────
        for well_status, long_name in _SEED_R_WELL_STATUS:
            con.execute(text("""
                MERGE dataview.dv_r_well_status AS tgt
                USING (SELECT :well_status AS well_status) AS src
                ON tgt.well_status = src.well_status
                WHEN NOT MATCHED THEN
                    INSERT (well_status, long_name, active_ind, row_created_by)
                    VALUES (:well_status, :long_name, 'Y', 'SYSTEM');
            """), {"well_status": well_status, "long_name": long_name})
        print(f"    dv_r_well_status : {len(_SEED_R_WELL_STATUS)} rows")

        # ── dv_r_uom ───────────────────────────────────────────────────
        for row in _SEED_R_UOM:
            uom_code, unit, desc, uom_type, si_eq, si_code = row
            con.execute(text("""
                MERGE dataview.dv_r_uom AS tgt
                USING (SELECT :uom_code AS uom_code) AS src
                ON tgt.uom_code = src.uom_code
                WHEN NOT MATCHED THEN
                    INSERT (uom_code, unit_of_measure, uom_description,
                            uom_type, si_equivalent, si_uom_code,
                            active_ind, row_created_by)
                    VALUES (:uom_code, :unit, :desc, :uom_type,
                            :si_eq, :si_code, 'Y', 'SYSTEM');
            """), {"uom_code": uom_code, "unit": unit, "desc": desc,
                   "uom_type": uom_type, "si_eq": si_eq, "si_code": si_code})
        print(f"    dv_r_uom         : {len(_SEED_R_UOM)} rows")

    print("  Reference seed complete.")


# =============================================================================
# VERIFICATION
# =============================================================================

def _verify(engine):
    """Count rows in every dataview table and print a summary."""
    sql = """
        SELECT TABLE_NAME
        FROM   INFORMATION_SCHEMA.TABLES
        WHERE  TABLE_SCHEMA = 'dataview'
          AND  TABLE_TYPE   = 'BASE TABLE'
        ORDER  BY TABLE_NAME
    """
    with engine.connect() as con:
        rows = con.execute(text(sql)).fetchall()

    if not rows:
        print("\n  WARNING: No tables found in dataview schema.")
        return

    print(f"\n  {'Table':<35} {'Rows':>8}")
    print(f"  {'-'*35} {'-'*8}")
    total_tables = 0
    with engine.connect() as con:
        for (tbl,) in rows:
            try:
                cnt = con.execute(
                    text(f"SELECT COUNT(*) FROM dataview.[{tbl}]")
                ).scalar()
            except Exception:
                cnt = "ERR"
            print(f"  {tbl:<35} {str(cnt):>8}")
            total_tables += 1

    print(f"\n  {total_tables} tables verified in dataview schema.")


# =============================================================================
# CLI
# =============================================================================

def _parse_args():
    p = argparse.ArgumentParser(
        description="Create the DataView schema on an existing SQL Server instance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              Windows auth (trusted connection):
                python setup_dataview.py --windows-auth

              SQL auth:
                python setup_dataview.py --username sa --password secret

              Different server / database:
                python setup_dataview.py --server MYPC\\\\SQLEXPRESS --database DataView --windows-auth

              Preview without touching the DB:
                python setup_dataview.py --dry-run
        """),
    )
    p.add_argument("--server",       default="", help="SQL Server host\\instance")
    p.add_argument("--database",     default="", help="Database name (default: from .env or PPDM39)")
    p.add_argument("--windows-auth", action="store_true", help="Use Windows/trusted auth")
    p.add_argument("--username",     default="", help="SQL auth username")
    p.add_argument("--password",     default="", help="SQL auth password")
    p.add_argument("--driver",       default="", help="ODBC driver name")
    p.add_argument("--ddl",          default="", help="Path to dv_schema_ddl.sql (auto-detected if omitted)")
    p.add_argument("--dry-run",      action="store_true", help="Show what would happen without making changes")
    p.add_argument("--no-seed",      action="store_true", help="Skip reference table seeding")
    p.add_argument("--verify-only",  action="store_true", help="Skip DDL — just verify existing tables")
    return p.parse_args()


def _die(msg: str):
    print(f"\n  ERROR: {msg}\n", file=sys.stderr)
    sys.exit(1)


# =============================================================================
# MAIN
# =============================================================================

def main():
    args = _parse_args()

    print()
    print("=" * 60)
    print("  DataView — Schema Setup")
    print("=" * 60)

    # ── Build engine ──────────────────────────────────────────────────
    print("\n  Connecting …")
    try:
        engine, server, database = _build_engine(args)
        _test_connection(engine, server, database)
    except Exception as exc:
        _die(str(exc))

    if args.verify_only:
        _verify(engine)
        return

    # ── DDL path ──────────────────────────────────────────────────────
    ddl_path = Path(args.ddl) if args.ddl else DDL_FILE
    if not ddl_path.exists():
        _die(
            f"Cannot find DDL file: {ddl_path}\n"
            f"  Place dv_schema_ddl.sql in schema_registry\\ or pass --ddl <path>"
        )

    # ── Run DDL ───────────────────────────────────────────────────────
    print("\n  Running DDL …")
    try:
        batches_run = _run_ddl(engine, ddl_path, dry_run=args.dry_run)
        if not args.dry_run:
            print(f"  DDL complete — {batches_run} batches executed.")
    except Exception as exc:
        _die(f"DDL failed: {exc}")

    # ── Seed references ───────────────────────────────────────────────
    if not args.no_seed:
        try:
            _seed_references(engine, dry_run=args.dry_run)
        except Exception as exc:
            _die(f"Seed failed: {exc}")

    # ── Verify ────────────────────────────────────────────────────────
    if not args.dry_run:
        _verify(engine)

    print()
    print("=" * 60)
    print("  DataView schema ready.")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()

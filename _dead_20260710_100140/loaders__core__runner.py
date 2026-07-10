"""
loaders/core/runner.py — Load orchestrator.

Given a plugin and a source file, runs:
  Phase 0: preflight (validate schema, tools, environment) [2026-05-28]
  Phase 1: parse source, write three staging CSVs
  Phase 2: BCP load into dv_well_ext_<source>, dv_well, dv_well_identifier
  Phase 3 (optional): cleanup staging files (only on success)

Designed to be callable from both CLI and Streamlit.

2026-05-28 hardening:
  - Phase 0 preflight: validates target tables exist, columns match, BCP
    locatable, source-file readable, h3 library importable. Fails fast
    with clear messages instead of getting 60% through parse and dying.
  - Idempotency: by default refuses to run if rows already exist for this
    source. RunOptions.reload=True (CLI --reload) clears them first.
  - Staging cleanup: only runs on successful completion. On any failure,
    files are left for inspection — and their paths are printed.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from loaders.core.bcp_transport import (
    BcpCsvWriter, BcpError, bcp_in, bcp_version, cleanup_staging,
    find_bcp_exe, get_staging_dir,
)
from loaders.core.cleaning import DV_IDENTIFIER_COLUMNS, DV_WELL_COLUMNS
from loaders.core.plugin_base import SourcePlugin
from loaders.core.stats import LoadStats

# Database connection (matches the DataView v3 dev environment)
DEFAULT_SERVER = r"localhost\SQLEXPRESS"
DEFAULT_DATABASE = "DataView"


class PreflightError(Exception):
    """Raised when preflight validation finds a blocking problem."""


@dataclass
class RunOptions:
    """Options for runner.run()."""
    dry_run: bool = False
    skip_bcp: bool = False
    keep_staging: bool = False
    reload: bool = False           # 2026-05-28: opt-in destructive re-load
    skip_preflight: bool = False   # 2026-05-28: escape hatch (not recommended)
    server: str = DEFAULT_SERVER
    database: str = DEFAULT_DATABASE
    # Optional callback for progress updates (e.g. Streamlit progress bar)
    on_progress: Callable[[str, int, int], None] | None = None


def _connect(server: str, database: str):
    """
    Return a pyodbc connection to (server, database) using trusted auth.
    Imported here (not at module top) so the loader doesn't fail to import
    on machines without pyodbc when only --list / --detect are needed.
    """
    try:
        import pyodbc
    except ImportError as e:
        raise PreflightError(
            "pyodbc is required for database checks but isn't installed. "
            "Install with: pip install pyodbc"
        ) from e
    # Prefer Driver 17 (matches our BCP recommendation), fall back if absent
    driver_candidates = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "SQL Server",  # last-resort built-in
    ]
    installed = set(pyodbc.drivers())
    chosen = next((d for d in driver_candidates if d in installed), None)
    if chosen is None:
        raise PreflightError(
            f"No SQL Server ODBC driver found. Installed drivers: {sorted(installed)}"
        )
    conn_str = (
        f"Driver={{{chosen}}};"
        f"Server={server};"
        f"Database={database};"
        f"Trusted_Connection=yes;"
        f"TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=10)


# -----------------------------------------------------------------------------
# Preflight
# -----------------------------------------------------------------------------
def preflight(
    plugin: SourcePlugin,
    source_path: Path,
    options: RunOptions,
) -> None:
    """
    Validate that this load can succeed before spending 90s on parse.

    Checks (in order — stops at first failure):
      1. Source file exists and is readable
      2. BCP executable is locatable (find_bcp_exe)
      3. Database connection works
      4. Target tables exist (plugin.native_table, dv_well, dv_well_identifier)
      5. Column counts on dv_well and dv_well_ext_<source> match what the
         plugin expects (positional BCP load requires exact alignment)
      6. h3 library importable if the plugin populates h3 (sniff well_columns
         for 'h3_r5' on one sample row — best-effort, not a hard check)
      7. Idempotency: if rows already exist for this source AND --reload not
         given, refuse with a clear message.

    Raises PreflightError on any failure. Caller is responsible for printing
    the message and exiting.
    """
    print("── Phase 0: preflight ──")

    # 1) Source file
    if not source_path.exists():
        raise PreflightError(f"Source file not found: {source_path}")
    if not source_path.is_file():
        raise PreflightError(f"Source path is not a file: {source_path}")
    print(f"   source: {source_path} ({source_path.stat().st_size:,} bytes)")

    # 2) BCP executable
    try:
        bcp_exe = find_bcp_exe()
        print(f"   bcp:    {bcp_version()}")
    except FileNotFoundError as e:
        raise PreflightError(str(e)) from e

    # 3) Database connection
    try:
        con = _connect(options.server, options.database)
    except Exception as e:
        raise PreflightError(
            f"Cannot connect to {options.server}/{options.database}: {e}"
        ) from e

    try:
        cur = con.cursor()

        # 4) Target tables exist
        target_tables = [
            plugin.native_table,            # dataview.dv_well_ext_<source>
            "dataview.dv_well",
            "dataview.dv_well_identifier",
        ]
        for fqn in target_tables:
            schema, _, name = fqn.partition(".")
            cur.execute(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
                schema, name,
            )
            if cur.fetchone()[0] != 1:
                raise PreflightError(
                    f"Target table {fqn} not found. Create it before loading."
                )
        print(f"   tables: all 3 target tables present")

        # 5) Column-count alignment
        schema, _, name = plugin.native_table.partition(".")
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            schema, name,
        )
        ext_col_count = cur.fetchone()[0]
        plugin_ext_cols = plugin.native_column_order()
        if ext_col_count != len(plugin_ext_cols):
            raise PreflightError(
                f"Column count mismatch on {plugin.native_table}: "
                f"DB has {ext_col_count}, plugin yields {len(plugin_ext_cols)}. "
                "Positional BCP load would mis-align. Update the table DDL "
                "or the plugin's native_column_order()."
            )

        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = 'dataview' AND TABLE_NAME = 'dv_well'"
        )
        dv_well_col_count = cur.fetchone()[0]
        if dv_well_col_count != len(DV_WELL_COLUMNS):
            raise PreflightError(
                f"Column count mismatch on dataview.dv_well: "
                f"DB has {dv_well_col_count}, code expects "
                f"{len(DV_WELL_COLUMNS)}. Update DV_WELL_COLUMNS in "
                f"cleaning.py OR adjust the table DDL."
            )
        print(f"   columns: ext={ext_col_count}, dv_well={dv_well_col_count} OK")

        # 6) h3 library — soft check. We don't know without parsing a row
        # whether the plugin populates h3 columns, so just inform the user
        # of import status. The plugin handles h3 absence gracefully (NULL
        # columns).
        try:
            import h3  # noqa: F401
            print(f"   h3:     library available")
        except ImportError:
            print(f"   h3:     not installed — h3 columns will be NULL "
                  f"(install: pip install h3)")

        # 7) Idempotency check
        cur.execute(
            "SELECT COUNT(*) FROM dataview.dv_well WHERE source = ?",
            plugin.source_label,
        )
        existing = cur.fetchone()[0]
        if existing > 0:
            if not options.reload:
                raise PreflightError(
                    f"dataview.dv_well already has {existing:,} rows for "
                    f"source='{plugin.source_label}'. "
                    f"Pass --reload to clear and re-load (DESTRUCTIVE — "
                    f"deletes existing rows in dv_well, dv_well_ext_"
                    f"{plugin.source_label.lower()}, and dv_well_identifier "
                    f"for this source)."
                )
            print(f"   reload: will clear {existing:,} existing "
                  f"'{plugin.source_label}' rows before load")

    finally:
        try:
            con.close()
        except Exception:
            pass

    print(f"   preflight passed.\n")


# -----------------------------------------------------------------------------
# Source-data cleanup (--reload)
# -----------------------------------------------------------------------------
def _clear_existing_source_rows(plugin: SourcePlugin, options: RunOptions) -> None:
    """
    Delete existing rows for this plugin's source from dv_well, the ext
    table, and dv_well_identifier. Called only when --reload was passed
    and preflight confirmed existing rows.

    Order: identifier → well → ext (children to parents, like the cleanup
    we did manually today). Wrapped in a single transaction so partial
    cleanup is impossible.
    """
    print("── Cleanup: removing existing source rows (--reload) ──")
    con = _connect(options.server, options.database)
    try:
        cur = con.cursor()
        con.autocommit = False
        cur.execute(
            "DELETE FROM dataview.dv_well_identifier WHERE source_system = ?",
            plugin.source_label,
        )
        n_id = cur.rowcount
        cur.execute(
            "DELETE FROM dataview.dv_well WHERE source = ?",
            plugin.source_label,
        )
        n_well = cur.rowcount
        # Ext table is source-specific (one table per source) so a TRUNCATE
        # is correct — no other-source rows can live in it.
        cur.execute(f"TRUNCATE TABLE {plugin.native_table}")
        con.commit()
        print(f"   dv_well_identifier: {n_id:,} deleted")
        print(f"   dv_well:            {n_well:,} deleted")
        print(f"   {plugin.native_table}: truncated")
        print()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------


def run(
    plugin: SourcePlugin,
    source_path: Path,
    options: RunOptions | None = None,
) -> LoadStats:
    """
    Run a plugin against a source file.

    The runner:
      1. Calls plugin.parse_rows(source_path) — a generator
      2. For each ParsedRow, writes:
           - one row to ext_csv (dv_well_ext_<source>)
           - one row to well_csv (dv_well)
           - 1-N rows to id_csv (dv_well_identifier, one per identifier tuple)
      3. Tracks stats in LoadStats
      4. Optionally BCPs the three CSVs into their target tables
      5. Optionally cleans up staging files

    Returns the LoadStats for inspection / display.
    """
    options = options or RunOptions()
    stats = LoadStats()

    print("=" * 70)
    print(f"PLUGIN LOAD: {plugin.name} ({plugin.description})")
    print("=" * 70)
    print(f"  Source        : {source_path}")
    print(f"  Native table  : {plugin.native_table}")
    print(f"  Source label  : '{plugin.source_label}'")
    print(f"  Server / DB   : {options.server} / {options.database}")
    print(f"  Dry run       : {options.dry_run}")
    print(f"  Skip BCP      : {options.skip_bcp}")
    print(f"  Reload        : {options.reload}")
    print(f"  Skip preflight: {options.skip_preflight}")
    print()

    # ───── Phase 0: preflight ─────
    # Validates that everything needed for the load is in place BEFORE
    # spending ~90 seconds on parse + staging. Catches schema drift,
    # missing BCP, existing-data conflicts, etc.
    if not options.skip_preflight and not options.dry_run:
        try:
            preflight(plugin, source_path, options)
        except PreflightError as e:
            print()
            print("PREFLIGHT FAILED")
            print("-" * 70)
            print(str(e))
            print("-" * 70)
            print("Aborting. Fix the issue above and re-run.")
            raise
    elif options.skip_preflight:
        print("── Phase 0: preflight SKIPPED (--skip-preflight) ──\n")
    # dry-run skips preflight too — dry-run is meant to be a no-DB exercise

    # If --reload AND we're not dry-running, clear existing source rows.
    # Preflight has already verified the rows exist and that --reload was
    # passed; here we just do the destructive part.
    if options.reload and not options.dry_run and not options.skip_preflight:
        _clear_existing_source_rows(plugin, options)

    staging_dir = get_staging_dir(f"dw_load_{plugin.name.lower()}")
    ext_csv  = staging_dir / f"{plugin.name.lower()}_ext.csv"
    well_csv = staging_dir / f"{plugin.name.lower()}_well.csv"
    id_csv   = staging_dir / f"{plugin.name.lower()}_identifier.csv"

    # ───── Phase 1: parse + stage ─────
    print("── Phase 1: parse + stage ──")
    stats.parse_start = _now()

    native_cols = plugin.native_column_order()
    well_cols   = plugin.well_column_order()

    ext_w  = BcpCsvWriter(ext_csv)
    well_w = BcpCsvWriter(well_csv)
    id_w   = BcpCsvWriter(id_csv)

    load_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    seen_uwis: set[str] = set()

    try:
        for parsed in plugin.parse_rows(source_path):
            stats.rows_read += 1

            # Progress callback every 10K rows
            if options.on_progress and stats.rows_read % 10_000 == 0:
                options.on_progress("parse", stats.rows_read, 0)

            if stats.rows_read % 50_000 == 0:
                print(f"   {stats.rows_read:,} rows read…")

            # Duplicate detection
            if parsed.uwi in seen_uwis:
                stats.duplicate_uwis += 1
                continue
            seen_uwis.add(parsed.uwi)
            stats.rows_accepted += 1

            # Stats counters (look at the standard PPDM columns)
            wc = parsed.well_columns
            if wc.get("surface_latitude") is not None:
                stats.rows_with_coords += 1
            else:
                stats.rows_without_coords += 1
            if wc.get("api_num"):
                stats.rows_with_api += 1
            if wc.get("operator_name"):
                stats.rows_with_operator += 1
            if wc.get("field_name"):
                stats.rows_with_field += 1

            # ext_csv row (native columns in plugin-defined order)
            ext_w.write_row(
                parsed.native_columns.get(c) for c in native_cols
            )

            # well_csv row (canonical dv_well order; absent cols → None)
            well_w.write_row(
                parsed.well_columns.get(c) for c in well_cols
            )

            # identifier_csv rows
            well_id = str(uuid.uuid4())
            for itype, ivalue, is_primary in parsed.identifiers:
                id_w.write_row([
                    well_id,
                    itype,
                    ivalue,
                    plugin.source_label,
                    load_ts,
                    1 if is_primary else 0,
                ])

    finally:
        n_ext  = ext_w.close()
        n_well = well_w.close()
        n_id   = id_w.close()

    stats.parse_end = _now()

    print(f"   staging files:")
    print(f"     {ext_csv.name}        : {n_ext:,} rows")
    print(f"     {well_csv.name}       : {n_well:,} rows")
    print(f"     {id_csv.name}         : {n_id:,} rows")
    print(f"   phase 1 elapsed: {stats.parse_seconds:.1f}s")

    if options.dry_run:
        print()
        print("Dry run — skipping BCP.")
        if not options.keep_staging:
            cleanup_staging(ext_csv, well_csv, id_csv)
        return stats

    if options.skip_bcp:
        print()
        print("--skip-bcp — staging CSVs kept for inspection:")
        print(f"   {ext_csv}")
        print(f"   {well_csv}")
        print(f"   {id_csv}")
        return stats

    # ───── Phase 2: BCP load ─────
    print()
    print("── Phase 2: BCP load ──")
    stats.load_start = _now()

    # Per-table error files (BCP -e writes rejected rows to these). Created
    # alongside the staging CSVs so they're collocated for inspection.
    err_files = {
        plugin.native_table:           staging_dir / f"{plugin.name.lower()}_ext.err.txt",
        "dataview.dv_well":            staging_dir / f"{plugin.name.lower()}_well.err.txt",
        "dataview.dv_well_identifier": staging_dir / f"{plugin.name.lower()}_identifier.err.txt",
    }

    # Track which BCPs have succeeded so we can be precise about state on
    # a mid-pipeline failure. (Partial state is the most painful failure
    # mode — see today's session notes.)
    bcps_succeeded: list[str] = []
    bcp_failure: BcpError | None = None

    try:
        for csv_path, table in (
            (ext_csv,  plugin.native_table),
            (well_csv, "dataview.dv_well"),
            (id_csv,   "dataview.dv_well_identifier"),
        ):
            if options.on_progress:
                options.on_progress(f"bcp {table}", 0, 0)
            print(f"   bcp in {table}: {csv_path.name}")
            rows, elapsed = bcp_in(
                csv_path=csv_path,
                table_fqn=table,
                server=options.server,
                database=options.database,
                error_file=err_files[table],
            )
            stats.bcp_rows_loaded[table] = rows
            stats.bcp_elapsed[table] = elapsed
            bcps_succeeded.append(table)
            print(f"     {rows:,} rows copied in {elapsed:.1f}s")
    except BcpError as e:
        bcp_failure = e
        stats.load_end = _now()
        # DO NOT clean up — staging is needed for the user to diagnose.
        print()
        print("=" * 70)
        print("LOAD FAILED")
        print("=" * 70)
        print(str(e))
        print()
        print("Staging files preserved for inspection:")
        for csv in (ext_csv, well_csv, id_csv):
            if csv.exists():
                print(f"   {csv}")
        for tbl, err in err_files.items():
            if err.exists() and err.stat().st_size > 0:
                print(f"   {err}  (BCP error rows for {tbl})")
        if bcps_succeeded:
            print()
            print(f"Note: the following BCPs DID succeed before the failure:")
            for t in bcps_succeeded:
                print(f"   - {t}  ({stats.bcp_rows_loaded.get(t, 0):,} rows)")
            print("Re-running with --reload will clear and reload all "
                  "three tables for this source.")
        raise
    finally:
        stats.load_end = _now()

    # Success: clean up unless the user asked to keep staging
    if not options.keep_staging:
        cleanup_staging(ext_csv, well_csv, id_csv)
        for err in err_files.values():
            # Tiny .err.txt files (zero-byte successes); clean these too
            try:
                if err.exists() and err.stat().st_size == 0:
                    err.unlink()
            except OSError:
                pass

    print()
    print("=" * 70)
    print("LOAD COMPLETE")
    print("=" * 70)
    for line in stats.summary_lines():
        print(f"  {line}")

    return stats


def _now() -> float:
    """Return monotonic seconds."""
    from time import monotonic
    return monotonic()

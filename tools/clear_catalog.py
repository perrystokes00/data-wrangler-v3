r"""
clear_catalog.py — reset the document pipeline to empty.  DRY-RUN by default.

Clears (FK constraints disabled, rows deleted, identities reseeded, constraints
re-enabled — all in one transaction):

  * every table in file_catalog   (GLOBAL_FILE_CATALOG, FILE_*_HEADER, cat_*)
  * every table in las_catalog     (binary curve / seismic detail)
  * from the catalog-derived dv_* tables (the promote allowlist: dv_well +
    details, dv_log_curve, dv_prod_*), ONLY the rows promote stamped with an
    INVENTORY_ID — i.e. the rows that came from the file catalog. Bulk-loaded
    or hand-loaded rows (INVENTORY_ID NULL), and every reference / spatial /
    lookup table (dv_country, dv_province_state, dv_county, dv_r_*,
    api_state_code, …), are left fully intact.

Optionally deletes the on-disk vault tree (<vault-root>\curated).

  python clear_catalog.py                                  # dry-run: list + counts
  python clear_catalog.py --apply                          # clear all DB tables
  python clear_catalog.py --apply --vault C:\Bulk\Vault    # also delete vault\curated
  python clear_catalog.py --apply --no-dv                  # leave dv_* alone
  python clear_catalog.py --apply --keep PIPELINE_RUN      # preserve named tables

Never touches WELL_REF, the reference seeders, or any reference/spatial table.
"""
import argparse
import os
import shutil
import sys

import pyodbc

CAT_SCHEMA = "file_catalog"
LAS_SCHEMA = "las_catalog"
DV_SCHEMA  = "dataview"

# Catalog-derived dv_* tables = the promote allowlist. Import to stay in sync
# with what promote populates; fall back to a hard copy if the import fails.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_catalog_mirror import MIRROR_TABLES as DV_TABLES
except Exception:
    DV_TABLES = [
        "dv_well", "dv_well_formation_top",
        "dv_well_dir_srvy_hdr", "dv_well_dir_srvy_sta",
        "dv_well_log", "dv_well_log_curve",   # deep log path
        "dv_log_curve",                       # legacy light path
        "dv_well_core", "dv_well_core_sample",
        "dv_well_petro_interp", "dv_well_petro_zone",
        "dv_well_completion", "dv_well_stimulation", "dv_well_dst",
        "dv_prod_entity", "dv_prod_volume",
    ]

# SET options required for DML on dv_well (it carries a spatial geography index).
_SET_OPTS = ("SET QUOTED_IDENTIFIER ON; SET ANSI_NULLS ON; SET ANSI_PADDING ON; "
             "SET ANSI_WARNINGS ON; SET ARITHABORT ON; "
             "SET CONCAT_NULL_YIELDS_NULL ON; SET NUMERIC_ROUNDABORT OFF;")


def connect(server, database):
    return pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};"
        f"DATABASE={database};Trusted_Connection=yes;",
        autocommit=False)


def _schema_tables(cur, schema):
    cur.execute(
        "SELECT t.name FROM sys.tables t "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "WHERE s.name = ? ORDER BY t.name", schema)
    return [r[0] for r in cur.fetchall()]


def _has_col(cur, schema, table, col):
    cur.execute(
        "SELECT 1 FROM sys.columns "
        "WHERE object_id = OBJECT_ID(?) AND name = ?",
        f"{schema}.{table}", col)
    return cur.fetchone() is not None


def _count(cur, schema, table, where=""):
    try:
        cur.execute(f"SELECT COUNT(*) FROM [{schema}].[{table}] {where}")
        return cur.fetchone()[0]
    except Exception:
        return -1


def gather(cur, do_dv, keep):
    """Everything we would clear, as [(schema, table, rowcount, scope)].

    scope is one of:
      'all'        delete every row (file_catalog / las_catalog working tables)
      'inventory'  delete only rows with INVENTORY_ID (catalog-promoted dv_*),
                   leaving bulk-loaded / hand-loaded rows untouched
      'skip'       a dv_* table with no INVENTORY_ID column — can't tell catalog
                   rows apart, so it is left alone
    """
    keepset = {k.upper() for k in keep}
    out = []
    for sch in (CAT_SCHEMA, LAS_SCHEMA):
        for t in _schema_tables(cur, sch):
            if t.upper() not in keepset:
                out.append((sch, t, _count(cur, sch, t), "all"))
    if do_dv:
        existing = set(_schema_tables(cur, DV_SCHEMA))
        for t in DV_TABLES:
            if t not in existing or t.upper() in keepset:
                continue
            if _has_col(cur, DV_SCHEMA, t, "INVENTORY_ID"):
                n = _count(cur, DV_SCHEMA, t, "WHERE INVENTORY_ID IS NOT NULL")
                out.append((DV_SCHEMA, t, n, "inventory"))
            else:
                out.append((DV_SCHEMA, t, -1, "skip"))
    return out


def clear(cur, tables, log):
    # disable FK constraints on every table we'll touch so delete order is free
    targets = [r for r in tables if r[3] != "skip"]
    for sch, tbl, _, _ in targets:
        cur.execute(f"ALTER TABLE [{sch}].[{tbl}] NOCHECK CONSTRAINT ALL")
    # delete per scope
    for sch, tbl, n, scope in tables:
        if scope == "skip":
            log(f"  SKIP    {sch}.{tbl}  (no INVENTORY_ID — can't scope to "
                f"catalog rows; left intact)")
            continue
        if scope == "inventory":
            cur.execute(
                f"DELETE FROM [{sch}].[{tbl}] WHERE INVENTORY_ID IS NOT NULL")
            log(f"  cleared {sch}.{tbl}  ({n:,} catalog rows; kept the rest)")
        else:  # 'all'
            cur.execute(f"DELETE FROM [{sch}].[{tbl}]")
            cur.execute(
                f"IF EXISTS (SELECT 1 FROM sys.identity_columns "
                f"WHERE object_id = OBJECT_ID('{sch}.{tbl}')) "
                f"DBCC CHECKIDENT('{sch}.{tbl}', RESEED, 0) WITH NO_INFOMSGS")
            log(f"  cleared {sch}.{tbl}  ({n:,} rows)")
    # re-enable constraints (plain CHECK — don't re-validate surviving rows)
    for sch, tbl, _, _ in targets:
        cur.execute(f"ALTER TABLE [{sch}].[{tbl}] CHECK CONSTRAINT ALL")


def clear_vault(vault_root, apply, log):
    curated = os.path.join(vault_root, "curated")
    if not os.path.isdir(curated):
        log(f"  vault: nothing at {curated}")
        return
    nfiles = sum(len(f) for _, _, f in os.walk(curated))
    if apply:
        shutil.rmtree(curated)
        log(f"  vault: deleted {curated}  ({nfiles:,} files)")
    else:
        log(f"  vault: would delete {curated}  ({nfiles:,} files)")


def main():
    ap = argparse.ArgumentParser(
        description="Clear the document-pipeline tables (+ optional vault).")
    ap.add_argument("--server", default=r"PERRY\SQLEXPRESS")
    ap.add_argument("--database", default="DataView")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default: dry-run, counts only)")
    ap.add_argument("--no-dv", action="store_true",
                    help="leave the dv_* catalog tables alone")
    ap.add_argument("--keep", nargs="*", default=[],
                    help="table name(s) to preserve, e.g. --keep PIPELINE_RUN")
    ap.add_argument("--vault", default=None,
                    help=r"vault root; deletes <root>\curated")
    a = ap.parse_args()

    con = connect(a.server, a.database)
    cur = con.cursor()
    cur.execute(_SET_OPTS)

    tables = gather(cur, do_dv=not a.no_dv, keep=a.keep)
    total = sum(n for _, _, n, sc in tables if n > 0 and sc != "skip")

    print(f"-- target : {a.server} / {a.database}")
    print(f"-- mode   : {'APPLY (delete)' if a.apply else 'DRY-RUN'}"
          f"{'  (dv_* kept)' if a.no_dv else ''}")
    print(f"\n{'table':48} {'rows':>10}  scope")
    print("-" * 72)
    for sch, tbl, n, scope in tables:
        rows = "   (skip)" if scope == "skip" else f"{n:>10,}"
        tag = {"all": "all rows", "inventory": "catalog rows only",
               "skip": "no INVENTORY_ID — left intact"}[scope]
        print(f"{sch + '.' + tbl:48} {rows}  {tag}")
    print("-" * 72)
    print(f"{'TOTAL rows to delete':48} {total:>10,}")
    if a.vault:
        clear_vault(a.vault, False, print)   # always show the vault plan

    if not a.apply:
        print("\n-- dry-run; nothing deleted. Re-run with --apply to clear.")
        con.close()
        return 0

    try:
        print()
        clear(cur, tables, print)
        con.commit()
    except Exception as e:
        con.rollback()
        print(f"\n-- ERROR (rolled back, nothing deleted): {e}", file=sys.stderr)
        con.close()
        return 1
    con.close()

    if a.vault:
        clear_vault(a.vault, True, print)

    print("\n-- done. Cleared file_catalog + las_catalog"
          + ("" if a.no_dv else " + dv_* catalog tables")
          + (" + vault\\curated" if a.vault else "") + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())

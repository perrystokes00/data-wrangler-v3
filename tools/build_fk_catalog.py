"""
build_fk_catalog.py  —  PPDM Loader · FK Catalog Builder
==========================================================
Generates a JSON catalog of all FK constraints, PKs, and table
classifications from a live database.  Run this once after installing
PPDM to populate the catalog; thereafter FK introspection reads from
the JSON file instead of querying the DB on every pipeline run.

Usage (SQL Server):
    python build_fk_catalog.py --dialect sqlserver ^
        --server PERRY\\SQLEXPRESS --database PPDM39_DEMO_1 --windows-auth
        ap.add_argument("--schema", default="dbo")

Usage (Oracle):
    python build_fk_catalog.py --dialect oracle ^
        --host localhost --port 1521 --service FREEPDB1 ^
        --username PERRY --password secret

Output:
    schema_registry/dataview_fk_catalog.json

The catalog is automatically used by fk.py when present.
Re-run any time you add tables or constraints to the database.
"""

from __future__ import annotations
import argparse
import json
import pathlib
import sys
from datetime import datetime

_OUT = pathlib.Path(__file__).parent / "schema_registry" / "dataview_fk_catalog.json"
_REFERENCE_PREFIXES = ("r_", "ra_", "rb_")


# ═══════════════════════════════════════════════════════════════════════
# ORACLE BUILDER
# ═══════════════════════════════════════════════════════════════════════

def _build_oracle(engine) -> dict:
    from sqlalchemy import text

    print("  Resolving Oracle schema...")
    with engine.connect() as con:
        schema = con.execute(text(
            "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
        )).scalar() or ""
    schema = schema.upper()
    print(f"  Schema: {schema}")

    catalog = {
        "dialect":      "oracle",
        "schema":       schema,
        "built_at":     datetime.utcnow().isoformat(),
        "fk_constraints": {},   # table → list of constraint dicts
        "table_pk":       {},   # table → list of pk col names
        "table_cols":     {},   # table → {col: {type, nullable, max_length}}
        "table_kind":     {},   # table → "reference" | "entity"
    }

    # ── All FK constraints ───────────────────────────────────────────
    print("  Fetching FK constraints...")
    with engine.connect() as con:
        fk_rows = con.execute(text("""
            SELECT
                con.constraint_name,
                con.table_name          AS child_table,
                cc.column_name          AS child_col,
                rcon.table_name         AS parent_table,
                pc.column_name          AS parent_col,
                cc.position             AS ordinal,
                CASE WHEN tc.nullable = 'Y' THEN 1 ELSE 0 END AS is_nullable
            FROM all_constraints con
            JOIN all_cons_columns cc
              ON cc.constraint_name = con.constraint_name
             AND cc.owner = con.owner
            JOIN all_constraints rcon
              ON rcon.constraint_name = con.r_constraint_name
             AND rcon.owner = con.r_owner
            JOIN all_cons_columns pc
              ON pc.constraint_name = rcon.constraint_name
             AND pc.owner = rcon.owner
             AND pc.position = cc.position
            JOIN all_tab_columns tc
              ON tc.owner = con.owner
             AND tc.table_name = con.table_name
             AND tc.column_name = cc.column_name
            WHERE con.constraint_type = 'R'
              AND con.owner = :sch
            ORDER BY con.table_name, con.constraint_name, cc.position
        """), {"sch": schema}).fetchall()

    # Group by (child_table, constraint_name)
    from collections import defaultdict
    _fk_map: dict[str, dict[str, dict]] = defaultdict(dict)
    for cname, ctbl, ccol, ptbl, pcol, ordinal, nullable in fk_rows:
        ctbl = ctbl.upper()
        cname = cname.upper()
        if cname not in _fk_map[ctbl]:
            _fk_map[ctbl][cname] = {
                "constraint_name": cname,
                "child_cols":  [],
                "parent_table": ptbl.upper(),
                "parent_cols": [],
                "nullable":    bool(nullable),
            }
        _fk_map[ctbl][cname]["child_cols"].append(ccol.upper())
        _fk_map[ctbl][cname]["parent_cols"].append(pcol.upper())

    for tbl, constraints in _fk_map.items():
        catalog["fk_constraints"][tbl] = list(constraints.values())

    # ── All PKs ──────────────────────────────────────────────────────
    print("  Fetching primary keys...")
    with engine.connect() as con:
        pk_rows = con.execute(text("""
            SELECT con.table_name, cc.column_name, cc.position
            FROM all_constraints con
            JOIN all_cons_columns cc
              ON cc.constraint_name = con.constraint_name
             AND cc.owner = con.owner
            WHERE con.constraint_type = 'P'
              AND con.owner = :sch
            ORDER BY con.table_name, cc.position
        """), {"sch": schema}).fetchall()

    pk_map: dict[str, list] = defaultdict(list)
    for tbl, col, _ in pk_rows:
        pk_map[tbl.upper()].append(col.upper())
    catalog["table_pk"] = dict(pk_map)

    # ── All column metadata ──────────────────────────────────────────
    print("  Fetching column metadata...")
    with engine.connect() as con:
        col_rows = con.execute(text("""
            SELECT table_name, column_name, data_type,
                   nullable, char_length, data_precision, data_scale
            FROM all_tab_columns
            WHERE owner = :sch
            ORDER BY table_name, column_id
        """), {"sch": schema}).fetchall()

    for tbl, col, dtype, nullable, charlen, prec, scale in col_rows:
        tbl = tbl.upper()
        col = col.upper()
        if tbl not in catalog["table_cols"]:
            catalog["table_cols"][tbl] = {}
        catalog["table_cols"][tbl][col] = {
            "type":       dtype,
            "nullable":   nullable == "Y",
            "max_length": int(charlen) if charlen else (int(prec) if prec else 0),
        }

    # ── Table classification ─────────────────────────────────────────
    all_tables = set(catalog["table_cols"].keys())
    for tbl in all_tables:
        tl = tbl.lower()
        catalog["table_kind"][tbl] = (
            "reference" if any(tl.startswith(p) for p in _REFERENCE_PREFIXES)
            else "entity"
        )

    print(f"  Done — {len(catalog['fk_constraints'])} tables with FKs, "
          f"{len(catalog['table_pk'])} tables with PKs, "
          f"{len(catalog['table_cols'])} tables total")
    return catalog


# ═══════════════════════════════════════════════════════════════════════
# SQL SERVER BUILDER
# ═══════════════════════════════════════════════════════════════════════

def _build_sqlserver(engine, schema: str = "dbo") -> dict:
    from sqlalchemy import text

    catalog = {
        "dialect":        "sqlserver",
        "schema":         schema,
        "built_at":       datetime.utcnow().isoformat(),
        "fk_constraints": {},
        "table_pk":       {},
        "table_cols":     {},
        "table_kind":     {},
    }

    # ── All FK constraints ───────────────────────────────────────────
    print("  Fetching FK constraints...")
    with engine.connect() as con:
        fk_rows = con.execute(text("""
            SELECT
                fk.name                         AS constraint_name,
                ct.name                         AS child_table,
                cc.name                         AS child_col,
                pt.name                         AS parent_table,
                pc.name                         AS parent_col,
                fkc.constraint_column_id        AS ordinal,
                cc.is_nullable                  AS is_nullable
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns  fkc
                 ON fkc.constraint_object_id = fk.object_id
            JOIN sys.tables  ct  ON ct.object_id  = fk.parent_object_id
            JOIN sys.schemas cs  ON cs.schema_id  = ct.schema_id
            JOIN sys.columns cc  ON cc.object_id  = fk.parent_object_id
                                 AND cc.column_id = fkc.parent_column_id
            JOIN sys.tables  pt  ON pt.object_id  = fk.referenced_object_id
            JOIN sys.schemas ps  ON ps.schema_id  = pt.schema_id
            JOIN sys.columns pc  ON pc.object_id  = fk.referenced_object_id
                                 AND pc.column_id = fkc.referenced_column_id
            WHERE cs.name = :sch
            ORDER BY ct.name, fk.name, fkc.constraint_column_id
        """), {"sch": schema}).fetchall()

    from collections import defaultdict
    _fk_map: dict[str, dict[str, dict]] = defaultdict(dict)
    for cname, ctbl, ccol, ptbl, pcol, ordinal, nullable in fk_rows:
        ctbl  = ctbl.upper()
        cname = cname.upper()
        if cname not in _fk_map[ctbl]:
            _fk_map[ctbl][cname] = {
                "constraint_name": cname,
                "child_cols":   [],
                "parent_table": ptbl.upper(),
                "parent_cols":  [],
                "nullable":     bool(nullable),
            }
        _fk_map[ctbl][cname]["child_cols"].append(ccol.upper())
        _fk_map[ctbl][cname]["parent_cols"].append(pcol.upper())

    for tbl, constraints in _fk_map.items():
        catalog["fk_constraints"][tbl] = list(constraints.values())

    # ── All PKs ──────────────────────────────────────────────────────
    print("  Fetching primary keys...")
    with engine.connect() as con:
        pk_rows = con.execute(text("""
            SELECT t.name, c.name, ic.key_ordinal
            FROM sys.indexes        i
            JOIN sys.index_columns  ic ON ic.object_id = i.object_id
                                      AND ic.index_id  = i.index_id
            JOIN sys.columns        c  ON c.object_id  = i.object_id
                                      AND c.column_id  = ic.column_id
            JOIN sys.tables         t  ON t.object_id  = i.object_id
            JOIN sys.schemas        s  ON s.schema_id  = t.schema_id
            WHERE i.is_primary_key = 1 AND s.name = :sch
            ORDER BY t.name, ic.key_ordinal
        """), {"sch": schema}).fetchall()

    pk_map: dict[str, list] = defaultdict(list)
    for tbl, col, _ in pk_rows:
        pk_map[tbl.upper()].append(col.upper())
    catalog["table_pk"] = dict(pk_map)

    # ── All column metadata ──────────────────────────────────────────
    print("  Fetching column metadata...")
    with engine.connect() as con:
        col_rows = con.execute(text("""
            SELECT
                t.name      AS table_name,
                c.name      AS col_name,
                tp.name     AS type_name,
                c.is_nullable,
                c.max_length,
                c.precision,
                c.scale
            FROM sys.columns  c
            JOIN sys.types    tp ON tp.user_type_id = c.user_type_id
            JOIN sys.tables   t  ON t.object_id  = c.object_id
            JOIN sys.schemas  s  ON s.schema_id  = t.schema_id
            WHERE s.name = :sch
            ORDER BY t.name, c.column_id
        """), {"sch": schema}).fetchall()

    for tbl, col, dtype, nullable, maxlen, prec, scale in col_rows:
        tbl = tbl.upper()
        col = col.upper()
        # nvarchar max_length is in bytes (2 per char)
        char_len = maxlen // 2 if dtype.lower().startswith("n") else maxlen
        if tbl not in catalog["table_cols"]:
            catalog["table_cols"][tbl] = {}
        catalog["table_cols"][tbl][col] = {
            "type":       dtype,
            "nullable":   bool(nullable),
            "max_length": char_len if char_len > 0 else 0,
        }

    # ── Table classification ─────────────────────────────────────────
    all_tables = set(catalog["table_cols"].keys())
    for tbl in all_tables:
        tl = tbl.lower()
        catalog["table_kind"][tbl] = (
            "reference" if any(tl.startswith(p) for p in _REFERENCE_PREFIXES)
            else "entity"
        )

    print(f"  Done — {len(catalog['fk_constraints'])} tables with FKs, "
          f"{len(catalog['table_pk'])} tables with PKs, "
          f"{len(catalog['table_cols'])} tables total")
    return catalog


# ═══════════════════════════════════════════════════════════════════════
# CONNECTION HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _connect_oracle(args):
    import oracledb
    from sqlalchemy import create_engine, text
    dsn = f"{args.host}:{args.port}/{args.service}"
    def _creator():
        return oracledb.connect(user=args.username, password=args.password, dsn=dsn)
    engine = create_engine("oracle+oracledb://", creator=_creator,
                           pool_size=2, max_overflow=2)
    with engine.connect() as con:
        ver = con.execute(text(
            "SELECT banner FROM v$version WHERE ROWNUM=1"
        )).scalar()
    print(f"  Connected: {ver[:60]}")
    return engine


def _connect_sqlserver(args):
    import urllib.parse
    from sqlalchemy import create_engine, text
    if args.windows_auth:
        cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};"
              f"SERVER={args.server};DATABASE={args.database};"
              f"Trusted_Connection=yes;")
    else:
        cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};"
              f"SERVER={args.server};DATABASE={args.database};"
              f"UID={args.username};PWD={args.password};")
    engine = create_engine(
        "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(cs),
        fast_executemany=True)
    with engine.connect() as con:
        ver = con.execute(text("SELECT @@VERSION")).scalar()
    print(f"  Connected: {str(ver)[:60]}")
    return engine


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Build PPDM FK catalog JSON from live database")
    ap.add_argument("--dialect", required=True, choices=["oracle", "sqlserver"])
    # Oracle args
    ap.add_argument("--host",     default="localhost")
    ap.add_argument("--port",     type=int, default=1521)
    ap.add_argument("--service",  default="FREEPDB1")
    # SQL Server args
    ap.add_argument("--server",   default="")
    ap.add_argument("--database", default="")
    ap.add_argument("--windows-auth", action="store_true")
    ap.add_argument("--schema", default="dbo")
    # Shared
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--out", default=str(_OUT),
                    help=f"Output path (default: {_OUT})")
    args = ap.parse_args()

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\nPPDM FK Catalog Builder — {args.dialect.upper()}")
    print("=" * 50)

    try:
        if args.dialect == "oracle":
            engine = _connect_oracle(args)
            catalog = _build_oracle(engine)
        else:
            engine = _connect_sqlserver(args)
            catalog = _build_sqlserver(engine, schema=args.schema)
    except Exception as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)

    out_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    size_kb = out_path.stat().st_size // 1024
    print(f"\nCatalog written to: {out_path}  ({size_kb} KB)")
    print("Done ✓")


if __name__ == "__main__":
    main()

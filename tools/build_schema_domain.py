"""
build_schema_domain.py  —  PPDM Loader · Schema Domain Builder
===============================================================
Regenerates dataview_schema_domain.json directly from a live database,
replacing the hand-crafted version with exact values from the installed
schema.  Supports Oracle and SQL Server.

Usage (Oracle):
    python build_schema_domain.py --dialect oracle ^
        --host localhost --port 1521 --service FREEPDB1 ^
        --username PERRY --password secret

Usage (SQL Server):
    python build_schema_domain.py --dialect sqlserver ^
        --server PERRY\\SQLEXPRESS --database PPDM39_DEMO_1 --windows-auth

Output:
    schema_registry/dataview_schema_domain.json

The output format is identical to the existing file so the app loads
it unchanged.  Re-run any time you alter the schema.
"""

from __future__ import annotations
import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone
from collections import defaultdict

_OUT = (pathlib.Path(__file__).parent.parent /
        "schema_registry" / "dataview_schema_domain.json")

# Table name prefix → category label
_CATEGORY_MAP = {
    "anl":   "ANL",  "bh":    "BH",   "c_":    "COOR",
    "coor":  "COOR", "cs":    "CS",   "cult":  "CULT",
    "doc":   "DOC",  "dp":    "DP",   "econ":  "ECON",
    "eq":    "EQ",   "fd":    "FD",   "gis":   "GIS",
    "land":  "LAND", "lith":  "LITH", "lu":    "LU",
    "ms":    "MS",   "pa":    "PA",   "pdep":  "PDEP",
    "pi":    "PI",   "ppdm":  "PPDM", "prod":  "PROD",
    "proj":  "PROJ", "r_":    "REF",  "ra_":   "REF",
    "rb_":   "REF",  "rm":    "RM",   "rpt":   "RPT",
    "sa":    "SA",   "seism": "SEIS", "sf":    "SF",
    "seis":  "SEIS", "sp":    "SP",   "srvy":  "SRVY",
    "strat": "STRAT","subs":  "SUBS", "surv":  "SURV",
    "tf":    "TF",   "ug":    "UG",   "uom":   "UOM",
    "well":  "WELL", "wl":    "WL",   "ws":    "WS",
    "wt":    "WT",
}

def _category(table_name: str) -> str:
    tl = table_name.lower()
    for prefix, cat in sorted(_CATEGORY_MAP.items(), key=lambda x: -len(x[0])):
        if tl.startswith(prefix):
            return cat
    return "OTHER"


def _ora_type_to_schema(dtype: str, char_len, prec, scale) -> str:
    """Convert Oracle data type to schema domain format."""
    d = dtype.upper()
    if d in ("VARCHAR2", "NVARCHAR2"):
        l = int(char_len) if char_len else 255
        return f"nvarchar({l})"
    if d in ("CHAR", "NCHAR"):
        l = int(char_len) if char_len else 1
        return f"nvarchar({l})"
    if d == "NUMBER":
        p = int(prec) if prec else 38
        s = int(scale) if scale else 0
        if s == 0:
            return f"numeric({p},0)"
        return f"numeric({p},{s})"
    if d == "FLOAT":
        return "float"
    if d == "DATE":
        return "datetime2"
    if d in ("TIMESTAMP", "TIMESTAMP(6)"):
        return "datetime2"
    if d == "CLOB":
        return "nvarchar(max)"
    if d == "BLOB":
        return "varbinary(max)"
    if d == "RAW":
        l = int(char_len) if char_len else 16
        return f"varbinary({l})"
    return dtype.lower()


def _ss_type_to_schema(dtype: str, max_length: int, prec, scale) -> str:
    """Normalize SQL Server type to schema domain format."""
    d = dtype.lower()
    if d in ("nvarchar", "nchar"):
        l = max_length // 2 if max_length > 0 else -1
        return f"nvarchar(max)" if l < 0 else f"nvarchar({l})"
    if d in ("varchar", "char"):
        l = max_length if max_length > 0 else -1
        return f"varchar(max)" if l < 0 else f"varchar({l})"
    if d in ("numeric", "decimal"):
        return f"numeric({prec or 18},{scale or 0})"
    return d


# ═══════════════════════════════════════════════════════════════════════
# ORACLE
# ═══════════════════════════════════════════════════════════════════════

def _build_oracle(engine) -> list[dict]:
    from sqlalchemy import text

    with engine.connect() as con:
        schema = con.execute(text(
            "SELECT SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM dual"
        )).scalar() or ""
    schema = schema.upper()
    print(f"  Schema: {schema}")

    # ── Columns ──────────────────────────────────────────────────────
    print("  Fetching columns...")
    with engine.connect() as con:
        col_rows = con.execute(text("""
            SELECT table_name, column_name, data_type,
                   nullable, char_length, data_precision, data_scale,
                   column_id
            FROM all_tab_columns
            WHERE owner = :sch
            ORDER BY table_name, column_id
        """), {"sch": schema}).fetchall()
    print(f"  {len(col_rows):,} columns fetched")

    # ── PKs ───────────────────────────────────────────────────────────
    print("  Fetching primary keys...")
    with engine.connect() as con:
        pk_rows = con.execute(text("""
            SELECT con.table_name, cc.column_name
            FROM all_constraints con
            JOIN all_cons_columns cc
              ON cc.constraint_name = con.constraint_name
             AND cc.owner = con.owner
            WHERE con.constraint_type = 'P'
              AND con.owner = :sch
        """), {"sch": schema}).fetchall()
    pk_set: set[tuple] = {(r[0].upper(), r[1].upper()) for r in pk_rows}

    # ── FKs ───────────────────────────────────────────────────────────
    print("  Fetching foreign keys...")
    with engine.connect() as con:
        fk_rows = con.execute(text("""
            SELECT
                con.table_name          AS child_table,
                cc.column_name          AS child_col,
                rcon.table_name         AS parent_table,
                pc.column_name          AS parent_col
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
            WHERE con.constraint_type = 'R'
              AND con.owner = :sch
        """), {"sch": schema}).fetchall()
    # child_col → (parent_table, parent_col)  — keep first FK if multiple
    fk_map: dict[tuple, tuple] = {}
    for ctbl, ccol, ptbl, pcol in fk_rows:
        key = (ctbl.upper(), ccol.upper())
        if key not in fk_map:
            fk_map[key] = (ptbl.upper(), pcol.upper())

    # ── Check constraints ─────────────────────────────────────────────
    print("  Fetching check constraints...")
    with engine.connect() as con:
        ck_rows = con.execute(text("""
            SELECT table_name, constraint_name, search_condition
            FROM all_constraints
            WHERE constraint_type = 'C'
              AND owner = :sch
              AND generated = 'USER NAME'
            ORDER BY table_name, constraint_name
        """), {"sch": schema}).fetchall()
    ck_map: dict[str, list[str]] = defaultdict(list)
    for tbl, cname, cond in ck_rows:
        if cond:
            ck_map[tbl.upper()].append(f"{cname}: ({cond})")

    # ── Assemble rows ─────────────────────────────────────────────────
    print("  Assembling schema domain rows...")
    rows = []
    for tbl, col, dtype, nullable, charlen, prec, scale, _ in col_rows:
        tbl_up  = tbl.upper()
        col_up  = col.upper()
        is_pk   = (tbl_up, col_up) in pk_set
        fk_info = fk_map.get((tbl_up, col_up))
        cat     = _category(tbl_up)
        rows.append({
            "model":          "PPDM 3.9",
            "category":       cat,
            "sub_category":   tbl.lower(),
            "table_schema":   "dbo",
            "table_name":     tbl.lower(),
            "column_name":    col.lower(),
            "data_type":      _ora_type_to_schema(dtype, charlen, prec, scale),
            "not_null":       "YES" if nullable == "N" else "NO",
            "is_primary_key": "YES" if is_pk else "NO",
            "is_foreign_key": "YES" if fk_info else "NO",
            "fk_table_schema": "dbo" if fk_info else None,
            "fk_table_name":   fk_info[0].lower() if fk_info else None,
            "fk_column_name":  fk_info[1] if fk_info else None,
            "check_constraints": " | ".join(ck_map.get(tbl_up, [])) or None,
        })

    return rows


# ═══════════════════════════════════════════════════════════════════════
# SQL SERVER
# ═══════════════════════════════════════════════════════════════════════

def _build_sqlserver(engine, schema: str = "dbo") -> list[dict]:
    from sqlalchemy import text

    print("  Fetching columns...")
    with engine.connect() as con:
        col_rows = con.execute(text("""
            SELECT
                t.name      AS table_name,
                c.name      AS col_name,
                tp.name     AS type_name,
                c.is_nullable,
                c.max_length,
                c.precision,
                c.scale,
                c.column_id
            FROM sys.columns  c
            JOIN sys.types    tp ON tp.user_type_id = c.user_type_id
            JOIN sys.tables   t  ON t.object_id = c.object_id
            JOIN sys.schemas  s  ON s.schema_id = t.schema_id
            WHERE s.name = :sch
            ORDER BY t.name, c.column_id
        """), {"sch": schema}).fetchall()
    print(f"  {len(col_rows):,} columns fetched")

    print("  Fetching primary keys...")
    with engine.connect() as con:
        pk_rows = con.execute(text("""
            SELECT t.name, c.name
            FROM sys.indexes       i
            JOIN sys.index_columns ic ON ic.object_id = i.object_id
                                     AND ic.index_id  = i.index_id
            JOIN sys.columns       c  ON c.object_id  = i.object_id
                                     AND c.column_id  = ic.column_id
            JOIN sys.tables        t  ON t.object_id  = i.object_id
            JOIN sys.schemas       s  ON s.schema_id  = t.schema_id
            WHERE i.is_primary_key = 1 AND s.name = :sch
        """), {"sch": schema}).fetchall()
    pk_set: set[tuple] = {(r[0].upper(), r[1].upper()) for r in pk_rows}

    print("  Fetching foreign keys...")
    with engine.connect() as con:
        fk_rows = con.execute(text("""
            SELECT
                ct.name AS child_table,
                cc.name AS child_col,
                pt.name AS parent_table,
                pc.name AS parent_col
            FROM sys.foreign_keys          fk
            JOIN sys.foreign_key_columns   fkc ON fkc.constraint_object_id = fk.object_id
            JOIN sys.tables  ct ON ct.object_id = fk.parent_object_id
            JOIN sys.schemas cs ON cs.schema_id = ct.schema_id
            JOIN sys.columns cc ON cc.object_id = fk.parent_object_id
                                AND cc.column_id = fkc.parent_column_id
            JOIN sys.tables  pt ON pt.object_id = fk.referenced_object_id
            JOIN sys.columns pc ON pc.object_id = fk.referenced_object_id
                                AND pc.column_id = fkc.referenced_column_id
            WHERE cs.name = :sch
        """), {"sch": schema}).fetchall()
    fk_map: dict[tuple, tuple] = {}
    for ctbl, ccol, ptbl, pcol in fk_rows:
        key = (ctbl.upper(), ccol.upper())
        if key not in fk_map:
            fk_map[key] = (ptbl.upper(), pcol.upper())

    print("  Fetching check constraints...")
    with engine.connect() as con:
        ck_rows = con.execute(text("""
            SELECT t.name, cc.name, cc.definition
            FROM sys.check_constraints cc
            JOIN sys.tables t ON t.object_id = cc.parent_object_id
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = :sch
            ORDER BY t.name, cc.name
        """), {"sch": schema}).fetchall()
    ck_map: dict[str, list[str]] = defaultdict(list)
    for tbl, cname, defn in ck_rows:
        if defn:
            ck_map[tbl.upper()].append(f"{cname}: {defn}")

    print("  Assembling schema domain rows...")
    rows = []
    for tbl, col, dtype, nullable, maxlen, prec, scale, _ in col_rows:
        tbl_up  = tbl.upper()
        col_up  = col.upper()
        is_pk   = (tbl_up, col_up) in pk_set
        fk_info = fk_map.get((tbl_up, col_up))
        cat     = _category(tbl_up)
        rows.append({
            "model":           "PPDM 3.9",
            "category":        cat,
            "sub_category":    tbl.lower(),
            "table_schema":    "dbo",
            "table_name":      tbl.lower(),
            "column_name":     col.lower(),
            "data_type":       _ss_type_to_schema(dtype, maxlen, prec, scale),
            "not_null":        "YES" if not nullable else "NO",
            "is_primary_key":  "YES" if is_pk else "NO",
            "is_foreign_key":  "YES" if fk_info else "NO",
            "fk_table_schema": "dbo" if fk_info else None,
            "fk_table_name":   fk_info[0].lower() if fk_info else None,
            "fk_column_name":  fk_info[1] if fk_info else None,
            "check_constraints": " | ".join(ck_map.get(tbl_up, [])) or None,
        })

    return rows


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
    print(f"  Connected: {str(ver)[:60]}")
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
        description="Build dataview_schema_domain.json from live database")
    ap.add_argument("--dialect", required=True, choices=["oracle", "sqlserver"])
    ap.add_argument("--host",     default="localhost")
    ap.add_argument("--port",     type=int, default=1521)
    ap.add_argument("--service",  default="FREEPDB1")
    ap.add_argument("--server",   default="")
    ap.add_argument("--database", default="")
    ap.add_argument("--windows-auth", action="store_true")
    ap.add_argument("--schema",       default="dbo",
                    help="SQL Server schema name (default: dbo)")
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--out", default=str(_OUT),
                    help=f"Output path (default: {_OUT})")
    args = ap.parse_args()

    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\nPPDM Schema Domain Builder — {args.dialect.upper()}")
    print("=" * 50)

    try:
        if args.dialect == "oracle":
            engine = _connect_oracle(args)
            rows = _build_oracle(engine)
        else:
            engine = _connect_sqlserver(args)
            rows = _build_sqlserver(engine, schema=args.schema)
    except Exception as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)

    payload = {"ppdm_39_schema_domain": rows}
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    size_kb = out_path.stat().st_size // 1024
    tables  = len({r["table_name"] for r in rows})
    print(f"\n  {len(rows):,} column rows across {tables:,} tables")
    print(f"  Written to: {out_path}  ({size_kb} KB)")
    print("Done ✓")


if __name__ == "__main__":
    main()

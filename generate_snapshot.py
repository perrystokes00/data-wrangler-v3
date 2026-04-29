"""
generate_snapshot.py  —  PPDM Database Schema Snapshot Generator
=================================================================
Uses a single server-side FOR JSON query — fast, one round trip.

Usage:
    python generate_snapshot.py

Edit the CONNECTION settings below to match your SQL Server.
Output is saved as db_schema_snapshot.json in the same folder.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import pyodbc
except ImportError:
    print("ERROR: pyodbc not installed. Run: pip install pyodbc")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════
# CONNECTION  —  edit these to match your setup
# ═══════════════════════════════════════════════════════════════════════
SERVER   = r"localhost"           # e.g. r"MYPC\SQLEXPRESS"
DATABASE = "PPDM39_DEMO_1"
DRIVER   = "ODBC Driver 17 for SQL Server"

# Windows Authentication — most common for local SQL Server
CONN_STR = (
    f"DRIVER={{{DRIVER}}};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    f"Trusted_Connection=yes;"
)

# SQL Server Authentication — uncomment if needed
# USERNAME = "sa"
# PASSWORD = "yourpassword"
# CONN_STR = (
#     f"DRIVER={{{DRIVER}}};"
#     f"SERVER={SERVER};"
#     f"DATABASE={DATABASE};"
#     f"UID={USERNAME};PWD={PASSWORD};"
# )

OUTPUT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "db_schema_snapshot.json"
)

# ═══════════════════════════════════════════════════════════════════════
# SERVER-SIDE FOR JSON QUERY  —  single round trip
# ═══════════════════════════════════════════════════════════════════════

# SQL Server FOR JSON PATH splits output into 2033-char chunks per row.
# We concatenate all rows to get the full JSON string.
SNAPSHOT_SQL = """
SELECT
    s.name          AS [schema],
    t.name          AS [table],
    CAST(SUM(p.rows) AS BIGINT) AS row_count,

    -- Columns sub-array
    (
        SELECT
            c.name                                          AS name,
            tp.name                                         AS type,
            c.max_length                                    AS length,
            CAST(c.is_nullable AS BIT)                      AS nullable,
            CASE WHEN pk.column_id IS NOT NULL
                 THEN CAST(1 AS BIT)
                 ELSE CAST(0 AS BIT) END                    AS is_pk
        FROM sys.columns c
        JOIN sys.types tp ON tp.user_type_id = c.user_type_id
        LEFT JOIN (
            SELECT ic.column_id, ic.object_id
            FROM sys.index_columns ic
            JOIN sys.indexes i
              ON i.object_id = ic.object_id
             AND i.index_id  = ic.index_id
            WHERE i.is_primary_key = 1
        ) pk ON pk.object_id = c.object_id AND pk.column_id = c.column_id
        WHERE c.object_id = t.object_id
        ORDER BY c.column_id
        FOR JSON PATH
    ) AS columns,

    -- Primary key columns sub-array
    (
        SELECT c.name AS col
        FROM sys.indexes i
        JOIN sys.index_columns ic
          ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c
          ON c.object_id = i.object_id AND c.column_id = ic.column_id
        WHERE i.object_id    = t.object_id
          AND i.is_primary_key = 1
        ORDER BY ic.key_ordinal
        FOR JSON PATH
    ) AS primary_key_json,

    -- Indexes sub-array (non-PK)
    (
        SELECT
            i.name                                          AS name,
            CAST(i.is_unique AS BIT)                        AS [unique],
            STRING_AGG(c.name, ', ')
                WITHIN GROUP (ORDER BY ic.key_ordinal)      AS columns
        FROM sys.indexes i
        JOIN sys.index_columns ic
          ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        JOIN sys.columns c
          ON c.object_id = i.object_id AND c.column_id = ic.column_id
        WHERE i.object_id      = t.object_id
          AND i.is_primary_key = 0
          AND i.name IS NOT NULL
        GROUP BY i.name, i.is_unique
        FOR JSON PATH
    ) AS indexes,

    -- Foreign keys out sub-array
    (
        SELECT
            fk.name                                         AS name,
            STRING_AGG(cc.name, ', ')
                WITHIN GROUP (ORDER BY fkc.constraint_column_id) AS columns,
            ps.name + '.' + pt.name                         AS ref_table,
            STRING_AGG(pc.name, ', ')
                WITHIN GROUP (ORDER BY fkc.constraint_column_id) AS ref_columns
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc
          ON fkc.constraint_object_id = fk.object_id
        JOIN sys.columns cc
          ON cc.object_id = fk.parent_object_id
         AND cc.column_id = fkc.parent_column_id
        JOIN sys.tables  pt ON pt.object_id  = fk.referenced_object_id
        JOIN sys.schemas ps ON ps.schema_id  = pt.schema_id
        JOIN sys.columns pc
          ON pc.object_id = fk.referenced_object_id
         AND pc.column_id = fkc.referenced_column_id
        WHERE fk.parent_object_id = t.object_id
        GROUP BY fk.name, ps.name, pt.name
        FOR JSON PATH
    ) AS foreign_keys,

    -- Referenced-by sub-array
    (
        SELECT
            cs.name + '.' + ct.name + ' (' +
            STRING_AGG(cc.name, ', ')
                WITHIN GROUP (ORDER BY fkc.constraint_column_id)
            + ')'                                           AS ref
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc
          ON fkc.constraint_object_id = fk.object_id
        JOIN sys.tables  ct ON ct.object_id = fk.parent_object_id
        JOIN sys.schemas cs ON cs.schema_id = ct.schema_id
        JOIN sys.columns cc
          ON cc.object_id = fk.parent_object_id
         AND cc.column_id = fkc.parent_column_id
        WHERE fk.referenced_object_id = t.object_id
        GROUP BY cs.name, ct.name, fk.name
        FOR JSON PATH
    ) AS referenced_by

FROM sys.tables t
JOIN sys.schemas s   ON s.schema_id  = t.schema_id
JOIN sys.partitions p ON p.object_id = t.object_id
                      AND p.index_id IN (0, 1)
GROUP BY s.name, t.name, t.object_id
ORDER BY s.name, t.name
FOR JSON PATH, ROOT('tables')
"""


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  PPDM Schema Snapshot Generator  (server-side FOR JSON)")
    print("=" * 60)
    print(f"  Server  : {SERVER}")
    print(f"  Database: {DATABASE}")
    print(f"  Output  : {OUTPUT_FILE}")
    print()

    # ── Connect ────────────────────────────────────────────────────────
    print("Connecting...", end=" ", flush=True)
    try:
        cnx = pyodbc.connect(CONN_STR, timeout=10)
        print("✓")
    except Exception as e:
        print(f"\nERROR: {e}")
        print("\nCheck SERVER, DATABASE and DRIVER settings at the top of the script.")
        print("Available ODBC drivers on this machine:")
        for d in pyodbc.drivers():
            print(f"  {d}")
        sys.exit(1)

    # ── Run single query ───────────────────────────────────────────────
    print("Running server-side FOR JSON query...", end=" ", flush=True)
    t0  = time.time()
    cur = cnx.cursor()
    cur.execute(SNAPSHOT_SQL)

    # SQL Server splits FOR JSON output into 2033-char chunks per row
    chunks = [row[0] for row in cur.fetchall() if row[0]]
    raw    = "".join(chunks)
    elapsed = time.time() - t0
    print(f"✓  ({elapsed:.1f}s)")

    if not raw:
        print("ERROR: Query returned no data. Check database name and permissions.")
        sys.exit(1)

    # ── Parse JSON ────────────────────────────────────────────────────
    print("Parsing result...", end=" ", flush=True)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"\nERROR parsing JSON: {e}")
        # Dump raw for debugging
        debug = OUTPUT_FILE.replace(".json", "_raw.txt")
        with open(debug, "w") as f:
            f.write(raw)
        print(f"Raw output saved to {debug} for inspection.")
        sys.exit(1)

    # ── Reshape into our standard snap format ─────────────────────────
    rows   = result.get("tables", result) if isinstance(result, dict) else result
    tables = {}

    for row in rows:
        key = f"{row['schema']}.{row['table']}"

        # primary_key comes as [{col: "x"}, ...] — flatten to ["x", ...]
        pk_raw = row.get("primary_key_json") or []
        if isinstance(pk_raw, str):
            pk_raw = json.loads(pk_raw)
        pk_list = [r["col"] for r in pk_raw] if pk_raw else []

        # columns, indexes, foreign_keys, referenced_by may be
        # JSON strings (if SQL Server returned them as strings) or
        # already parsed lists
        def _parse(val):
            if val is None:
                return []
            if isinstance(val, list):
                return val
            if isinstance(val, str):
                return json.loads(val)
            return []

        cols    = _parse(row.get("columns"))
        indexes = _parse(row.get("indexes"))
        fks     = _parse(row.get("foreign_keys"))
        ref_by  = [r["ref"] for r in _parse(row.get("referenced_by"))]

        tables[key] = {
            "schema":       row["schema"],
            "table":        row["table"],
            "row_count":    int(row.get("row_count") or 0),
            "columns":      cols,
            "primary_key":  pk_list,
            "indexes":      indexes,
            "foreign_keys": fks,
            "referenced_by": ref_by,
        }

    print(f"✓  {len(tables):,} tables")

    snap = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "database":      DATABASE,
        "tables":        tables,
    }

    # ── Save ───────────────────────────────────────────────────────────
    print(f"Saving to {OUTPUT_FILE}...", end=" ", flush=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2)
    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"✓  ({size_kb:.0f} KB)")

    # ── Summary ────────────────────────────────────────────────────────
    total_cols = sum(len(t["columns"])      for t in tables.values())
    total_fks  = sum(len(t["foreign_keys"]) for t in tables.values())
    total_idxs = sum(len(t["indexes"])      for t in tables.values())

    print()
    print("=" * 60)
    print("  SNAPSHOT COMPLETE")
    print("=" * 60)
    print(f"  Tables      : {len(tables):>6,}")
    print(f"  Columns     : {total_cols:>6,}")
    print(f"  PKs defined : {sum(1 for t in tables.values() if t['primary_key']):>6,} tables")
    print(f"  Indexes     : {total_idxs:>6,}")
    print(f"  Foreign Keys: {total_fks:>6,}")
    print(f"  File size   : {size_kb:>6.0f} KB")
    print(f"  Query time  : {elapsed:>6.1f}s")
    print(f"  Generated   : {snap['generated_utc'][:19]} UTC")
    print()
    print("  Ready — copy db_schema_snapshot.json to your app folder.")
    print("=" * 60)

    cnx.close()


if __name__ == "__main__":
    main()

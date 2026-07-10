"""
populate_h3.py — fill the per-well H3 columns (h3_r4..h3_r7) that the
density-grid views (dataview_federation.v_well_density_r4..r7) aggregate.

Why: those views just GROUP BY h3_rN. Any well with lat/lon but a NULL
h3_rN drops out of every grid (your r6 view showed 200 such dataview
wells, and newly loaded states won't have H3 until this runs). This
computes the cells in Python and writes them back with a single
staging-table JOIN UPDATE per table — no per-row UPDATE loop.

Run after every new data load:
    python populate_h3.py            # only rows missing any h3_rN
    python populate_h3.py --all      # recompute every row (full refresh)

Requires: pip install h3   (v3 or v4 both handled)
"""
import sys
import pyodbc

try:
    import h3
except ImportError:
    print("Need the h3 package:  pip install h3")
    sys.exit(1)

# ── config ─────────────────────────────────────────────────────────
SERVER   = r"127.0.0.1\SQLEXPRESS"
DATABASE = "DataView"
DRIVER   = "ODBC Driver 17 for SQL Server"

# (schema, table, lat_col, lon_col, key_hint). key_hint is used only if no
# identity/PK is discovered.
TABLES = [
    ("dataview",     "dv_well", "surface_latitude", "surface_longitude", "uwi"),
    ("dataview_gom", "well",    "surface_latitude", "surface_longitude", "well_id"),
]
RES = [4, 5, 6, 7]
BATCH = 20000
ALL = "--all" in sys.argv
# ───────────────────────────────────────────────────────────────────


def _cell(lat, lon, res):
    if hasattr(h3, "latlng_to_cell"):          # h3 v4
        return h3.latlng_to_cell(lat, lon, res)
    return h3.geo_to_h3(lat, lon, res)         # h3 v3


def _connect():
    return pyodbc.connect(
        f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={DATABASE};"
        f"Trusted_Connection=yes;", timeout=15)


def _key_col(cur, schema, table, hint):
    # identity first
    cur.execute("""
        SELECT c.name FROM sys.identity_columns c
        JOIN sys.tables t ON t.object_id=c.object_id
        JOIN sys.schemas s ON s.schema_id=t.schema_id
        WHERE s.name=? AND t.name=?""", schema, table)
    r = cur.fetchone()
    if r:
        return r[0]
    # single-column PK
    cur.execute("""
        SELECT kcu.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
          ON tc.CONSTRAINT_NAME=kcu.CONSTRAINT_NAME
        WHERE tc.TABLE_SCHEMA=? AND tc.TABLE_NAME=?
          AND tc.CONSTRAINT_TYPE='PRIMARY KEY'""", schema, table)
    pk = cur.fetchall()
    if len(pk) == 1:
        return pk[0][0]
    return hint


def _existing_h3_cols(cur, schema, table):
    cur.execute("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA=? AND TABLE_NAME=? AND COLUMN_NAME LIKE 'h3_r%'""",
        schema, table)
    have = {r[0].lower() for r in cur.fetchall()}
    return [r for r in RES if f"h3_r{r}" in have]


def _process(cn, schema, table, lat_c, lon_c, hint):
    cur = cn.cursor()
    key = _key_col(cur, schema, table, hint)
    res_cols = _existing_h3_cols(cur, schema, table)
    if not res_cols:
        print(f"  {schema}.{table}: no h3_r* columns — skipping")
        return
    print(f"  {schema}.{table}: key={key}, columns={['h3_r'+str(r) for r in res_cols]}")

    null_pred = " OR ".join(f"h3_r{r} IS NULL" for r in res_cols)
    where = (f"{lat_c} IS NOT NULL AND {lon_c} IS NOT NULL"
             + ("" if ALL else f" AND ({null_pred})"))
    cur.execute(f"SELECT [{key}], {lat_c}, {lon_c} FROM {schema}.{table} WHERE {where}")
    rows = cur.fetchall()
    print(f"    candidates: {len(rows):,}")
    if not rows:
        return

    # compute
    updates = []
    for k, lat, lon in rows:
        try:
            cells = [_cell(float(lat), float(lon), r) for r in res_cols]
        except Exception:
            continue
        updates.append([str(k)] + cells)
    if not updates:
        return

    # stage
    cols_ddl = ", ".join(f"h3_r{r} NVARCHAR(15)" for r in res_cols)
    cur.execute(f"CREATE TABLE #h3 (k NVARCHAR(64), {cols_ddl})")
    placeholders = ",".join(["?"] * (1 + len(res_cols)))
    cur.fast_executemany = True
    insert_sql = (f"INSERT INTO #h3 (k, "
                  + ", ".join(f"h3_r{r}" for r in res_cols)
                  + f") VALUES ({placeholders})")
    for i in range(0, len(updates), BATCH):
        cur.executemany(insert_sql, updates[i:i + BATCH])

    # single set-based UPDATE via JOIN
    set_clause = ", ".join(f"t.h3_r{r} = s.h3_r{r}" for r in res_cols)
    cur.execute(f"""
        UPDATE t SET {set_clause}
        FROM {schema}.{table} t
        JOIN #h3 s ON CAST(t.[{key}] AS NVARCHAR(64)) = s.k""")
    print(f"    updated: {cur.rowcount:,}")
    cur.execute("DROP TABLE #h3")
    cn.commit()


def main():
    cn = _connect()
    print(f"populate_h3 — mode={'ALL (full recompute)' if ALL else 'NULL only'}")
    for schema, table, lat_c, lon_c, hint in TABLES:
        try:
            _process(cn, schema, table, lat_c, lon_c, hint)
        except pyodbc.Error as e:
            print(f"  {schema}.{table}: ERROR {e}")
    cn.close()
    print("Done. The v_well_density_r* views now reflect the filled cells "
          "(no rebuild needed — they aggregate live).")


if __name__ == "__main__":
    main()

"""
refresh_demo_grids.py — one-shot, idempotent setup + refresh of the H3 hex
grids for the DEMO project. Standalone like populate_h3.py: no app imports, no
dependency on page_pipeline / h3_grids. Run it whenever the demo data changes.

It does three things, all safe to re-run:

  1. ensures the h3_r4..h3_r7 + h3_coord_hash columns (and the r5/r6 grid
     indexes) exist on dataview.dv_well
  2. refreshes the per-well H3 cells — compute in Python, stage in a temp
     table, apply with a single set-based JOIN UPDATE (no per-row loop)
  3. ensures the dataview_federation.v_well_density_r4..r7 views your map app
     reads (h3, well_count, dv_schema) exist

After it runs, the map app finds the views and the hexes draw. The views
aggregate live, so step 2 alone refreshes the grids on subsequent runs.

    python refresh_demo_grids.py          # fill only missing cells
    python refresh_demo_grids.py --all    # recompute every cell

Requires: pip install h3 pyodbc
Edit SERVER / DATABASE to point at your demo instance.
"""
import sys
import hashlib

try:
    import pyodbc
except ImportError:
    print("Need pyodbc:  pip install pyodbc")
    sys.exit(1)
try:
    import h3
except ImportError:
    print("Need h3:  pip install h3")
    sys.exit(1)

# ── config — point these at your demo database ─────────────────────────────
SERVER   = r"PERRY\SQLEXPRESS"
DATABASE = "DataView_Demo"
DRIVER   = "ODBC Driver 17 for SQL Server"
SCHEMA   = "dataview"
TABLE    = "dv_well"
LAT, LON = "surface_latitude", "surface_longitude"
KEY      = "uwi"
RES      = [4, 5, 6, 7]
BATCH    = 20000
ALL      = "--all" in sys.argv
# ───────────────────────────────────────────────────────────────────────────


def _cell(lat, lon, res):
    if hasattr(h3, "latlng_to_cell"):          # h3 v4
        return h3.latlng_to_cell(lat, lon, res)
    return h3.geo_to_h3(lat, lon, res)         # h3 v3


def _coord_hash(lat, lon):
    # matches the WranglerView formula: SHA256(f"{lat}|{lon}").hexdigest().upper()
    return hashlib.sha256(f"{float(lat)}|{float(lon)}".encode("utf-8")
                          ).hexdigest().upper()


def _connect():
    return pyodbc.connect(
        f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={DATABASE};"
        f"Trusted_Connection=yes;", timeout=15)


def _columns(cur, schema, table):
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?", schema, table)
    return {r[0].lower() for r in cur.fetchall()}


def ensure_columns(cur):
    have = _columns(cur, SCHEMA, TABLE)
    if LAT.lower() not in have or LON.lower() not in have:
        raise RuntimeError(
            f"{SCHEMA}.{TABLE} has no {LAT}/{LON} columns — wrong table?")
    wanted = [(f"h3_r{r}", "VARCHAR(16) NULL") for r in RES]
    wanted.append(("h3_coord_hash", "CHAR(64) NULL"))
    added = []
    for name, decl in wanted:
        if name.lower() not in have:
            cur.execute(f"ALTER TABLE [{SCHEMA}].[{TABLE}] ADD [{name}] {decl}")
            added.append(name)
    for r in (5, 6):
        idx = f"IX_{TABLE}_h3_r{r}"
        cur.execute("SELECT 1 FROM sys.indexes WHERE name=? "
                    "AND object_id=OBJECT_ID(?)", idx, f"{SCHEMA}.{TABLE}")
        if not cur.fetchone():
            cur.execute(f"CREATE NONCLUSTERED INDEX [{idx}] "
                        f"ON [{SCHEMA}].[{TABLE}] ([h3_r{r}])")
            added.append(idx)
    cur.connection.commit()
    print(f"    columns/indexes: {'added ' + ', '.join(added) if added else 'all present'}")


def refresh_cells(cur):
    null_pred = " OR ".join(f"h3_r{r} IS NULL" for r in RES) + " OR h3_coord_hash IS NULL"
    where = (f"{LAT} IS NOT NULL AND {LON} IS NOT NULL"
             + ("" if ALL else f" AND ({null_pred})"))
    cur.execute(f"SELECT [{KEY}], {LAT}, {LON} FROM [{SCHEMA}].[{TABLE}] WHERE {where}")
    rows = cur.fetchall()
    print(f"    candidates: {len(rows):,}")
    if not rows:
        if not ALL:
            print("    (nothing missing — grids already current)")
        else:
            print(f"    (no wells with coordinates in {SCHEMA}.{TABLE})")
        return

    updates = []
    for k, lat, lon in rows:
        try:
            cells = [_cell(float(lat), float(lon), r) for r in RES]
            updates.append([str(k)] + cells + [_coord_hash(lat, lon)])
        except Exception:
            continue
    if not updates:
        print("    no valid coordinates to compute")
        return

    cols = [f"h3_r{r}" for r in RES] + ["h3_coord_hash"]
    ddl = ", ".join((f"{c} NVARCHAR(16)" if c.startswith("h3_r")
                     else f"{c} NVARCHAR(64)") for c in cols)
    cur.execute(f"CREATE TABLE #h3 (k NVARCHAR(64), {ddl})")
    ph = ",".join(["?"] * (1 + len(cols)))
    cur.fast_executemany = True
    ins = f"INSERT INTO #h3 (k, {', '.join(cols)}) VALUES ({ph})"
    for i in range(0, len(updates), BATCH):
        cur.executemany(ins, updates[i:i + BATCH])

    set_clause = ", ".join(f"t.{c} = s.{c}" for c in cols)
    cur.execute(f"""
        UPDATE t SET {set_clause}
        FROM [{SCHEMA}].[{TABLE}] t
        JOIN #h3 s ON CAST(t.[{KEY}] AS NVARCHAR(64)) = s.k""")
    print(f"    updated: {cur.rowcount:,}")
    cur.execute("DROP TABLE #h3")
    cur.connection.commit()


def ensure_views(cur):
    cur.execute("IF NOT EXISTS (SELECT 1 FROM sys.schemas "
                "WHERE name='dataview_federation') "
                "EXEC('CREATE SCHEMA dataview_federation')")
    cur.connection.commit()
    for r in RES:
        # CREATE OR ALTER needs SQL Server 2016 SP1+. If yours is older, swap
        # to: DROP VIEW IF EXISTS ...; then CREATE VIEW ...
        cur.execute(f"""
            CREATE OR ALTER VIEW dataview_federation.v_well_density_r{r} AS
                SELECT '{SCHEMA}' AS dv_schema,
                       h3_r{r}    AS h3,
                       COUNT_BIG(*) AS well_count
                FROM [{SCHEMA}].[{TABLE}]
                WHERE h3_r{r} IS NOT NULL
                GROUP BY h3_r{r}""")
    cur.connection.commit()
    print(f"    views: dataview_federation.v_well_density_r{RES[0]}..r{RES[-1]} ready")


def main():
    print(f"refresh_demo_grids — {SERVER} / {DATABASE} — "
          f"mode={'ALL (full recompute)' if ALL else 'missing-only'}")
    try:
        cn = _connect()
    except pyodbc.Error as e:
        print(f"  connection failed: {e}")
        sys.exit(1)
    cur = cn.cursor()
    try:
        print("[1/3] columns");  ensure_columns(cur)
        print("[2/3] cells");    refresh_cells(cur)
        print("[3/3] views");    ensure_views(cur)
        print("Done. Open the map app on the demo project — the hexes will draw.")
    except Exception as e:
        print(f"  ERROR: {e}")
    finally:
        cn.close()


if __name__ == "__main__":
    main()

"""Provenance audit for the dataview.dv_* tables.

For every dv_* table in one or more databases, reports:
  * total rows
  * catalog rows  — INVENTORY_ID IS NOT NULL (the AUTHORITATIVE "came up through
    the file-catalog pipeline" signal; present on both headers and child rows)
  * other rows    — everything else (bulk loads, federation, test data)
  * source split  — COUNT(*) per `source` value, so label-based provenance
    (CATALOG / PDF_HEADER / SHAPEFILE / OSDU / LAS_HEADER vs KGS / DATA_LOADER /
    test sources) is visible too.

Why two signals: `source` only reflects who CREATED a header. When the catalog
promote enriches a pre-existing well (e.g. a KGS row) it fills NULLs but never
clobbers `source`, so that contribution is invisible by source yet shows up as a
non-NULL INVENTORY_ID on the child rows. INVENTORY_ID is therefore the complete
test; source is informational.

Run:
    python provenance_audit.py                      # audits DataView + DataView_Demo
    python provenance_audit.py --database DataView_Demo
    python provenance_audit.py --server PERRY\\SQLEXPRESS --schema dataview
"""

import argparse
import sys

# Source labels the file-catalog pipeline stamps (per-loader). Informational —
# the INVENTORY_ID test below is the authoritative one and doesn't rely on this.
CATALOG_SOURCES = {
    "CATALOG", "PDF_HEADER", "SHAPEFILE", "OSDU", "LAS_HEADER", "WITSML",
}


def _connect(server, database):
    import pyodbc
    return pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={server};DATABASE={database};Trusted_Connection=yes",
        autocommit=True, timeout=10)


def _dv_tables(cur, schema):
    cur.execute(
        "SELECT t.name FROM sys.tables t "
        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
        "WHERE s.name = ? AND t.name LIKE 'dv[_]%' ORDER BY t.name", schema)
    return [r[0] for r in cur.fetchall()]


def _columns(cur, schema, table):
    cur.execute(
        "SELECT UPPER(COLUMN_NAME) FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?", schema, table)
    return {r[0] for r in cur.fetchall()}


def _audit_db(server, database, schema):
    try:
        cn = _connect(server, database)
    except Exception as e:
        print(f"\n=== {database} ===  (cannot connect: {e})")
        return
    cur = cn.cursor()
    try:
        tables = _dv_tables(cur, schema)
    except Exception as e:
        print(f"\n=== {database} ===  (query failed: {e})")
        cn.close()
        return
    if not tables:
        print(f"\n=== {database}.{schema} ===  no dv_* tables found")
        cn.close()
        return

    print(f"\n=== {database}.{schema} — {len(tables)} dv_* table(s) ===")
    print(f"{'table':30}{'rows':>11}{'catalog':>11}{'other':>11}  source split")
    print("-" * 110)

    t_rows = t_cat = t_cat_known = 0
    for t in tables:
        try:
            cset = _columns(cur, schema, t)
            total = cur.execute(
                f"SELECT COUNT(*) FROM [{schema}].[{t}]").fetchone()[0]
            catn = None
            if "INVENTORY_ID" in cset:
                catn = cur.execute(
                    f"SELECT COUNT(*) FROM [{schema}].[{t}] "
                    "WHERE INVENTORY_ID IS NOT NULL").fetchone()[0]
            src = ""
            if "SOURCE" in cset:
                cur.execute(
                    f"SELECT [source], COUNT(*) FROM [{schema}].[{t}] "
                    "GROUP BY [source] ORDER BY COUNT(*) DESC")
                pairs = [(("(null)" if r[0] is None else str(r[0])), r[1])
                         for r in cur.fetchall()]
                # mark catalog-origin source labels with *
                shown = []
                for s, n in pairs[:10]:
                    star = "*" if s in CATALOG_SOURCES else ""
                    shown.append(f"{s}{star}:{n:,}")
                src = " · ".join(shown)
                if len(pairs) > 10:
                    src += " …"
                t_cat_known += sum(
                    n for s, n in pairs if s in CATALOG_SOURCES)
        except Exception as e:
            print(f"{t:30}  (error: {str(e)[:60]})")
            continue

        cat_s = f"{catn:,}" if catn is not None else "—"
        oth_s = f"{total - catn:,}" if catn is not None else "—"
        print(f"{t:30}{total:>11,}{cat_s:>11}{oth_s:>11}  {src}")
        t_rows += total
        if catn is not None:
            t_cat += catn

    print("-" * 110)
    print(f"{'TOTAL':30}{t_rows:>11,}{t_cat:>11,}{t_rows - t_cat:>11,}")
    print(f"  catalog (INVENTORY_ID not null): {t_cat:,}   "
          f"catalog-labelled source* total: {t_cat_known:,}")
    print("  * = source value stamped by the catalog pipeline. "
          "INVENTORY_ID is the authoritative signal; a catalog-enriched "
          "pre-existing well keeps its original source.")
    cn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default=r"PERRY\SQLEXPRESS")
    ap.add_argument("--database", default=None,
                    help="single DB to audit (default: DataView + DataView_Demo)")
    ap.add_argument("--schema", default="dataview")
    a = ap.parse_args()

    try:
        import pyodbc  # noqa: F401
    except ImportError:
        print("pyodbc not installed in this Python. "
              "pip install pyodbc, or run with the venv that has it.")
        return 2

    dbs = [a.database] if a.database else ["DataView", "DataView_Demo"]
    print(f"Provenance audit · server {a.server} · schema {a.schema}")
    for db in dbs:
        _audit_db(a.server, db, a.schema)
    return 0


if __name__ == "__main__":
    sys.exit(main())

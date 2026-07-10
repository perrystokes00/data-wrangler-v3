"""
seed_las_catalog.py  --  synthesize LAS curve volume for promote benchmarking
=============================================================================
Generates N synthetic LAS files x C curves directly into las_catalog, with
matching GLOBAL_FILE_CATALOG rows and real dv_well UWIs, so the rows actually
PROMOTE (resolve INVENTORY_ID + pass the has_well gate) instead of being held.

Every row is tagged with a prefix (default 'synth_') so it's trivially
removable. This COMMITS (the data must persist for the benchmark to use it);
clean it up afterwards with --clean.

    cd C:\\...\\data_wrangler_v3
    python seed_las_catalog.py --files 5000 --curves 40     # -> 200k curve rows
    python test_promote_fast.py --apply                     # now eligible != 0
    python seed_las_catalog.py --clean                      # remove synth rows

Targets DataView_Demo by default and refuses a DB literally named 'DataView'.
"""
from __future__ import annotations
import argparse
import sys
import pyodbc

PREFIX_DEFAULT = "synth_"
MNEMS = ["GR", "CALI", "SP", "RHOB", "NPHI", "DPHI", "PEF", "RT", "RXO",
         "ILD", "ILM", "SFLU", "DT", "DTC", "DTS", "CGR", "SGR", "POTA",
         "THOR", "URAN", "DRHO", "BS", "TENS", "ROP", "MINV", "MNOR"]
UNITS = {"GR": "GAPI", "CALI": "IN", "RHOB": "G/C3", "NPHI": "V/V",
         "DT": "US/F", "RT": "OHMM", "PEF": "B/E"}


def _connect(server, database):
    for drv in ("ODBC Driver 18 for SQL Server",
                "ODBC Driver 17 for SQL Server",
                "SQL Server Native Client 11.0", "SQL Server"):
        try:
            cs = (f"DRIVER={{{drv}}};SERVER={server};DATABASE={database};"
                  f"Trusted_Connection=yes;TrustServerCertificate=yes")
            conn = pyodbc.connect(cs, autocommit=False)
            cur = conn.cursor()
            cur.fast_executemany = True
            print(f"connected via: {drv}")
            return conn, cur
        except pyodbc.Error:
            continue
    sys.exit("Could not connect — check the ODBC driver name and server.")


def _clean(conn, cur, prefix):
    print(f"deleting rows tagged '{prefix}%' ...")
    cur.execute("DELETE FROM las_catalog.LAS_FILE_CURVE WHERE LAS_FILE_ID LIKE ?",
                prefix + "%")
    c1 = cur.rowcount or 0
    cur.execute("DELETE FROM las_catalog.LAS_FILE WHERE LAS_FILE_ID LIKE ?",
                prefix + "%")
    c2 = cur.rowcount or 0
    cur.execute("DELETE FROM file_catalog.GLOBAL_FILE_CATALOG WHERE INVENTORY_ID LIKE ?",
                prefix + "%")
    c3 = cur.rowcount or 0
    conn.commit()
    print(f"removed: {c1:,} curves, {c2:,} files, {c3:,} catalog rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="localhost\\SQLEXPRESS")
    ap.add_argument("--database", default="DataView_Demo")
    ap.add_argument("--files", type=int, default=5000)
    ap.add_argument("--curves", type=int, default=40,
                    help="curves per file (unique mnemonics so each promotes)")
    ap.add_argument("--prefix", default=PREFIX_DEFAULT)
    ap.add_argument("--batch", type=int, default=10000)
    ap.add_argument("--clean", action="store_true",
                    help="delete previously seeded synth rows and exit")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.database.strip().lower() == "dataview" and not args.force:
        sys.exit("Refusing to seed 'DataView' (looks like prod). "
                 "Use DataView_Demo, or pass --force.")

    conn, cur = _connect(args.server, args.database)

    if args.clean:
        _clean(conn, cur, args.prefix)
        conn.close()
        return

    # real UWIs so the has_well gate passes
    cur.execute("SELECT TOP (?) uwi FROM dataview.dv_well "
                "WHERE uwi IS NOT NULL AND LTRIM(RTRIM(uwi)) <> ''",
                min(args.files, 20000))
    pool = [r[0] for r in cur.fetchall()]
    if not pool:
        sys.exit("No UWIs in dataview.dv_well — load wells first, "
                 "else every synthetic curve is held (has_well = 0).")
    print(f"sampled {len(pool):,} real UWIs from dv_well")

    p = args.prefix
    file_rows, cat_rows, curve_rows = [], [], []
    for i in range(args.files):
        fid = f"{p}{i:06d}"
        fname = f"{fid}.las"
        uwi = pool[i % len(pool)]
        file_rows.append((fid, "SYNTH", uwi, f"SYNTH WELL {i}", fname, "2.0",
                          "FT", 0.0, 10000.0, 0.5, 20000, args.curves, "Y", "SYNTH"))
        cat_rows.append((fid, f"C:\\synth\\{fname}", fname, ".las", "WELL_LOG"))
        for j in range(args.curves):
            mnem = MNEMS[j] if j < len(MNEMS) else f"CURV{j:03d}"
            curve_rows.append((fid, mnem, UNITS.get(mnem, "----"),
                               f"Synthetic {mnem}", "LOG", "", "SYNTH"))

    print(f"generating {len(file_rows):,} files, {len(curve_rows):,} curves ...")

    def _bulk(sql, rows):
        for k in range(0, len(rows), args.batch):
            cur.executemany(sql, rows[k:k + args.batch])

    _bulk("INSERT INTO file_catalog.GLOBAL_FILE_CATALOG "
          "(INVENTORY_ID, FILE_PATH, FILE_NAME, FILE_EXT, FILE_TYPE_GROUP) "
          "VALUES (?,?,?,?,?)", cat_rows)
    _bulk("INSERT INTO las_catalog.LAS_FILE "
          "(LAS_FILE_ID, REPOSITORY_ID, UWI, WELL_NAME, FILE_NAME, LAS_VERSION, "
          " DEPTH_UOM, TOP_DEPTH, BASE_DEPTH, DEPTH_STEP, SAMPLE_COUNT, "
          " CURVE_COUNT, ACTIVE_IND, SOURCE) "
          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", file_rows)
    _bulk("INSERT INTO las_catalog.LAS_FILE_CURVE "
          "(LAS_FILE_ID, CURVE_ID, CURVE_UNIT, CURVE_DESCRIPTION, CURVE_TYPE, "
          " API_CODE, SOURCE) VALUES (?,?,?,?,?,?,?)", curve_rows)

    conn.commit()
    print(f"\nseeded & committed: {len(file_rows):,} LAS files · "
          f"{len(curve_rows):,} curves · {len(cat_rows):,} catalog rows")
    print(f"each file has {args.curves} unique mnemonics, so all "
          f"{len(curve_rows):,} should promote (none held).")
    print("\nnext:")
    print("  python test_promote_fast.py --apply")
    print(f"cleanup when done:")
    print(f"  python seed_las_catalog.py --clean --prefix {p}")
    conn.close()


if __name__ == "__main__":
    main()

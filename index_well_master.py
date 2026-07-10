r"""
index_well_master.py — add the indexes the enrich join needs on the gold master.

enrich_file_headers pass 1 resolves a well's UWI by:
    JOIN well_master_gold m ON m.NAME_NORM = <header name>
and pass 2 / reverse-capture filter on m.UWI14. With no index on NAME_NORM /
UWI14, each enrich scans the whole ~4M-row master (your 5.56s). This creates two
covering indexes ONCE so those become seeks. Idempotent (skips if present).

    py index_well_master.py                       # defaults below
    py index_well_master.py "PERRY\\SQLEXPRESS" WELL_REF well_ref well_master_gold
"""
import sys, time
import worker_core as w
from sqlalchemy import text

SERVER = sys.argv[1] if len(sys.argv) > 1 else r"PERRY\SQLEXPRESS"
REFDB  = sys.argv[2] if len(sys.argv) > 2 else "WELL_REF"
SCHEMA = sys.argv[3] if len(sys.argv) > 3 else "well_ref"
TABLE  = sys.argv[4] if len(sys.argv) > 4 else "well_master_gold"

e = w.make_engine(SERVER, REFDB)          # must be IN the ref DB to CREATE INDEX
FQ = f"{SCHEMA}.{TABLE}"

# (index name, key cols, include cols) — only created if the columns exist
PLAN = [
    ("IX_WM_NAME_NORM", ["NAME_NORM"], ["UWI14", "UWI_SUSPECT"]),
    ("IX_WM_UWI14",     ["UWI14"],     ["UWI_SUSPECT"]),
]

with e.connect() as c:
    cols = {r[0].upper() for r in c.execute(text(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t"), {"s": SCHEMA, "t": TABLE})}
    if not cols:
        print(f"!! {FQ} not found in {REFDB}. Pass the right server/db/schema/table.")
        sys.exit(1)
    n = c.execute(text(f"SELECT COUNT(*) FROM {FQ}")).scalar()
    print(f"{FQ}: {n:,} rows\ncolumns present: NAME_NORM={('NAME_NORM' in cols)} "
          f"UWI14={('UWI14' in cols)} UWI_SUSPECT={('UWI_SUSPECT' in cols)}\n")

    existing = {r[0] for r in c.execute(text(
        "SELECT name FROM sys.indexes WHERE object_id = OBJECT_ID(:o)"),
        {"o": FQ}) if r[0]}

    for name, keys, incl in PLAN:
        need = [k for k in keys if k.upper() in cols]
        if len(need) != len(keys):
            print(f"skip {name}: missing key column(s) {set(keys)-cols}")
            continue
        if name in existing:
            print(f"ok   {name}: already exists")
            continue
        inc = [x for x in incl if x.upper() in cols]
        inc_sql = f" INCLUDE ({', '.join(inc)})" if inc else ""
        ddl = f"CREATE INDEX {name} ON {FQ} ({', '.join(keys)}){inc_sql}"
        print(f"create {name} …", end=" ", flush=True)
        t0 = time.perf_counter()
        # autocommit for DDL on a large table
        cc = c.connection
        cur = cc.cursor()
        cur.execute(ddl)
        cc.commit()
        print(f"done in {time.perf_counter()-t0:.1f}s")

print("\nDone. Re-run the pipeline — enrich pass 1 should drop from ~5.5s to <0.5s.")

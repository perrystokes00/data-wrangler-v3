#!/usr/bin/env python3
r"""
load_well_master.py
===================
Copy the federated well header from Snowflake into well_ref.WELL_MASTER in the
local catalog DB (SQL Express), normalising the join keys in Snowflake (which
has regex) and loading via BULK INSERT (which honours CSV quoting, so empty
strings and embedded delimiters survive).

Chain (all one command):
    Snowflake  COPY INTO @~/well_master/  (SELECT * + UWI14 + NAME_NORM +
               UWI_SUSPECT, gzipped, quoted CSV)
        -> GET to C:\Bulk\wellref
        -> gunzip
        -> BULK INSERT into well_ref.WELL_MASTER_STAGING
        -> INSERT ... into well_ref.WELL_MASTER  (typed lat/long, UWI14, flag)
        -> indexes + per-source UWI_SUSPECT report

The ENTIRE source header is carried verbatim; three computed columns are added:
    UWI14        digits only, 10-14 -> padded to API-14 (sci-notation handled)
    NAME_NORM    UPPER + whitespace-collapsed (matches the app's name key)
    UWI_SUSPECT  1 when the raw UWI arrived in exponential/decimal form. Those
                 already lost precision upstream, so the salvaged UWI14 is
                 unreliable — flagged so backfill/coverage can skip it and you
                 can reload those sources later.

Auth: native Snowflake + TOTP (prompts for password then a passcode).

Examples:
    python load_well_master.py --limit 5000          # test
    python load_well_master.py --replace             # full load
    python load_well_master.py --source-col SOURCE_SYSTEM --replace

Requires: pip install snowflake-connector-python pyodbc
BULK INSERT reads the file as the SQL Server service account, so the download
dir must be readable by it — C:\Bulk works in this setup.
"""
import argparse
import getpass
import glob
import gzip
import os
import shutil
import sys
import time

# ── Defaults ─────────────────────────────────────────────────────────────────
DEFAULT_SERVER = r"PERRY\SQLEXPRESS"
DEFAULT_DB     = "DataView_Demo"
DEFAULT_DRIVER = "ODBC Driver 17 for SQL Server"
DEFAULT_DLDIR  = r"C:\Bulk\wellref"          # readable by the SQL service acct

SF_ACCOUNT, SF_USER, SF_ROLE = "YDWXNCV-VL88062", "PMSTOKES00", "ACCOUNTADMIN"
SF_WAREHOUSE, SF_DATABASE, SF_SCHEMA, SF_TABLE = \
    "WV_WH", "WELL_FEDERATION", "CURATED", "WELL_MASTER"

DEST_SCHEMA, DEST_TABLE = "well_ref", "WELL_MASTER"
STAGE = "@~/well_master/"
EXTRA_COLS = ["UWI14", "NAME_NORM", "UWI_SUSPECT"]

CANDIDATES = {
    "uwi":    ["uwi14", "uwi", "api14", "api_14", "api", "api_number",
               "apinumber", "well_api", "api_no"],
    "name":   ["well_name", "wellname", "well_nm", "name", "lease_name", "lease"],
    "lat":    ["surface_latitude", "latitude", "lat", "surf_lat", "y"],
    "long":   ["surface_longitude", "longitude", "long", "lon", "lng",
               "surf_long", "x"],
    "source": ["source_list", "source", "source_name", "source_system",
               "source_id", "data_source", "datasource", "src", "src_system",
               "federation_source", "well_source", "origin", "provider"],
    "depth":  ["total_depth", "final_td", "td", "total_depth_ft", "depth_total",
               "totaldepth", "total_md", "td_ft", "tvd"],
    "spud":   ["spud_date", "spud_dt", "spuddate", "spud", "spud_dttm",
               "spud_date_dt", "date_spud"],
}

# Default columns carried into the reference table (the rest of the federation
# header is dropped to keep the footprint down). Override with --columns.
# Missing names are skipped; the detected uwi/name/lat/long/source columns are
# always added even if not listed here.
CORE_COLS = [
    "MASTER_ID", "SOURCE_LIST",
    "UWI", "API_NUM", "API_10",
    "WELL_NAME", "WELL_NUM", "OPERATOR_NAME", "FIELD_NAME",
    "SURFACE_LATITUDE", "SURFACE_LONGITUDE",
    "COUNTY", "PROVINCE_STATE", "COUNTRY",
    "WELL_STATUS", "WELL_TYPE", "STD_WELL_TYPE", "STD_WELL_STATUS",
]


def detect_col(cols, keys):
    low = {c.lower(): c for c in cols}
    for k in keys:
        if k in low:
            return low[k]
    return None


# ── Snowflake ───────────────────────────────────────────────────────────────
def connect_snowflake(a):
    try:
        import snowflake.connector as sf
    except ImportError:
        sys.exit("pip install snowflake-connector-python")
    kw = dict(account=a.sf_account, user=a.sf_user, role=a.sf_role,
              warehouse=a.sf_warehouse, database=a.sf_database, schema=a.sf_schema)
    if a.authenticator == "externalbrowser":
        kw["authenticator"] = "externalbrowser"
        return sf.connect(**kw)
    if a.authenticator == "username_password_mfa":
        kw["authenticator"] = "username_password_mfa"
    kw["password"] = a.sf_password or getpass.getpass("Snowflake password: ")
    passcode = a.passcode
    if not passcode:
        entered = input("TOTP passcode (Enter to skip if no MFA): ").strip()
        if entered:
            passcode = entered
    if passcode:
        kw["passcode"] = passcode
    return sf.connect(**kw)


def source_columns(cur, src):
    cur.execute(f"SELECT * FROM {src} LIMIT 0")
    return [d[0] for d in cur.description]


def build_select(src, selected, det, key_cols, limit, alias=None):
    """Projected SELECT plus computed UWI14 / NAME_NORM / UWI_SUSPECT.

    `alias` maps a source column to a canonical output name (the detected TD /
    spud columns -> TOTAL_DEPTH / SPUD_DATE) so the reference lands with the
    same column names as the catalog's FILE_WELL_HEADER.

    UWI14 comes from the first of `key_cols` (UWI, then API_NUM, API_10) that
    yields 10+ digits, so a blank/short UWI doesn't drop a well that has an API
    in another column. Scientific/decimal forms are converted via DOUBLE first.
    UWI_SUSPECT stays keyed on the primary UWI column (auto-swapping a suspect
    well to a clean API here would desync it from the catalog, which still has
    the mangled value — those sources want a real reload)."""
    alias = alias or {}
    proj = ", ".join(
        (f'"{c}" AS {alias[c]}' if c in alias else f'"{c}"') for c in selected)

    def dig(col):
        c = f'"{col}"::string'
        return (f"REGEXP_REPLACE(IFF({c} ILIKE '%E%' AND TRY_TO_DOUBLE({c}) "
                f"IS NOT NULL, TO_VARCHAR(TRY_TO_DOUBLE({c})::BIGINT), {c}),"
                f"'[^0-9]','')")

    coalesce = "COALESCE(" + ", ".join(
        f"IFF(LENGTH({dig(c)})>=10,{dig(c)},NULL)" for c in key_cols) + ")"
    uwi14 = ("CASE WHEN LENGTH(KEYDIG) BETWEEN 10 AND 14 THEN RPAD(KEYDIG,14,'0') "
             "WHEN LENGTH(KEYDIG) > 14 THEN LEFT(KEYDIG,14) ELSE NULL END")
    name_norm = (f"UPPER(TRIM(REGEXP_REPLACE(\"{det['name']}\"::string,'\\\\s+',' ')))"
                 if det["name"] else "NULL")
    u = f'"{det["uwi"]}"::string'
    suspect = f"IFF({u} ILIKE '%E%' OR {u} LIKE '%.%',1,0)"
    lim = f" LIMIT {limit}" if limit else ""

    return (f"SELECT {proj}, {uwi14} AS UWI14, {name_norm} AS NAME_NORM, "
            f"{suspect} AS UWI_SUSPECT "
            f"FROM (SELECT t.*, {coalesce} AS KEYDIG FROM {src} t{lim})")


def unload(cur, select_sql):
    print("Clearing stage …")
    try:
        cur.execute(f"REMOVE {STAGE}")
    except Exception:
        pass
    print("COPY INTO stage (normalising in Snowflake) …")
    cur.execute(f"""
        COPY INTO {STAGE} FROM ({select_sql})
        FILE_FORMAT=(TYPE=CSV FIELD_DELIMITER='\\t' RECORD_DELIMITER='\\n'
                     FIELD_OPTIONALLY_ENCLOSED_BY='"' COMPRESSION=GZIP NULL_IF=(''))
        HEADER=TRUE OVERWRITE=TRUE MAX_FILE_SIZE=5000000000;
    """)
    rows = cur.fetchall()
    print(f"  unloaded: {rows[0] if rows else '?'}")


def download(cur, dldir):
    os.makedirs(dldir, exist_ok=True)
    for f in glob.glob(os.path.join(dldir, "*")):
        try:
            os.unlink(f)
        except Exception:
            pass
    uri = "file://" + dldir.replace("\\", "/").rstrip("/") + "/"
    print(f"GET -> {dldir} …")
    cur.execute(f"GET {STAGE} '{uri}'")
    gz = glob.glob(os.path.join(dldir, "*.gz"))
    if not gz:
        sys.exit("GET produced no .gz files — check the stage/path.")
    csvs = []
    for g in gz:
        out = g[:-3] if g.endswith(".gz") else g + ".csv"
        with gzip.open(g, "rb") as fin, open(out, "wb") as fout:
            shutil.copyfileobj(fin, fout)
        csvs.append(out)
    print(f"  {len(csvs)} file(s) ready.")
    return csvs


# ── SQL Server ────────────────────────────────────────────────────────────────
def sql_conn(a):
    try:
        import pyodbc
    except ImportError:
        sys.exit("pip install pyodbc")
    return pyodbc.connect(
        f"DRIVER={{{a.odbc_driver}}};SERVER={a.server};DATABASE={a.database};"
        "Trusted_Connection=yes;", autocommit=True)


def build_tables(cn, a, data_cols, det):
    full  = f"{a.schema}.{a.table}"
    stage = f"{a.schema}.{a.table}_STAGING"
    cur = cn.cursor()
    cur.execute(f"IF SCHEMA_ID('{a.schema}') IS NULL EXEC('CREATE SCHEMA {a.schema}');")
    if a.replace:
        cur.execute(f"IF OBJECT_ID('{full}','U') IS NOT NULL DROP TABLE {full};")
    else:
        # If the table exists with a different column set (e.g. an earlier
        # load used a different layout), inserting will fail deep with a cryptic
        # "invalid column name". Catch it here with a clear message.
        existing = [r[0] for r in cur.execute(f"""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA='{a.schema}' AND TABLE_NAME='{a.table}'
              AND COLUMN_NAME NOT IN ('REF_ID','LOADED_AT')
        """).fetchall()]
        if existing and set(existing) != set(data_cols):
            cur.close()
            sys.exit(f"{full} already exists with a different column set. "
                     f"Re-run with --replace to rebuild it.")

    def final_type(c):
        if c in (det["lat"], det["long"]):
            return "FLOAT NULL"
        if c == "UWI14":
            return "CHAR(14) NULL"
        if c == "NAME_NORM":
            return "NVARCHAR(400) NULL"
        if c == "UWI_SUSPECT":
            return "BIT NULL"
        return "NVARCHAR(1000) NULL"

    body = ",\n  ".join(f"[{c}] {final_type(c)}" for c in data_cols)
    cur.execute(f"""
        IF OBJECT_ID('{full}','U') IS NULL
        CREATE TABLE {full} (
          REF_ID BIGINT IDENTITY(1,1) PRIMARY KEY,
          {body},
          LOADED_AT DATETIME2 NOT NULL CONSTRAINT DF_{a.table}_LOADED
                    DEFAULT SYSUTCDATETIME()
        );""")

    # staging — everything text/lenient; typing happens on the way into final
    cur.execute(f"IF OBJECT_ID('{stage}','U') IS NOT NULL DROP TABLE {stage};")
    sbody = ",\n  ".join(f"[{c}] NVARCHAR(4000) NULL" for c in data_cols)
    cur.execute(f"CREATE TABLE {stage} (\n  {sbody}\n);")
    cur.close()
    return full, stage


def bulk_insert(cn, a, stage, csvs):
    cur = cn.cursor()
    for path in csvs:
        print(f"BULK INSERT {os.path.basename(path)} …")
        cur.execute(f"""
            BULK INSERT {stage} FROM '{path}'
            WITH (FORMAT='CSV', FIELDQUOTE='"', FIELDTERMINATOR='\\t',
                  ROWTERMINATOR='0x0a', FIRSTROW=2, CODEPAGE='65001', TABLOCK);""")
    cur.close()


def finalize(cn, a, full, stage, data_cols, det):
    cur = cn.cursor()
    target = ", ".join(f"[{c}]" for c in data_cols)

    def expr(c):
        n = f"NULLIF([{c}],'')"
        if c in (det["lat"], det["long"]):
            return f"TRY_CONVERT(FLOAT,{n})"
        if c == "UWI_SUSPECT":
            return f"TRY_CONVERT(BIT,{n})"
        return n

    sel = ", ".join(expr(c) for c in data_cols)
    print("Inserting staging -> final …")
    cur.execute(f"""
        INSERT INTO {full} ({target})
        SELECT {sel} FROM {stage}
        WHERE LEN(NULLIF([UWI14],'')) = 14;""")
    cur.execute(f"DROP TABLE {stage};")

    incl_name = f", [{det['name']}]" if det["name"] else ""
    print("Building indexes …")
    cur.execute(f"""
        IF EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_{a.table}_UWI14'
                   AND object_id=OBJECT_ID('{full}'))
            DROP INDEX IX_{a.table}_UWI14 ON {full};
        CREATE INDEX IX_{a.table}_UWI14 ON {full}(UWI14)
            INCLUDE (NAME_NORM, UWI_SUSPECT{incl_name});""")
    cur.execute(f"""
        IF EXISTS (SELECT 1 FROM sys.indexes WHERE name='IX_{a.table}_NAMENORM'
                   AND object_id=OBJECT_ID('{full}'))
            DROP INDEX IX_{a.table}_NAMENORM ON {full};
        CREATE INDEX IX_{a.table}_NAMENORM ON {full}(NAME_NORM)
            INCLUDE (UWI14);""")

    n  = cur.execute(f"SELECT COUNT(*) FROM {full};").fetchval()
    nd = cur.execute(f"SELECT COUNT(DISTINCT UWI14) FROM {full};").fetchval()
    ns = cur.execute(f"SELECT COUNT(*) FROM {full} WHERE UWI_SUSPECT=1;").fetchval()
    print(f"\n{full}: {n:,} rows · {nd:,} distinct UWI14 · {ns:,} suspect UWIs.")

    if det["source"]:
        print("\nSuspect UWIs by source (reload these):")
        for r in cur.execute(f"""
            SELECT [{det['source']}] AS SRC, COUNT(*) AS TOTAL,
                   SUM(CAST(UWI_SUSPECT AS INT)) AS SUSPECT
            FROM {full} GROUP BY [{det['source']}]
            HAVING SUM(CAST(UWI_SUSPECT AS INT)) > 0
            ORDER BY SUSPECT DESC;""").fetchall():
            print(f"   {r.SRC}: {r.SUSPECT:,} / {r.TOTAL:,}")
    else:
        print("\n(no source column detected — pass --source-col for a per-source "
              "suspect breakdown)")

    nm = f"[{det['name']}]" if det["name"] else "NULL"
    print("\nSpot-check:")
    for r in cur.execute(f"SELECT TOP 8 UWI14, {nm} AS WN, UWI_SUSPECT "
                         f"FROM {full} ORDER BY NEWID();").fetchall():
        print("  ", tuple(r))
    cur.close()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--authenticator", default="snowflake",
                   choices=["externalbrowser", "username_password_mfa", "snowflake"])
    p.add_argument("--sf-account", default=SF_ACCOUNT)
    p.add_argument("--sf-user", default=SF_USER)
    p.add_argument("--sf-role", default=SF_ROLE)
    p.add_argument("--sf-warehouse", default=SF_WAREHOUSE)
    p.add_argument("--sf-database", default=SF_DATABASE)
    p.add_argument("--sf-schema", default=SF_SCHEMA)
    p.add_argument("--sf-table", default=SF_TABLE)
    p.add_argument("--sf-password", default=None)
    p.add_argument("--passcode", default=None)
    p.add_argument("--uwi-col", dest="uwi_col", default=None)
    p.add_argument("--name-col", dest="name_col", default=None)
    p.add_argument("--lat-col", dest="lat_col", default=None)
    p.add_argument("--long-col", dest="long_col", default=None)
    p.add_argument("--source-col", dest="source_col", default=None)
    p.add_argument("--depth-col", dest="depth_col", default=None)
    p.add_argument("--spud-col", dest="spud_col", default=None)
    p.add_argument("--inspect", action="store_true",
                   help="Connect, list columns + detection, then exit (no reload).")
    p.add_argument("--server", default=DEFAULT_SERVER)
    p.add_argument("--database", default=DEFAULT_DB)
    p.add_argument("--odbc-driver", default=DEFAULT_DRIVER)
    p.add_argument("--schema", default=DEST_SCHEMA)
    p.add_argument("--table", default=DEST_TABLE)
    p.add_argument("--dldir", default=DEFAULT_DLDIR)
    p.add_argument("--columns", default=None,
                   help="comma-separated columns to carry (default: built-in "
                        "core set). The uwi/name/lat/long/source columns are "
                        "always added.")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--keep-files", action="store_true")
    a = p.parse_args()

    conn = connect_snowflake(a)
    cur = conn.cursor()
    src = f"{a.sf_database}.{a.sf_schema}.{a.sf_table}"
    cols = source_columns(cur, src)
    print(f"\n{a.sf_table} has {len(cols)} columns:")
    print("  " + ", ".join(cols))

    det = {k: (getattr(a, f"{k}_col") or detect_col(cols, v))
           for k, v in CANDIDATES.items()}
    print("\nDetected:")
    for k in ("uwi", "name", "lat", "long", "source", "depth", "spud"):
        print(f"  {k:7} -> {det[k]}")
    if not det["uwi"]:
        sys.exit("No UWI column found. Pass --uwi-col.")

    # Carry TD / spud date under canonical names so the reference matches the
    # catalog's FILE_WELL_HEADER columns (TOTAL_DEPTH, SPUD_DATE) directly.
    alias = {}
    if det.get("depth"):
        alias[det["depth"]] = "TOTAL_DEPTH"
    if det.get("spud"):
        alias[det["spud"]] = "SPUD_DATE"

    # Resolve which columns to carry: the requested/core set, filtered to those
    # that exist, plus the detected key columns (always needed).
    requested = ([c.strip() for c in a.columns.split(",")] if a.columns
                 else CORE_COLS)
    by_upper = {c.upper(): c for c in cols}
    selected = []
    for c in requested:
        actual = by_upper.get(c.upper())
        if actual and actual not in selected:
            selected.append(actual)
        elif not actual:
            print(f"  (skipping '{c}' — not in source)")
    for key in (det["uwi"], det["name"], det["lat"], det["long"], det["source"],
                det["depth"], det["spud"]):
        if key and key not in selected:
            selected.append(key)
    print(f"\nCarrying {len(selected)} columns: {', '.join(selected)}")
    if alias:
        print("Aliasing: " + ", ".join(f"{k} -> {v}" for k, v in alias.items()))

    # Key fallback chain: UWI, then API_NUM/API_10 when UWI yields no key.
    key_cols = [det["uwi"]] + [by_upper[n] for n in ("API_NUM", "API_10",
                "API14", "API_14") if n in by_upper and by_upper[n] != det["uwi"]]
    print(f"UWI14 key from: {', '.join(key_cols)}")

    t0 = time.time()
    unload(cur, build_select(src, selected, det, key_cols, a.limit, alias))
    csvs = download(cur, a.dldir)
    cur.close(); conn.close()

    data_cols = [alias.get(c, c) for c in selected] + EXTRA_COLS
    cn = sql_conn(a)
    full, stage = build_tables(cn, a, data_cols, det)
    bulk_insert(cn, a, stage, csvs)
    finalize(cn, a, full, stage, data_cols, det)
    cn.close()

    if not a.keep_files:
        for f in csvs:
            try:
                os.unlink(f)
            except Exception:
                pass
    print(f"\nDone in {time.time()-t0:.1f}s.")


if __name__ == "__main__":
    main()

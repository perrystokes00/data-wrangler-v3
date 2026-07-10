r"""
load_well_header_csv.py — load a synthetic/external well-header CSV into cat_well so
the wells promote into dv_well and any HELD document data (tops, surveys, production,
completions) for those UWIs can then attach to a parent and promote.

Use when documents reference wells that aren't in dv_well and aren't in the gold
reference (e.g. synthetic test wells) — you supply the headers directly via CSV.

Maps well_header.csv -> cat_well (only columns that exist are inserted):
    UWI               -> UWI (dashes/space/slash stripped, padded to 14)
    WELL_NAME         -> WELL_NAME
    OPERATOR          -> OPERATOR_NAME
    FIELD_NAME        -> FIELD_NAME
    PROVINCE_STATE    -> PROVINCE_STATE
    COUNTY            -> COUNTY
    COUNTRY           -> COUNTRY
    SURFACE_LATITUDE  -> SURFACE_LATITUDE
    SURFACE_LONGITUDE -> SURFACE_LONGITUDE
    DRILLERS_TD       -> FINAL_TD
Adds ACTIVE_IND='Y', ROW_QUALITY='FINAL', PPDM_GUID, SOURCE='DATA_LOADER',
PROMOTED=0, ROW_CREATED_BY/DATE — the same shape worker_core writes for LAS headers.

Usage:
  py load_well_header_csv.py --csv well_header.csv            # preview
  py load_well_header_csv.py --csv well_header.csv --apply    # insert into cat_well
Then run promote (py run_promote_now.py) to build dv_well + release held doc data.
"""
import sys, os, uuid, datetime

CAT = "file_catalog"
DV  = "dataview"

# CSV column -> cat_well column
MAP = {
    "UWI":               "UWI",
    "WELL_NAME":         "WELL_NAME",
    "OPERATOR":          "OPERATOR_NAME",
    "FIELD_NAME":        "FIELD_NAME",
    "PROVINCE_STATE":    "PROVINCE_STATE",
    "COUNTY":            "COUNTY",
    "COUNTRY":           "COUNTRY",
    "SURFACE_LATITUDE":  "SURFACE_LATITUDE",
    "SURFACE_LONGITUDE": "SURFACE_LONGITUDE",
    "DRILLERS_TD":       "FINAL_TD",
}

_NORM = ("LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),"
         "'-',''),' ',''),'/','')))+'00000000000000',14)")


def _norm_uwi(u):
    s = (u or "").replace("-", "").replace(" ", "").replace("/", "")
    return (s + "00000000000000")[:14] if s else None


def _cat_well_columns(cur):
    return {r[0].upper() for r in cur.execute(
        "SELECT c.name FROM sys.columns c JOIN sys.tables t ON t.object_id=c.object_id "
        "JOIN sys.schemas s ON s.schema_id=t.schema_id "
        "WHERE s.name=? AND t.name='cat_well'", CAT).fetchall()}


def load(cur, df, log=print):
    """Insert header rows into cat_well (PROMOTED=0). Skips UWIs already present in
    cat_well. Returns count inserted."""
    have = _cat_well_columns(cur)
    # which mapped targets actually exist on cat_well
    usable = {src: tgt for src, tgt in MAP.items()
              if tgt.upper() in have and src in df.columns}
    extra_cols = [c for c in ("ACTIVE_IND", "ROW_QUALITY", "PPDM_GUID", "SOURCE",
                              "PROMOTED", "ROW_CREATED_BY", "ROW_CREATED_DATE")
                  if c in have]
    now = datetime.datetime.utcnow()

    # existing normalized UWIs in cat_well (skip dups)
    existing = set()
    for r in cur.execute(f"SELECT {_NORM.format(col='UWI')} FROM {CAT}.cat_well").fetchall():
        if r[0]:
            existing.add(r[0])

    ins_cols = [usable[s] for s in usable] + extra_cols
    placeholders = ", ".join("?" for _ in ins_cols)
    collist = ", ".join(f"[{c}]" for c in ins_cols)
    sql = f"INSERT INTO {CAT}.cat_well ({collist}) VALUES ({placeholders})"

    n = skipped = 0
    for _, row in df.iterrows():
        nu = _norm_uwi(row.get("UWI", ""))
        if not nu or nu in existing:
            skipped += 1
            continue
        vals = []
        for s in usable:
            v = row.get(s, "")
            if usable[s] == "UWI":
                v = nu                      # store the normalized UWI
            vals.append(v if v not in ("", None) else None)
        for c in extra_cols:
            vals.append({"ACTIVE_IND": "Y", "ROW_QUALITY": "FINAL",
                         "PPDM_GUID": str(uuid.uuid4()), "SOURCE": "DATA_LOADER",
                         "PROMOTED": 0, "ROW_CREATED_BY": "HEADER_CSV",
                         "ROW_CREATED_DATE": now}[c])
        cur.execute(sql, *vals)
        n += cur.rowcount or 0
        existing.add(nu)
    if log:
        log(f"[load] inserted {n} cat_well header(s), skipped {skipped} "
            f"(already present / blank UWI)")
        log(f"[load] columns written: {ins_cols}")
    return n


def _held_overlap(cur, df, log=print):
    """How many of the CSV's UWIs have HELD document data waiting for a parent well?
    These are the ones this load will unblock."""
    uwis = {u for u in (_norm_uwi(x) for x in df["UWI"]) if u}
    if not uwis:
        return
    # temp table of csv uwis
    cur.execute("IF OBJECT_ID('tempdb..#csvuwi') IS NOT NULL DROP TABLE #csvuwi")
    cur.execute("CREATE TABLE #csvuwi (uwi char(14) PRIMARY KEY)")
    for u in uwis:
        try: cur.execute("INSERT INTO #csvuwi (uwi) VALUES (?)", u)
        except Exception: pass
    log("\n[overlap] held document UWIs that match this CSV (would be unblocked):")
    for cat in ("cat_well_formation_top", "cat_prod_volume", "cat_well_dir_srvy_hdr",
                "cat_well_dir_srvy_sta", "cat_well_completion", "cat_well_log_curve"):
        try:
            n = cur.execute(f"""
                SELECT COUNT(*) FROM {CAT}.{cat} m
                JOIN #csvuwi c ON c.uwi = {_NORM.format(col='m.UWI')}
                WHERE m.PROMOTED=0""").fetchone()[0]
            if n:
                log(f"   {cat}: {n} held rows match")
        except Exception:
            pass
    cur.execute("IF OBJECT_ID('tempdb..#csvuwi') IS NOT NULL DROP TABLE #csvuwi")


def main():
    import pandas as pd
    csv = None
    if "--csv" in sys.argv:
        csv = sys.argv[sys.argv.index("--csv") + 1]
    for cand in ([csv] if csv else []) + ["well_header.csv",
                 r"C:\Bulk\well_header.csv",
                 os.path.expanduser(r"~\Downloads\well_header.csv")]:
        if cand and os.path.exists(cand):
            csv = cand; break
    if not csv or not os.path.exists(csv):
        sys.exit("well_header.csv not found — pass --csv <path>")

    apply = "--apply" in sys.argv
    df = pd.read_csv(csv, dtype=str, keep_default_na=False)
    print(f"read {len(df)} header rows from {csv}")

    import pyodbc
    conn = pyodbc.connect(
        r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
    conn.autocommit = False
    cur = conn.cursor()

    _held_overlap(cur, df)

    if not apply:
        print("\n(preview) re-run with --apply to insert these headers into cat_well,")
        print("          then: py run_promote_now.py")
        conn.rollback(); return
    n = load(cur, df)
    conn.commit()
    print(f"\ncommitted {n} header(s) into cat_well.")
    print("now run: py run_promote_now.py   (builds dv_well + releases held doc data)")


if __name__ == "__main__":
    main()

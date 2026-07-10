r"""
load_ks_header_to_gold.py — load KGS well headers (API + LAT/LON) into
well_master_gold via BULK INSERT (not pyodbc executemany), so the LAS pipeline
enriches coords from gold. Idempotent: inserts only UWIs gold lacks.

  py load_ks_header_to_gold.py --csv "C:\...\ks_wells.csv"           # preview
  py load_ks_header_to_gold.py --csv "C:\...\ks_wells.csv" --apply
  py load_ks_header_to_gold.py --csv "C:\...\ks_wells.csv" --apply --fill-existing
"""
import sys, os
import pandas as pd
import pyodbc

CSV = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else \
      r"C:\Users\perry\OneDrive\Documents\KSGS\ks_wells.csv"
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
REF = "WELL_REF.well_ref.well_master_gold"
STG = "stg.ks_gold"
BULK_DIR = r"C:\bcp_tmp"
CSV_OUT = os.path.join(BULK_DIR, "ks_gold.tsv")
COLS = ["uwi14", "api_10", "surface_latitude", "surface_longitude",
        "well_name", "operator_name", "county"]

def col(cols, *names):
    m = {c.lower().strip(): c for c in cols}
    return next((m[n] for n in names if n in m), None)

# ── build the rows ───────────────────────────────────────────────────────────
df = pd.read_csv(CSV, dtype=str)
uc  = col(df.columns, "api_num_nodash", "uwi14", "uwi")
la  = col(df.columns, "latitude", "lat")
lo  = col(df.columns, "longitude", "lon")
nmc = col(df.columns, "lease_well_name", "well_name", "lease")
opc = col(df.columns, "curr_operator", "orig_operator", "operator_name")
cnc = col(df.columns, "county")
if not (uc and la and lo):
    sys.exit(f"need API/lat/lon columns. found: {list(df.columns)}")

api = df[uc].fillna("").str.replace(r"\D", "", regex=True)
lat = pd.to_numeric(df[la], errors="coerce")
lon = pd.to_numeric(df[lo], errors="coerce")
keep = (api.str.len() >= 10) & lat.notna() & lon.notna() & ~((lat == 0) & (lon == 0))

out = pd.DataFrame({
    "uwi14": (api + "00000000000000").str[:14],
    "api_10": api.str[:10],
    "surface_latitude": lat.map(lambda x: "" if pd.isna(x) else repr(float(x))),
    "surface_longitude": lon.map(lambda x: "" if pd.isna(x) else repr(float(x))),
    "well_name": (df[nmc] if nmc else pd.Series([""] * len(df))).fillna(""),
    "operator_name": (df[opc] if opc else pd.Series([""] * len(df))).fillna(""),
    "county": (df[cnc] if cnc else pd.Series([""] * len(df))).fillna(""),
})[keep].drop_duplicates("uwi14")
for tc in ("well_name", "operator_name", "county"):
    out[tc] = out[tc].astype(str).str.replace(r"[\t\r\n|]", " ", regex=True).str.strip()
print(f"{os.path.basename(CSV)}: {len(df):,} rows -> {len(out):,} valid header wells")

# ── write TSV + BULK INSERT into a wide staging table ────────────────────────
os.makedirs(BULK_DIR, exist_ok=True)
out[COLS].to_csv(CSV_OUT, sep="\t", index=False, header=False,
                 lineterminator="\n", encoding="utf-8")

cn = pyodbc.connect(CONN, autocommit=True)
cur = cn.cursor()
_gold_cols = {r[0].lower() for r in cur.execute(
    "SELECT name FROM WELL_REF.sys.columns "
    "WHERE object_id=OBJECT_ID('WELL_REF.well_ref.well_master_gold')").fetchall()}
def _has(c):
    return c.lower() in _gold_cols
cur.execute("IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg')")
cur.execute(f"IF OBJECT_ID('{STG}') IS NOT NULL DROP TABLE {STG}")
_types = {"uwi14": "nvarchar(14)", "api_10": "nvarchar(10)"}
cur.execute("CREATE TABLE " + STG + " (" +
            ", ".join(f"[{c}] {_types.get(c, 'nvarchar(max)')}" for c in COLS) + ")")
cur.execute(
    "BULK INSERT " + STG + " FROM '" + CSV_OUT.replace("'", "''") + "' "
    "WITH (FIELDTERMINATOR='\\t', ROWTERMINATOR='0x0a', TABLOCK, "
    "BATCHSIZE=50000, CODEPAGE='65001')")
cur.execute(f"CREATE INDEX IX_ks_gold_uwi14 ON {STG}(uwi14)")
staged = cur.execute(f"SELECT COUNT(*) FROM {STG}").fetchone()[0]
new = cur.execute(f"SELECT COUNT(*) FROM {STG} s WHERE NOT EXISTS "
                  f"(SELECT 1 FROM {REF} g WHERE g.uwi14 = s.uwi14)").fetchone()[0]
print(f"staged {staged:,} · new to gold: {new:,} · already in gold: {staged-new:,}")

if "--apply" not in sys.argv:
    print("\n[dry run] add --apply to bulk-insert the new wells into gold.")
    cur.execute(f"DROP TABLE {STG}")
    sys.exit(0)

# schema-adaptive: (gold column, source expression) — keep only real columns
_pairs = [
    ("uwi14",             "s.uwi14"),
    ("api_10",            "s.api_10"),
    ("surface_latitude",  "TRY_CONVERT(float, s.surface_latitude)"),
    ("surface_longitude", "TRY_CONVERT(float, s.surface_longitude)"),
    ("well_name",         "NULLIF(s.well_name,'')"),
    ("operator_name",     "NULLIF(s.operator_name,'')"),
    ("county",            "NULLIF(s.county,'')"),
    ("province_state",    "'KS'"),
    ("country",           "'USA'"),
    ("primary_source",    "'KGS'"),
    ("source_list",       "'KGS'"),
    ("source_count",      "1"),
    ("quality_score",     "90"),
    ("long_lat_source",   "'KGS header'"),
    ("built_at",          "SYSDATETIME()"),
]
_use = [(c, e) for (c, e) in _pairs if _has(c)]
_collist = ", ".join(f"[{c}]" for c, _e in _use)
_sellist = ", ".join(e for _c, e in _use)
ins = cur.execute(
    f"INSERT INTO {REF} ({_collist}) SELECT {_sellist} FROM {STG} s "
    f"WHERE NOT EXISTS (SELECT 1 FROM {REF} g WHERE g.uwi14 = s.uwi14)").rowcount
print(f"inserted {ins:,} new well(s) into gold "
      f"(skipped non-existent cols: {[c for c,_ in _pairs if not _has(c)]})")

if "--fill-existing" in sys.argv:
    upd = cur.execute(f"""
        UPDATE g SET g.surface_latitude = TRY_CONVERT(float, s.surface_latitude),
                     g.surface_longitude = TRY_CONVERT(float, s.surface_longitude)
        FROM {REF} g JOIN {STG} s ON s.uwi14 = g.uwi14
        WHERE (g.surface_latitude IS NULL OR g.surface_longitude IS NULL
               OR (g.surface_latitude = 0 AND g.surface_longitude = 0))""").rowcount
    print(f"filled coords on {upd:,} existing gold row(s)")

cur.execute(f"DROP TABLE {STG}")
print("\ngold now covers these Kansas wells — LAS loads enrich coords on promote.")

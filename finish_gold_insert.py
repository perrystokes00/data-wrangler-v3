"""finish_gold_insert.py — insert the already-staged stg.ks_gold rows into gold,
auto-fitting every string to gold's real column widths (no truncation possible).
Uses the data BULK INSERT already staged; no re-load. py finish_gold_insert.py [--fill-existing]"""
import sys, pyodbc
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
REF = "WELL_REF.well_ref.well_master_gold"
STG = "stg.ks_gold"

cn = pyodbc.connect(CONN, autocommit=True)
cur = cn.cursor()
if not cur.execute("SELECT OBJECT_ID('" + STG + "')").fetchone()[0]:
    sys.exit("stg.ks_gold not found — re-run load_ks_header_to_gold.py once to stage it, "
             "then run this.")
staged = cur.execute("SELECT COUNT(*) FROM " + STG).fetchone()[0]
print(f"staged rows: {staged:,}")

# gold columns -> (char width, type)
glen = {}
for r in cur.execute(
        "SELECT c.name, c.max_length, ty.name typ "
        "FROM WELL_REF.sys.columns c JOIN WELL_REF.sys.types ty ON ty.user_type_id=c.user_type_id "
        "WHERE c.object_id=OBJECT_ID('WELL_REF.well_ref.well_master_gold')").fetchall():
    n = r.max_length
    if r.typ in ("nvarchar", "nchar") and n > 0:
        n //= 2
    glen[r.name.lower()] = (n, r.typ)

def has(c):
    return c.lower() in glen

def wrap(col, expr):
    """LEFT()-fit any string column's value/literal to its width; leave numerics/dates."""
    n, typ = glen.get(col.lower(), (0, ""))
    if typ in ("char", "nchar", "varchar", "nvarchar") and n and n > 0:
        return f"LEFT({expr}, {n})"
    return expr

pairs = [
    ("uwi14", "s.uwi14"), ("api_10", "s.api_10"),
    ("surface_latitude", "TRY_CONVERT(float, s.surface_latitude)"),
    ("surface_longitude", "TRY_CONVERT(float, s.surface_longitude)"),
    ("well_name", "NULLIF(s.well_name,'')"), ("operator_name", "NULLIF(s.operator_name,'')"),
    ("county", "NULLIF(s.county,'')"),
    ("province_state", "'KS'"), ("country", "'US'"),
    ("primary_source", "'KGS'"), ("source_list", "'KGS'"),
    ("source_count", "1"), ("quality_score", "90"), ("built_at", "SYSDATETIME()"),
]
use = [(c, wrap(c, e)) for (c, e) in pairs if has(c)]
collist = ", ".join(f"[{c}]" for c, _ in use)
sellist = ", ".join(e for _, e in use)

ins = cur.execute(
    f"INSERT INTO {REF} ({collist}) SELECT {sellist} FROM {STG} s "
    f"WHERE NOT EXISTS (SELECT 1 FROM {REF} g WHERE g.uwi14 = s.uwi14)").rowcount
print(f"inserted {ins:,} new well(s) into gold "
      f"(cols used: {[c for c,_ in use]})")

if "--fill-existing" in sys.argv:
    upd = cur.execute(f"""
        UPDATE g SET g.surface_latitude = TRY_CONVERT(float, s.surface_latitude),
                     g.surface_longitude = TRY_CONVERT(float, s.surface_longitude)
        FROM {REF} g JOIN {STG} s ON s.uwi14 = g.uwi14
        WHERE (g.surface_latitude IS NULL OR g.surface_longitude IS NULL
               OR (g.surface_latitude = 0 AND g.surface_longitude = 0))""").rowcount
    print(f"filled coords on {upd:,} existing gold row(s)")

cur.execute("DROP TABLE " + STG)
print("done — staging dropped.")

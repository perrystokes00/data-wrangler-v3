"""gold_match_diag.py — is the gold miss a suffix-normalization issue (match on
API10 vs full API14) or does gold simply not have these Kansas wells?
py gold_match_diag.py"""
import urllib.parse as _u
import pandas as pd
from sqlalchemy import create_engine, text

CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))
REF = "WELL_REF.well_ref.well_master_gold"

def digits(u):
    return "".join(c for c in str(u) if c.isdigit())

with eng.begin() as c:
    ks   = c.execute(text(f"SELECT COUNT(*) FROM {REF} WHERE uwi14 LIKE '15%'")).scalar()
    swd  = c.execute(text(f"SELECT COUNT(*) FROM {REF} WHERE uwi14 LIKE '15175%'")).scalar()
    uwis = [r[0] for r in c.execute(text(
        "SELECT DISTINCT UWI FROM file_catalog.cat_well WHERE UWI IS NOT NULL"))]
print(f"gold Kansas (uwi14 '15…')       : {ks:,}")
print(f"gold Seward   (uwi14 '15175…')  : {swd:,}")

rows = []
for u in uwis:
    d = digits(u)
    if len(d) >= 10:
        api14 = (d + "0000")[:14] if len(d) == 10 else d.ljust(14, "0")[:14]
        rows.append((str(u), d[:10], api14))
df = pd.DataFrame(rows, columns=["uwi", "api10", "api14"])
print(f"\ncat_well distinct UWIs          : {len(uwis):,}   (with 10+ digits: {len(df):,})")

df.to_sql("cw_keys", eng, schema="stg", if_exists="replace", index=False, chunksize=5000)
with eng.begin() as c:
    m14 = c.execute(text(
        f"SELECT COUNT(DISTINCT k.api14) FROM stg.cw_keys k JOIN {REF} g ON g.uwi14 = k.api14")).scalar()
    m10 = c.execute(text(
        f"SELECT COUNT(DISTINCT k.api10) FROM stg.cw_keys k "
        f"JOIN {REF} g ON LEFT(g.uwi14,10) = k.api10")).scalar()
    # of API10 matches, how many gold rows carry coords
    m10c = c.execute(text(
        f"SELECT COUNT(DISTINCT k.api10) FROM stg.cw_keys k "
        f"JOIN {REF} g ON LEFT(g.uwi14,10) = k.api10 "
        f"WHERE g.surface_latitude IS NOT NULL "
        f"AND NOT (g.surface_latitude=0 AND g.surface_longitude=0)")).scalar()
    c.execute(text("DROP TABLE stg.cw_keys"))

print(f"\ncat_well wells matching gold on full API14 : {m14:,}")
print(f"cat_well wells matching gold on API10      : {m10:,}   <- suffix-agnostic")
print(f"   of those, gold has coords               : {m10c:,}")
print("\n=> if API10 >> API14, the suffix (0000 vs real) was the blocker.")
print("   if API10 is also ~0, gold genuinely lacks these wells (use the CSV).")

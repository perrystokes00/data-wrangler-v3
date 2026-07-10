"""ks_in_gold.py — are any of the UWIs in the Kansas well-header file present in
the golden well database? Reports full-14 and API10 (suffix-agnostic) matches.
  py ks_in_gold.py [--file PATH]
"""
import sys, os, urllib.parse as _u
import pandas as pd
from sqlalchemy import create_engine, text

KS = sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else \
     r"C:\Users\perry\OneDrive\Documents\KSGS\ks_wells.txt"
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))
REF = "WELL_REF.well_ref.well_master_gold"

if not os.path.exists(KS):
    sys.exit(f"not found: {KS}")

# the KS header file is a quoted CSV with API_NUM_NODASH = UWI14
df = pd.read_csv(KS, dtype=str)
cols = {c.lower().strip(): c for c in df.columns}
uc = next((cols[k] for k in ("api_num_nodash", "uwi14", "uwi", "api_number", "api") if k in cols), None)
if not uc:
    sys.exit(f"no UWI column found. columns: {list(df.columns)}")
print(f"file: {os.path.basename(KS)}   UWI column: {uc}   rows: {len(df):,}")

def digits(v):
    return "".join(c for c in str(v) if c.isdigit())

keys = set()
for v in df[uc].dropna():
    d = digits(v)
    if len(d) >= 10:
        api14 = (d + "0000")[:14] if len(d) == 10 else d.ljust(14, "0")[:14]
        keys.add((d[:10], api14))
kf = pd.DataFrame(keys, columns=["api10", "api14"])
tot = len(kf)
print(f"distinct KS UWIs (10+ digits): {tot:,}")

with eng.begin() as c:
    c.execute(text("IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg')"))
kf.to_sql("ks_hdr", eng, schema="stg", if_exists="replace", index=False, chunksize=10000)

with eng.begin() as c:
    gold_tot = c.execute(text(f"SELECT COUNT(*) FROM {REF}")).scalar()
    g14 = c.execute(text(f"SELECT COUNT(DISTINCT k.api14) FROM stg.ks_hdr k JOIN {REF} g ON g.uwi14=k.api14")).scalar()
    g10 = c.execute(text(f"SELECT COUNT(DISTINCT k.api10) FROM stg.ks_hdr k JOIN {REF} g ON LEFT(g.uwi14,10)=k.api10")).scalar()
    hit = c.execute(text(f"SELECT TOP 5 k.api14 FROM stg.ks_hdr k JOIN {REF} g ON g.uwi14=k.api14")).fetchall()
    hit10 = c.execute(text(
        f"SELECT TOP 5 k.api14, MIN(g.uwi14) gold_uwi14 FROM stg.ks_hdr k "
        f"JOIN {REF} g ON LEFT(g.uwi14,10)=k.api10 GROUP BY k.api14")).fetchall()
    c.execute(text("DROP TABLE stg.ks_hdr"))

print(f"\ngold rows total : {gold_tot:,}")
print(f"\nKS header UWIs found in gold:")
print(f"  full API14 match : {g14:,}  ({100.0*g14/tot:.2f}%)")
print(f"  API10  match     : {g10:,}  ({100.0*g10/tot:.2f}%)")
print(f"\nsample API14 hits : {[r[0] for r in hit]}")
print(f"sample API10 hits (ks -> gold): {[(r[0], r[1]) for r in hit10]}")

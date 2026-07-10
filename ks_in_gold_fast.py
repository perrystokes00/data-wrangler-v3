"""ks_in_gold_fast.py — fast: pull gold's Kansas rows only, compare sets in Python.
py ks_in_gold_fast.py [--file PATH]"""
import sys, os, urllib.parse as _u
import pandas as pd
from sqlalchemy import create_engine, text

KS = sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else \
     r"C:\Users\perry\OneDrive\Documents\KSGS\ks_wells.txt"
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))
REF = "WELL_REF.well_ref.well_master_gold"

def digits(v):
    return "".join(c for c in str(v) if c.isdigit())

df = pd.read_csv(KS, dtype=str)
cols = {c.lower().strip(): c for c in df.columns}
uc = next((cols[k] for k in ("api_num_nodash", "uwi14", "uwi", "api_number") if k in cols), None)
ks14, ks10 = set(), set()
for v in df[uc].dropna():
    d = digits(v)
    if len(d) >= 10:
        ks14.add((d + "0000")[:14] if len(d) == 10 else d.ljust(14, "0")[:14])
        ks10.add(d[:10])
print(f"KS header file: {len(df):,} rows, {len(ks14):,} distinct UWI14")

with eng.begin() as c:
    gold = [r[0] for r in c.execute(text(f"SELECT uwi14 FROM {REF} WHERE uwi14 LIKE '15%'"))]
g14 = {str(u) for u in gold}
g10 = {str(u)[:10] for u in gold}
print(f"gold Kansas rows: {len(gold):,}")

print(f"\nKS UWIs also in gold:")
print(f"  full API14 : {len(ks14 & g14):,}")
print(f"  API10      : {len(ks10 & g10):,}")
print(f"\nsample API10 overlap: {list(ks10 & g10)[:5]}")

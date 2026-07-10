"""ks_gold_uwi14_now.py — after the gold rebuild, how many Kansas wells match on
the (now fixed) uwi14? py ks_gold_uwi14_now.py"""
import sys, os, urllib.parse as _u
import pandas as pd
from sqlalchemy import create_engine, text

KS = sys.argv[sys.argv.index("--file") + 1] if "--file" in sys.argv else \
     r"C:\Users\perry\OneDrive\Documents\KSGS\ks_wells.txt"
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))
REF = "WELL_REF.well_ref.well_master_gold"

def to14(v):
    d = "".join(c for c in str(v) if c.isdigit())
    return (d + "00000000000000")[:14] if len(d) >= 10 else None

df = pd.read_csv(KS, dtype=str)
cols = {c.lower().strip(): c for c in df.columns}
uc = next((cols[k] for k in ("api_num_nodash", "uwi14", "uwi") if k in cols), None)
ks14 = {to14(v) for v in df[uc].dropna()}
ks14.discard(None)
print(f"ks_wells.txt: {len(df):,} rows -> {len(ks14):,} distinct uwi14")

with eng.begin() as c:
    g14  = {str(r[0]).strip() for r in c.execute(text(
        f"SELECT uwi14 FROM {REF} WHERE uwi14 LIKE '15%'"))}
    g14c = {str(r[0]).strip() for r in c.execute(text(
        f"SELECT uwi14 FROM {REF} WHERE uwi14 LIKE '15%' "
        f"AND surface_latitude IS NOT NULL AND NOT (surface_latitude=0 AND surface_longitude=0)"))}
print(f"gold Kansas uwi14 (now): {len(g14):,}   with coords: {len(g14c):,}")

match  = ks14 & g14
matchc = ks14 & g14c
print(f"\nKansas wells matching gold on uwi14 : {len(match):,}  "
      f"({100.0*len(match)/max(1,len(ks14)):.1f}%)")
print(f"  of those, gold has coords         : {len(matchc):,}")
print(f"sample: {list(match)[:5]}")

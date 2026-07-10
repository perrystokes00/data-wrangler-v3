r"""
extract_matched_wells.py — from the KGS well-header CSV, keep ONLY the wells whose
UWI matches a well you've already loaded (cat_well / dv_well / FILE_WELL_HEADER),
so you load a few hundred coordinate rows instead of all ~550k.

  py extract_matched_wells.py
  py extract_matched_wells.py --csv "C:\...\well_header.csv" --out "C:\...\matched.csv"
"""
import sys, os, urllib.parse as _u
import pandas as pd
from sqlalchemy import create_engine, text

CSV = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else \
      r"C:\Users\perry\OneDrive\Documents\KSGS\ks_wells.txt"
OUT = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else \
      os.path.join(os.path.dirname(CSV), "well_header_matched.csv")
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))

def to14(v):
    d = "".join(c for c in str(v) if c.isdigit())
    return (d + "00000000000000")[:14] if len(d) >= 10 else None

# 1) the UWIs you've loaded (union across the three tables, normalized to 14)
loaded = set()
with eng.begin() as c:
    for q in (
        "SELECT DISTINCT UWI   FROM file_catalog.cat_well           WHERE UWI   IS NOT NULL",
        "SELECT DISTINCT uwi   FROM dataview.dv_well                 WHERE uwi   IS NOT NULL",
        "SELECT DISTINCT UWI14 FROM file_catalog.FILE_WELL_HEADER    WHERE UWI14 IS NOT NULL",
    ):
        try:
            for r in c.execute(text(q)):
                u = to14(r[0])
                if u:
                    loaded.add(u)
        except Exception as e:
            print(f"  (skip: {str(e)[:60]})")
print(f"loaded wells (distinct UWI14): {len(loaded):,}")
if not loaded:
    sys.exit("no loaded UWIs found — nothing to match against")

# 2) read the header CSV, normalize its UWI, keep only matches
df = pd.read_csv(CSV, dtype=str)
cols = {c.lower().strip(): c for c in df.columns}
uc = next((cols[k] for k in ("api_num_nodash", "uwi14", "uwi", "api_number") if k in cols), None)
if not uc:
    sys.exit(f"no UWI column in {os.path.basename(CSV)}: {list(df.columns)}")
print(f"{os.path.basename(CSV)}: {len(df):,} rows, UWI column '{uc}'")

df["_uwi14"] = df[uc].map(to14)
matched = df[df["_uwi14"].isin(loaded)].drop(columns=["_uwi14"])
matched.to_csv(OUT, index=False, encoding="utf-8")

hit = set(df.loc[df["_uwi14"].isin(loaded), "_uwi14"])
print(f"\nmatched {len(matched):,} well rows ({len(hit):,} distinct UWIs) -> {OUT}")
print(f"loaded UWIs with NO header match: {len(loaded) - len(hit):,}")

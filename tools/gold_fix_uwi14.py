"""
gold_fix_uwi14.py — gold.uwi14 is corrupted/misaligned for many rows (state code
doesn't match api_10 or the coords). api_10 is the correct key. This rebuilds
uwi14 = api_10 + '0000' wherever it disagrees, so every uwi14 join works again.

  py gold_fix_uwi14.py           # preview how many rows are wrong
  py gold_fix_uwi14.py --apply   # rebuild uwi14 from api_10
"""
import sys, urllib.parse as _u
from sqlalchemy import create_engine, text

CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))
REF = "WELL_REF.well_ref.well_master_gold"

# a row is "wrong" if uwi14's first 10 don't equal api_10 (and api_10 is a clean 10-digit)
BAD = ("api_10 IS NOT NULL AND LEN(RTRIM(api_10)) = 10 "
       "AND LEFT(uwi14,10) <> RTRIM(api_10)")

with eng.begin() as c:
    tot = c.execute(text(f"SELECT COUNT(*) FROM {REF}")).scalar()
    bad = c.execute(text(f"SELECT COUNT(*) FROM {REF} WHERE {BAD}")).scalar()
    ks_before = c.execute(text(f"SELECT COUNT(*) FROM {REF} WHERE uwi14 LIKE '15%'")).scalar()
print(f"gold rows                    : {tot:,}")
print(f"uwi14 disagrees with api_10  : {bad:,}  ({100.0*bad/tot:.1f}%)")
print(f"uwi14 starting '15' (before) : {ks_before:,}")

print("\nsample mismatches (uwi14 | api_10 | lat,lon):")
with eng.begin() as c:
    for r in c.execute(text(
            f"SELECT TOP 6 uwi14, api_10, surface_latitude, surface_longitude "
            f"FROM {REF} WHERE {BAD} AND surface_latitude IS NOT NULL")).fetchall():
        print("  ", tuple(r))

if "--apply" not in sys.argv:
    print("\n[dry run] add --apply to rebuild uwi14 = api_10 + '0000' for the wrong rows.")
    sys.exit(0)

with eng.begin() as c:
    n = c.execute(text(
        f"UPDATE {REF} SET uwi14 = RTRIM(api_10) + '0000' WHERE {BAD}")).rowcount
    ks_after = c.execute(text(f"SELECT COUNT(*) FROM {REF} WHERE uwi14 LIKE '15%'")).scalar()
print(f"\nrebuilt uwi14 on {n:,} rows")
print(f"uwi14 starting '15' (after)  : {ks_after:,}   (was {ks_before:,})")

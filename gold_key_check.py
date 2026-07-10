"""gold_key_check.py — is the cat_well UWI actually in gold, or is the join key off?
py gold_key_check.py"""
import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

print("cat_well UWI samples:")
for r in cur.execute("SELECT TOP 8 UWI, WELL_NAME FROM file_catalog.cat_well").fetchall():
    print(f"  {r.UWI!r:22} {r.WELL_NAME}")

# is a known KS well in gold, tried a few ways?
tests = ["15175003950000", "15175003950000".rstrip("0"), "1517500395",
         "15-175-00395", "151750039500"]
print("\nlookups in gold (well_master_gold.uwi14):")
for t in tests:
    n = cur.execute("SELECT COUNT(*) FROM WELL_REF.well_ref.well_master_gold "
                    "WHERE uwi14 = ?", t).fetchone()[0]
    print(f"  uwi14 = {t!r:18} -> {n}")

# what do KS uwi14 values in gold actually look like?
print("\nsample gold uwi14 starting '15175':")
for r in cur.execute("SELECT TOP 5 uwi14, surface_latitude, surface_longitude "
                     "FROM WELL_REF.well_ref.well_master_gold "
                     "WHERE uwi14 LIKE '15175%'").fetchall():
    print(f"  {r.uwi14!r}  {r.surface_latitude}, {r.surface_longitude}")

# how many gold rows are Kansas (15) at all?
ks = cur.execute("SELECT COUNT(*) FROM WELL_REF.well_ref.well_master_gold "
                 "WHERE uwi14 LIKE '15%'").fetchone()[0]
print(f"\ngold rows with uwi14 '15…' (Kansas): {ks:,}")

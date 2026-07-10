"""diag_promote_eligible.py — run promote's EXACT eligibility query for dir_srvy_hdr
to see why eligible=0 despite 8 PROMOTED=0 rows. Tests the EXISTS dv_well join and
the _norm UWI match directly. py diag_promote_eligible.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

NORM = ("(CASE WHEN NULLIF(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/',''))),'') IS NULL THEN NULL "
        "ELSE LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/',''))) + '00000000000000', 14) END)")

cat = "file_catalog.cat_well_dir_srvy_hdr"
print("1) total PROMOTED=0 rows:",
      c.execute(f"SELECT COUNT(*) FROM {cat} m WHERE m.PROMOTED=0").fetchone()[0])

# the actual eligibility: PROMOTED=0 AND EXISTS dv_well matching normalized UWI
q = (f"SELECT COUNT(*) FROM {cat} m WHERE m.PROMOTED=0 "
     f"AND EXISTS (SELECT 1 FROM dataview.dv_well w "
     f"WHERE w.UWI = {NORM.format(col='m.UWI')})")
print("2) eligible (PROMOTED=0 AND matching dv_well):", c.execute(q).fetchone()[0])

# show each staged UWI and whether it has a dv_well match
print("\n3) per staged UWI — does dv_well have it?")
rows = c.execute(f"""SELECT m.UWI,
    {NORM.format(col='m.UWI')} AS norm_uwi,
    (SELECT COUNT(*) FROM dataview.dv_well w WHERE w.UWI = {NORM.format(col='m.UWI')}) AS in_dvwell
    FROM {cat} m WHERE m.PROMOTED=0""").fetchall()
for r in rows:
    tag = "OK" if r[2] else "NO dv_well  <-- won't promote"
    print(f"   UWI={r[0]!r}  norm={r[1]!r}  in_dv_well={r[2]}  {tag}")

# and what dv_well actually contains for comparison
print("\n4) dv_well UWIs (first 10):")
for r in c.execute("SELECT TOP 10 uwi, DATALENGTH(uwi) FROM dataview.dv_well ORDER BY uwi").fetchall():
    print(f"   uwi={r[0]!r}  bytes={r[1]}")

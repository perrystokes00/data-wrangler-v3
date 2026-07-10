"""gold_dupe_check.py — (1) find the source well master and check if it has the
same uwi14 corruption; (2) show whether the rows dedup would remove are corrupted
duplicates (safe) or real wells (loss). py gold_dupe_check.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()
f = lambda q: cur.execute(q).fetchone()
REF = "WELL_REF.well_ref.well_master_gold"

print("=== candidate source tables in WELL_REF (well/master) ===")
cands = cur.execute("""
    SELECT s.name sch, t.name tbl, SUM(p.rows) rows
    FROM WELL_REF.sys.tables t
    JOIN WELL_REF.sys.schemas s ON s.schema_id=t.schema_id
    JOIN WELL_REF.sys.partitions p ON p.object_id=t.object_id AND p.index_id IN (0,1)
    WHERE (t.name LIKE '%well%' OR t.name LIKE '%master%')
    GROUP BY s.name, t.name ORDER BY rows DESC""").fetchall()
for r in cands:
    print(f"  WELL_REF.{r.sch}.{r.tbl}: {r.rows:,}")

# check each candidate that has a uwi14 + api-like column for the same corruption
print("\n=== uwi14-vs-api corruption per candidate ===")
for r in cands:
    full = f"WELL_REF.{r.sch}.{r.tbl}"
    colrows = cur.execute(
        "SELECT name FROM WELL_REF.sys.columns WHERE object_id=OBJECT_ID(?)", full).fetchall()
    cols = {x[0].lower() for x in colrows}
    if "uwi14" not in cols:
        continue
    apicol = next((x for x in ("api_10", "api10", "api", "api_number") if x in cols), None)
    if not apicol:
        print(f"  {full}: has uwi14 but no api column"); continue
    tot = f(f"SELECT COUNT(*) FROM {full}")[0]
    bad = f(f"SELECT COUNT(*) FROM {full} WHERE {apicol} IS NOT NULL "
            f"AND LEN(RTRIM({apicol}))=10 AND LEFT(uwi14,10)<>RTRIM({apicol})")[0]
    print(f"  {full}: {tot:,} rows, uwi14 corrupted: {bad:,} ({100.0*bad/max(1,tot):.1f}%)")

print("\n=== what dedup would REMOVE from gold (corrupted vs real?) ===")
row = f(f"""
    WITH ranked AS (
      SELECT uwi14, api_10, surface_latitude, quality_score,
        ROW_NUMBER() OVER (PARTITION BY api_10 ORDER BY
          CASE WHEN LEFT(uwi14,10)=RTRIM(api_10) THEN 0 ELSE 1 END,
          CASE WHEN surface_latitude IS NOT NULL THEN 0 ELSE 1 END,
          ISNULL(quality_score,0) DESC) rn
      FROM {REF} WHERE api_10 IS NOT NULL)
    SELECT
      SUM(CASE WHEN rn>1 THEN 1 ELSE 0 END),
      SUM(CASE WHEN rn>1 AND LEFT(uwi14,10)<>RTRIM(api_10) THEN 1 ELSE 0 END),
      SUM(CASE WHEN rn>1 AND surface_latitude IS NULL THEN 1 ELSE 0 END)
    FROM ranked""")
rem, rem_corrupt, rem_nocoord = row[0] or 0, row[1] or 0, row[2] or 0
print(f"rows dedup removes            : {rem:,}")
print(f"  of those, corrupted uwi14   : {rem_corrupt:,}  ({100.0*rem_corrupt/max(1,rem):.1f}%)")
print(f"  of those, had NO coords     : {rem_nocoord:,}")
print(f"  -> real wells lost (valid+coords): {rem - rem_corrupt - (rem_nocoord):,} (rough upper bound overlap)")
print("\n=> if 'corrupted' ~= removed, dedup only drops the corruption, not real wells.")

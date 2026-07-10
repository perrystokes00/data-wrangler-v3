"""diag_h3_join.py — the H3 UPDATE joins char(14) dv_well.uwi = nvarchar(80) staging.uwi
and matches 0. Rebuild the compute+stage manually, then test WHY the join fails and what a
fixed (normalized) join would match. py diag_h3_join.py"""
import pyodbc, os, csv, tempfile, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))
OUT=r"C:\Bulk\reports\h3_join.txt"
os.makedirs(os.path.dirname(OUT),exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
SERVER,DB=r"localhost\SQLEXPRESS","DataView_Demo"
c=pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SERVER};DATABASE={DB};Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q):
    try: return c.execute(q).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:60]}"

# rebuild a tiny staging table with 5 known uwis and test the join both ways
log("=== build test staging (nvarchar) with 5 real uwis ===")
c.execute("IF OBJECT_ID('stg.h3_jointest') IS NOT NULL DROP TABLE stg.h3_jointest")
c.execute("IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg')")
c.execute("CREATE TABLE stg.h3_jointest (uwi NVARCHAR(80), h3_r5 NVARCHAR(15))")
uwis = [r[0] for r in c.execute("SELECT TOP 5 uwi FROM dataview.dv_well WHERE surface_latitude IS NOT NULL").fetchall()]
for u in uwis:
    c.execute("INSERT INTO stg.h3_jointest VALUES (?, ?)", u, "TESTCELL")
log(f"  inserted {len(uwis)} rows: {uwis}")

log("\n=== join tests ===")
raw = one("SELECT COUNT(*) FROM dataview.dv_well t JOIN stg.h3_jointest s ON t.uwi = s.uwi")
log(f"  raw join (char = nvarchar):           {raw}")
cast = one("SELECT COUNT(*) FROM dataview.dv_well t JOIN stg.h3_jointest s ON t.uwi = CAST(s.uwi AS char(14))")
log(f"  CAST(s.uwi AS char(14)):              {cast}")
trim = one("SELECT COUNT(*) FROM dataview.dv_well t JOIN stg.h3_jointest s ON RTRIM(t.uwi) = RTRIM(s.uwi)")
log(f"  RTRIM both sides:                     {trim}")
coll = one("SELECT COUNT(*) FROM dataview.dv_well t JOIN stg.h3_jointest s ON t.uwi = s.uwi COLLATE database_default")
log(f"  COLLATE database_default:             {coll}")

log("\n=== is there a hidden char? compare byte-by-byte ===")
try:
    r=c.execute("SELECT TOP 1 CONVERT(varbinary(40), t.uwi), CONVERT(varbinary(40), s.uwi) FROM dataview.dv_well t, stg.h3_jointest s WHERE RTRIM(t.uwi)=RTRIM(s.uwi)").fetchone()
    if r: log(f"  dv_well uwi bytes:  {r[0].hex() if r[0] else None}"); log(f"  staging uwi bytes:  {r[1].hex() if r[1] else None}")
except Exception as e: log("  "+str(e)[:80])

c.execute("DROP TABLE stg.h3_jointest")
log("\n=== VERDICT ===")
log("  Whichever join test returns 5 is the fix. Likely CAST(s.uwi AS char(14)) or")
log("  COLLATE — the char(14) vs nvarchar(80) mismatch is the same bug as the enrich join.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

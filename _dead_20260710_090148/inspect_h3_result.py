"""inspect_h3_result.py — compute wrote 655 but BCP staged 0. Inspect the result CSV that
run_h3 left behind, and try the BCP load manually capturing the REAL error (BCP writes
per-row errors that exit-code 0 hides). py inspect_h3_result.py"""
import os, tempfile, subprocess
tmp=tempfile.gettempdir()
result=os.path.join(tmp,"h3_result.csv")
print("result CSV:", result, "exists:", os.path.exists(result))
if not os.path.exists(result):
    print("NOT FOUND — run_h3 may have deleted it. Re-run run_h3 (it now keeps it on 0-stage)."); raise SystemExit
sz=os.path.getsize(result); print("size:", sz, "bytes")
with open(result,"rb") as f: raw=f.read()
print("first 200 bytes (raw):", raw[:200])
with open(result,encoding="utf-8",errors="replace") as f: lines=f.readlines()
print("line count:", len(lines))
for l in lines[:3]: print("  line:", repr(l))
# field counts
import collections
fc=collections.Counter(l.count("|") for l in lines)
print("pipe-count distribution (want 4 per line):", dict(fc))
# check for BOM
print("has UTF-8 BOM:", raw[:3]==b'\xef\xbb\xbf')

# now try a manual BCP load into a fresh table capturing stderr + error file
SERVER,DB=r"localhost\SQLEXPRESS","DataView_Demo"
errf=os.path.join(tmp,"h3_bcp_err.txt")
import pyodbc
c=pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SERVER};DATABASE={DB};Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
c.execute("IF OBJECT_ID('stg.h3insp') IS NOT NULL DROP TABLE stg.h3insp")
c.execute("IF SCHEMA_ID('stg') IS NULL EXEC('CREATE SCHEMA stg')")
c.execute("CREATE TABLE stg.h3insp (uwi NVARCHAR(80), h3_r4 NVARCHAR(15), h3_r5 NVARCHAR(15), h3_r6 NVARCHAR(15), h3_r7 NVARCHAR(15))")
print("\n=== manual BCP load with error file ===")
r=subprocess.run(["bcp","stg.h3insp","in",result,"-c","-t|","-C","65001","-T",f"-S{SERVER}",f"-d{DB}","-q","-e",errf],
                 capture_output=True,text=True)
print("rc:", r.returncode)
print("stdout tail:", (r.stdout or "")[-300:])
print("stderr:", (r.stderr or "")[:300])
cnt=c.execute("SELECT COUNT(*) FROM stg.h3insp").fetchone()[0]
print("loaded into staging:", cnt)
if os.path.exists(errf):
    esz=os.path.getsize(errf)
    print(f"BCP error file ({esz} bytes):")
    if esz: print(open(errf,encoding="utf-8",errors="replace").read()[:500])
c.execute("IF OBJECT_ID('stg.h3insp') IS NOT NULL DROP TABLE stg.h3insp")
print("\n=== VERDICT ===")
print("If loaded>0 here but run_h3 stages 0: run_h3's load differs (no -e, or table def).")
print("If loaded=0 + error file shows rows: the CSV format mismatches the table columns.")

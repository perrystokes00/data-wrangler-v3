"""test_h3_load_widths.py — CSV is clean (15-char h3 cells, pipe-delim, no BOM) yet BCP
says Column 5 truncation. Test loading the KEPT result CSV into tables of varying widths to
find what BCP actually needs. py test_h3_load_widths.py"""
import os, tempfile, subprocess, pyodbc
tmp=tempfile.gettempdir(); result=os.path.join(tmp,"h3_result.csv")
SERVER,DB=r"localhost\SQLEXPRESS","DataView_Demo"
if not os.path.exists(result): raise SystemExit("result CSV gone — re-run run_h3 first")
c=pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SERVER};DATABASE={DB};Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

# max field length actually in the file
maxlens=[0,0,0,0,0]
with open(result,encoding="utf-8",errors="replace") as f:
    for line in f:
        parts=line.rstrip("\r\n").split("|")
        for i in range(min(5,len(parts))):
            maxlens[i]=max(maxlens[i],len(parts[i]))
print("max field lengths in CSV:", maxlens, "(uwi,h3_r4,h3_r5,h3_r6,h3_r7)")

for width in (15, 20, 50):
    c.execute("IF OBJECT_ID('stg.h3w') IS NOT NULL DROP TABLE stg.h3w")
    c.execute(f"CREATE TABLE stg.h3w (uwi NVARCHAR(80), a NVARCHAR({width}), b NVARCHAR({width}), d NVARCHAR({width}), e NVARCHAR({width}))")
    errf=os.path.join(tmp,f"err{width}.txt")
    r=subprocess.run(["bcp","stg.h3w","in",result,"-c","-t|","-C","65001","-T",f"-S{SERVER}",f"-d{DB}","-q","-e",errf],
                     capture_output=True,text=True)
    cnt=c.execute("SELECT COUNT(*) FROM stg.h3w").fetchone()[0]
    err=""
    if os.path.exists(errf) and os.path.getsize(errf):
        err=open(errf,encoding="utf-8",errors="replace").read()[:120].replace("\n"," ")
    print(f"  NVARCHAR({width}): loaded {cnt}  {'ERR: '+err if err else 'OK'}")
    c.execute("IF OBJECT_ID('stg.h3w') IS NOT NULL DROP TABLE stg.h3w")

print("\n=== also try WITHOUT -C 65001 (default codepage) at width 20 ===")
c.execute("CREATE TABLE stg.h3w (uwi NVARCHAR(80), a NVARCHAR(20), b NVARCHAR(20), d NVARCHAR(20), e NVARCHAR(20))")
errf=os.path.join(tmp,"err_noC.txt")
r=subprocess.run(["bcp","stg.h3w","in",result,"-c","-t|","-T",f"-S{SERVER}",f"-d{DB}","-q","-e",errf],capture_output=True,text=True)
cnt=c.execute("SELECT COUNT(*) FROM stg.h3w").fetchone()[0]
err=open(errf,encoding="utf-8",errors="replace").read()[:120].replace("\n"," ") if os.path.exists(errf) and os.path.getsize(errf) else ""
print(f"  no -C, NVARCHAR(20): loaded {cnt}  {'ERR: '+err if err else 'OK'}")
c.execute("IF OBJECT_ID('stg.h3w') IS NOT NULL DROP TABLE stg.h3w")
print("\n=== VERDICT ===")
print("Whichever config loads 655 is the fix for run_h3's step 3.")

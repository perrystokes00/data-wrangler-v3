"""test_h3_rowterm.py — every delimiter fails identically; column 5 absorbs everything ->
ROW terminator is the problem, not field. File uses \\n (0x0a). Test explicit -r values.
py test_h3_rowterm.py"""
import os, tempfile, subprocess, pyodbc
tmp=tempfile.gettempdir(); result=os.path.join(tmp,"h3_result.csv")
SERVER,DB=r"localhost\SQLEXPRESS","DataView_Demo"
if not os.path.exists(result): raise SystemExit("re-run run_h3 first")
c=pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SERVER};DATABASE={DB};Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

# confirm the row-terminator bytes in the file
with open(result,"rb") as f: raw=f.read(200)
print("bytes around first newline:", raw[74:82].hex(" "), "->", repr(raw[74:82]))
print("file uses \\r\\n:", b'\r\n' in raw, "  uses bare \\n:", b'\n' in raw and b'\r\n' not in raw[:200])

def mk():
    c.execute("IF OBJECT_ID('stg.h3r') IS NOT NULL DROP TABLE stg.h3r")
    c.execute("CREATE TABLE stg.h3r (uwi NVARCHAR(80), a NVARCHAR(50), b NVARCHAR(50), d NVARCHAR(50), e NVARCHAR(50))")
def load(extra,label):
    mk(); errf=os.path.join(tmp,"rt.txt")
    if os.path.exists(errf): os.remove(errf)
    r=subprocess.run(["bcp","stg.h3r","in",result,"-c","-t|","-T",f"-S{SERVER}",f"-d{DB}","-q","-e",errf]+extra,capture_output=True,text=True)
    cnt=c.execute("SELECT COUNT(*) FROM stg.h3r").fetchone()[0]
    err=open(errf,encoding="utf-8",errors="replace").read()[:70].replace("\n"," ") if os.path.exists(errf) and os.path.getsize(errf) else ""
    print(f"  {label}: loaded {cnt}  {('ERR '+err) if err else 'OK'}")
    c.execute("IF OBJECT_ID('stg.h3r') IS NOT NULL DROP TABLE stg.h3r")

print("\n=== row terminator tests ===")
load(["-r","\\n"], r"-r \n")
load(["-r","0x0a"], "-r 0x0a")
load(["-r","\\r\\n"], r"-r \r\n")
load([], "no -r (bcp default)")

# also: maybe the FIRST field (uwi) is the problem — rewrite with a rebuilt clean file
print("\n=== rewrite file fresh with explicit \\r\\n and load ===")
clean=os.path.join(tmp,"h3_clean.csv")
with open(result,encoding="utf-8",errors="replace") as fin, open(clean,"w",encoding="utf-8",newline="\r\n") as fout:
    for line in fin:
        fout.write(line.rstrip("\r\n")+"\n")
mk(); errf=os.path.join(tmp,"rc.txt")
r=subprocess.run(["bcp","stg.h3r","in",clean,"-c","-t|","-T",f"-S{SERVER}",f"-d{DB}","-q","-e",errf],capture_output=True,text=True)
cnt=c.execute("SELECT COUNT(*) FROM stg.h3r").fetchone()[0]
print(f"  rewritten \\r\\n file: loaded {cnt}")
c.execute("IF OBJECT_ID('stg.h3r') IS NOT NULL DROP TABLE stg.h3r")
print("\nWhichever loads 655 is the fix.")

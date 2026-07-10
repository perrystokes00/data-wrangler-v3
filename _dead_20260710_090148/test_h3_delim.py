"""test_h3_delim.py — width isn't the issue (50 still truncates). BCP isn't splitting on
the pipe. Test terminator variations + a tab-delimited rewrite to find what actually works.
py test_h3_delim.py"""
import os, tempfile, subprocess, pyodbc, csv
tmp=tempfile.gettempdir(); result=os.path.join(tmp,"h3_result.csv")
SERVER,DB=r"localhost\SQLEXPRESS","DataView_Demo"
if not os.path.exists(result): raise SystemExit("re-run run_h3 first (keeps CSV on 0-stage)")
c=pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SERVER};DATABASE={DB};Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

def mktable():
    c.execute("IF OBJECT_ID('stg.h3d') IS NOT NULL DROP TABLE stg.h3d")
    c.execute("CREATE TABLE stg.h3d (uwi NVARCHAR(80), a NVARCHAR(50), b NVARCHAR(50), d NVARCHAR(50), e NVARCHAR(50))")
def load(args, label):
    mktable()
    errf=os.path.join(tmp,"td.txt")
    if os.path.exists(errf): os.remove(errf)
    r=subprocess.run(["bcp","stg.h3d","in"]+args+["-e",errf],capture_output=True,text=True)
    cnt=c.execute("SELECT COUNT(*) FROM stg.h3d").fetchone()[0]
    err=open(errf,encoding="utf-8",errors="replace").read()[:90].replace("\n"," ") if os.path.exists(errf) and os.path.getsize(errf) else ""
    print(f"  {label}: loaded {cnt}  {('ERR '+err) if err else 'OK'}")
    c.execute("IF OBJECT_ID('stg.h3d') IS NOT NULL DROP TABLE stg.h3d")
    return cnt

base=[result,"-c","-T",f"-S{SERVER}",f"-d{DB}","-q"]
print("=== terminator variations (the current file, pipe-delimited) ===")
load(base+["-t|","-C","65001"], "-t|  -C65001   (current run_h3)")
load(base+["-t","|","-C","65001"], "-t | (separate arg) -C65001")
load(base+["-t|"], "-t|  (no -C)")
load(base+["-t","|"], "-t | (separate) no -C")

# rewrite the file TAB-delimited and try that
print("\n=== rewrite as TAB-delimited, load with -t\\t ===")
tabfile=os.path.join(tmp,"h3_tab.csv")
with open(result,encoding="utf-8",errors="replace") as fin, open(tabfile,"w",encoding="utf-8",newline="") as fout:
    for line in fin:
        fout.write(line.rstrip("\r\n").replace("|","\t")+"\n")
mktable()
errf=os.path.join(tmp,"tt.txt")
r=subprocess.run(["bcp","stg.h3d","in",tabfile,"-c","-T",f"-S{SERVER}",f"-d{DB}","-q","-e",errf],capture_output=True,text=True)
cnt=c.execute("SELECT COUNT(*) FROM stg.h3d").fetchone()[0]  # default terminator is \t
err=open(errf,encoding="utf-8",errors="replace").read()[:90].replace("\n"," ") if os.path.exists(errf) and os.path.getsize(errf) else ""
print(f"  tab-delim, default -t: loaded {cnt}  {('ERR '+err) if err else 'OK'}")
c.execute("IF OBJECT_ID('stg.h3d') IS NOT NULL DROP TABLE stg.h3d")
print("\n=== VERDICT ===")
print("Whichever loads 655 is the fix. If '-t | (separate arg)' works but '-t|' doesn't,")
print("the glued -t| is the bug. If only TAB works, pipe is being eaten by the shell/bcp.")

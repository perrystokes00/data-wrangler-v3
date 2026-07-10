"""diag_h3_bcp.py — join works (5/5) yet the real run updated 0. So staging was empty or
BCP mangled it. Reproduce steps 2-3 manually and inspect the CSV + staging contents.
py diag_h3_bcp.py"""
import pyodbc, os, csv, tempfile, subprocess, sys
sys.path.insert(0, os.path.join(r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3","modules"))
OUT=r"C:\Bulk\reports\h3_bcp.txt"
os.makedirs(os.path.dirname(OUT),exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
SERVER,DB=r"localhost\SQLEXPRESS","DataView_Demo"
conn=pyodbc.connect(f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={SERVER};DATABASE={DB};Trusted_Connection=yes;Encrypt=no",autocommit=True)
c=conn.cursor()

# step 1: queryout coords (mirror run_h3)
tmp=tempfile.gettempdir()
coords=os.path.join(tmp,"h3d_coords.csv"); result=os.path.join(tmp,"h3d_result.csv")
sel="SELECT uwi, CAST(surface_latitude AS FLOAT), CAST(surface_longitude AS FLOAT) FROM dataview.dv_well WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL"
log("[1] bcp queryout coords…")
r=subprocess.run(["bcp"," ".join(sel.split()),"queryout",coords,"-c","-t|","-C","65001","-T",f"-S{SERVER}",f"-d{DB}","-q"],capture_output=True,text=True)
log("   bcp rc="+str(r.returncode)+" out="+(r.stdout or "")[-80:].replace("\n"," "))
log("   coords.csv exists="+str(os.path.exists(coords))+" size="+str(os.path.getsize(coords) if os.path.exists(coords) else 0))
if os.path.exists(coords):
    with open(coords,encoding="utf-8",errors="replace") as f:
        head=[next(f,"") for _ in range(3)]
    log("   first coords lines: "+repr(head))

# step 2: compute h3 (mirror run_h3)
import h3_grids
to_cell,_=h3_grids._bind_h3()
H3COLS=list(h3_grids.H3_COLUMNS)
log("[2] compute H3 -> result.csv…")
n=0
with open(coords,encoding="utf-8",errors="replace") as fin, open(result,"w",encoding="utf-8",newline="") as fout:
    w=csv.writer(fout,delimiter="|")
    for line in fin:
        p=line.rstrip("\r\n").split("|")
        if len(p)<3: continue
        try: row=h3_grids.compute_h3_row(float(p[1]),float(p[2]),to_cell=to_cell)
        except Exception: continue
        w.writerow([p[0]]+[row.get(cc,"") or "" for cc in H3COLS]); n+=1
log(f"   wrote {n} result rows")
if os.path.exists(result):
    with open(result,encoding="utf-8",errors="replace") as f:
        head=[next(f,"") for _ in range(3)]
    log("   first result lines: "+repr(head))

# step 3: load staging + count + test join
log("[3] load staging + count…")
c.execute("IF OBJECT_ID('stg.h3dbg') IS NOT NULL DROP TABLE stg.h3dbg")
coldefs=", ".join(["[uwi] NVARCHAR(80)"]+[f"[{cc}] NVARCHAR(15)" for cc in H3COLS])
c.execute(f"CREATE TABLE stg.h3dbg ({coldefs})")
rb=subprocess.run(["bcp","stg.h3dbg","in",result,"-c","-t|","-C","65001","-T",f"-S{SERVER}",f"-d{DB}","-q"],capture_output=True,text=True)
log("   bcp load rc="+str(rb.returncode)+" out="+(rb.stdout or "")[-100:].replace("\n"," ")+" err="+(rb.stderr or "")[:100])
cnt=c.execute("SELECT COUNT(*) FROM stg.h3dbg").fetchone()[0]
log(f"   staging row count: {cnt}")
if cnt:
    s=c.execute("SELECT TOP 3 uwi, h3_r5 FROM stg.h3dbg").fetchall()
    log("   staging sample: "+str([tuple(x) for x in s]))
    j=c.execute("SELECT COUNT(*) FROM dataview.dv_well t JOIN stg.h3dbg s ON t.uwi=s.uwi").fetchone()[0]
    log(f"   JOIN to dv_well matches: {j}")
c.execute("IF OBJECT_ID('stg.h3dbg') IS NOT NULL DROP TABLE stg.h3dbg")
log("\n=== VERDICT ===")
log("  If staging count=0: BCP load failed (check err) or result.csv empty (compute issue).")
log("  If staging>0 but JOIN=0: the loaded uwi differs (encoding). If JOIN>0: the real")
log("  run_h3 should have worked — maybe it errored silently; re-run it now.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

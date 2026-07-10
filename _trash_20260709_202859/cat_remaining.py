"""cat_remaining.py — what's left in the cat_* mirror tables after promote: total vs
held (PROMOTED=0) vs promoted (PROMOTED=1), and the distinct held UWIs. py cat_remaining.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\cat_remaining.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

cat_tabs = [r[0] for r in c.execute("""SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME LIKE 'cat[_]%' ORDER BY TABLE_NAME""").fetchall()]

log(f"{'table':30} {'total':>7} {'held':>7} {'promoted':>9}")
log("-"*60)
grand_t=grand_h=grand_p=0
held_tables=[]
for t in cat_tabs:
    cols=[r[0].upper() for r in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME=?", t).fetchall()]
    tot=c.execute(f"SELECT COUNT(*) FROM file_catalog.{t}").fetchone()[0]
    if "PROMOTED" in cols:
        held=c.execute(f"SELECT COUNT(*) FROM file_catalog.{t} WHERE PROMOTED=0").fetchone()[0]
        prom=c.execute(f"SELECT COUNT(*) FROM file_catalog.{t} WHERE PROMOTED=1").fetchone()[0]
    else:
        held=prom="-"
    log(f"{t:30} {tot:>7} {str(held):>7} {str(prom):>9}")
    grand_t+=tot
    if isinstance(held,int):
        grand_h+=held; grand_p+=prom
        if held>0: held_tables.append((t,held))
log("-"*60)
log(f"{'TOTAL':30} {grand_t:>7} {grand_h:>7} {grand_p:>9}")

log("\n=== tables still holding rows (PROMOTED=0) + their UWIs ===")
if not held_tables:
    log("  none — all cat_* rows promoted.")
for t,h in held_tables:
    col = "UWI" if "UWI" in [x.upper() for x in [r[0] for r in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME=?", t).fetchall()]] else None
    try:
        us=[str(r[0]).strip() for r in c.execute(f"SELECT DISTINCT UWI FROM file_catalog.{t} WHERE PROMOTED=0").fetchall()]
        log(f"  {t}: {h} held  UWIs={us}")
    except Exception:
        log(f"  {t}: {h} held")

log("\n=== why held? for each held UWI, is it in dv_well? ===")
NORM="LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{c}),'-',''),' ',''),'/','')))+'00000000000000',14)"
seen=set()
for t,_ in held_tables:
    try:
        for r in c.execute(f"SELECT DISTINCT {NORM.format(c='UWI')} FROM file_catalog.{t} WHERE PROMOTED=0").fetchall():
            u=r[0]
            if u and u not in seen:
                seen.add(u)
                indv=c.execute("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=?", u).fetchone()[0]
                coords=c.execute("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=? AND surface_latitude IS NOT NULL", u).fetchone()[0]
                log(f"  {u}: in_dv_well={indv} with_coords={coords}")
    except Exception:
        pass
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

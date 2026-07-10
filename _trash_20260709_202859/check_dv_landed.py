"""check_dv_landed.py — the RIGHT check: did the PDF data promote to dv_* under MAYBERRY
(15007243240000)? cat_* being empty is EXPECTED (promote drains it). py check_dv_landed.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\dv_landed.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

U = "15007243240000"
log(f"=== dv_* data for MAYBERRY ({U}) — did the PDFs promote here? ===")
tables = [
    ("dv_well","well header"),
    ("dv_well_dir_srvy_hdr","survey header"),
    ("dv_well_dir_srvy_sta","survey stations"),
    ("dv_well_formation_top","formation tops"),
    ("dv_well_dst","DST / well test"),
    ("dv_well_completion","completions"),
    ("dv_prod_volume","production"),
    ("dv_well_petro_interp","petrophysical"),
    ("dv_well_core","core"),
]
for t,label in tables:
    n = one(f"SELECT COUNT(*) FROM dataview.{t} WHERE uwi=?", U)
    log(f"  {t:26} ({label}): {n}")

log("\n=== survey stations: are md/incl/azim POPULATED? (the key-map fix on live data) ===")
tot = one(f"SELECT COUNT(*) FROM dataview.dv_well_dir_srvy_sta WHERE uwi='{U}'")
filled = one(f"SELECT COUNT(*) FROM dataview.dv_well_dir_srvy_sta WHERE uwi='{U}' AND md IS NOT NULL AND incl IS NOT NULL")
log(f"  survey stations: {tot} total, {filled} with md/incl populated")
if isinstance(tot,int) and tot>0:
    for r in c.execute(f"SELECT TOP 5 md,incl,azim,tvd FROM dataview.dv_well_dir_srvy_sta WHERE uwi='{U}' ORDER BY md").fetchall():
        log(f"    md={r[0]} incl={r[1]} azim={r[2]} tvd={r[3]}")

log("\n=== was the recent promote successful? check PROMOTED_AT on the pdfs ===")
for r in c.execute("SELECT FILE_NAME, PROMOTED_AT, CATALOG_READINESS FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.pdf' ORDER BY FILE_NAME").fetchall():
    log(f"  {r[0]}: promoted_at={r[1]} ready={r[2]}")

log("\n=== VERDICT ===")
log("  If dv_* tables show rows for MAYBERRY: THE PDF DATA PROMOTED. cat_* being empty")
log("  is correct — promote moved the rows out. Extraction -> capture -> promote WORKS.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

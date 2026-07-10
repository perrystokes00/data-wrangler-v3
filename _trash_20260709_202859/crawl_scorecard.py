"""crawl_scorecard.py — file-by-file report for the current crawl: was each file
EXTRACTED, CAPTURED, and PROMOTED? Scoped to a folder (default: what's in the catalog).
Captured/promoted are determined by where the data actually is (cat_* = staged, dv_* =
promoted), since promote drains cat_*.
  py crawl_scorecard.py                          # all files in catalog
  py crawl_scorecard.py --path sample_pdfs       # only files whose FILE_PATH contains this
"""
import pyodbc, os, sys
OUT = r"C:\Bulk\reports\crawl_scorecard.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

path_filter = None
if "--path" in sys.argv:
    path_filter = sys.argv[sys.argv.index("--path")+1]

NORM = "LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{c}),'-',''),' ',''),'/','')))+'00000000000000',14)"

# the detail tables to check, cat_ (staged) and dv_ (promoted)
DETAIL = [
    ("cat_well","dv_well","header"),
    ("cat_well_dir_srvy_sta","dv_well_dir_srvy_sta","survey sta"),
    ("cat_well_formation_top","dv_well_formation_top","tops"),
    ("cat_well_dst","dv_well_dst","well test"),
    ("cat_well_completion","dv_well_completion","completions"),
    ("cat_prod_volume","dv_prod_volume","production"),
    ("cat_well_petro_interp","dv_well_petro_interp","petro"),
    ("cat_well_core","dv_well_core","core"),
    ("cat_well_log","dv_well_log","log"),
    ("cat_well_log_curve","dv_well_log_curve","curves"),
]

where = "1=1"
params = []
if path_filter:
    where = "g.FILE_PATH LIKE ?"
    params = ['%'+path_filter+'%']

files = c.execute(f"""SELECT g.FILE_NAME, g.INVENTORY_ID, g.MATCHED_UWI,
    g.HEADER_EXTRACTED, g.CATALOG_READINESS, wh.REPORT_TYPE
    FROM file_catalog.GLOBAL_FILE_CATALOG g
    LEFT JOIN file_catalog.FILE_WELL_HEADER wh ON wh.INVENTORY_ID=g.INVENTORY_ID
    WHERE {where} ORDER BY g.FILE_NAME""", *params).fetchall()

log(f"{'FILE':<44} {'EXTRACT':<8} {'CAPTURE':<9} {'PROMOTE':<9} TYPE / DETAIL")
log("-"*110)
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception: return 0

n_ext=n_cap=n_prom=0
for f in files:
    fn, inv, muwi, hx, ready, rtype = f
    extracted = "Y" if hx == "Y" else ("ERR" if hx=="E" else ("skip" if hx=="S" else "N"))
    # captured: any cat_* rows for this INVENTORY_ID (staged, not yet promoted)
    cap_rows = 0; cap_detail = []
    for cat,dv,label in DETAIL:
        n = one(f"SELECT COUNT(*) FROM file_catalog.{cat} WHERE INVENTORY_ID=?", inv)
        if n: cap_rows += n; cap_detail.append(f"{label}:{n}")
    # promoted: dv_* rows for this INVENTORY_ID (or by UWI for header)
    prom_rows = 0; prom_detail = []
    for cat,dv,label in DETAIL:
        # dv_ tables carry INVENTORY_ID for per-file lineage
        n = one(f"SELECT COUNT(*) FROM dataview.{dv} WHERE INVENTORY_ID=?", inv)
        if n: prom_rows += n; prom_detail.append(f"{label}:{n}")
    captured = "Y" if cap_rows or prom_rows else "N"   # if promoted, it WAS captured
    promoted = "Y" if prom_rows else "N"
    if extracted=="Y": n_ext+=1
    if captured=="Y": n_cap+=1
    if promoted=="Y": n_prom+=1
    detail = ("promoted[" + " ".join(prom_detail) + "]") if prom_detail else \
             ("staged[" + " ".join(cap_detail) + "]" if cap_detail else "no detail rows")
    log(f"{fn[:44]:<44} {extracted:<8} {captured:<9} {promoted:<9} {rtype or '?'} · {detail}")

log("-"*110)
log(f"TOTAL: {len(files)} files · extracted {n_ext} · captured {n_cap} · promoted {n_prom}")
log("\n(captured=Y means data reached cat_* or dv_*; promoted=Y means it reached dv_*.")
log(" A promoted file shows captured=Y even though cat_* is now drained — that's correct.)")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

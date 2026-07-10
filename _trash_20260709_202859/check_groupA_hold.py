"""check_groupA_hold.py — well IS in dv_well but its doc data (tops/prod/completion) is
held. Why? py check_groupA_hold.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\groupA.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L = []
def log(*a):
    s = " ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
def one(q, *a):
    try: return c.execute(q, *a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

NORM = "LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/','')))+'00000000000000',14)"

log("=== held formation_top rows: UWI + is that well in dv_well? ===")
q = ("SELECT DISTINCT " + NORM.format(col='UWI') + " AS nuwi, "
     "(SELECT COUNT(*) FROM dataview.dv_well d WHERE d.uwi=" + NORM.format(col='cat_well_formation_top.UWI') + ") AS in_dv "
     "FROM file_catalog.cat_well_formation_top WHERE PROMOTED=0")
try:
    for r in c.execute(q).fetchall():
        log(f"  top uwi={r[0]}  in_dv_well={r[1]}")
except Exception as e:
    log("  err:", str(e)[:80])

log("\n=== ANADARKO 1H well (42317123450000): exact dv_well state ===")
u = "42317123450000"
log("  dv_well exact '=' match: " + str(one("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=?", u)))
stored = one("SELECT TOP 1 '[' + CONVERT(varchar(40), uwi) + ']' FROM dataview.dv_well WHERE uwi LIKE '42317123450000%'")
log("  dv_well stored value:    " + str(stored))
log("  dv_well LIKE match:      " + str(one("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi LIKE '42317123450000%'")))

log("\n=== the held cat_well_formation_top UWI stored value (padding/space check) ===")
sv = one("SELECT TOP 1 '[' + CONVERT(varchar(40), UWI) + ']' FROM file_catalog.cat_well_formation_top WHERE PROMOTED=0")
log("  cat top UWI stored: " + str(sv))

log("\n=== held counts by table ===")
for t in ("cat_well_formation_top","cat_prod_volume","cat_well_completion","cat_well_dir_srvy_hdr"):
    log(f"  {t}: held=" + str(one(f"SELECT COUNT(*) FROM file_catalog.{t} WHERE PROMOTED=0")))

log("\n=== KEY TEST: do the held UWIs match dv_well when both normalized? ===")
q2 = ("SELECT COUNT(DISTINCT t.n) FROM "
      "(SELECT DISTINCT " + NORM.format(col='UWI') + " AS n FROM file_catalog.cat_well_formation_top WHERE PROMOTED=0) t "
      "JOIN dataview.dv_well d ON d.uwi = t.n")
log("  held-top UWIs that DO match a dv_well: " + str(one(q2)))
q3 = ("SELECT COUNT(DISTINCT " + NORM.format(col='UWI') + ") FROM file_catalog.cat_well_formation_top WHERE PROMOTED=0")
log("  total distinct held-top UWIs: " + str(one(q3)))
open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("\n>>> written to", OUT, "— upload it")

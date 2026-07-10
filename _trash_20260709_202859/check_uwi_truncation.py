"""check_uwi_truncation.py — the held cat_well_formation_top UWI is stored as 10 digits
(4246120987) not 14. Is truncation breaking the dv_well match, or are these wells just
absent? Compare the raw stored UWI, its padded form, and dv_well. py check_uwi_truncation.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\uwi_trunc.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== RAW stored UWI in each held detail table (length check) ===")
for t in ("cat_well_formation_top","cat_prod_volume","cat_well_completion","cat_well_dir_srvy_hdr"):
    try:
        rows = c.execute(f"SELECT DISTINCT '['+CONVERT(varchar(40),UWI)+']' AS u, LEN(CONVERT(varchar(40),UWI)) AS ln FROM file_catalog.{t} WHERE PROMOTED=0").fetchall()
        log(f"  {t}:")
        for r in rows[:8]:
            log(f"      {r[0]}  len={r[1]}")
    except Exception as e:
        log(f"  {t}: err {str(e)[:50]}")

log("\n=== the ANADARKO 1H family: what UWIs are actually in dv_well? ===")
for pref in ("42317","42461","42135","35101","42005"):
    rows = c.execute(f"SELECT uwi FROM dataview.dv_well WHERE uwi LIKE '{pref}%'").fetchall()
    vals = [r[0].strip() if r[0] else r[0] for r in rows][:5]
    log(f"  dv_well uwi LIKE {pref}%: {vals}")

log("\n=== does the well for a held top exist under the FULL 14-digit uwi? ===")
# held top shows 4246120987 (10 digits). The file MATCHED_UWI was 42461209870000.
# Is 42461209870000 in dv_well?
for u in ("42461209870000","42461880020000","42317990010000","42135222220000"):
    log(f"  dv_well has {u}: {one('SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=?', u)}")

log("\n=== VERDICT ===")
log("  If the detail UWI is stored as 10 digits but the well is in dv_well under 14")
log("  digits, the padding (10->14 by appending 0000) must match the well's real 14.")
log("  4246120987 -> 42461209870000. If THAT is in dv_well, the join should work and")
log("  the hold is a promote-logic gate. If NOT in dv_well, the well truly is absent")
log("  (these synthetic wells need the header CSV loaded).")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

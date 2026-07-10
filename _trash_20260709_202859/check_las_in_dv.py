"""check_las_in_dv.py — are the 20 LAS wells actually in dv_well? Check by the real UWIs
(from the LAS filenames) directly, not via a SOURCE join. Resolves the contradiction:
146 curves promoted but the well-join said 0. py check_las_in_dv.py"""
import pyodbc, os, re
OUT = r"C:\Bulk\reports\las_in_dv.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q, *a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:35]}"

# get the LAS filenames -> derive UWI -> check dv_well + dv_well_log_curve
def uwi_from_name(base):
    stem = os.path.splitext(base)[0]
    if re.fullmatch(r"[\d_\-]+", stem):
        d = re.sub(r"\D","",stem)
        if 10<=len(d)<=14: return (d[:14] if len(d)>=14 else d.ljust(14,"0"))
    m = re.search(r"(\d{2}_\d{3}_\d{5}_\d{4})", base)
    if m:
        d = re.sub(r"\D","",m.group(1)); return (d[:14] if len(d)>=14 else d.ljust(14,"0"))
    return None

log("=== each LAS: derived UWI -> in dv_well? curves in dv_well_log_curve? ===")
rows = c.execute("SELECT FILE_NAME FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' ORDER BY FILE_NAME").fetchall()
in_dv = 0; have_curves = 0
for r in rows:
    fn = r[0]; u = uwi_from_name(fn)
    dvw = one("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=?", u) if u else 0
    dvc = one("SELECT COUNT(*) FROM dataview.dv_well_log_curve WHERE uwi=?", u) if u else 0
    if isinstance(dvw,int) and dvw: in_dv += 1
    if isinstance(dvc,int) and dvc: have_curves += 1
    log(f"  {fn}  uwi={u}  dv_well={dvw}  dv_curves={dvc}")
log(f"\n  LAS wells IN dv_well: {in_dv}/20")
log(f"  LAS wells with curves in dv_well_log_curve: {have_curves}/20")

log("\n=== the earlier SOURCE join found 0 — is cat_well now empty of LAS_HEADER? ===")
log("  cat_well SOURCE=LAS_HEADER: " + str(one("SELECT COUNT(*) FROM file_catalog.cat_well WHERE SOURCE='LAS_HEADER'")))
log("  (0 here just means cat_well was promoted-out/cleared; the dv_well check above is truth)")

log("\n=== orphan check: curves whose uwi is NOT in dv_well (would be a real problem) ===")
n = one("""SELECT COUNT(*) FROM dataview.dv_well_log_curve cc
    WHERE NOT EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi=cc.uwi)""")
log(f"  orphan curves (no parent well in dv_well): {n}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

"""diag_why_held.py — the codes are seeded but 98 tops / 576 prod still held. WHY?
Check: (a) do their parent wells exist in dv_well? (b) any still-unseeded ref value?
writes to file. py diag_why_held.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\why_held.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

NORM = ("(CASE WHEN NULLIF(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/',''))),'') IS NULL THEN NULL "
        "ELSE LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/',''))) + '00000000000000', 14) END)")

for cat in ("cat_well_formation_top","cat_prod_volume","cat_well_dir_srvy_hdr"):
    log(f"\n=== {cat}: why held? ===")
    # (a) parent well in dv_well?
    try:
        q = (f"SELECT COUNT(*) FROM file_catalog.{cat} m WHERE m.PROMOTED=0 "
             f"AND NOT EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi = {NORM.format(col='m.UWI')})")
        no_well = c.execute(q).fetchone()[0]
        held = c.execute(f"SELECT COUNT(*) FROM file_catalog.{cat} WHERE PROMOTED=0").fetchone()[0]
        log(f"   held total: {held}   of which NO parent dv_well: {no_well}")
        if no_well == held and held:
            log(f"   --> ALL held rows lack a parent well in dv_well (governance hold, correct)")
        elif no_well:
            log(f"   --> {no_well} held for missing well; {held-no_well} held for OTHER reason (ref code?)")
        else:
            log(f"   --> parent wells exist; held must be an unseeded ref code")
    except Exception as e:
        log(f"   parent-well check err: {str(e)[:60]}")
    # (b) distinct SOURCE / UOM values still not in reference
    for col, ref, refcol in (("SOURCE","dv_r_source","source"),
                             ("DEPTH_OUOM","dv_r_uom","uom_code"),
                             ("VOLUME_OUOM","dv_r_uom","uom_code"),
                             ("RATE_OUOM","dv_r_uom","uom_code")):
        try:
            q = (f"SELECT DISTINCT LTRIM(RTRIM(CONVERT(varchar(64),m.{col}))) FROM file_catalog.{cat} m "
                 f"WHERE m.PROMOTED=0 AND m.{col} IS NOT NULL "
                 f"AND NOT EXISTS (SELECT 1 FROM dataview.{ref} r WHERE r.{refcol}=m.{col})")
            miss = [r[0] for r in c.execute(q).fetchall()]
            if miss:
                log(f"   {col}: UNSEEDED values still holding rows: {miss}")
        except Exception:
            pass  # column may not exist on this table
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

r"""
remap_held_uwis.py — TEST helper: repoint all held (PROMOTED=0) document data to one
existing coordinate-bearing dv_well UWI, so the whole promote chain can be exercised
end-to-end. Updates every held cat_* detail table's UWI column AND the catalog
MATCHED_UWI, set-based. Preview/apply. Writes the original UWIs to the report.

This is for TESTING that everything promotes — it deliberately borrows an existing well
as the parent for orphan document data. Not for production data.

  py remap_held_uwis.py                              # preview (default target = first dv_well w/ coords)
  py remap_held_uwis.py --target 15007243240000      # choose the target well
  py remap_held_uwis.py --target 15007243240000 --apply
"""
import sys, pyodbc, os
OUT = r"C:\Bulk\reports\remap.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

apply = "--apply" in sys.argv
target = None
if "--target" in sys.argv:
    target = sys.argv[sys.argv.index("--target")+1]

conn = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
conn.autocommit = not apply
c = conn.cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

# pick a target well with coords if not supplied
if not target:
    target = one("SELECT TOP 1 uwi FROM dataview.dv_well WHERE surface_latitude IS NOT NULL ORDER BY uwi")
target = str(target).strip()
tinfo = c.execute("SELECT well_name, surface_latitude, surface_longitude FROM dataview.dv_well WHERE uwi=?", target).fetchone()
if not tinfo:
    log(f"TARGET {target!r} not found in dv_well (or has no row). Aborting.")
    open(OUT,"w",encoding="utf-8").write("\n".join(L)); print("\n".join(L)); sys.exit(1)
log(f"TARGET well: {target!r}  {tinfo[0]!r}  coords=({tinfo[1]},{tinfo[2]})")
if not (tinfo[1] is not None and tinfo[2] is not None):
    log("  WARNING: target has no coords — pick another with --target");

# tables + their UWI column (from the probe)
TABS = [
    ("cat_well","uwi"), ("cat_well_formation_top","uwi"), ("cat_prod_volume","UWI"),
    ("cat_prod_entity","uwi"), ("cat_well_completion","uwi"), ("cat_well_dir_srvy_hdr","uwi"),
    ("cat_well_dir_srvy_sta","uwi"), ("cat_well_dst","uwi"), ("cat_well_log","uwi"),
    ("cat_well_log_curve","uwi"), ("cat_log_curve","UWI"),
]

log("\n=== held rows that will be repointed to the target ===")
total = 0
orig = {}
for t, col in TABS:
    try:
        held = one(f"SELECT COUNT(*) FROM file_catalog.{t} WHERE PROMOTED=0")
        if isinstance(held,int) and held>0:
            # capture distinct original UWIs for the report
            us = [str(r[0]).strip() for r in c.execute(f"SELECT DISTINCT {col} FROM file_catalog.{t} WHERE PROMOTED=0").fetchall()]
            orig[t] = us
            log(f"  {t}: {held} held rows  (from UWIs: {us})")
            total += held
    except Exception as e:
        log(f"  {t}: err {str(e)[:40]}")
log(f"  TOTAL held rows to repoint: {total}")

# also the catalog MATCHED_UWI on the held document files
docs = one("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE FILE_EXT IN ('.pdf','.xlsx','.docx','.xml')
      AND MATCHED_UWI IS NOT NULL AND LTRIM(RTRIM(MATCHED_UWI))<>''
      AND LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),MATCHED_UWI),'-',''),' ',''),'/','')))+'00000000000000',14) IN (
          SELECT DISTINCT LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),uwi),'-',''),' ',''),'/','')))+'00000000000000',14)
          FROM file_catalog.cat_well_formation_top WHERE PROMOTED=0)""")
log(f"  catalog doc rows whose MATCHED_UWI will be set to target: ~{docs}")

if not apply:
    log("\n(preview) re-run with --apply --target <uwi> to repoint, then run promote.")
    conn.rollback()
    open(OUT,"w",encoding="utf-8").write("\n".join(L)); print("\n".join(L)); sys.exit()

# APPLY: set every held row's UWI column to target
log("\n=== applying ===")
for t, col in TABS:
    try:
        n = c.execute(f"UPDATE file_catalog.{t} SET {col} = ? WHERE PROMOTED=0", target).rowcount
        if n: log(f"  {t}: set {n} row(s) UWI -> {target}")
    except Exception as e:
        log(f"  {t}: err {str(e)[:60]}")

# set MATCHED_UWI on the held document catalog rows to target too
try:
    n = c.execute("""UPDATE g SET g.MATCHED_UWI = ?
        FROM file_catalog.GLOBAL_FILE_CATALOG g
        WHERE g.FILE_EXT IN ('.pdf','.xlsx','.docx','.xml')
          AND g.MATCHED_UWI IS NOT NULL AND LTRIM(RTRIM(g.MATCHED_UWI))<>''
          AND LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),g.MATCHED_UWI),'-',''),' ',''),'/','')))+'00000000000000',14) NOT IN (
              SELECT uwi FROM dataview.dv_well WHERE surface_latitude IS NOT NULL)""", target).rowcount
    log(f"  GLOBAL_FILE_CATALOG: set MATCHED_UWI on {n} doc row(s) -> {target}")
except Exception as e:
    log(f"  MATCHED_UWI update err: {str(e)[:80]}")

conn.commit()
log("\ncommitted. now run promote (py run_promote_now.py) — the doc data now has a")
log("coordinate-bearing parent well and should promote.")
log(f"\nORIGINAL UWIs (for reference/rollback): {orig}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

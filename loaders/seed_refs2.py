r"""
seed_refs2.py — seed dv_r_uom + dv_r_source to match the exact schemas seen in
diag_refs (uom_code / source+short_name+long_name), pulling the codes actually
present in the held cat_* rows. Idempotent. py seed_refs2.py --apply
"""
import sys, pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
c = cur.cursor()
APPLY = "--apply" in sys.argv
NOW = "SYSUTCDATETIME()"

# ---- dv_r_uom (key: uom_code) ------------------------------------------------
uom_needed = set()
for col in ("curve_unit", "depth_ouom"):
    for r in c.execute(f"SELECT DISTINCT {col} FROM file_catalog.cat_well_log_curve "
                       f"WHERE {col} IS NOT NULL").fetchall():
        if (r[0] or "").strip():
            uom_needed.add(r[0].strip())
for r in c.execute("SELECT DISTINCT depth_ouom FROM file_catalog.cat_well_log "
                   "WHERE depth_ouom IS NOT NULL").fetchall():
    if (r[0] or "").strip():
        uom_needed.add(r[0].strip())

uom_have = {str(r[0]).strip() for r in c.execute(
    "SELECT uom_code FROM dataview.dv_r_uom").fetchall() if r[0] is not None}
uom_missing = sorted(uom_needed - uom_have)
print(f"dv_r_uom: {len(uom_needed)} used · {len(uom_have)} present · {len(uom_missing)} missing")
print(f"   -> {uom_missing}")

# ---- dv_r_source (key: source) ----------------------------------------------
src_needed = set()
for t in ("cat_well_log_curve", "cat_well_log", "cat_well"):
    for r in c.execute(f"SELECT DISTINCT source FROM file_catalog.{t} "
                       f"WHERE source IS NOT NULL").fetchall():
        if (r[0] or "").strip():
            src_needed.add(r[0].strip())
src_have = {str(r[0]).strip() for r in c.execute(
    "SELECT source FROM dataview.dv_r_source").fetchall() if r[0] is not None}
src_missing = sorted(src_needed - src_have)
print(f"dv_r_source: {len(src_needed)} used · {len(src_have)} present · {len(src_missing)} missing")
print(f"   -> {src_missing}")

if not APPLY:
    print("\n[preview] add --apply to insert."); sys.exit(0)

for u in uom_missing:
    c.execute(
        "INSERT INTO dataview.dv_r_uom "
        "(uom_code, unit_of_measure, uom_description, active_ind, row_created_by, row_created_date) "
        f"VALUES (?, ?, ?, 'Y', 'SEED', {NOW})", u, u, u)
for s in src_missing:
    c.execute(
        "INSERT INTO dataview.dv_r_source "
        "(source, short_name, long_name, active_ind, row_created_by, row_created_date) "
        f"VALUES (?, ?, ?, 'Y', 'SEED', {NOW})", s, s, f"{s} (seeded)")
print(f"\ninserted {len(uom_missing)} uom + {len(src_missing)} source row(s).")
print("now: py repromote2.py")

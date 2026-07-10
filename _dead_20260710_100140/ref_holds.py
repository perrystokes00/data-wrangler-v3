"""ref_holds.py — which unresolved reference-code values are holding cat_* rows
from promote? Lists distinct source / depth_ouom / curve_unit values in the
mirror that aren't in the matching dv_r_* reference table, with counts, so you
know exactly what to seed. py ref_holds.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()

def cols(tbl):
    return {r[0].lower() for r in cur.execute(
        "SELECT c.name FROM sys.columns c WHERE c.object_id=OBJECT_ID(?)", tbl).fetchall()}

# (mirror table, code column, reference table, reference key column)
CHECKS = [
    ("file_catalog.cat_well_log",        "source",     "dataview.dv_r_source",      "source"),
    ("file_catalog.cat_well_log",        "depth_ouom", "dataview.dv_r_uom",         "uom_id"),
    ("file_catalog.cat_well_log_curve",  "source",     "dataview.dv_r_source",      "source"),
    ("file_catalog.cat_well_log_curve",  "curve_unit", "dataview.dv_r_uom",         "uom_id"),
    ("file_catalog.cat_well_log_curve",  "depth_ouom", "dataview.dv_r_uom",         "uom_id"),
]

def exists(tbl):
    return cur.execute("SELECT OBJECT_ID(?)", tbl).fetchone()[0] is not None

for mtbl, mcol, rtbl, rcol in CHECKS:
    if not exists(mtbl):
        continue
    if mcol not in cols(mtbl):
        print(f"\n{mtbl}.{mcol}: (column not present) — skip"); continue
    ref_ok = exists(rtbl) and rcol in cols(rtbl)
    print(f"\n=== {mtbl}.{mcol}  vs  {rtbl}.{rcol} {'' if ref_ok else '(ref table/col MISSING)'} ===")
    if ref_ok:
        q = (f"SELECT LTRIM(RTRIM(m.[{mcol}])) val, COUNT(*) n "
             f"FROM {mtbl} m "
             f"WHERE NULLIF(LTRIM(RTRIM(m.[{mcol}])),'') IS NOT NULL "
             f"AND NOT EXISTS (SELECT 1 FROM {rtbl} r "
             f"                WHERE LTRIM(RTRIM(r.[{rcol}]))=LTRIM(RTRIM(m.[{mcol}]))) "
             f"GROUP BY LTRIM(RTRIM(m.[{mcol}])) ORDER BY n DESC")
    else:
        q = (f"SELECT LTRIM(RTRIM(m.[{mcol}])) val, COUNT(*) n FROM {mtbl} m "
             f"WHERE NULLIF(LTRIM(RTRIM(m.[{mcol}])),'') IS NOT NULL "
             f"GROUP BY LTRIM(RTRIM(m.[{mcol}])) ORDER BY n DESC")
    rows = cur.execute(q).fetchall()
    if not rows:
        print("  (all values resolve — nothing held here)")
    for r in rows[:25]:
        print(f"  {r.val!r:20} {r.n:,}")
    if len(rows) > 25:
        print(f"  … +{len(rows)-25} more distinct value(s)")

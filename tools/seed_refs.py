r"""
seed_refs.py — after a schema rebuild the dv_r_* reference tables are empty, so
promote holds every log/curve on the curve_unit / depth_ouom / source FKs. This
reads the DISTINCT values actually present in the held cat_* rows and inserts any
missing ones into the matching dv_r_* table. Idempotent (only inserts missing).

  py seed_refs.py            # preview what it would add
  py seed_refs.py --apply
"""
import sys, pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
APPLY = "--apply" in sys.argv

def cols(schema, table):
    return [r[0].lower() for r in cur.execute(
        "SELECT c.name FROM sys.columns c "
        "WHERE c.object_id = OBJECT_ID(?)", f"{schema}.{table}").fetchall()]

def seed(ref_table, code_col, src_selects, label):
    """src_selects: list of SELECT DISTINCT queries returning candidate codes."""
    rc = cols("dataview", ref_table)
    if not rc:
        print(f"  {ref_table}: table missing — skipped"); return
    if code_col.lower() not in rc:
        # find the likely code column
        code_col = next((c for c in rc if c in ("uom_code","source_code","code","uom","source")), rc[0])
    # gather needed codes from the cat_* data
    needed = set()
    for q in src_selects:
        try:
            for r in cur.execute(q).fetchall():
                v = (r[0] or "").strip() if isinstance(r[0], str) else r[0]
                if v not in (None, ""):
                    needed.add(str(v))
        except Exception as e:
            print(f"  ({label} source skip: {str(e)[:50]})")
    if not needed:
        print(f"  {ref_table}: nothing needed"); return
    have = {str(r[0]).strip() for r in cur.execute(
        f"SELECT [{code_col}] FROM dataview.{ref_table}").fetchall() if r[0] is not None}
    missing = sorted(needed - have)
    print(f"  {ref_table}.[{code_col}]: {len(needed)} used · {len(have)} present · "
          f"{len(missing)} missing")
    if missing:
        print(f"     -> {missing[:20]}{' …' if len(missing)>20 else ''}")
    if APPLY and missing:
        # insert code (+ a description column if the table has one)
        desc_col = next((c for c in rc if c in ("description","descr","uom_description",
                                                "source_description","name")), None)
        for m in missing:
            if desc_col:
                cur.execute(f"INSERT INTO dataview.{ref_table} ([{code_col}],[{desc_col}]) "
                            f"VALUES (?, ?)", m, m)
            else:
                cur.execute(f"INSERT INTO dataview.{ref_table} ([{code_col}]) VALUES (?)", m)
        print(f"     inserted {len(missing)} into {ref_table}")

print(f"{'APPLYING' if APPLY else 'PREVIEW'} — seeding dv_r_* from held cat_* values\n")

seed("dv_r_uom", "uom_code", [
    "SELECT DISTINCT curve_unit FROM file_catalog.cat_well_log_curve WHERE curve_unit IS NOT NULL",
    "SELECT DISTINCT depth_ouom FROM file_catalog.cat_well_log_curve WHERE depth_ouom IS NOT NULL",
    "SELECT DISTINCT depth_ouom FROM file_catalog.cat_well_log WHERE depth_ouom IS NOT NULL",
], "uom")

seed("dv_r_source", "source_code", [
    "SELECT DISTINCT source FROM file_catalog.cat_well_log_curve WHERE source IS NOT NULL",
    "SELECT DISTINCT source FROM file_catalog.cat_well_log WHERE source IS NOT NULL",
    "SELECT DISTINCT source FROM file_catalog.cat_well WHERE source IS NOT NULL",
], "source")

if not APPLY:
    print("\n[preview] add --apply to insert the missing codes, then re-run promote.")
else:
    print("\nseeded. now re-run promote — the held logs/curves should move to dv_*.")

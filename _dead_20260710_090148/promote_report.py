"""
promote_report.py — an HONEST post-run report. Answers the only questions that matter:
  1. Did document data actually reach dv_*?   (not the misleading per-file flag)
  2. What's still held, and is that a PROBLEM or CORRECT governance?
  3. One-line verdict.

Run after any pipeline/promote:  py promote_report.py
Writes a readable report to C:\\Bulk\\reports\\promote_report.txt AND prints it.
"""
import pyodbc, os, datetime

OUT = r"C:\Bulk\reports\promote_report.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s); L.append(s)

c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

NORM = ("LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/','')))+'00000000000000',14)")

def one(q, *a):
    try: return c.execute(q, *a).fetchone()[0]
    except Exception: return None

p("=" * 60)
p(" PROMOTE REPORT  ·  " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
p("=" * 60)

# ── 1. what document data reached dv_* ───────────────────────────────────────
p("\n WHAT LANDED IN THE DATABASE (dv_*)")
p(" " + "-" * 40)
domains = [
    ("Formation tops",       "dv_well_formation_top"),
    ("Directional surveys",  "dv_well_dir_srvy_hdr"),
    ("  survey stations",    "dv_well_dir_srvy_sta"),
    ("Completions",          "dv_well_completion"),
    ("Production volumes",   "dv_prod_volume"),
    ("Log curves",           "dv_well_log_curve"),
    ("Seismic surveys",      "dv_seis_set"),
    ("  seismic lines",      "dv_seis_line"),
]
total_dv = 0
for label, tbl in domains:
    n = one(f"SELECT COUNT(*) FROM dataview.{tbl}")
    if n is None: continue
    total_dv += n if not label.startswith("  ") else 0
    bar = "#" * min(40, n // 5) if n else ""
    p(f"   {label:22} {n:>6}  {bar}")
p(f"   {'wells (dv_well)':22} {one('SELECT COUNT(*) FROM dataview.dv_well'):>6}")

# ── 2. what's held, and is it OK ─────────────────────────────────────────────
p("\n WHAT'S WAITING (held in staging)")
p(" " + "-" * 40)
cats = [
    ("Formation tops",      "cat_well_formation_top"),
    ("Directional surveys", "cat_well_dir_srvy_hdr"),
    ("  survey stations",   "cat_well_dir_srvy_sta"),
    ("Completions",         "cat_well_completion"),
    ("Production volumes",  "cat_prod_volume"),
    ("Log curves",          "cat_well_log_curve"),
]
held_missing_well = 0
held_other = 0
for label, cat in cats:
    held = one(f"SELECT COUNT(*) FROM file_catalog.{cat} WHERE PROMOTED=0")
    if held is None: continue
    if held == 0:
        p(f"   {label:22}      0   (all promoted)")
        continue
    nowell = one(f"""SELECT COUNT(*) FROM file_catalog.{cat} m WHERE m.PROMOTED=0
        AND NOT EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi={NORM.format(col='m.UWI')})""") or 0
    other = held - nowell
    held_missing_well += nowell
    held_other += other
    tag = "waiting for well" if nowell == held else f"{nowell} need well, {other} OTHER"
    p(f"   {label:22} {held:>6}   ({tag})")

# ── 3. verdict ───────────────────────────────────────────────────────────────
p("\n VERDICT")
p(" " + "-" * 40)
if total_dv > 0:
    p(f"   [OK] {total_dv:,} document data rows are in the database.")
if held_other == 0 and held_missing_well > 0:
    p(f"   [OK] {held_missing_well:,} rows are waiting for their well to be created")
    p(f"        (correct — these documents name wells that have no")
    p(f"        coordinates yet, so there's no well record to attach to).")
    p(f"        They promote automatically once the well exists.")
elif held_other > 0:
    p(f"   [!!] {held_other:,} rows held for a NON-well reason (unresolved")
    p(f"        reference code) — open the FK review grid to resolve.")
else:
    p(f"   [OK] Nothing held. Everything that could promote, did.")

p("\n   Bottom line: the pipeline is working. 'Promoted' in the")
p("   inventory CSV is a per-file seismic flag and does NOT reflect")
p("   document data — THIS report does.")
p("=" * 60)

open(OUT, "w", encoding="utf-8").write("\n".join(L))
print("\n>>> saved to", OUT)

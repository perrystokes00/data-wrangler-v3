"""check_well.py — what data does a well have, across all domains?
Usage:  py check_well.py                 (defaults to 42317123450000)
        py check_well.py 15035247200000  (any UWI14)
Self-checking: only queries dv_* tables that exist and have a 'uwi' column,
so it never errors on a name mismatch. Documents come from GLOBAL_FILE_CATALOG."""
import sys, pyodbc

UWI = (sys.argv[1] if len(sys.argv) > 1 else "42317123450000").strip()

c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

# domains: (table, friendly label) — order roughly by interest
domains = [
    ("dv_well",                 "the well record"),
    ("dv_well_formation_top",   "formation tops"),
    ("dv_strat_interval",       "strat intervals"),
    ("dv_well_dir_srvy_hdr",    "directional survey hdr"),
    ("dv_well_dir_srvy_sta",    "directional survey sta"),
    ("dv_well_completion",      "completions"),
    ("dv_well_casing",          "casing"),
    ("dv_well_perforation",     "perforations"),
    ("dv_well_dst",             "DST"),
    ("dv_well_dst_period",      "DST periods"),
    ("dv_well_core",            "core"),
    ("dv_well_core_sample",     "core samples"),
    ("dv_well_core_photo",      "core photos"),
    ("dv_well_petro_interp",    "petro interpretation"),
    ("dv_well_petro_zone",      "petro zones"),
    ("dv_well_stimulation",     "stimulation"),
    ("dv_well_shows",           "shows"),
    ("dv_well_pressure",        "pressure"),
    ("dv_well_mud_log",         "mud log"),
    ("dv_well_log",             "logs"),
    ("dv_well_log_curve",       "log curves"),
    ("dv_prod_entity",          "production entity"),
    ("dv_well_alias",           "well aliases"),
    ("dv_well_legal",           "well legal"),
]

def has_uwi(tbl):
    return c.execute("""SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dataview' AND TABLE_NAME=? AND COLUMN_NAME='uwi'""",
        tbl).fetchone()[0] > 0

print(f"\n=== data inventory for well {UWI} ===\n")
print(f"  {'domain':26} {'count':>7}  has")
print(f"  {'-'*26} {'-'*7}  ---")
results = []
for tbl, label in domains:
    if not has_uwi(tbl):
        continue
    try:
        n = c.execute(f"SELECT COUNT(*) FROM dataview.{tbl} WHERE uwi = ?", UWI).fetchone()[0]
    except Exception as e:
        n = -1
    results.append((label, n))

# documents (keyed by UWI14 in the file catalog)
try:
    nd = c.execute("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE UWI14 = ? AND ISNULL(FLAG_DELETE,'N') <> 'Y'""", UWI).fetchone()[0]
    results.append(("catalogued documents", nd))
except Exception:
    pass

# YES first, then by count desc
results.sort(key=lambda r: (0 if r[1] > 0 else 1, -r[1]))
for label, n in results:
    tag = "YES" if n > 0 else ("ERR" if n < 0 else "no")
    print(f"  {label:26} {max(n,0):>7,}  {tag}")

haves = [l for l, n in results if n > 0]
print(f"\n  {len(haves)} domain(s) with data: {', '.join(haves) if haves else '(none)'}\n")

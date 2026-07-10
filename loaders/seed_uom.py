"""
seed_uom.py — seed the missing wireline UOM codes into dataview.dv_r_uom so the
held log curves promote. curve_unit/depth_ouom are FKs to dv_r_uom.uom_code;
the KGS logs use standard log units not yet seeded. Idempotent — inserts only
codes actually holding cat_well_log_curve/cat_well_log rows that aren't present.

  py seed_uom.py           # preview which codes would be added
  py seed_uom.py --apply   # insert them
"""
import sys, datetime, pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()

# known descriptions/types for common wireline units (fallback: OTHER/no desc)
META = {
    "F": ("Feet", "LENGTH"), "M": ("Metres", "LENGTH"), "IN": ("Inches", "LENGTH"),
    "OHMM": ("Ohm-metre", "RESISTIVITY"), "OHM": ("Ohm", "RESISTIVITY"),
    "GAPI": ("Gamma API units", "RADIOACTIVITY"), "API": ("API units", "RADIOACTIVITY"),
    "G/CC": ("Grams per cubic centimetre", "DENSITY"),
    "G/C3": ("Grams per cubic centimetre", "DENSITY"),
    "K/M3": ("Kilograms per cubic metre", "DENSITY"),
    "US/F": ("Microseconds per foot", "SONIC"), "USPF": ("Microseconds per foot", "SONIC"),
    "US": ("Microseconds", "TIME"), "MV": ("Millivolts", "VOLTAGE"),
    "V/V": ("Volume per volume", "RATIO"), "DEC": ("Decimal fraction", "RATIO"),
    "DECP": ("Decimal fraction", "RATIO"), "FRAC": ("Fraction", "RATIO"),
    "PU": ("Porosity units", "POROSITY"), "%": ("Percent", "RATIO"),
    "CPS": ("Counts per second", "RATE"), "MMHO": ("Millimho", "CONDUCTIVITY"),
    "MMO/M": ("Millimho per metre", "CONDUCTIVITY"), "B/E": ("Barns per electron", "OTHER"),
    "PPM": ("Parts per million", "RATIO"), "LB": ("Pounds", "MASS"),
    "LBS": ("Pounds", "MASS"), "NONE": ("Unitless", "OTHER"),
}

# distinct codes holding rows, missing from dv_r_uom (case-insensitive on uom_code)
def missing(col, tbl):
    return [r[0] for r in cur.execute(f"""
        SELECT DISTINCT LTRIM(RTRIM(m.[{col}]))
        FROM file_catalog.{tbl} m
        WHERE NULLIF(LTRIM(RTRIM(m.[{col}])),'') IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM dataview.dv_r_uom r
                          WHERE UPPER(LTRIM(RTRIM(r.uom_code)))=UPPER(LTRIM(RTRIM(m.[{col}]))))
    """).fetchall()]

codes = set()
for col, tbl in (("curve_unit", "cat_well_log_curve"),
                 ("depth_ouom", "cat_well_log_curve"),
                 ("depth_ouom", "cat_well_log")):
    codes |= set(missing(col, tbl))
codes = sorted(x for x in codes if x)

print(f"{len(codes)} UOM code(s) holding rows and missing from dv_r_uom:")
for x in codes:
    desc, typ = META.get(x.upper(), (x, "OTHER"))
    print(f"  {x!r:10} -> {typ:14} {desc}")

if "--apply" not in sys.argv:
    print("\n[dry run] add --apply to insert them into dataview.dv_r_uom.")
    sys.exit(0)

now = datetime.datetime.now()
ins = 0
for x in codes:
    desc, typ = META.get(x.upper(), (x, "OTHER"))
    cur.execute(
        "INSERT INTO dataview.dv_r_uom "
        "(uom_code, unit_of_measure, uom_description, uom_type, active_ind, "
        " row_created_by, row_created_date) "
        "VALUES (?,?,?,?, 'Y', 'SEED_UOM', ?)",
        x, desc, desc, typ, now)
    ins += 1
print(f"\ninserted {ins} UOM code(s). Re-run promote — the held log curves should move.")

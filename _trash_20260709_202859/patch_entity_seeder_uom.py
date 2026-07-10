r"""
patch_entity_seeder_uom.py — add dv_r_uom seeding to entity_seeder.seed_reference_tables
so a rebuilt DB is promote-ready (no manual seed_refs step). Seeds a canonical UOM
set AND any distinct curve_unit/depth_ouom found in the catalog, plus ensures
dv_r_source carries 'LAS'. Idempotent (IF NOT EXISTS). In place, .bak.
py patch_entity_seeder_uom.py
"""
import sys, os, ast
P = "entity_seeder.py"
if not os.path.exists(P):
    P = os.path.join("modules", "entity_seeder.py")
if not os.path.exists(P):
    sys.exit("entity_seeder.py not found")
s = open(P, encoding="utf-8").read()
if "_seed_uom" in s:
    print("already patched"); sys.exit(0)

# 1) call the UOM seeder at the end of seed_reference_tables (before the final print)
anchor = '''    _execute_many(engine, ws_sql, ws_params)

    print("  Reference tables seeded.")'''
inject = '''    _execute_many(engine, ws_sql, ws_params)

    # dv_r_uom — canonical set + any units actually present in the catalog
    _seed_uom(engine, loader_tag)

    print("  Reference tables seeded.")'''
if anchor not in s:
    sys.exit("FAILED: seed_reference_tables tail anchor not found")
s = s.replace(anchor, inject, 1)

# 2) add the _seed_uom helper after seed_reference_tables
helper = '''

# ── Unit of Measure ───────────────────────────────────────────────────
# Canonical UOM codes seen across KGS/vendor LAS headers. Messy variants
# (FT/FEET/F, OHM-M/OHMM, GAPI/api) are all seeded as-is so promote never
# holds a curve on the curve_unit/depth_ouom FK; normalization to canonical
# units is a separate data-quality task.
CANON_UOM = [
    "FT", "FEET", "F", "M", "IN", "INCH",
    "GAPI", "API", "NAPI", "API-N", "API-GR",
    "OHM-M", "OHMM", "OHM", "OHM/M", "M.OHM", "MMHO", "MMHO/M", "MMHO-M",
    "G/CC", "G/C3", "GM/CC", "KG/M3", "K/M3", "B/CM3",
    "US/F", "US/FT", "USEC", "USEC/FT", "USPF", "US", "SEC", "MSEC", "MS", "S",
    "MV", "V", "V/V", "PU", "DEC", "DECP", "DEC(LS)", "FRAC", "PERC", "PERCENT",
    "%", "PPM", "CPS", "LB", "LBS", "LBF", "PSI", "DEG", "DEGF", "DIM",
    "BARN", "BARN/E", "B/E", "CU", "C/C", "CFCF", "FT3", "F3", "FT3/FT3",
    "FT/MIN", "FT/HR", "F/HR", "FPM", "MD", "MIN/FT", "MINUTES", "NONE",
    "UNITS", "POROSITY", "DELT-CPS", "SC/S", "----",
]

def _seed_uom(engine, loader_tag: str = "ENTITY_SEEDER") -> None:
    """Seed dv_r_uom with the canonical set plus any distinct curve_unit /
    depth_ouom already present in the catalog. Also ensure dv_r_source has 'LAS'."""
    print("  Seeding dv_r_uom (+ ensuring dv_r_source has LAS)...")

    # collect codes: canonical + whatever the loaded catalog actually carries
    codes = {c.strip() for c in CANON_UOM if c and c.strip()}
    try:
        with engine.connect() as con:
            from sqlalchemy import text as _t
            for q in (
                "SELECT DISTINCT curve_unit FROM file_catalog.cat_well_log_curve WHERE curve_unit IS NOT NULL",
                "SELECT DISTINCT depth_ouom FROM file_catalog.cat_well_log_curve WHERE depth_ouom IS NOT NULL",
                "SELECT DISTINCT depth_ouom FROM file_catalog.cat_well_log WHERE depth_ouom IS NOT NULL",
            ):
                for r in con.execute(_t(q)):
                    v = (r[0] or "").strip() if isinstance(r[0], str) else r[0]
                    if v:
                        codes.add(str(v))
    except Exception as e:
        print(f"    (catalog UOM scan skipped: {str(e)[:60]})")

    uom_sql = """
        IF NOT EXISTS (SELECT 1 FROM dataview.dv_r_uom WHERE uom_code = ?)
        INSERT INTO dataview.dv_r_uom (
            uom_code, unit_of_measure, uom_description, active_ind,
            row_created_by, row_created_date, row_changed_by, row_changed_date
        ) VALUES (?, ?, ?, 'Y', ?, GETDATE(), ?, GETDATE())
    """
    uom_params = [(c, c, c, c, loader_tag, loader_tag) for c in sorted(codes)]
    _execute_many(engine, uom_sql, uom_params)

    # ensure LAS source exists (curves carry source='LAS')
    las_sql = """
        IF NOT EXISTS (SELECT 1 FROM dataview.dv_r_source WHERE source = ?)
        INSERT INTO dataview.dv_r_source (
            source, short_name, long_name, active_ind,
            row_created_by, row_created_date, row_changed_by, row_changed_date
        ) VALUES (?, ?, ?, 'Y', ?, GETDATE(), ?, GETDATE())
    """
    _execute_many(engine, las_sql, [("LAS", "LAS", "LAS well log", "LAS", loader_tag, loader_tag)])
    print(f"  dv_r_uom seeded ({len(uom_params)} codes).")
'''

# insert the helper right after the seed_reference_tables function (before the BA section marker)
marker = "# ── Business Associate ────────────────────────────────────────────────"
if marker not in s:
    sys.exit("FAILED: business-associate section marker not found")
s = s.replace(marker, helper.lstrip("\n") + "\n\n" + marker, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: seed_reference_tables now also seeds dv_r_uom + LAS source")

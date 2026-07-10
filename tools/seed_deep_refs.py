r"""
seed_deep_refs.py — permanent reference seeding for deep-extract source & UOM codes.

The deep loaders (office/pdf/witsml/dlis) emit SOURCE codes (DATA_LOADER, WITSML,
OFFICE, DLIS, ...) and UOM codes (ft, FT, BBL, MCF, curve units, ...) that promote
FKs into dv_r_source / dv_r_uom. If those codes aren't seeded, promote HOLDS the
rows (parks them rather than 547-crashing). This seeds the full set idempotently.

Two ways to use it:
  • CLI, one-off / after a reset:
        py seed_deep_refs.py            # preview what's missing
        py seed_deep_refs.py --apply    # insert missing codes
  • Permanent: import and call from entity_seeder.py so a demo_reset re-seed always
    includes these codes:
        from seed_deep_refs import seed_deep_refs
        seed_deep_refs(cur)             # idempotent; returns (n_source, n_uom)

Keep this list in sync with the SOURCE/OUOM values the loaders write. Adding a new
document loader that emits a new source/unit? Add it here so promote never holds on it.
"""
import sys

# ---- the SOURCE codes the deep loaders emit (dv_r_source.source PK) ----------
SOURCES = [
    ("DATA_LOADER",        "Generic tabular data loader"),
    ("OFFICE",             "Office document (xlsx/docx/csv)"),
    ("WITSML",             "WITSML XML"),
    ("DLIS",               "DLIS log"),
    ("LIS",                "LIS log"),
    ("DIRECTIONAL_SURVEY", "Directional survey document"),
    ("PDF",                "PDF document"),
    ("OSDU",               "OSDU / JSON well log"),
    ("SHAPEFILE",          "ESRI shapefile"),
    ("SEGY",               "SEG-Y seismic"),
]

# ---- the UOM codes the cat_* rows use (dv_r_uom.uom_code PK) ------------------
# Seed BOTH cases seen in the data (ft AND FT) since the FK match is case-sensitive.
UOMS = [
    # depth / length
    "ft", "FT", "M", "m", "0.1 in", "IN", "in", "US/F",
    # volume / rate (production)
    "BBL", "bbl", "MCF", "mcf", "FT3", "ft3", "M3", "m3",
    "BBL/D", "MCF/D", "STB/D",
    # log-curve units
    "%", "1/s", "c/min", "deg", "degC", "gAPI", "gapi",
    "g", "G/CC", "g/cm3", "KN", "kPa", "m/h", "M/HR",
    "ms", "mS/m", "mV", "ohm.m", "OHMM", "OHM-M", "PU",
    "RPM", "s", "V/V", "API", "psi", "PSI",
]


def seed_deep_refs(cur, log=print):
    """Idempotently insert any missing deep-extract SOURCE and UOM reference codes.
    `cur` is a live pyodbc cursor (caller owns the transaction/commit). Returns
    (n_source_inserted, n_uom_inserted)."""
    have_src = {r[0] for r in cur.execute("SELECT source FROM dataview.dv_r_source").fetchall()}
    have_uom = {r[0] for r in cur.execute("SELECT uom_code FROM dataview.dv_r_uom").fetchall()}

    ns = nu = 0
    for code, desc in SOURCES:
        if code in have_src:
            continue
        cur.execute(
            "INSERT INTO dataview.dv_r_source "
            "  (source, short_name, long_name, active_ind, row_created_by, row_created_date) "
            "SELECT ?, ?, ?, 'Y', 'SEED_DEEP', GETDATE() "
            "WHERE NOT EXISTS (SELECT 1 FROM dataview.dv_r_source WHERE source = ?)",
            code, code, desc, code)
        ns += cur.rowcount or 0
    for code in UOMS:
        if code in have_uom:
            continue
        cur.execute(
            "INSERT INTO dataview.dv_r_uom "
            "  (uom_code, unit_of_measure, uom_description, active_ind, row_created_by, row_created_date) "
            "SELECT ?, ?, ?, 'Y', 'SEED_DEEP', GETDATE() "
            "WHERE NOT EXISTS (SELECT 1 FROM dataview.dv_r_uom WHERE uom_code = ?)",
            code, code, code, code)
        nu += cur.rowcount or 0

    if log:
        log(f"[seed_deep_refs] dv_r_source +{ns}, dv_r_uom +{nu}")
    return ns, nu


def _missing(cur):
    have_src = {r[0] for r in cur.execute("SELECT source FROM dataview.dv_r_source").fetchall()}
    have_uom = {r[0] for r in cur.execute("SELECT uom_code FROM dataview.dv_r_uom").fetchall()}
    ms = [c for c, _ in SOURCES if c not in have_src]
    mu = [c for c in UOMS if c not in have_uom]
    return ms, mu


def main():
    import pyodbc
    apply = "--apply" in sys.argv
    conn = pyodbc.connect(
        r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
    conn.autocommit = not apply  # preview reads only; apply commits at end
    cur = conn.cursor()

    ms, mu = _missing(cur)
    print("=== missing dv_r_source ===\n  ", ms or "(none)")
    print("=== missing dv_r_uom ===\n  ", mu or "(none)")
    if not apply:
        print("\n(preview) run with --apply to insert them")
        return
    ns, nu = seed_deep_refs(cur)
    conn.commit()
    print(f"\nseeded dv_r_source +{ns}, dv_r_uom +{nu} — committed")
    print("now re-run promote (py run_promote_now.py) to lift any held rows")


if __name__ == "__main__":
    main()

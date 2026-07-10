"""seed_references.py — idempotent standard-reference seeder for dataview.dv_r_*.

After a DataView_* database is recreated from DDL, the dv_r_* reference tables
are EMPTY, so the promote FK guard holds every row whose well_status / well_type
/ depth_datum / uom value can't be resolved (the "held N — unresolved …" lines).
This seeds the standard petroleum values into the reference tables that dv_*
foreign keys actually point at, so promote can resolve them.

Design:
  * Schema-aware — discovers (ref_table, ref_col) from sys.foreign_keys (only
    dv_r_* tables that are real FK targets), and introspects each table's columns
    so the INSERT fills required NOT NULL fields (active_ind, audit cols) whatever
    the exact layout is.
  * Idempotent — INSERT ... WHERE NOT EXISTS on the code; safe to re-run after
    every schema publish.
  * Governance-respecting — auto-seeds only the curated STANDARD values. For
    values present in your actual data that still don't match, it REPORTS them
    (so you add-to-reference or map-to-canonical explicitly) instead of silently
    seeding whatever is in the files. Use --seed-observed to also add those.

Usage:
    python seed_references.py                       # DataView_Demo (default)
    python seed_references.py --database DataView
    python seed_references.py --dry-run             # show what WOULD seed
    python seed_references.py --seed-observed        # also add data-observed codes
"""

import argparse
import sys

SCHEMA = "dataview"

# ── curated standard values, keyed by a semantic name ────────────────────────
# (code, description). Codes are the canonical petroleum-industry abbreviations.
CATALOG = {
    "uom": [
        ("BBL", "Barrels"), ("MBBL", "Thousand barrels"),
        ("MMBBL", "Million barrels"), ("BBL/D", "Barrels per day"),
        ("STB", "Stock tank barrel"), ("BWPD", "Barrels water per day"),
        ("BOPD", "Barrels oil per day"),
        ("MCF", "Thousand cubic feet"), ("MMCF", "Million cubic feet"),
        ("BCF", "Billion cubic feet"), ("SCF", "Standard cubic feet"),
        ("MCF/D", "Thousand cubic feet per day"),
        ("MMCF/D", "Million cubic feet per day"),
        ("PSI", "Pounds per square inch"), ("PSIA", "PSI absolute"),
        ("PSIG", "PSI gauge"),
        ("FT", "Feet"), ("M", "Meters"), ("IN", "Inches"),
        ("DEGF", "Degrees Fahrenheit"), ("DEGC", "Degrees Celsius"),
        ("API", "API gravity"), ("PCT", "Percent"),
        ("MD", "Millidarcy"), ("FRAC", "Fraction"),
        ("GAL", "Gallons"), ("LB", "Pounds"), ("TON", "Tons"),
        ("DAY", "Days"), ("HR", "Hours"),
    ],
    "source": [
        ("CATALOG", "Promoted from file catalog"),
        ("LAS_HEADER", "LAS well-log header"),
        ("PDF_HEADER", "PDF document header"),
        ("SHAPEFILE", "Shapefile attribute"),
        ("OSDU", "OSDU / master JSON"),
        ("WITSML", "WITSML document"),
        ("DLIS", "DLIS well-log header"),
    ],
    "well_status": [
        ("ACTIVE", "Active"), ("INACTIVE", "Inactive"),
        ("PRODUCING", "Producing"), ("INJECTING", "Injecting"),
        ("SHUT_IN", "Shut in"), ("SUSPENDED", "Suspended"),
        ("TA", "Temporarily abandoned"),
        ("PLUGGED", "Plugged"),
        ("PLUGGED_AND_ABANDONED", "Plugged and abandoned"),
        ("ABANDONED", "Abandoned"), ("DRILLING", "Drilling"),
        ("COMPLETED", "Completed"), ("DRY", "Dry hole"),
        ("LOCATION", "Location / permitted"), ("PERMITTED", "Permitted"),
        ("CANCELLED", "Cancelled"), ("UNKNOWN", "Unknown"),
    ],
    "well_type": [
        ("OIL", "Oil well"), ("GAS", "Gas well"),
        ("OIL_GAS", "Oil and gas well"),
        ("INJECTION", "Injection well"), ("DISPOSAL", "Disposal well"),
        ("WATER", "Water well"), ("WATER_SUPPLY", "Water supply well"),
        ("OBSERVATION", "Observation well"),
        ("STRATIGRAPHIC", "Stratigraphic test"),
        ("SERVICE", "Service well"), ("STORAGE", "Storage well"),
        ("GEOTHERMAL", "Geothermal well"), ("DRY_HOLE", "Dry hole"),
        ("EXPLORATION", "Exploration well"),
        ("DEVELOPMENT", "Development well"), ("UNKNOWN", "Unknown"),
    ],
    "depth_datum": [
        ("KB", "Kelly bushing"), ("DF", "Derrick floor"),
        ("RT", "Rotary table"), ("GL", "Ground level"),
        ("GR", "Ground"), ("MSL", "Mean sea level"),
        ("CF", "Casing flange"), ("THF", "Tubing head flange"),
        ("UNKNOWN", "Unknown"),
    ],
}

# map a ref-table suffix (after 'dv_r_') or a ref-col name to a CATALOG key
ALIASES = {
    "uom": "uom", "unit": "uom", "uom_code": "uom", "units": "uom",
    "source": "source", "data_source": "source", "source_code": "source",
    "well_status": "well_status", "status": "well_status",
    "wellstatus": "well_status", "well_status_code": "well_status",
    "well_type": "well_type", "type": "well_type", "welltype": "well_type",
    "well_type_code": "well_type",
    "depth_datum": "depth_datum", "datum": "depth_datum",
    "depth_datum_type": "depth_datum", "elevation_datum": "depth_datum",
}

_NUMERIC = {"int", "bigint", "smallint", "tinyint", "decimal", "numeric",
            "float", "real", "money", "smallmoney", "bit"}
_DATELIKE = {"date", "datetime", "datetime2", "smalldatetime",
             "datetimeoffset", "time"}
_GETDATE = "__GETDATE__"


def _connect(server, database):
    import pyodbc
    return pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={server};DATABASE={database};Trusted_Connection=yes",
        autocommit=False, timeout=15)


def _ref_fk_targets(cur):
    """Distinct (ref_table, ref_col, [(local_table, local_col)…]) for every FK
    that points at a dataview.dv_r_* table."""
    cur.execute(
        "SELECT rt.name, cref.name, pt.name, cpa.name "
        "FROM sys.foreign_keys fk "
        "JOIN sys.foreign_key_columns fkc "
        "       ON fkc.constraint_object_id = fk.object_id "
        "JOIN sys.tables  rt ON rt.object_id = fk.referenced_object_id "
        "JOIN sys.schemas rs ON rs.schema_id = rt.schema_id "
        "JOIN sys.tables  pt ON pt.object_id = fk.parent_object_id "
        "JOIN sys.columns cref ON cref.object_id = fkc.referenced_object_id "
        "                     AND cref.column_id = fkc.referenced_column_id "
        "JOIN sys.columns cpa  ON cpa.object_id = fkc.parent_object_id "
        "                     AND cpa.column_id = fkc.parent_column_id "
        "WHERE rs.name = ? AND rt.name LIKE 'dv[_]r[_]%'", SCHEMA)
    out = {}
    for ref_t, ref_c, loc_t, loc_c in cur.fetchall():
        out.setdefault((ref_t, ref_c), []).append((loc_t, loc_c))
    return out


def _columns(cur, table):
    cur.execute(
        "SELECT COLUMN_NAME, IS_NULLABLE, "
        "  CASE WHEN COLUMN_DEFAULT IS NULL THEN 0 ELSE 1 END, DATA_TYPE "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
        SCHEMA, table)
    return [(n, (nl == "YES"), bool(hd), dt.lower()) for n, nl, hd, dt in cur.fetchall()]


def _catalog_key(ref_table, ref_col):
    suffix = ref_table[len("dv_r_"):].lower() if ref_table.lower().startswith("dv_r_") else ref_table.lower()
    for cand in (suffix, ref_col.lower()):
        if cand in CATALOG:
            return cand
        if cand in ALIASES:
            return ALIASES[cand]
    return None


def _row_values(cols, ref_col, code, descr):
    """Build {column: value} for one reference row, filling required columns so
    the INSERT satisfies NOT NULL whatever the table's exact shape is."""
    by_lower = {c[0].lower(): c for c in cols}
    vals = {}
    # the code column
    real_code_col = by_lower.get(ref_col.lower(), (ref_col,))[0]
    vals[real_code_col] = code
    # a human-readable column, if the table has one
    for cand in ("long_name", "description", "name", "uom"):
        if cand in by_lower and by_lower[cand][0] not in vals:
            vals[by_lower[cand][0]] = descr
            break
    if "short_name" in by_lower and by_lower["short_name"][0] not in vals:
        vals[by_lower["short_name"][0]] = code
    if "abbreviation" in by_lower and by_lower["abbreviation"][0] not in vals:
        vals[by_lower["abbreviation"][0]] = code
    # fill remaining NOT NULL / known audit columns
    for name, nullable, hasdef, dtype in cols:
        if name in vals:
            continue
        ln = name.lower()
        if ln in ("active_ind", "active_flag", "active", "is_active"):
            vals[name] = "Y"
        elif ln in ("row_created_by", "row_changed_by", "created_by",
                    "changed_by", "row_updated_by", "updated_by"):
            vals[name] = "SEED"
        elif ln in ("row_created_date", "row_changed_date", "created_date",
                    "changed_date", "created_at", "updated_at",
                    "row_updated_date"):
            vals[name] = _GETDATE
        elif not nullable and not hasdef:
            if dtype in _NUMERIC:
                vals[name] = 0
            elif dtype in _DATELIKE:
                vals[name] = _GETDATE
            else:
                vals[name] = ""        # empty string for unknown NOT NULL text
    return vals


def _insert_sql(table, ref_col, vals):
    cols, ph, params = [], [], []
    for c, v in vals.items():
        cols.append(f"[{c}]")
        if v == _GETDATE:
            ph.append("GETDATE()")
        else:
            ph.append("?")
            params.append(v)
    sql = (f"INSERT INTO {SCHEMA}.[{table}] ({', '.join(cols)}) "
           f"SELECT {', '.join(ph)} WHERE NOT EXISTS "
           f"(SELECT 1 FROM {SCHEMA}.[{table}] WHERE [{ref_col}] = ?)")
    params.append(vals_code(vals, ref_col))
    return sql, params


def vals_code(vals, ref_col):
    for c, v in vals.items():
        if c.lower() == ref_col.lower():
            return v
    return None


def _seed_table(cur, table, ref_col, pairs, dry):
    cols = _columns(cur, table)
    if not cols:
        return 0, "table not found"
    seeded = 0
    for code, descr in pairs:
        vals = _row_values(cols, ref_col, code, descr)
        sql, params = _insert_sql(table, ref_col, vals)
        if dry:
            cur.execute(f"SELECT CASE WHEN EXISTS (SELECT 1 FROM {SCHEMA}.[{table}] "
                        f"WHERE [{ref_col}] = ?) THEN 0 ELSE 1 END", code)
            seeded += cur.fetchone()[0]
        else:
            cur.execute(sql, *params)
            seeded += cur.rowcount or 0
    return seeded, "ok"


def _observed_unmatched(cur, ref_table, ref_col, locals_):
    """Distinct values present in the referencing columns that AREN'T in the
    reference yet — i.e. what would hold on promote. Reported, not auto-seeded."""
    found = {}
    for loc_t, loc_c in locals_:
        # only look at catalog mirrors / dv tables that exist
        cur.execute("SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
                    "WHERE TABLE_NAME = ?", loc_t)
        if not cur.fetchone():
            continue
        try:
            cur.execute(
                f"SELECT DISTINCT m.[{loc_c}] FROM {SCHEMA}.[{loc_t}] m "
                f"WHERE m.[{loc_c}] IS NOT NULL AND LTRIM(RTRIM(m.[{loc_c}])) <> '' "
                f"AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.[{ref_table}] r "
                f"WHERE r.[{ref_col}] = m.[{loc_c}])")
            for (v,) in cur.fetchall():
                found.setdefault(str(v), []).append(f"{loc_t}.{loc_c}")
        except Exception:
            # local table may live in file_catalog, not dataview — skip quietly
            pass
    return found


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default=r"PERRY\SQLEXPRESS")
    ap.add_argument("--database", default="DataView_Demo")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would seed; write nothing")
    ap.add_argument("--seed-observed", action="store_true",
                    help="ALSO seed values found in your data that aren't "
                         "standard (otherwise they're only reported)")
    a = ap.parse_args()

    try:
        import pyodbc  # noqa: F401
    except ImportError:
        print("pyodbc not installed in this Python — run from the venv that has it.")
        return 2

    cn = _connect(a.server, a.database)
    cur = cn.cursor()
    print(f"seed_references · {a.server}/{a.database} · schema {SCHEMA}"
          f"{'  (DRY RUN)' if a.dry_run else ''}\n")

    targets = _ref_fk_targets(cur)
    if not targets:
        print("No dv_r_* foreign-key targets found — is the schema created?")
        return 1

    total = 0
    unseeded_tables, report_unmatched = [], []
    for (ref_t, ref_c), locals_ in sorted(targets.items()):
        key = _catalog_key(ref_t, ref_c)
        if key:
            n, status = _seed_table(cur, ref_t, ref_c, CATALOG[key], a.dry_run)
            total += n
            print(f"  {ref_t:28} [{ref_c}]  +{n} {('(would add)' if a.dry_run else 'added')}"
                  f"  ← {key}")
        else:
            unseeded_tables.append((ref_t, ref_c))
        # what's still unmatched in the actual data?
        obs = _observed_unmatched(cur, ref_t, ref_c, locals_)
        if obs:
            report_unmatched.append((ref_t, ref_c, obs))

    # optionally seed data-observed values too (off by default — governance)
    if a.seed_observed and report_unmatched:
        print("\nseeding data-observed values (--seed-observed):")
        for ref_t, ref_c, obs in report_unmatched:
            pairs = [(code, code) for code in obs]
            n, _ = _seed_table(cur, ref_t, ref_c, pairs, a.dry_run)
            total += n
            print(f"  {ref_t:28} [{ref_c}]  +{n} observed")

    if not a.dry_run:
        cn.commit()

    if unseeded_tables:
        print("\nreferenced reference tables with NO curated standard set "
              "(seed manually if your data uses them):")
        for ref_t, ref_c in unseeded_tables:
            print(f"  - {ref_t} [{ref_c}]")

    if report_unmatched and not a.seed_observed:
        print("\nvalues in your data NOT resolved by the standard set "
              "(resolve explicitly — add to reference or map to canonical):")
        for ref_t, ref_c, obs in report_unmatched:
            sample = ", ".join(sorted(obs)[:12])
            more = f"  …(+{len(obs) - 12} more)" if len(obs) > 12 else ""
            print(f"  {ref_t} [{ref_c}] — {len(obs)} unmatched: {sample}{more}")

    print(f"\n{'would seed' if a.dry_run else 'seeded'} {total} reference row(s).")
    cn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

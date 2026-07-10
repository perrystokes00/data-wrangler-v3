"""
spatial_seeder.py
=================
Bulk seeds the geographic reference tables (dv_country, dv_province_state,
dv_county) used by dv_well's country / province_state / county FKs.

Codes are API Bulletin D12A (the petroleum standard the well API/UWI numbers are
built from) — NOT FIPS. county_id is the 5-digit API code (api_state+api_county,
e.g. '42329' = Midland, TX). The fips_* columns are a crosswalk, populated only
where an onshore match exists (null for offshore areas / Alaska quadrangles).

Data lives in three CSVs beside this module (geo_country.csv,
geo_province_state.csv, geo_county.csv).

Seed order respects FK deps:
  1. dv_country          (no FK to other geo)
  2. dv_province_state   (FK -> dv_country)
  3. dv_county           (FK -> dv_country, dv_province_state)

Usage (mirrors entity_seeder):
    from dataview.mapping.spatial_seeder import seed_spatial
    seed_spatial(engine, loader_tag="IMPORTER")
"""
from __future__ import annotations

import csv
from pathlib import Path

CHUNK_SIZE = 2000
_DATA = Path(__file__).parent


def _load_csv(name: str) -> list[dict]:
    with open(_DATA / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _n(v):
    """Empty string -> None (so NULLs land in the FIPS/abbrev columns)."""
    return v if (v is not None and v != "") else None


def seed_spatial(engine, loader_tag: str = "SPATIAL_SEEDER") -> None:
    """
    Seed dv_country, dv_province_state, dv_county with D12A reference data.
    Idempotent — IF NOT EXISTS on every row, safe to call on every load.
    """
    print("  Seeding spatial tables (dv_country, dv_province_state, dv_county)...")

    results = {
        "dv_country": _seed_table(
            engine, "dataview", "dv_country", "country_code",
            _COUNTRY_SPEC, _load_csv("geo_country.csv"), loader_tag),
        "dv_province_state": _seed_table(
            engine, "dataview", "dv_province_state", "province_state_id",
            _PROVINCE_SPEC, _load_csv("geo_province_state.csv"), loader_tag),
        "dv_county": _seed_table(
            engine, "dataview", "dv_county", "county_id",
            _COUNTY_SPEC, _load_csv("geo_county.csv"), loader_tag),
    }

    for tbl, r in results.items():
        if r["skipped"]:
            print(f"  {tbl}: dropped columns not in schema -> "
                  f"{', '.join(r['skipped'])}")
        if r["error"]:
            print(f"  {tbl}: ERROR -> {r['error']}")
        print(f"  {tbl}: {r['count']} rows in table")
    print("  Spatial tables seeded.")
    return results


# Column spec entries: (table_column, kind, arg)
#   kind "csv": arg = (csv_field, use_n)  -> bound parameter from the CSV row
#   kind "tag": arg = None                -> bound parameter = loader_tag
#   kind "lit": arg = sql_text            -> inline SQL literal (no parameter)
# Any spec column not present in the actual table is dropped automatically, so
# the seeder tolerates schema drift (e.g. a build without api_state_code).
_AUDIT = [
    ("active_ind",       "lit", "'Y'"),
    ("row_created_by",   "tag", None),
    ("row_created_date", "lit", "GETDATE()"),
    ("row_changed_by",   "tag", None),
    ("row_changed_date", "lit", "GETDATE()"),
]
_COUNTRY_SPEC = [
    ("country_code",    "csv", ("country_code", False)),
    ("country_code_a2", "csv", ("country_code_a2", True)),
    ("country_name",    "csv", ("country_name", False)),
] + _AUDIT
_PROVINCE_SPEC = [
    ("province_state_id",     "csv", ("province_state_id", False)),
    ("country_code",          "csv", ("country_code", False)),
    ("province_state_name",   "csv", ("province_state_name", False)),
    ("province_state_abbrev", "csv", ("province_state_abbrev", True)),
    ("province_state_type",   "csv", ("province_state_type", True)),
    ("fips_code",             "csv", ("fips_code", True)),
    ("api_state_code",        "csv", ("api_state_code", True)),
] + _AUDIT
_COUNTY_SPEC = [
    ("county_id",         "csv", ("county_id", False)),
    ("province_state_id", "csv", ("province_state_id", False)),
    ("country_code",      "csv", ("country_code", False)),
    ("county_name",       "csv", ("county_name", False)),
    ("county_type",       "csv", ("county_type", True)),
    ("fips_state_code",   "csv", ("fips_state_code", True)),
    ("fips_county_code",  "csv", ("fips_county_code", True)),
    ("fips_full",         "csv", ("fips_full", True)),
    ("api_state_code",    "csv", ("api_state_code", True)),
    ("api_county_code",   "csv", ("api_county_code", True)),
] + _AUDIT


def _table_columns(cur, schema: str, table: str) -> set:
    cur.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?", (schema, table))
    return {r[0].lower() for r in cur.fetchall()}


def _seed_table(engine, schema, table, pk, spec, rows, loader_tag) -> dict:
    """Idempotent insert of `rows` into schema.table, using only the spec
    columns that actually exist. Returns {count, skipped, error}."""
    fq = f"{schema}.{table}"
    out = {"count": 0, "skipped": [], "error": None}
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        actual = _table_columns(cur, schema, table)
        usable = [c for c in spec if c[0].lower() in actual]
        out["skipped"] = [c[0] for c in spec if c[0].lower() not in actual]

        cols_sql = ", ".join(c[0] for c in usable)
        vals_sql = ", ".join("?" if c[1] in ("csv", "tag") else c[2]
                             for c in usable)
        sql = (f"IF NOT EXISTS (SELECT 1 FROM {fq} WHERE {pk} = ?) "
               f"INSERT INTO {fq} ({cols_sql}) VALUES ({vals_sql})")

        def _resolve(c, row):
            if c[1] == "tag":
                return loader_tag
            field, use_n = c[2]
            v = row.get(field)
            return _n(v) if use_n else v

        params = []
        for row in rows:
            p = [row.get(pk)]
            p += [_resolve(c, row) for c in usable if c[1] in ("csv", "tag")]
            params.append(tuple(p))

        cur.fast_executemany = True
        for i in range(0, len(params), CHUNK_SIZE):
            cur.executemany(sql, params[i:i + CHUNK_SIZE])
            raw.commit()

        cur.execute(f"SELECT COUNT(*) FROM {fq}")
        out["count"] = int(cur.fetchone()[0])
        cur.close()
    except Exception as e:
        raw.rollback()
        out["error"] = str(e)
        try:                                   # best-effort count after failure
            c2 = raw.cursor()
            c2.execute(f"SELECT COUNT(*) FROM {fq}")
            out["count"] = int(c2.fetchone()[0])
            c2.close()
        except Exception:
            pass
    finally:
        raw.close()
    return out


def _engine(server: str, database: str):
    """SQLAlchemy engine (seed_spatial uses engine.raw_connection())."""
    import urllib.parse
    from sqlalchemy import create_engine
    odbc = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};"
            f"DATABASE={database};Trusted_Connection=yes")
    return create_engine(
        "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(odbc))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Seed dv_country / dv_province_state / dv_county "
                    "(API Bulletin D12A reference data) into a DataView "
                    "database. Idempotent — safe to re-run after a reset.")
    ap.add_argument("--server", default=r"PERRY\SQLEXPRESS")
    ap.add_argument("--database", default="DataView_Demo")
    ap.add_argument("--loader-tag", default="SPATIAL_SEEDER")
    args = ap.parse_args()

    missing = [c for c in ("geo_country.csv", "geo_province_state.csv",
                           "geo_county.csv") if not (_DATA / c).exists()]
    if missing:
        raise SystemExit(
            "Missing reference CSV(s) beside spatial_seeder.py: "
            + ", ".join(missing)
            + "\n(They must sit in the same folder as this script.)")

    print(f"Seeding spatial reference into [{args.database}] on {args.server}")
    res = seed_spatial(_engine(args.server, args.database),
                       loader_tag=args.loader_tag)
    print("Done.")
    if any(v["error"] for v in res.values()):
        raise SystemExit(1)

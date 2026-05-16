"""
build_well_geojson.py
=====================
Generates a static wells.geojson file from dataview.dv_well and
dataview_gom.well. Run nightly via Task Scheduler or on-demand.

Usage:
    python build_well_geojson.py
    python build_well_geojson.py --out C:\\DataView\\wells.geojson
    python build_well_geojson.py --schema dataview
    python build_well_geojson.py --schema gom

The output file is loaded by the well map at startup — no database
query required on map load.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from sqlalchemy import create_engine, text
except ImportError:
    sys.exit("pip install sqlalchemy pyodbc")


# ── Default connection (same as app_v3.py) ────────────────────────────────

DEFAULT_CONN = (
    "mssql+pyodbc://127.0.0.1\\SQLEXPRESS/DataView"
    "?driver=ODBC+Driver+17+for+SQL+Server"
    "&trusted_connection=yes"
    "&TrustServerCertificate=yes"
)


def build_geojson(engine, schema: str = "all") -> dict:
    """Query dv_well and/or GOM wells, return a GeoJSON FeatureCollection."""
    all_wells = []

    # ── dataview.dv_well ──────────────────────────────────────────────
    if schema in ("all", "dataview"):
        sql = """
            SELECT w.uwi, w.well_name, w.api_num,
                   w.surface_latitude, w.surface_longitude,
                   w.county, w.province_state, w.well_status,
                   w.well_type, w.source, w.area,
                   ISNULL(ba.ba_name, '') AS operator_name,
                   ISNULL(f.field_name, '') AS field_name,
                   ISNULL(f.basin_name, '') AS basin_name,
                   CONVERT(VARCHAR(10), w.spud_date, 120) AS spud_date,
                   w.final_td,
                   'dataview' AS _schema
            FROM dataview.dv_well w
            LEFT JOIN dataview.dv_business_associate ba
                   ON ba.ba_id = w.operator_ba_id
            LEFT JOIN dataview.dv_field f
                   ON f.field_id = w.field_id
            WHERE w.surface_latitude IS NOT NULL
              AND w.surface_longitude IS NOT NULL
            FOR JSON PATH
        """
        try:
            with engine.connect() as con:
                result = con.execute(text(sql))
                chunks = [row[0] for row in result if row[0]]
                if chunks:
                    all_wells.extend(json.loads("".join(chunks)))
                    print(f"  dataview.dv_well: {len(all_wells):,} wells")
        except Exception as e:
            print(f"  dataview.dv_well query failed: {e}")

    # ── dataview_gom.well ─────────────────────────────────────────────
    if schema in ("all", "gom"):
        sql_gom = """
            SELECT CONVERT(VARCHAR(36), w.well_id) AS uwi,
                   w.well_name,
                   w.api_well_number AS api_num,
                   w.surface_latitude,
                   w.surface_longitude,
                   CAST('' AS NVARCHAR(100)) AS county,
                   w.region AS province_state,
                   ISNULL(w.status_code, '') AS well_status,
                   ISNULL(w.type_code, '') AS well_type,
                   'GOM' AS source,
                   'Gulf of America' AS area,
                   ISNULL(w.company_name, '') AS operator_name,
                   ISNULL(w.bottom_area_code, '') AS field_name,
                   '' AS basin_name,
                   CONVERT(VARCHAR(10), w.spud_date, 120) AS spud_date,
                   w.bh_total_md_ft AS final_td,
                   'gom' AS _schema
            FROM dataview_gom.well w
            WHERE w.surface_latitude IS NOT NULL
              AND w.surface_longitude IS NOT NULL
            FOR JSON PATH
        """
        n_before = len(all_wells)
        try:
            with engine.connect() as con:
                result = con.execute(text(sql_gom))
                chunks = [row[0] for row in result if row[0]]
                if chunks:
                    all_wells.extend(json.loads("".join(chunks)))
                    print(f"  dataview_gom.well: {len(all_wells) - n_before:,} wells")
        except Exception as e:
            print(f"  dataview_gom.well query failed (may not exist): {e}")

    # ── Build GeoJSON ─────────────────────────────────────────────────
    features = []
    for w in all_wells:
        lat = w.get("surface_latitude")
        lon = w.get("surface_longitude")
        if lat is None or lon is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "uwi":      w.get("uwi", ""),
                "name":     w.get("well_name", ""),
                "api":      w.get("api_num", ""),
                "operator": w.get("operator_name", ""),
                "field":    w.get("field_name", ""),
                "basin":    w.get("basin_name", ""),
                "county":   w.get("county", ""),
                "state":    w.get("province_state", ""),
                "status":   w.get("well_status", ""),
                "type":     w.get("well_type", ""),
                "source":   w.get("source", ""),
                "area":     w.get("area", ""),
                "spud":     w.get("spud_date", ""),
                "td":       w.get("final_td"),
                "schema":   w.get("_schema", ""),
            },
        })

    geojson = {
        "type": "FeatureCollection",
        "metadata": {
            "generated": datetime.now(timezone.utc).isoformat(),
            "total_wells": len(features),
            "schemas": schema,
        },
        "features": features,
    }
    return geojson


def main():
    ap = argparse.ArgumentParser(
        description="Build wells.geojson from DataView database")
    ap.add_argument("--out", default="wells.geojson",
                    help="Output file path (default: wells.geojson in current dir)")
    ap.add_argument("--schema", default="all",
                    choices=["all", "dataview", "gom"],
                    help="Which schema(s) to include")
    ap.add_argument("--conn", default=DEFAULT_CONN,
                    help="SQLAlchemy connection string")
    args = ap.parse_args()

    print(f"Connecting to database…")
    engine = create_engine(args.conn)

    print(f"Querying wells (schema={args.schema})…")
    geojson = build_geojson(engine, schema=args.schema)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(geojson), encoding="utf-8")

    n = geojson["metadata"]["total_wells"]
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\nDone: {n:,} wells → {out_path.resolve()} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()

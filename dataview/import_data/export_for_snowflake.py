"""
export_for_snowflake.py — Export wells to CSV for Snowflake upload.

Usage:
    python export_for_snowflake.py
    python export_for_snowflake.py --source tx
    python export_for_snowflake.py --limit 10000
"""
import argparse, os, sys, time
from pathlib import Path

try:
    import pyodbc
except ImportError:
    sys.exit("pip install pyodbc")

OUT_DIR = Path(r"C:\Bulk\snowflake_export")


def export(cursor, label, sql, csv_path):
    print(f"\n── {label} ──────────────────────────────────")
    t0 = time.time()
    print(f"  Querying…", flush=True)

    try:
        cursor.execute(sql)
    except Exception as e:
        print(f"  QUERY ERROR: {e}")
        return 0

    columns = [desc[0] for desc in cursor.description]
    total = 0
    bar_w = 40

    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(",".join(columns) + "\n")
        while True:
            rows = cursor.fetchmany(10000)
            if not rows:
                break
            for row in rows:
                vals = []
                for v in row:
                    if v is None:
                        vals.append("")
                    else:
                        s = str(v).replace(",", " ").replace("\n", " ").replace("\r", "").replace('"', "'")
                        vals.append(s)
                f.write(",".join(vals) + "\n")
            total += len(rows)
            mb = os.path.getsize(csv_path) / (1024*1024)
            filled = min(bar_w, int(total / 25000))
            bar = chr(9608) * filled + chr(9617) * (bar_w - filled)
            print(f"\r  [{bar}] {total:>10,} rows  {mb:>6.1f} MB", end="", flush=True)

    mb = os.path.getsize(csv_path) / (1024*1024)
    bar = chr(9608) * bar_w
    print(f"\r  [{bar}] {total:>10,} rows  {mb:>6.1f} MB  ({time.time()-t0:.1f}s)")
    print(f"  → {csv_path}")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="all", choices=["all","tx","ks","nd","osdu","gom"])
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    top = f"TOP {args.limit}" if args.limit else ""

    print("WranglerView — Export for Snowflake")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        "SERVER=127.0.0.1\\SQLEXPRESS;"
        "DATABASE=DataView;"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )

    sources = []
    if args.source in ("all", "tx"):
        sources.append(("Texas RRC", f"SELECT {top} uwi, api_num, well_name, operator_name, field_name, surface_latitude, surface_longitude, county, province_state, well_status, well_type, CONVERT(VARCHAR(10), spud_date, 120) AS spud_date, CONVERT(VARCHAR(10), completion_date, 120) AS completion_date, final_td, source, area FROM dataview.dv_well WHERE source = 'RRC_TX_SHP' AND surface_latitude IS NOT NULL", "raw_tx_well.csv"))
    if args.source in ("all", "ks"):
        sources.append(("Kansas KGS", f"SELECT {top} uwi, api_num, well_name, operator_name, field_name, surface_latitude, surface_longitude, county, province_state, well_status, well_type, CONVERT(VARCHAR(10), spud_date, 120) AS spud_date, CONVERT(VARCHAR(10), completion_date, 120) AS completion_date, final_td, source, area FROM dataview.dv_well WHERE source = 'KGS_GEOJSON'", "raw_ks_well.csv"))
    if args.source in ("all", "nd"):
        sources.append(("North Dakota", f"SELECT {top} uwi, api_num, well_name, operator_name, field_name, surface_latitude, surface_longitude, county, province_state, well_status, well_type, CONVERT(VARCHAR(10), spud_date, 120) AS spud_date, CONVERT(VARCHAR(10), completion_date, 120) AS completion_date, final_td, source, area FROM dataview.dv_well WHERE source = 'NDIC'", "raw_nd_well.csv"))
    if args.source in ("all", "osdu"):
        sources.append(("OSDU", f"SELECT {top} uwi, api_num, well_name, operator_name, field_name, surface_latitude, surface_longitude, county, province_state, well_status, well_type, CONVERT(VARCHAR(10), spud_date, 120) AS spud_date, CONVERT(VARCHAR(10), completion_date, 120) AS completion_date, final_td, source, area FROM dataview.dv_well WHERE source = 'OSDU'", "raw_osdu_well.csv"))
    if args.source in ("all", "gom"):
        sources.append(("BOEM GOM", f"SELECT {top} CONVERT(VARCHAR(36), well_id) AS well_id, api_well_number, well_name, company_name, region, bottom_area_code, bottom_block_number, surface_latitude, surface_longitude, bottom_latitude, bottom_longitude, bh_total_md_ft, true_vertical_depth_ft, CONVERT(VARCHAR(10), spud_date, 120) AS spud_date, status_code, type_code, water_depth_ft FROM dataview_gom.well WHERE surface_latitude IS NOT NULL", "raw_boem_well.csv"))

    t0 = time.time()
    grand = 0
    for label, sql, fname in sources:
        csv_path = str(OUT_DIR / fname)
        n = export(conn.cursor(), label, sql, csv_path)
        grand += n

    conn.close()
    print(f"\n  Total: {grand:,} rows in {time.time()-t0:.1f}s")
    print(f"  Files: {OUT_DIR}")


if __name__ == "__main__":
    main()

"""
load_rrc_maf016.py
==================
Standalone CLI loader for RRC MAF016 Master API File.
Uses the format_library + rrc_maf016 translator.

Download: https://mft.rrc.texas.gov/link/701db9a3-32b5-488d-812b-cd6ff7d0fe85

Usage:
    python load_rrc_maf016.py --file "training/Texas/maf016.cc003"
    python load_rrc_maf016.py --file "maf016.cc003" --county "130,310,240"
    python load_rrc_maf016.py --file "maf016.cc003" --db DataView_Test --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dw_utils import make_engine, dedup
from translators.tx_rrc_well_master import read


def main() -> None:
    ap = argparse.ArgumentParser(description="Load RRC MAF016 into DataView")
    ap.add_argument("--file",    required=True, help="Path to MAF016 file e.g. maf016.cc003")
    ap.add_argument("--county",  default=None,  help="Comma-separated RRC county codes e.g. 130,310,240")
    ap.add_argument("--db",      default="DataView", help="Target database (default: DataView)")
    ap.add_argument("--limit",   type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    county_filter = None
    if args.county:
        county_filter = {c.strip() for c in args.county.split(",")}

    rows, errors = read(args.file, limit=args.limit, county_filter=county_filter)

    if errors:
        print(f"\n{len(errors)} parse errors (first 10):")
        for e in errors[:10]:
            print(f"  {e}")

    if not rows:
        print("No rows parsed — check file path and county filter")
        sys.exit(1)

    rows = dedup(rows)
    print(f"After dedup: {len(rows):,} unique UWIs")

    # County breakdown
    cnts = {}
    for r in rows:
        cnts[r.get("county", "UNKNOWN")] = cnts.get(r.get("county", "UNKNOWN"), 0) + 1
    print("\nCounty breakdown:")
    for c, n in sorted(cnts.items(), key=lambda x: -x[1])[:15]:
        print(f"  {c or 'UNKNOWN':25} {n:,}")

    if args.dry_run:
        print("\nDRY RUN — first 5 rows:")
        for r in rows[:5]:
            print(f"  {r['uwi']} | {r['well_name'][:30]:30} | "
                  f"{r.get('_operator','')[:25]:25} | {r.get('well_status')}")
        return

    print(f"\nLoading into {args.db}...")
    engine = make_engine(args.db)

    import pandas as pd
    from sqlalchemy import text

    with engine.connect() as con:
        existing = set(
            pd.read_sql(text("SELECT uwi FROM dataview.dv_well"), con)["uwi"].tolist()
        )

    new_rows    = [r for r in rows if r["uwi"] not in existing]
    update_rows = [r for r in rows if r["uwi"] in existing]
    print(f"New: {len(new_rows):,}  |  Update: {len(update_rows):,}")

    INSERT_COLS = [
        "uwi", "well_name", "well_type", "well_status",
        "province_state", "country", "county",
        "operator_ba_id", "field_id",
        "final_td", "depth_datum",
        "spud_date", "completion_date", "api_num",
        "active_ind", "source", "row_created_by", "row_changed_by",
    ]

    # ── Seed business associates and fields first ─────────────────────
    print("Seeding entities...")
    from entity_seeder import seed_entities
    rows = seed_entities(rows, engine, source="RRC", loader_tag="TX_RRC_WELL_MASTER")

    inserted = errored = 0

    if new_rows:
        col_list     = ", ".join(f"[{c}]" for c in INSERT_COLS)
        placeholders = ", ".join("?" * len(INSERT_COLS))
        sql = (
            f"IF NOT EXISTS (SELECT 1 FROM dataview.dv_well WHERE [uwi]=?)\n"
            f"INSERT INTO dataview.dv_well ({col_list}) VALUES ({placeholders})"
        )
        chunk    = 2000
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.fast_executemany = True
            for i in range(0, len(new_rows), chunk):
                batch  = new_rows[i:i+chunk]
                params = [
                    tuple([r["uwi"]] + [r.get(c) for c in INSERT_COLS])
                    for r in batch
                ]
                try:
                    cursor.executemany(sql, params)
                    raw_conn.commit()
                    inserted += len(batch)
                    print(f"  Inserted {inserted:,} / {len(new_rows):,}...")
                except Exception as e:
                    raw_conn.rollback()
                    errored += len(batch)
                    print(f"  Chunk error: {e}")
            cursor.close()
        finally:
            raw_conn.close()

    if update_rows:
        update_sql = """
            UPDATE dataview.dv_well SET
                well_status     = COALESCE(?, well_status),
                final_td        = COALESCE(?, final_td),
                spud_date       = COALESCE(?, spud_date),
                completion_date = COALESCE(?, completion_date),
                api_num         = COALESCE(NULLIF(?,''), api_num),
                row_changed_by  = ?,
                row_changed_date= GETDATE()
            WHERE uwi = ?
        """
        updated  = 0
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.fast_executemany = True
            for i in range(0, len(update_rows), 2000):
                batch  = update_rows[i:i+2000]
                params = [(r.get("well_status"), r.get("final_td"),
                           r.get("spud_date"), r.get("completion_date"),
                           r.get("api_num"), "TX_RRC_WELL_MASTER", r["uwi"])
                          for r in batch]
                cursor.executemany(update_sql, params)
                raw_conn.commit()
                updated += len(batch)
            print(f"Updated {updated:,} existing wells")
            cursor.close()
        finally:
            raw_conn.close()

    print(f"\nDone — inserted {inserted:,}, updated {len(update_rows):,}, errored {errored:,}")


if __name__ == "__main__":
    main()

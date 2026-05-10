"""
load_kgs_wells.py
=================
Standalone CLI loader for Kansas Geological Survey well header CSV files.
Uses the format_library + kgs_well_header translator.

Usage:
    python load_kgs_wells.py --file "training/Kansas/ks_wells_test1.csv"
    python load_kgs_wells.py --file "ks_wells.csv" --db DataView_Test --dry-run
    python load_kgs_wells.py --file "ks_wells.csv" --limit 100
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add v3 root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dw_utils import make_engine, dedup
from translators.ks_kgs_well_header import read


def main() -> None:
    ap = argparse.ArgumentParser(description="Load KGS well header CSV into DataView")
    ap.add_argument("--file",    required=True, help="Path to KGS CSV file")
    ap.add_argument("--db",      default="DataView", help="Target database (default: DataView)")
    ap.add_argument("--limit",   type=int, default=None, help="Max rows to parse (testing)")
    ap.add_argument("--dry-run", action="store_true", help="Parse only, no DB writes")
    args = ap.parse_args()

    # ── Parse ─────────────────────────────────────────────────────────
    rows, errors = read(args.file, limit=args.limit)

    if errors:
        print(f"\n{len(errors)} parse errors (first 10):")
        for e in errors[:10]:
            print(f"  {e}")

    if not rows:
        print("No rows parsed — check file path and format")
        sys.exit(1)

    # ── Summary ───────────────────────────────────────────────────────
    rows = dedup(rows)
    print(f"\nAfter dedup: {len(rows):,} unique UWIs")

    # County breakdown
    cnts = {}
    for r in rows:
        cnts[r.get("county", "UNKNOWN")] = cnts.get(r.get("county", "UNKNOWN"), 0) + 1
    print("\nCounty breakdown:")
    for c, n in sorted(cnts.items(), key=lambda x: -x[1])[:15]:
        print(f"  {c or 'UNKNOWN':25} {n:,}")

    # Status breakdown
    statuses = {}
    for r in rows:
        statuses[r.get("well_status", "?")] = statuses.get(r.get("well_status", "?"), 0) + 1
    print("\nStatus breakdown:")
    for s, n in sorted(statuses.items(), key=lambda x: -x[1]):
        print(f"  {s:20} {n:,}")

    if args.dry_run:
        print("\nDRY RUN — first 5 rows:")
        for r in rows[:5]:
            print(f"  {r['uwi']} | {r['well_name'][:30]:30} | "
                  f"{r.get('_operator','')[:25]:25} | "
                  f"{r.get('county',''):15} | "
                  f"TD={r.get('final_td')} | {r.get('well_status')}")
        return

    # ── Load ──────────────────────────────────────────────────────────
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
        "surface_latitude", "surface_longitude",
        "active_ind", "source",
        "row_created_by", "row_changed_by",
    ]

    # ── Seed business associates and fields first ─────────────────────
    print("Seeding entities...")
    from entity_seeder import seed_entities
    rows = seed_entities(rows, engine, source="KGS", loader_tag="KS_KGS_LOADER")

    inserted = skipped = errored = 0

    if new_rows:
        col_list     = ", ".join(f"[{c}]" for c in INSERT_COLS)
        placeholders = ", ".join("?" * len(INSERT_COLS))
        sql = (
            f"IF NOT EXISTS (SELECT 1 FROM dataview.dv_well WHERE [uwi]=?)\n"
            f"INSERT INTO dataview.dv_well ({col_list}) VALUES ({placeholders})"
        )
        chunk = 2000
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
                well_status      = COALESCE(?, well_status),
                final_td         = COALESCE(?, final_td),
                spud_date        = COALESCE(?, spud_date),
                completion_date  = COALESCE(?, completion_date),
                operator_ba_id   = COALESCE(NULLIF(?,''), operator_ba_id),
                field_id         = COALESCE(NULLIF(?,''), field_id),
                surface_latitude = COALESCE(?, surface_latitude),
                surface_longitude= COALESCE(?, surface_longitude),
                row_changed_by   = ?,
                row_changed_date = GETDATE()
            WHERE uwi = ?
        """
        chunk    = 2000
        updated  = 0
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.fast_executemany = True
            for i in range(0, len(update_rows), chunk):
                batch  = update_rows[i:i+chunk]
                params = [
                    (
                        r.get("well_status"),
                        r.get("final_td"),
                        r.get("spud_date"),
                        r.get("completion_date"),
                        r.get("operator_ba_id"),
                        r.get("field_id"),
                        r.get("surface_latitude"),
                        r.get("surface_longitude"),
                        "KS_KGS_LOADER",
                        r["uwi"],
                    )
                    for r in batch
                ]
                cursor.executemany(update_sql, params)
                raw_conn.commit()
                updated += len(batch)
                print(f"  Updated {updated:,} / {len(update_rows):,}...")
            cursor.close()
        finally:
            raw_conn.close()
        print(f"Updated {updated:,} existing wells")

    print(f"\nDone — inserted {inserted:,}, updated {len(update_rows):,}, "
          f"skipped {skipped:,}, errored {errored:,}")


if __name__ == "__main__":
    main()

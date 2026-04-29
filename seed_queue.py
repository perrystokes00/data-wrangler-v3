"""
seed_queue.py  --  Seed CSV to Bulk Queue
==========================================
Reads a folder of seed CSV files, infers the target PPDM table from the
filename, and adds them to bulk_queue.json ready for the batch loader.

Usage:
    python seed_queue.py --seed-dir "C:\\path\\to\\seed_files"

Options:
    --seed-dir      Folder containing seed CSV files (required)
    --pattern       Glob pattern for files (default: *.csv)
    --mode          insert or upsert (default: insert)
    --clear         Clear existing queue before adding (flag)
    --dry-run       Print what would be queued without writing (flag)
"""

import argparse
import csv
import json
import pathlib
import sys
from datetime import datetime

_BASE_DIR   = pathlib.Path(__file__).parent
_QUEUE_FILE = _BASE_DIR / "bulk_queue.json"


def _infer_table(stem: str) -> str:
    """
    Convert CSV filename stem to PPDM table name.
    Examples:
        r_well_class           -> R_WELL_CLASS
        ppdm_unit_of_measure   -> PPDM_UNIT_OF_MEASURE
        seed_dbo_r_area_type   -> R_AREA_TYPE   (strips seed_dbo_ prefix)
        seed_dbo_area_country  -> AREA           (strips seed_dbo_ prefix)
    """
    s = stem.lower()
    # Strip common prefixes
    for prefix in ("seed_dbo_", "seed_", "dbo_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.upper()


def _get_pk_cols(table: str, rows: list) -> list:
    """
    Try to infer PK columns from known PPDM naming conventions.
    Falls back to first column.
    """
    if not rows:
        return []
    cols = list(rows[0].keys())

    # Known composite PKs
    composite = {
        "R_WELL_STATUS":   ["STATUS_TYPE", "STATUS"],
        "R_WELLBORE_SYMBOLS": ["FLUID_TYPE", "WELLBORE_STATUS"],
        "AREA_CONTAIN":    ["CONTAINING_AREA_ID", "CONTAINING_AREA_TYPE",
                            "CONTAINED_AREA_ID",  "CONTAINED_AREA_TYPE"],
    }
    if table.upper() in composite:
        return composite[table.upper()]

    # Standard PPDM single-col PK patterns
    pk_candidates = [
        c for c in cols if c.upper() in (
            table.upper().replace("R_", "") + "_TYPE",
            table.upper().replace("R_", "") + "_ID",
            table.upper().replace("R_", ""),
            table.upper() + "_ID",
        )
    ]
    if pk_candidates:
        return [pk_candidates[0]]

    # Try column that ends with _TYPE or _ID or matches table stem
    stem = table.upper().lstrip("R_").lstrip("PPDM_")
    for c in cols:
        cu = c.upper()
        if cu.endswith("_TYPE") or cu.endswith("_ID") or cu == stem:
            return [c]

    # Fallback — first column
    return [cols[0]]


def _load_queue() -> list:
    try:
        if _QUEUE_FILE.exists():
            return json.loads(_QUEUE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_queue(q: list):
    safe = [{k: v for k, v in j.items() if k != "last_result"} for j in q]
    _QUEUE_FILE.write_text(json.dumps(safe, indent=2), encoding="utf-8")


def build_queue(seed_dir: str, pattern: str = "*.csv", mode: str = "insert",
                clear: bool = False, dry_run: bool = False):

    seed_path = pathlib.Path(seed_dir)
    if not seed_path.exists():
        print(f"ERROR: seed-dir not found: {seed_path}")
        sys.exit(1)

    csv_files = sorted(seed_path.glob(pattern))
    if not csv_files:
        print(f"No files matching {pattern!r} in {seed_path}")
        sys.exit(0)

    queue = [] if clear else _load_queue()
    next_id = max((j.get("id", 0) for j in queue), default=0) + 1
    added = 0

    for f in csv_files:
        table = _infer_table(f.stem)

        # Read CSV
        try:
            with open(f, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                rows = [r for r in reader]
        except Exception as e:
            print(f"  SKIP {f.name}: read error — {e}")
            continue

        if not rows:
            print(f"  SKIP {f.name}: empty file")
            continue

        pk_cols = _get_pk_cols(table, rows)

        entry = {
            "id":           next_id,
            "file_path":    str(f),
            "file_name":    f.name,
            "target_table": table,
            "mode":         mode,
            "fingerprint":  "",
            "mapped_cols":  0,
            "status":       "ready",
            "added":        datetime.now().isoformat()[:19],
            "seed_mode":    True,        # tells run_job to use RTM-style insert
            "pk_columns":   pk_cols,
            "row_count":    len(rows),
        }

        if dry_run:
            print(f"  [DRY RUN] {f.name} -> {table} | pk={pk_cols} | {len(rows)} rows")
        else:
            queue.append(entry)
            print(f"  Queued: {f.name} -> {table} | pk={pk_cols} | {len(rows)} rows")
            next_id += 1
            added += 1

    if not dry_run:
        _save_queue(queue)
        print(f"\nDone — {added} file(s) added to queue. Run the batch loader to process.")
    else:
        print(f"\n[DRY RUN] {len(csv_files)} file(s) would be queued.")


def main():
    ap = argparse.ArgumentParser(description="Queue seed CSV files for bulk loading")
    ap.add_argument("--seed-dir", required=True,  help="Folder containing seed CSV files")
    ap.add_argument("--pattern",  default="*.csv", help="File glob pattern (default: *.csv)")
    ap.add_argument("--mode",     default="insert",choices=["insert","upsert"],
                    help="Load mode (default: insert)")
    ap.add_argument("--clear",    action="store_true", help="Clear queue before adding")
    ap.add_argument("--dry-run",  action="store_true", help="Preview without writing")
    args = ap.parse_args()

    build_queue(
        seed_dir = args.seed_dir,
        pattern  = args.pattern,
        mode     = args.mode,
        clear    = args.clear,
        dry_run  = args.dry_run,
    )


if __name__ == "__main__":
    main()

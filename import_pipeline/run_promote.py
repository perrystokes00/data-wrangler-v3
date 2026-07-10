"""Standalone promote — lift the POOL's cat_* rows into dv_*, without re-running
capture. Dry-run by default; pass --apply to execute.

  py run_promote.py            # dry-run: show what WOULD lift
  py run_promote.py --apply    # actually promote cat_* -> dv_*
"""
import argparse, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worker_core as wc
import promote_catalog as pc

ap = argparse.ArgumentParser()
ap.add_argument("--server", default=r"localhost\SQLEXPRESS")
ap.add_argument("--database", default="DataView_Demo")
ap.add_argument("--apply", action="store_true")
a = ap.parse_args()

engine = wc.make_engine(a.server, a.database)
raw = engine.raw_connection()
try:
    cur = raw.cursor()
    print(f"{'APPLY' if a.apply else 'DRY-RUN'} — promoting cat_* -> dv_* "
          f"on {a.database}\n")
    pc.run_promote(cur, None, a.apply, log=lambda m: print("  " + str(m)))
    if a.apply:
        raw.commit()
        print("\n[promote] committed.")
    else:
        raw.rollback()
        print("\n[promote] dry-run — nothing written.")
finally:
    raw.close()

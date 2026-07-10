"""
stage_timer.py  --  find out where the pipeline actually spends its time
========================================================================
Drop-in instrumentation. Wrap any stage or SQL statement and get a sorted
"slowest first" report with row counts and % of total wall-clock. No deps
beyond the stdlib; works with a pyodbc/sqlalchemy cursor or on its own.

Two ways to use it
------------------
1) Time arbitrary blocks of work (any stage):

    from stage_timer import StageTimer
    T = StageTimer("promote 42330000350000")
    with T.stage("dedup"):
        run_dedup()
    with T.stage("fk_resolution"):
        resolve_fks()
    with T.stage("enrich_from_gold"):
        enrich()
    with T.stage("bulk_load_sqlserver"):
        load()
    T.report()

2) Time individual SQL statements (captures rowcount automatically):

    T = StageTimer("promote header")
    T.exec(cur, "dedup delete",  "DELETE x FROM cat_well x WHERE ...")
    T.exec(cur, "fk operator",   "UPDATE s SET ba_id=... FROM stg s JOIN ...")
    T.exec(cur, "enrich gold",   "UPDATE w SET ... FROM dv_well w JOIN gold g ...", params)
    conn.commit()
    T.report()                       # prints table
    T.to_csv("promote_timings.csv")  # optional: keep a history to compare runs
"""
from __future__ import annotations
import time
import csv
import contextlib
from datetime import datetime


class StageTimer:
    def __init__(self, run_label: str = "", echo: bool = True):
        self.run_label = run_label
        self.echo = echo
        self.rows: list[dict] = []          # {stage, seconds, rowcount, ts}
        self._t0 = time.perf_counter()

    # ---- time an arbitrary block ------------------------------------------
    @contextlib.contextmanager
    def stage(self, label: str):
        t = time.perf_counter()
        rc = None
        try:
            yield self
        finally:
            dt = time.perf_counter() - t
            self._record(label, dt, rc)

    # ---- time a single SQL statement (and grab rowcount) ------------------
    def exec(self, cur, label: str, sql: str, params=None):
        t = time.perf_counter()
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        dt = time.perf_counter() - t
        rc = getattr(cur, "rowcount", None)
        self._record(label, dt, rc)
        return cur

    def _record(self, label, seconds, rowcount):
        self.rows.append({"stage": label, "seconds": round(seconds, 4),
                          "rowcount": rowcount,
                          "ts": datetime.now().isoformat(timespec="seconds")})
        if self.echo:
            rc = "" if rowcount in (None, -1) else f"  rows={rowcount:,}"
            print(f"  [{seconds:7.3f}s] {label}{rc}")

    # ---- summary ----------------------------------------------------------
    def total(self) -> float:
        return time.perf_counter() - self._t0

    def report(self):
        if not self.rows:
            print("(no stages timed)")
            return
        measured = sum(r["seconds"] for r in self.rows)
        wall = self.total()
        width = min(40, max(len(r["stage"]) for r in self.rows))
        print(f"\n=== timings: {self.run_label} ===")
        print(f"{'stage':<{width}}  {'seconds':>9}  {'%meas':>6}  rows")
        print("-" * (width + 30))
        for r in sorted(self.rows, key=lambda x: -x["seconds"]):
            pct = (r["seconds"] / measured * 100) if measured else 0
            rc = "" if r["rowcount"] in (None, -1) else f"{r['rowcount']:,}"
            print(f"{r['stage']:<{width}}  {r['seconds']:>9.3f}  "
                  f"{pct:>5.1f}%  {rc}")
        print("-" * (width + 30))
        print(f"{'measured total':<{width}}  {measured:>9.3f}")
        print(f"{'wall-clock total':<{width}}  {wall:>9.3f}  "
              f"(untimed gap: {wall - measured:.3f}s)")

    def to_csv(self, path: str):
        with open(path, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["run_label", "stage", "seconds",
                                               "rowcount", "ts"])
            if fh.tell() == 0:
                w.writeheader()
            for r in self.rows:
                w.writerow({"run_label": self.run_label, **r})

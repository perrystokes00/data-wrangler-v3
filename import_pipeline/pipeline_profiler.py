"""
pipeline_profiler.py  --  find every slow spot in the pipeline, empirically
===========================================================================
Two diagnostics in one, because the bottleneck might be anywhere:

  1. STAGE TIMING (Python side): wrap any pipeline stage and get wall-time
     PLUS the SQL Server logical-reads it burned (reads ≈ how much data it
     churned — the real tell for a scan-heavy stage).

  2. DMV ANALYSIS (SQL Server side): after a run, ask SQL Server itself —
       * which indexes it WISHES existed (usually THE fix for "generally slow")
       * which statements cost the most total time / reads
       * which tables are being SCANNED instead of seeked
       * how big each table actually is
     This covers EVERY stage that ran, even ones not wrapped, because the
     engine records all of it.

Usage
-----
    cd C:\\...\\data_wrangler_v3

    # A) Just analyze — run your NORMAL pipeline first, then this. Reports the
    #    slow statements + missing indexes across everything that ran.
    python pipeline_profiler.py --analyze-only

    # B) Profile promote end-to-end (runs run_promote under rollback, times it,
    #    then analyzes). Uses your real promote_catalog.run_promote.
    python pipeline_profiler.py --run-promote

    # C) Per-table breakdown of promote (times each dv_* table individually).
    python pipeline_profiler.py --run-promote --per-table

Wrap your OWN stages like this (scan, catalog, capture, vault, enrich, …):
    from pipeline_profiler import Profiler
    prof = Profiler(cur)
    with prof.stage("scan"):     run_scan(...)
    with prof.stage("catalog"):  run_catalog(...)
    with prof.stage("capture"):  run_capture(...)
    prof.report()
    from pipeline_profiler import analyze; analyze(cur, since)
"""
from __future__ import annotations
import argparse
import contextlib
import sys
import time
import pyodbc


# ── connection ──────────────────────────────────────────────────────────────
def connect(server, database):
    for drv in ("ODBC Driver 18 for SQL Server",
                "ODBC Driver 17 for SQL Server",
                "SQL Server Native Client 11.0", "SQL Server"):
        try:
            cs = (f"DRIVER={{{drv}}};SERVER={server};DATABASE={database};"
                  f"Trusted_Connection=yes;TrustServerCertificate=yes")
            conn = pyodbc.connect(cs, autocommit=False)
            cur = conn.cursor()
            cur.fast_executemany = True
            print(f"connected via: {drv}\n")
            return conn, cur
        except pyodbc.Error:
            continue
    sys.exit("Could not connect — check the ODBC driver name and server.")


def _session_stats(cur) -> dict:
    cur.execute("SELECT cpu_time, logical_reads, reads, writes "
                "FROM sys.dm_exec_sessions WHERE session_id = @@SPID")
    r = cur.fetchone()
    return {"cpu": r[0], "logical_reads": r[1], "reads": r[2], "writes": r[3]}


# ── stage timing ────────────────────────────────────────────────────────────
class Profiler:
    def __init__(self, cur, echo=True):
        self.cur = cur
        self.echo = echo
        self.rows = []

    @contextlib.contextmanager
    def stage(self, label):
        b = _session_stats(self.cur)
        t = time.perf_counter()
        try:
            yield self
        finally:
            dt = time.perf_counter() - t
            a = _session_stats(self.cur)
            rec = {"stage": label, "seconds": dt,
                   "logical_reads": a["logical_reads"] - b["logical_reads"],
                   "cpu_ms": a["cpu"] - b["cpu"]}
            self.rows.append(rec)
            if self.echo:
                print(f"  [{dt:8.3f}s] {label:<28} "
                      f"reads={rec['logical_reads']:>12,}  "
                      f"cpu={rec['cpu_ms']:>7}ms")

    def report(self):
        if not self.rows:
            return
        tot = sum(r["seconds"] for r in self.rows) or 1e-9
        w = min(34, max(len(r["stage"]) for r in self.rows))
        print(f"\n=== stage timing (slowest first) ===")
        print(f"{'stage':<{w}}  {'sec':>8}  {'%':>5}  {'logical_reads':>14}  {'cpu_ms':>8}")
        print("-" * (w + 44))
        for r in sorted(self.rows, key=lambda x: -x["seconds"]):
            print(f"{r['stage']:<{w}}  {r['seconds']:>8.3f}  "
                  f"{r['seconds']/tot*100:>4.0f}%  {r['logical_reads']:>14,}  "
                  f"{r['cpu_ms']:>8,}")
        print("-" * (w + 44))
        print(f"{'TOTAL':<{w}}  {tot:>8.3f}")


# ── DMV reports ─────────────────────────────────────────────────────────────
def report_missing_indexes(cur, top=20):
    print("\n=== indexes SQL Server WISHES existed (highest impact first) ===")
    try:
        cur.execute(f"""
            SELECT TOP ({top})
              CAST(ROUND(s.avg_total_user_cost * s.avg_user_impact
                   * (s.user_seeks + s.user_scans), 0) AS BIGINT) AS score,
              d.statement AS table_name,
              ISNULL(d.equality_columns, '') AS eq_cols,
              ISNULL(d.inequality_columns, '') AS ineq_cols,
              ISNULL(d.included_columns, '') AS incl_cols,
              s.user_seeks + s.user_scans AS uses,
              CAST(s.avg_user_impact AS INT) AS pct_improve
            FROM sys.dm_db_missing_index_group_stats s
            JOIN sys.dm_db_missing_index_groups g
                 ON s.group_handle = g.index_group_handle
            JOIN sys.dm_db_missing_index_details d
                 ON g.index_handle = d.index_handle
            WHERE d.database_id = DB_ID()
            ORDER BY score DESC
        """)
        rows = cur.fetchall()
        if not rows:
            print("  (none — either already well-indexed, or run the pipeline "
                  "first so SQL Server has something to recommend)")
            return
        for r in rows:
            print(f"\n  score {r.score:,}  ·  {r.uses} use(s)  ·  ~{r.pct_improve}% faster")
            print(f"    {r.table_name}")
            cols = r.eq_cols + ((", " + r.ineq_cols) if r.ineq_cols else "")
            print(f"    key: {cols}")
            if r.incl_cols:
                print(f"    include: {r.incl_cols}")
    except pyodbc.Error as e:
        print(f"  (could not read missing-index DMVs: {str(e).splitlines()[0]})")


def report_top_queries(cur, since, top=15):
    print(f"\n=== slowest statements since {since} (by total elapsed) ===")
    try:
        cur.execute(f"""
            SELECT TOP ({top})
              CAST(qs.total_elapsed_time/1000.0 AS DECIMAL(12,1)) AS total_ms,
              qs.execution_count AS execs,
              CAST(qs.total_elapsed_time/1000.0/qs.execution_count
                   AS DECIMAL(12,2)) AS avg_ms,
              qs.total_logical_reads AS reads,
              SUBSTRING(st.text, (qs.statement_start_offset/2)+1,
                ((CASE qs.statement_end_offset WHEN -1
                      THEN DATALENGTH(st.text)
                      ELSE qs.statement_end_offset END
                  - qs.statement_start_offset)/2)+1) AS stmt
            FROM sys.dm_exec_query_stats qs
            CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
            WHERE qs.last_execution_time >= ?
            ORDER BY qs.total_elapsed_time DESC
        """, since)
        rows = cur.fetchall()
        if not rows:
            print("  (nothing recorded since start — did a stage actually run?)")
            return
        for r in rows:
            stmt = " ".join((r.stmt or "").split())[:160]
            print(f"\n  {r.total_ms:>9} ms total · {r.execs:>4} exec · "
                  f"{r.avg_ms:>8} ms avg · {r.reads:>12,} reads")
            print(f"    {stmt}")
    except pyodbc.Error as e:
        print(f"  (could not read query-stats DMVs: {str(e).splitlines()[0]})")


def report_table_sizes(cur, schemas=("dataview", "file_catalog", "las_catalog"),
                        top=25):
    print("\n=== table sizes (biggest first) ===")
    try:
        inlist = ",".join(f"'{s}'" for s in schemas)
        cur.execute(f"""
            SELECT TOP ({top}) s.name + '.' + t.name AS tbl,
                   SUM(p.rows) AS rows,
                   CAST(SUM(a.total_pages)*8/1024.0 AS DECIMAL(12,1)) AS mb
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            JOIN sys.partitions p ON p.object_id = t.object_id
                 AND p.index_id IN (0,1)
            JOIN sys.allocation_units a ON a.container_id = p.partition_id
            WHERE s.name IN ({inlist})
            GROUP BY s.name, t.name
            ORDER BY SUM(p.rows) DESC
        """)
        print(f"  {'table':<45} {'rows':>12} {'MB':>9}")
        for r in cur.fetchall():
            print(f"  {r.tbl:<45} {r.rows:>12,} {r.mb:>9}")
    except pyodbc.Error as e:
        print(f"  (could not read size DMVs: {str(e).splitlines()[0]})")


def report_index_scans(cur, schemas=("dataview", "file_catalog", "las_catalog"),
                       top=20):
    print("\n=== tables taking SCANS (vs seeks) — scan-heavy = missing/unused index ===")
    try:
        inlist = ",".join(f"'{s}'" for s in schemas)
        cur.execute(f"""
            SELECT TOP ({top}) s.name + '.' + t.name AS tbl,
                   ISNULL(i.name, '(heap)') AS idx,
                   us.user_scans, us.user_seeks, us.user_lookups
            FROM sys.dm_db_index_usage_stats us
            JOIN sys.tables t ON t.object_id = us.object_id
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            LEFT JOIN sys.indexes i ON i.object_id = us.object_id
                 AND i.index_id = us.index_id
            WHERE us.database_id = DB_ID() AND s.name IN ({inlist})
              AND us.user_scans > 0
            ORDER BY us.user_scans DESC
        """)
        rows = cur.fetchall()
        if not rows:
            print("  (no scans recorded — run the pipeline first)")
            return
        print(f"  {'table':<40} {'index':<22} {'scans':>8} {'seeks':>8}")
        for r in rows:
            print(f"  {r.tbl:<40} {r.idx:<22} {r.user_scans:>8,} {r.user_seeks:>8,}")
    except pyodbc.Error as e:
        print(f"  (could not read index-usage DMVs: {str(e).splitlines()[0]})")


def analyze(cur, since):
    report_missing_indexes(cur)
    report_top_queries(cur, since)
    report_index_scans(cur)
    report_table_sizes(cur)


# ── promote drivers ─────────────────────────────────────────────────────────
def _silent(*_a, **_k):
    pass


def run_promote_whole(conn, cur, prof, apply):
    from promote_catalog import run_promote
    with prof.stage("run_promote (all)"):
        run_promote(cur, uwi=None, apply=apply, log=_silent)
    conn.rollback()


def run_promote_per_table(conn, cur, prof, apply):
    from promote_catalog import (discover_tables, promote_table,
                                 promote_seismic, promote_las_catalog)
    for dv in discover_tables(cur):
        with prof.stage(dv):
            promote_table(cur, dv, None, apply)
    with prof.stage("__seismic"):
        promote_seismic(cur, apply, _silent)
    with prof.stage("__las_curve"):
        promote_las_catalog(cur, apply, _silent)
    conn.rollback()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="localhost\\SQLEXPRESS")
    ap.add_argument("--database", default="DataView_Demo")
    ap.add_argument("--analyze-only", action="store_true",
                    help="skip running promote; just dump DMV reports")
    ap.add_argument("--run-promote", action="store_true",
                    help="run run_promote (under rollback), timed, then analyze")
    ap.add_argument("--per-table", action="store_true",
                    help="with --run-promote: time each dv_* table separately")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if (args.run_promote and args.database.strip().lower() == "dataview"
            and not args.force):
        sys.exit("Refusing to --run-promote against 'DataView' (prod). "
                 "Use DataView_Demo, or --force (it rolls back, but still).")

    conn, cur = connect(args.server, args.database)
    cur.execute("SELECT GETDATE()")
    since = cur.fetchone()[0]

    if args.run_promote or not args.analyze_only:
        prof = Profiler(cur)
        print("running promote (rolled back afterwards)...\n")
        if args.per_table:
            run_promote_per_table(conn, cur, prof, apply=True)
        else:
            run_promote_whole(conn, cur, prof, apply=True)
        prof.report()

    analyze(cur, since)
    conn.rollback()
    conn.close()
    print("\ndone — nothing committed.")


if __name__ == "__main__":
    main()

"""
BCP-backed bundle fetch.

The pyodbc/pandas read path is the bottleneck (the section queries are instant
in SQL Server but slow to marshal back into Python). This goes around it: each
section's SELECT runs server-side and streams to a flat file via bcp.exe, which
is then read into a DataFrame. fetch_bundle_bcp() returns the same
{section: DataFrame} shape as exporters.fetch_bundle, so it's a drop-in fast
fetch that every export format can ride.

Pattern mirrors the loaders: one open connection stages the selected UWIs in a
GLOBAL temp table (##dw_export_uwis) — kept alive so bcp's own connection can
see it — and each section is JOINed against it via a subquery.

Intermediate files use a TAB delimiter (invisible to the user; the final format
is produced by the normal writers), which avoids the comma-in-text problem raw
BCP-CSV would have. Auth assumes Windows/trusted (bcp -T).
"""
import os
import subprocess
import tempfile
import time

import pandas as pd

from dataview.import_data.exporters import _SECTION_SQL, _SECTION_ORDER

# bcp v16+ (do NOT use the old Driver-11 bcp on PATH). First existing wins.
_BCP_CANDIDATES = [
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\170\Tools\Binn\bcp.exe",
    r"C:\Program Files\Microsoft SQL Server\Client SDK\ODBC\180\Tools\Binn\bcp.exe",
    "bcp",  # PATH fallback
]

_STAGE = "##dw_export_uwis"


def _find_bcp(bcp_exe=None):
    if bcp_exe and os.path.exists(bcp_exe):
        return bcp_exe
    for cand in _BCP_CANDIDATES:
        if cand == "bcp" or os.path.exists(cand):
            return cand
    raise RuntimeError("bcp.exe not found. Pass bcp_exe=... explicitly.")


def _bcp_sql(section_sql, db):
    """Adapt a section's SELECT for bcp: resolve the :uwis list to a subquery on
    the staging temp table, and fully qualify the database (bcp's own connection
    has no DB context)."""
    sql = section_sql.replace(":uwis", f"(SELECT uwi FROM {_STAGE})")
    sql = sql.replace("dataview.dv_", f"[{db}].dataview.dv_")
    return sql


def _run_bcp_sections(engine, uwis, sections, out_dir, bcp_exe, verbose):
    """BCP each wanted section to a TAB-delimited file. Returns
    {section: (file_path, [col_names])}."""
    bcp = _find_bcp(bcp_exe)
    want = [s for s in _SECTION_ORDER
            if s in (set(sections) if sections is not None else set(_SECTION_SQL))
            and s in _SECTION_SQL]
    uwis = list(dict.fromkeys(str(u) for u in uwis if u is not None and str(u) != ""))
    results = {}

    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute("SELECT CONVERT(NVARCHAR(256), SERVERPROPERTY('ServerName')), DB_NAME()")
        srv, db = cur.fetchone()
        srv, db = str(srv), str(db)

        cur.execute(f"IF OBJECT_ID('tempdb..{_STAGE}') IS NOT NULL DROP TABLE {_STAGE}")
        cur.execute(f"CREATE TABLE {_STAGE} (uwi NVARCHAR(40) NOT NULL PRIMARY KEY)")
        try:
            cur.fast_executemany = True
        except Exception:
            pass
        if uwis:
            cur.executemany(f"INSERT INTO {_STAGE} (uwi) VALUES (?)", [(u,) for u in uwis])
        raw.commit()

        for key in want:
            sql = _bcp_sql(_SECTION_SQL[key], db)
            data_path = os.path.join(out_dir, f"_{key}.tsv")
            t0 = time.time()
            try:
                cur.execute(sql + " OFFSET 0 ROWS FETCH NEXT 1 ROWS ONLY")
                cols = [d[0] for d in cur.description]
                cur.fetchall()
            except Exception as e:
                if verbose:
                    print(f"[bcp] section '{key}' header probe failed: {e}")
                continue

            cmd = [bcp, sql, "queryout", data_path,
                   "-S", srv, "-T", "-c", "-t", "\t", "-r", "\n", "-C", "65001"]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                if verbose:
                    print(f"[bcp] section '{key}' FAILED:\n{proc.stdout}\n{proc.stderr}")
                continue

            results[key] = (data_path, cols)
            if verbose:
                print(f"[bcp] section '{key}': {time.time()-t0:.2f}s")

        cur.execute(f"IF OBJECT_ID('tempdb..{_STAGE}') IS NOT NULL DROP TABLE {_STAGE}")
        raw.commit()
    finally:
        raw.close()
    return results


def fetch_bundle_bcp(engine, uwis, sections=None, bcp_exe=None, verbose=True):
    """Fast drop-in for exporters.fetch_bundle (onshore SQL Server).
    Returns {section: DataFrame}; data is pulled via BCP, not pyodbc."""
    out = {}
    with tempfile.TemporaryDirectory(prefix="dw_bcp_") as td:
        files = _run_bcp_sections(engine, uwis, sections, td, bcp_exe, verbose)
        for key, (path, cols) in files.items():
            dtype = {"uwi": str} if "uwi" in cols else None
            try:
                out[key] = pd.read_csv(
                    path, sep="\t", names=cols, header=None,
                    na_values=[""], keep_default_na=True,
                    dtype=dtype, low_memory=False)
            except pd.errors.EmptyDataError:
                out[key] = pd.DataFrame(columns=cols)
            except Exception as e:
                if verbose:
                    print(f"[bcp] section '{key}' parse failed: {e}")
                out[key] = pd.DataFrame(columns=cols)

    want = set(sections) if sections is not None else set(_SECTION_SQL)
    for k in want:
        out.setdefault(k, pd.DataFrame())
    return out

"""
walk_bulk.py -- scan petroleum files, write CSV, BULK INSERT into SQL Server
Fastest possible pipeline for large file counts.

Usage:
    python walk_bulk.py \\server\share
    python walk_bulk.py \\server\share --threads 16
"""
import os, sys, csv, time, threading, queue, tempfile
from pathlib import Path
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
root    = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\perry"
threads = int(sys.argv[3]) if "--threads" in sys.argv else 10
tmp_csv = Path(tempfile.gettempdir()) / "petroleum_scan.csv"

EXTENSIONS = {
    '.las', '.lis', '.dlis', '.dlf', '.dis',
    '.segy', '.sgy', '.seg', '.p190', '.p90',
    '.pdf',
    '.shp', '.geojson', '.gpkg', '.kml', '.kmz',
    '.xlsx', '.xls', '.xlsm',
    '.docx', '.doc',
    '.csv', '.tsv',
    '.tif', '.tiff',
}

CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=127.0.0.1\\SQLEXPRESS;"
    "DATABASE=DataView;"
    "Trusted_Connection=yes;"
)

DDL = """
IF OBJECT_ID('tempdb..#petroleum_files') IS NOT NULL
    DROP TABLE #petroleum_files;
CREATE TABLE #petroleum_files (
    id          INT IDENTITY(1,1) PRIMARY KEY,
    file_path   NVARCHAR(1000) NOT NULL,
    file_name   NVARCHAR(260)  NOT NULL,
    extension   NVARCHAR(20)   NOT NULL,
    size_bytes  BIGINT,
    modified_dt NVARCHAR(20),
    scan_dt     DATETIME2 DEFAULT GETUTCDATE()
);
"""

# ── Shared state ──────────────────────────────────────────────────────────────
dir_queue     = queue.Queue()
result_queue  = queue.Queue()
dir_queue.put(root)

_file_count   = [0]
_folder_count = [0]
_error_count  = [0]
_active       = [threads]
_ext_counts   = {}
_lock         = threading.Lock()

# ── Worker ────────────────────────────────────────────────────────────────────
def worker():
    while True:
        try:
            dirpath = dir_queue.get(timeout=2.0)
        except queue.Empty:
            with _lock:
                _active[0] -= 1
            time.sleep(0.1)
            with _lock:
                if dir_queue.empty() and _active[0] == 0:
                    result_queue.put(None)
                    return
                _active[0] += 1
            continue

        with _lock:
            _folder_count[0] += 1

        try:
            with os.scandir(dirpath) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            dir_queue.put(entry.path)
                        else:
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in EXTENSIONS:
                                st = entry.stat()
                                mod = datetime.fromtimestamp(
                                    st.st_mtime, tz=timezone.utc
                                ).strftime("%Y-%m-%d %H:%M:%S")
                                result_queue.put((
                                    entry.path[:1000],
                                    entry.name[:260],
                                    ext,
                                    st.st_size,
                                    mod,
                                ))
                                with _lock:
                                    _file_count[0] += 1
                                    _ext_counts[ext] = _ext_counts.get(ext, 0) + 1
                    except OSError:
                        with _lock:
                            _error_count[0] += 1
        except (PermissionError, OSError):
            with _lock:
                _error_count[0] += 1

# ── CSV writer ────────────────────────────────────────────────────────────────
def csv_writer():
    pills = 0
    with tmp_csv.open("w", newline="", encoding="utf-8",
                      buffering=8*1024*1024) as f:
        w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        batch = []
        while True:
            item = result_queue.get()
            if item is None:
                pills += 1
                if pills >= threads:
                    if batch:
                        w.writerows(batch)
                    return
                continue
            batch.append(item)
            if len(batch) >= 10_000:
                w.writerows(batch)
                batch.clear()

# ── Phase 1: Walk + write CSV ─────────────────────────────────────────────────
print(f"Scanning   : {root}")
print(f"Threads    : {threads}")
print(f"Temp CSV   : {tmp_csv}")
print("-" * 60)

t0 = time.perf_counter()

wthreads = [threading.Thread(target=worker, daemon=True)
            for _ in range(threads)]
wthread  = threading.Thread(target=csv_writer, daemon=True)

wthread.start()
for wt in wthreads:
    wt.start()

while wthread.is_alive():
    time.sleep(3)
    elapsed = time.perf_counter() - t0
    print(f"  {_folder_count[0]:>8,} folders  "
          f"{_file_count[0]:>8,} matched  "
          f"{elapsed:.1f}s  "
          f"{_folder_count[0]/elapsed:,.0f} folders/sec")

wthread.join()
for wt in wthreads:
    wt.join(timeout=1)

t_walk = time.perf_counter() - t0
csv_mb = tmp_csv.stat().st_size / 1024 / 1024
print(f"\nPhase 1 done: {_file_count[0]:,} files in {t_walk:.1f}s "
      f"({csv_mb:.1f} MB CSV)")

# ── Phase 2: BULK INSERT ──────────────────────────────────────────────────────
print("\nPhase 2: BULK INSERT into #petroleum_files ...")
t1 = time.perf_counter()

import pyodbc
con = pyodbc.connect(CONN_STR, autocommit=True)
cur = con.cursor()

# Create temp table
cur.execute(DDL)

# BULK INSERT — SQL Server reads the CSV directly
# Path must be accessible from the SQL Server process
bulk_sql = f"""
BULK INSERT #petroleum_files
    (file_path, file_name, extension, size_bytes, modified_dt)
FROM '{tmp_csv}'
WITH (
    FIELDTERMINATOR = ',',
    ROWTERMINATOR   = '\\n',
    FIRSTROW        = 1,
    CODEPAGE        = '65001',
    TABLOCK
);
"""
cur.execute(bulk_sql)

t_load = time.perf_counter() - t1

# Verify
cur.execute("SELECT COUNT(*), SUM(size_bytes) FROM #petroleum_files")
row = cur.fetchone()
print(f"Inserted   : {row[0]:,} rows  "
      f"({(row[1] or 0)/1024/1024/1024:.2f} GB total)")
print(f"Load time  : {t_load:.2f}s")

# By extension
cur.execute("""
    SELECT extension, COUNT(*) cnt, SUM(size_bytes)/1024/1024 mb
    FROM #petroleum_files
    GROUP BY extension ORDER BY cnt DESC
""")
print("\nBy extension:")
for r in cur.fetchall():
    print(f"  {r[0]:<12} {r[1]:>8,} files   {r[2] or 0:>10,.0f} MB")

con.close()

# ── Summary ───────────────────────────────────────────────────────────────────
elapsed = time.perf_counter() - t0
print(f"\n{'─'*60}")
print(f"Phase 1 (walk+CSV) : {t_walk:.2f}s")
print(f"Phase 2 (BULK INS) : {t_load:.2f}s")
print(f"Total              : {elapsed:.2f}s")
print(f"Files              : {_file_count[0]:,}")
print(f"Folders            : {_folder_count[0]:,}")
print(f"Errors             : {_error_count[0]:,}")

# Cleanup temp CSV
tmp_csv.unlink(missing_ok=True)

"""
walk_and_load.py -- scan petroleum files and bulk insert into SQL Server
Creates a temp staging table, walks the share, bulk inserts in chunks.

Usage:
    python walk_and_load.py C:\path\to\scan
    python walk_and_load.py \\server\share --threads 16 --chunk 10000
"""
import os, sys, csv, time, threading, queue, tempfile, io
from pathlib import Path
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
root      = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\perry"
threads   = int(sys.argv[3]) if "--threads"  in sys.argv else 10
chunk     = int(sys.argv[3]) if "--chunk"    in sys.argv else 5000

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

# ── DB connection (same as DataView) ─────────────────────────────────────────
import pyodbc

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
    id           INT IDENTITY(1,1) PRIMARY KEY,
    file_path    NVARCHAR(1000)  NOT NULL,
    file_name    NVARCHAR(260)   NOT NULL,
    extension    NVARCHAR(20)    NOT NULL,
    size_bytes   BIGINT,
    modified_dt  DATETIME2,
    scan_dt      DATETIME2       DEFAULT GETUTCDATE()
);
"""

INSERT_SQL = """
INSERT INTO #petroleum_files
    (file_path, file_name, extension, size_bytes, modified_dt)
VALUES (?, ?, ?, ?, ?)
"""

# ── Shared state ──────────────────────────────────────────────────────────────
dir_queue    = queue.Queue()
result_queue = queue.Queue()
dir_queue.put(root)

_file_count   = [0]
_folder_count = [0]
_insert_count = [0]
_error_count  = [0]
_active       = [threads]
_ext_counts   = {}
_lock         = threading.Lock()

# ── Walker worker ─────────────────────────────────────────────────────────────
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
                                    ext[:20],
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

# ── DB inserter ───────────────────────────────────────────────────────────────
def inserter():
    con = pyodbc.connect(CONN_STR, autocommit=False)
    cur = con.cursor()
    cur.fast_executemany = True

    # Create temp table
    cur.execute(DDL)
    con.commit()
    print("Temp table #petroleum_files created.")

    pills  = 0
    batch  = []
    total  = 0

    while True:
        item = result_queue.get()
        if item is None:
            pills += 1
            if pills >= threads:
                # Flush remaining
                if batch:
                    cur.executemany(INSERT_SQL, batch)
                    con.commit()
                    total += len(batch)
                    with _lock:
                        _insert_count[0] = total
                break
            continue

        batch.append(item)
        if len(batch) >= chunk:
            cur.executemany(INSERT_SQL, batch)
            con.commit()
            total += len(batch)
            with _lock:
                _insert_count[0] = total
            batch.clear()

    # Summary query
    cur.execute("SELECT COUNT(*), SUM(size_bytes) FROM #petroleum_files")
    row = cur.fetchone()
    print(f"\nDB verify: {row[0]:,} rows  |  "
          f"{(row[1] or 0)/1024/1024/1024:.2f} GB total")

    # Show by extension
    cur.execute("""
        SELECT extension, COUNT(*) as cnt, SUM(size_bytes)/1024/1024 as mb
        FROM #petroleum_files
        GROUP BY extension
        ORDER BY cnt DESC
    """)
    print("\nBy extension (from DB):")
    for r in cur.fetchall():
        print(f"  {r[0]:<12} {r[1]:>8,} files   {r[2]:>10,.0f} MB")

    con.close()

# ── Launch ────────────────────────────────────────────────────────────────────
print(f"Scanning   : {root}")
print(f"Threads    : {threads}")
print(f"Chunk size : {chunk:,}")
print(f"DB         : 127.0.0.1\\SQLEXPRESS / DataView / #petroleum_files")
print("-" * 60)

t0 = time.perf_counter()

worker_threads  = [threading.Thread(target=worker,   daemon=True)
                   for _ in range(threads)]
inserter_thread = threading.Thread(target=inserter,  daemon=True)

inserter_thread.start()
for wt in worker_threads:
    wt.start()

# Progress
while inserter_thread.is_alive():
    time.sleep(3)
    elapsed = time.perf_counter() - t0
    print(f"  {_folder_count[0]:>8,} folders  "
          f"{_file_count[0]:>8,} found  "
          f"{_insert_count[0]:>8,} inserted  "
          f"{elapsed:.1f}s")

inserter_thread.join()
for wt in worker_threads:
    wt.join(timeout=1)

elapsed = time.perf_counter() - t0
print("-" * 60)
print(f"Folders    : {_folder_count[0]:,}")
print(f"Found      : {_file_count[0]:,}")
print(f"Inserted   : {_insert_count[0]:,}")
print(f"Errors     : {_error_count[0]:,}")
print(f"Time       : {elapsed:.2f}s")
print(f"Rate       : {_file_count[0]/elapsed:,.0f} files/sec")
print()
print("By extension:")
for ext, cnt in sorted(_ext_counts.items(), key=lambda x: -x[1]):
    print(f"  {ext:<12} {cnt:>10,}")

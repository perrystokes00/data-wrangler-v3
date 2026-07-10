"""
walk_petroleum.py -- multithreaded petroleum file scanner
Filters to standard petroleum file extensions only.
Writes found_petroleum.csv

Usage:
    python walk_petroleum.py C:\path\to\scan
    python walk_petroleum.py \\server\share --threads 16
"""
import os, sys, csv, time, threading, queue
from pathlib import Path

# ── Petroleum file extensions ─────────────────────────────────────────────────
EXTENSIONS = {
    # Well logs
    '.las', '.lis', '.dlis', '.dlf', '.dis',
    # Seismic
    '.segy', '.sgy', '.seg', '.p190', '.p90',
    # Documents
    '.pdf',
    # Shapefiles / spatial
    '.shp', '.geojson', '.gpkg', '.kml', '.kmz',
    # Office / data
    '.xlsx', '.xls', '.xlsm',
    '.docx', '.doc',
    '.csv', '.tsv',
    # Images
    '.tif', '.tiff',
}

# ── Args ──────────────────────────────────────────────────────────────────────
root    = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\perry"
threads = int(sys.argv[3]) if "--threads" in sys.argv else 10
out     = Path("found_petroleum.csv")

print(f"Scanning   : {root}")
print(f"Extensions : {len(EXTENSIONS)} types")
print(f"Threads    : {threads}")
print(f"Output     : {out}")
print("-" * 55)

# ── Shared state ──────────────────────────────────────────────────────────────
dir_queue    = queue.Queue()
result_queue = queue.Queue()
dir_queue.put(root)

_file_count   = [0]
_folder_count = [0]
_error_count  = [0]
_active       = [threads]
_ext_counts   = {}
_ext_lock     = threading.Lock()
_lock         = threading.Lock()

BATCH_SIZE = 500

# ── Worker ────────────────────────────────────────────────────────────────────
def worker():
    local_exts = {}
    while True:
        try:
            dirpath = dir_queue.get(timeout=2.0)
        except queue.Empty:
            with _lock:
                _active[0] -= 1
            time.sleep(0.1)
            with _lock:
                if dir_queue.empty() and _active[0] == 0:
                    # Merge local ext counts into global
                    with _ext_lock:
                        for ext, cnt in local_exts.items():
                            _ext_counts[ext] = _ext_counts.get(ext, 0) + cnt
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
                                result_queue.put((
                                    entry.path,
                                    entry.name,
                                    ext,
                                    st.st_size,
                                    int(st.st_mtime),
                                ))
                                with _lock:
                                    _file_count[0] += 1
                                local_exts[ext] = local_exts.get(ext, 0) + 1
                    except OSError:
                        with _lock:
                            _error_count[0] += 1
        except (PermissionError, OSError):
            with _lock:
                _error_count[0] += 1

# ── Writer ────────────────────────────────────────────────────────────────────
def writer():
    pills = 0
    with out.open("w", newline="", encoding="utf-8", buffering=4*1024*1024) as f:
        w = csv.writer(f)
        w.writerow(["path", "file_name", "extension", "size_bytes", "modified"])
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
            if len(batch) >= BATCH_SIZE:
                w.writerows(batch)
                batch.clear()

# ── Launch ────────────────────────────────────────────────────────────────────
t0 = time.perf_counter()

worker_threads = [threading.Thread(target=worker, daemon=True)
                  for _ in range(threads)]
writer_thread  = threading.Thread(target=writer, daemon=True)

writer_thread.start()
for wt in worker_threads:
    wt.start()

while writer_thread.is_alive():
    time.sleep(3)
    elapsed = time.perf_counter() - t0
    fc = _file_count[0]
    dc = _folder_count[0]
    print(f"  {dc:>8,} folders  {fc:>8,} matches  "
          f"{elapsed:.1f}s")

writer_thread.join()
for wt in worker_threads:
    wt.join(timeout=1)

elapsed = time.perf_counter() - t0
size_mb = out.stat().st_size / 1024 / 1024

print("-" * 55)
print(f"Folders    : {_folder_count[0]:,}")
print(f"Matched    : {_file_count[0]:,}")
print(f"Errors     : {_error_count[0]:,}")
print(f"Time       : {elapsed:.2f}s")
print(f"Rate       : {_folder_count[0]/elapsed:,.0f} folders/sec")
print(f"Output     : {out}  ({size_mb:.1f} MB)")
print()
print("By extension:")
for ext, cnt in sorted(_ext_counts.items(), key=lambda x: -x[1]):
    print(f"  {ext:<12} {cnt:>10,}")

"""
walk_fast.py -- multithreaded file system walk
Collects: full path, size, modified time -> found_files_fast.csv

Usage:
    python walk_fast.py C:\path\to\scan
    python walk_fast.py \\server\share  --threads 16
"""
import os, sys, csv, time, threading, queue
from pathlib import Path

# ── Args ──────────────────────────────────────────────────────────────────────
root       = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\perry"
threads    = int(sys.argv[3]) if "--threads" in sys.argv else 10
out        = Path("found_files_fast.csv")
BATCH_SIZE = 500   # rows per writer batch

print(f"Scanning : {root}")
print(f"Threads  : {threads}")
print(f"Output   : {out}")
print("-" * 55)

# ── Shared state ──────────────────────────────────────────────────────────────
dir_queue   = queue.Queue()          # dirs to scan
result_queue= queue.Queue()          # (path, size, mtime) tuples
dir_queue.put(root)

_file_count  = [0]
_folder_count= [0]
_error_count = [0]
_active      = [threads]             # workers still running
_lock        = threading.Lock()

# ── Worker: pulls dirs, scans, pushes files ───────────────────────────────────
def worker():
    while True:
        try:
            dirpath = dir_queue.get(timeout=2.0)
        except queue.Empty:
            # No dirs for 2s — check if we're really done
            with _lock:
                _active[0] -= 1
            # Give other workers a chance to add more dirs
            time.sleep(0.1)
            with _lock:
                if dir_queue.empty() and _active[0] == 0:
                    result_queue.put(None)  # poison pill for writer
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
                            st = entry.stat()
                            result_queue.put((
                                entry.path,
                                st.st_size,
                                int(st.st_mtime),
                            ))
                            with _lock:
                                _file_count[0] += 1
                    except OSError:
                        with _lock:
                            _error_count[0] += 1
        except (PermissionError, OSError):
            with _lock:
                _error_count[0] += 1

# ── Writer: pulls results, writes CSV in batches ──────────────────────────────
def writer():
    pills = 0
    with out.open("w", newline="", encoding="utf-8", buffering=4*1024*1024) as f:
        w = csv.writer(f)
        w.writerow(["path", "size_bytes", "modified"])
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

# Progress on main thread
while writer_thread.is_alive():
    time.sleep(3)
    elapsed = time.perf_counter() - t0
    fc = _file_count[0]
    dc = _folder_count[0]
    print(f"  {dc:>8,} folders  {fc:>10,} files  "
          f"{elapsed:.1f}s  {fc/elapsed:,.0f} files/sec")

writer_thread.join()
for wt in worker_threads:
    wt.join(timeout=1)

elapsed = time.perf_counter() - t0
size_mb = out.stat().st_size / 1024 / 1024

print("-" * 55)
print(f"Folders  : {_folder_count[0]:,}")
print(f"Files    : {_file_count[0]:,}")
print(f"Errors   : {_error_count[0]:,}")
print(f"Time     : {elapsed:.2f}s")
print(f"Rate     : {_file_count[0]/elapsed:,.0f} files/sec")
print(f"Output   : {out}  ({size_mb:.1f} MB)")

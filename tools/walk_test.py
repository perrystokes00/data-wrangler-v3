"""
walk_test.py -- pure file system walk, no processing
Collects: full path, file size, modified time
Writes to found_files.csv

Usage:
    python walk_test.py C:\path\to\scan
    python walk_test.py \\server\share
"""
import os, sys, time, csv
from pathlib import Path

root = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\perry"
out  = Path("found_files.csv")

print(f"Scanning: {root}")
print(f"Output:   {out}")
print("-" * 50)

t0      = time.perf_counter()
count   = 0
folders = 0
errors  = 0
stack   = [root]

with out.open("w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["path", "size_bytes", "modified"])

    while stack:
        dirpath = stack.pop()
        folders += 1
        try:
            with os.scandir(dirpath) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    else:
                        try:
                            st = entry.stat()
                            writer.writerow([
                                entry.path,
                                st.st_size,
                                int(st.st_mtime),
                            ])
                            count += 1
                        except OSError:
                            errors += 1
        except (PermissionError, OSError):
            errors += 1

        if folders % 5_000 == 0:
            e = time.perf_counter() - t0
            print(f"  {folders:>8,} folders  {count:>10,} files  "
                  f"{e:.1f}s  {count/e:,.0f} files/sec")

elapsed = time.perf_counter() - t0
size_mb = out.stat().st_size / 1024 / 1024

print("-" * 50)
print(f"Folders : {folders:,}")
print(f"Files   : {count:,}")
print(f"Errors  : {errors:,}")
print(f"Time    : {elapsed:.2f}s")
print(f"Rate    : {count/elapsed:,.0f} files/sec")
print(f"Output  : {out}  ({size_mb:.1f} MB)")

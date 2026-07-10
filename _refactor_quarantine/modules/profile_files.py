"""Profile per-file processing time — find the slow files, see the distribution.
Runs single-threaded (so timings are clean, no worker contention) over the
already-queued files. Reports slowest files + per-extension averages.

  py profile_files.py                 # profile all 'done' files
  py profile_files.py --limit 400     # just the first 400 (faster sample)
  py profile_files.py --ext .pdf      # only PDFs
"""
import argparse, time
import worker_core as wc
from sqlalchemy import text

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--ext", default=None)
a = ap.parse_args()

engine = wc.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
where = "WHERE FILE_PATH IS NOT NULL"
if a.ext:
    where += f" AND LOWER(FILE_EXT) = '{a.ext.lower()}'"
top = f"TOP {a.limit}" if a.limit else ""

with engine.connect() as c:
    rows = c.execute(text(
        f"SELECT {top} INVENTORY_ID, FILE_PATH, FILE_EXT, MATCHED_UWI "
        f"FROM file_catalog.GLOBAL_FILE_CATALOG {where} ORDER BY FILE_EXT"
    )).fetchall()

print(f"profiling {len(rows)} files single-threaded...\n")
times = []          # (seconds, ext, path, rows, status)
ext_tot = {}        # ext -> [count, total_s]
def _log(*_): pass

for iid, path, ext, uwi in rows:
    rec = {"INVENTORY_ID": iid, "FILE_PATH": path, "FILE_EXT": ext,
           "MATCHED_UWI": uwi}
    t0 = time.perf_counter()
    try:
        r = wc.process_file(engine, rec, log=_log)
        st, nr = r.status, r.rows_written
    except Exception as e:
        st, nr = "EXC", 0
    dt = time.perf_counter() - t0
    times.append((dt, ext, path, nr, st))
    e = (ext or "?").lower()
    ext_tot.setdefault(e, [0, 0.0])
    ext_tot[e][0] += 1
    ext_tot[e][1] += dt

total = sum(t[0] for t in times)
print(f"total {total:.1f}s over {len(times)} files "
      f"= {len(times)/total:.1f} files/s\n")

print("── per-extension ──")
for e, (n, tot) in sorted(ext_tot.items(), key=lambda x: -x[1][1]):
    print(f"  {e:8} {n:5} files  {tot:7.1f}s total  {tot/n*1000:7.0f} ms/file")

print("\n── 15 slowest files ──")
for dt, ext, path, nr, st in sorted(times, reverse=True)[:15]:
    import os
    print(f"  {dt*1000:7.0f} ms  [{ext}] {st:5} {nr:4}r  {os.path.basename(path)}")

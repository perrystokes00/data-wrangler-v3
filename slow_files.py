"""Find the files that stall the pool — process single-threaded with per-file
timing, flag anything over a threshold. Run on a fresh (cold) cache to catch
the cold-read offenders."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import worker_core as wc
from sqlalchemy import text

THRESH_MS = float(sys.argv[1]) if len(sys.argv) > 1 else 2000.0
engine = wc.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")

# pull the file list in catalog order (same order the pool claims)
with engine.connect() as c:
    rows = c.execute(text("""
        SELECT INVENTORY_ID, FILE_PATH, FILE_EXT
          FROM file_catalog.GLOBAL_FILE_CATALOG
         ORDER BY INVENTORY_ID
    """)).fetchall()

print(f"timing {len(rows)} files single-threaded; flagging > {THRESH_MS:.0f}ms\n")

class Rec:  # minimal file_rec shim
    pass

slow = []
t0 = time.time()
for i, (iid, fpath, ext) in enumerate(rows):
    rec = Rec()
    rec.INVENTORY_ID = iid; rec.FILE_PATH = fpath
    rec.FILE_EXT = ext; rec.MATCHED_UWI = None
    st = time.time()
    try:
        wc.process_file(engine, rec, lambda m: None)
    except Exception as e:
        print(f"  ERROR {os.path.basename(fpath or '')}: {e}")
    ms = (time.time() - st) * 1000
    if ms > THRESH_MS:
        slow.append((ms, ext, os.path.basename(fpath or "")))
        print(f"  SLOW {ms:7.0f}ms  [{ext}]  {os.path.basename(fpath or '')}")

print(f"\ntotal {time.time()-t0:.0f}s · {len(slow)} files over {THRESH_MS:.0f}ms")
slow.sort(reverse=True)
print("\n── slowest ──")
for ms, ext, name in slow[:20]:
    print(f"  {ms:7.0f}ms  [{ext}]  {name}")

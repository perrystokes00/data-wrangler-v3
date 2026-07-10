"""Which files are in the directory but NOT inventoried? Shows the gap between
files on disk and rows in GLOBAL_FILE_CATALOG, grouped by extension."""
import os, sys
from collections import Counter
import worker_core as w
from sqlalchemy import text

ROOT = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl"

# what's on disk
disk = Counter()
disk_files = set()
for dp, _, files in os.walk(ROOT):
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        disk[ext] += 1
        disk_files.add(f.lower())
print(f"=== ON DISK: {sum(disk.values())} files under {ROOT}")
for ext, n in sorted(disk.items(), key=lambda kv: -kv[1]):
    print(f"   {ext or '(no ext)':12} {n}")

# what's inventoried
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    inv = c.execute(text("""
        SELECT LOWER(FILE_EXT), COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
        GROUP BY LOWER(FILE_EXT)""")).fetchall()
    inv_names = {r[0].lower() for r in c.execute(text(
        "SELECT FILE_NAME FROM file_catalog.GLOBAL_FILE_CATALOG")).fetchall()}
invd = {ext: n for ext, n in inv}
print(f"\n=== INVENTORIED: {sum(invd.values())} files")

print("\n=== GAP by extension (on disk but not inventoried) ===")
for ext, n in sorted(disk.items(), key=lambda kv: -kv[1]):
    got = invd.get(ext, 0)
    gap = n - got
    flag = "  <-- SKIPPED" if gap > 0 else ""
    print(f"   {ext or '(no ext)':12} disk={n:4} inventoried={got:4} gap={gap}{flag}")

print("\n=== sample filenames on disk but NOT inventoried ===")
missing = sorted(disk_files - inv_names)
for f in missing[:25]:
    print(f"   {f}")
print(f"   ... {len(missing)} total missing" if len(missing) > 25 else
      f"   ({len(missing)} total)")

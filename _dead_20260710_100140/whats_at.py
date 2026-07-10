"""Show what file types cluster around the collapse point (catalog order)."""
import os
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    rows = c.execute(text("""
        SELECT INVENTORY_ID, FILE_EXT, FILE_PATH,
               ROW_NUMBER() OVER (ORDER BY INVENTORY_ID) AS rn
          FROM file_catalog.GLOBAL_FILE_CATALOG
    """)).fetchall()

# bucket by 100s, show ext distribution in the 800-1100 danger zone
from collections import Counter
print("── file-ext distribution by position (catalog order) ──")
for lo in range(700, 1200, 100):
    band = [r for r in rows if lo <= r[3] < lo+100]
    cnt = Counter((r[1] or "").lower() for r in band)
    top = ", ".join(f"{k}:{v}" for k,v in cnt.most_common(6))
    print(f"  {lo:4}-{lo+100:<4}  {top}")

# also: where do the heavy types (.dlis .lis .xlsx) land?
print("\n── positions of heavy file types ──")
for ext in (".dlis",".lis",".xlsx",".segy",".sgy"):
    pos = sorted(r[3] for r in rows if (r[1] or "").lower()==ext)
    if pos:
        print(f"  {ext:7} count={len(pos):3}  positions {pos[0]}–{pos[-1]}  "
              f"(median {pos[len(pos)//2]})")

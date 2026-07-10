"""Time _shp_outline_wkt to see if the geometry read is the 198s culprit.
Times: cold import, then per-file reads."""
import time, os

t0 = time.time()
import geopandas as gpd
print(f"geopandas cold import: {time.time()-t0:.1f}s")

t0 = time.time()
import sys; sys.path.insert(0, ".")
from extract_core import _shp_outline_wkt
print(f"import extract_core: {time.time()-t0:.1f}s")

base = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_shapefiles"
shps = []
for root, _, files in os.walk(base):
    for f in files:
        if f.lower().endswith(".shp"):
            shps.append(os.path.join(root, f))

print(f"\nfound {len(shps)} shapefiles; timing _shp_outline_wkt on each:")
for p in shps:
    t0 = time.time()
    wkt = _shp_outline_wkt(p)
    dt = time.time() - t0
    got = "WKT" if wkt else "None"
    print(f"   {os.path.basename(p):35} {dt:6.2f}s  -> {got}")

# also time a SEG-Y extract to see if that's slow
print("\n=== is SEG-Y extract slow? time one .segy ===")
segy = []
seg_base = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl"
for root, _, files in os.walk(seg_base):
    for f in files:
        if f.lower().endswith((".segy",".sgy")):
            segy.append(os.path.join(root, f))
            if len(segy) >= 3: break
    if len(segy) >= 3: break
from extract_core import _extract_fields
for p in segy[:3]:
    t0 = time.time()
    _extract_fields(p, os.path.splitext(p)[1].lower())
    print(f"   {os.path.basename(p):35} {time.time()-t0:6.2f}s")

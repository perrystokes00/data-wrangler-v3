"""
kgs_las.py — fetch and/or separate the KGS LAS files listed in las68301.csv.
Saved files are named <UWI14>.las (from API_NUM_NODASH) so they're UWI-keyed.

  py kgs_las.py --list                              # show entries, no I/O
  py kgs_las.py --separate "SRC_TREE" "OUT_DIR"     # copy the ones you already have
  py kgs_las.py --download "OUT_DIR"                # download the rest from KGS
  py kgs_las.py --separate SRC OUT --download OUT   # do both (separate, then fetch missing)

Default CSV is las68301.csv in the current folder (override with --csv PATH).
"""
import sys, os, csv, shutil, time
from pathlib import Path

CSV = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else "las68301.csv"

rows = []
with open(CSV, newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        uwi = (r.get("API_NUM_NODASH") or "").strip()
        url = (r.get("URL") or "").strip()
        if url:
            rows.append((uwi, url, os.path.basename(url.split("?")[0])))
print(f"{len(rows):,} LAS entries in {os.path.basename(CSV)}")

def dest_name(uwi, base):
    return f"{uwi}.las" if uwi else base

if "--list" in sys.argv:
    for uwi, url, base in rows[:20]:
        print(f"  UWI {uwi}  file {base}")
    if len(rows) > 20:
        print(f"  … +{len(rows) - 20} more")
    sys.exit(0)

# ── separate: find each URL's .las in an existing tree, copy to OUT as <uwi>.las
if "--separate" in sys.argv:
    i = sys.argv.index("--separate")
    src, out = sys.argv[i + 1], sys.argv[i + 2]
    Path(out).mkdir(parents=True, exist_ok=True)
    print(f"indexing existing .las under {src} …")
    index = {p.name.lower(): p for p in Path(src).rglob("*.las")}
    print(f"  {len(index):,} .las files on disk")
    found = miss = 0
    for uwi, url, base in rows:
        p = index.get(base.lower())
        if p:
            shutil.copyfile(p, os.path.join(out, dest_name(uwi, base))); found += 1
        else:
            miss += 1
    print(f"separated {found:,} you already had -> {out}  (still missing: {miss:,})")

# ── download: fetch from URLs to OUT as <uwi>.las (skips existing)
if "--download" in sys.argv:
    import urllib.request
    i = sys.argv.index("--download")
    out = sys.argv[i + 1]
    Path(out).mkdir(parents=True, exist_ok=True)
    got = skip = fail = 0
    for k, (uwi, url, base) in enumerate(rows, 1):
        dst = os.path.join(out, dest_name(uwi, base))
        if os.path.exists(dst):
            skip += 1; continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(dst, "wb") as fh:
                shutil.copyfileobj(resp, fh)
            got += 1
            time.sleep(0.2)                       # be polite to the KGS server
        except Exception as e:
            fail += 1
            print(f"  FAIL {base}: {str(e)[:70]}")
        if k % 50 == 0:
            print(f"  … {k}/{len(rows)}  (got {got} · skip {skip} · fail {fail})", flush=True)
    print(f"downloaded {got:,} · skipped(existing) {skip:,} · failed {fail:,} -> {out}")

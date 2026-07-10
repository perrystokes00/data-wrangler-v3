"""find_h3_csv.py — locate the h3_result.csv wherever it is, then inspect + test-load it.
Re-runs run_h3's temp path logic AND searches common spots. py find_h3_csv.py"""
import os, tempfile, glob, subprocess
cands=[]
# 1) python's tempfile (what run_h3 uses)
cands.append(os.path.join(tempfile.gettempdir(),"h3_result.csv"))
cands.append(os.path.join(tempfile.gettempdir(),"h3_coords.csv"))
# 2) env TEMP/TMP
for e in ("TEMP","TMP"):
    if os.environ.get(e):
        cands.append(os.path.join(os.environ[e],"h3_result.csv"))
# 3) search C:\Users\perry\AppData\Local\Temp and C:\Bulk
for base in (r"C:\Users\perry\AppData\Local\Temp", r"C:\Bulk", os.getcwd()):
    if os.path.isdir(base):
        cands += glob.glob(os.path.join(base,"**","h3_result.csv"),recursive=True)
        cands += glob.glob(os.path.join(base,"h3_result.csv"))
seen=set(); uniq=[c for c in cands if not (c in seen or seen.add(c))]
print("searched paths:")
found=None
for c in uniq:
    ex=os.path.exists(c)
    print(f"  {'FOUND' if ex else '  -  '}  {c}" + (f"  ({os.path.getsize(c)} bytes)" if ex else ""))
    if ex and not found: found=c
if not found:
    print("\nh3_result.csv not found anywhere. run_h3 deleted it OR the patch didn't take.")
    print("Check the patch applied: does run_h3.py have 'computed_rows' and the early return?")
    raise SystemExit

print(f"\n=== inspecting {found} ===")
with open(found,"rb") as f: raw=f.read()
print("size:",len(raw),"bytes")
print("first 120 bytes raw:",raw[:120])
print("UTF-8 BOM present:", raw[:3]==b'\xef\xbb\xbf')
print("UTF-16 LE BOM present:", raw[:2]==b'\xff\xfe')
lines=raw.decode("utf-8",errors="replace").splitlines()
print("line count:",len(lines))
for l in lines[:3]: print("  ",repr(l))
import collections
print("pipe counts:",dict(collections.Counter(l.count("|") for l in lines[:50])))

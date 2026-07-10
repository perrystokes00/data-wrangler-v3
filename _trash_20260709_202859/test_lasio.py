"""test_lasio.py — how many KGS LAS files does lasio.read actually parse, and does
it find UWI/API? This is what bcp_capture depends on. py test_lasio.py"""
import glob, os
try:
    import lasio
except ImportError:
    print("lasio not installed in this env"); raise SystemExit

FOLDER = r"C:\Users\perry\OneDrive\Documents\KSGS\LAS_Files\_selected"
files = glob.glob(os.path.join(FOLDER, "*.las"))[:60]
ok = err = has_uwi = no_uwi = 0
errs = {}
for fp in files:
    try:
        las = lasio.read(fp, ignore_data=True)
        ok += 1
        def wv(*keys):
            for k in keys:
                try:
                    v = str(las.well[k].value).strip()
                    if v: return v
                except Exception: pass
            return None
        u = wv("UWI","API","APINUM","API_NUMBER","APINO","APIN")
        d = "".join(c for c in str(u or "") if c.isdigit())
        if len(d) >= 10:
            has_uwi += 1
        else:
            no_uwi += 1
            if no_uwi <= 5:
                print(f"  NO-UWI: {os.path.basename(fp)}  wv returned={u!r}")
    except Exception as e:
        err += 1
        k = type(e).__name__
        errs[k] = errs.get(k, 0) + 1
        if err <= 5:
            print(f"  READ-FAIL: {os.path.basename(fp)}  {k}: {str(e)[:70]}")

print(f"\nof {len(files)} files: lasio OK={ok} · read-fail={err}")
print(f"  of the OK ones: has valid UWI={has_uwi} · no/short UWI={no_uwi}")
if errs: print("  read-fail types:", errs)

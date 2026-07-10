"""test_parse_rows.py — run bcp_capture.parse_las_rows on real files with a BLANK
passed-uwi (simulating a fresh scan where MATCHED_UWI is empty) and count how many
produce a cat_well row. Isolates: does the WORKER lose rows, or the DB load?
py test_parse_rows.py"""
import sys, os, glob
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bcp_capture import parse_las_rows

FOLDER = r"C:\Users\perry\OneDrive\Documents\KSGS\LAS_Files\_selected"
files = glob.glob(os.path.join(FOLDER, "*.las"))[:60]

with_uwi_blank = 0    # simulate fresh scan: no MATCHED_UWI passed
with_uwi_passed = 0   # simulate run_load: MATCHED_UWI passed
for fp in files:
    # fresh-scan simulation: pass empty uwi, inv=some id, force=False
    out_blank = parse_las_rows((fp, "", "TESTINV", False))
    if out_blank.get("cat_well"):
        with_uwi_blank += 1
    # passed-uwi simulation: pass a dummy valid uwi
    out_pass = parse_las_rows((fp, "15000000000000", "TESTINV", False))
    if out_pass.get("cat_well"):
        with_uwi_passed += 1

print(f"of {len(files)} files:")
print(f"  cat_well produced with BLANK passed-uwi (fresh scan) : {with_uwi_blank}")
print(f"  cat_well produced with a passed-uwi (run_load style)  : {with_uwi_passed}")
print()
if with_uwi_blank == len(files):
    print("=> worker resolves UWI from the HEADER fine even with blank passed-uwi.")
    print("   So the loss is in the DB LOAD or the pipeline's file SELECTION, not parse.")
elif with_uwi_blank < with_uwi_passed:
    print("=> worker LOSES rows when passed-uwi is blank — it's NOT falling back to")
    print("   the header UWI properly. That's the fresh-scan bug.")

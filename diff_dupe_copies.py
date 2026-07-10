r"""
diff_dupe_copies.py — show the ACTUAL differences between the root and modules\ copies of a
diverged file, so you can reconcile them safely (not blind-copy). Reports which lines differ
and a summary, so you can decide which copy is newer/correct before unifying.

  py diff_dupe_copies.py pdf_survey_catalog.py
  py diff_dupe_copies.py              # diffs all diverged dupes
"""
import os, sys, difflib
ROOT = os.getcwd()
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

targets = sys.argv[1:] if len(sys.argv)>1 else [
    "bcp_capture.py","catalog_capture.py","file_viewer.py","page_workbench.py",
    "pdf_survey_catalog.py","pipeline_batch_ui.py","shapefile_catalog.py"]

for fn in targets:
    rp = os.path.join(ROOT, fn); mp = os.path.join(ROOT,"modules",fn)
    if not (os.path.exists(rp) and os.path.exists(mp)):
        log(f"\n### {fn}: not a dupe (missing one side)"); continue
    a = open(rp,encoding="utf-8",errors="replace").read().splitlines()
    b = open(mp,encoding="utf-8",errors="replace").read().splitlines()
    sm = difflib.SequenceMatcher(None, a, b)
    ratio = sm.ratio()
    log(f"\n### {fn}  (similarity {ratio:.1%})")
    log(f"    root:    {len(a)} lines   modules: {len(b)} lines")
    # count changed blocks
    adds=dels=mods=0
    sample=[]
    for tag,i1,i2,j1,j2 in sm.get_opcodes():
        if tag=="equal": continue
        if tag=="insert": adds += (j2-j1)
        elif tag=="delete": dels += (i2-i1)
        elif tag=="replace": mods += max(i2-i1,j2-j1)
        if len(sample)<6:
            if tag=="delete": sample.append(f"    only in ROOT   : {a[i1][:80]}")
            elif tag=="insert": sample.append(f"    only in MODULES: {b[j1][:80]}")
            elif tag=="replace":
                sample.append(f"    ROOT   : {a[i1][:70]}")
                sample.append(f"    MODULES: {b[j1][:70]}")
    log(f"    lines only in root: {dels}   only in modules: {adds}   changed: {mods}")
    for s in sample: log(s)
    if ratio > 0.98:
        log("    -> nearly identical; safe to keep the live copy and delete the other")
        log("       AFTER porting any one-off fix (e.g. the UWI regex) into the live one.")
    else:
        log("    -> meaningfully diverged; review the diff before deleting either.")

log("\n=== recommendation ===")
log("  For pdf_survey_catalog.py specifically: the ROOT copy has the new UWI regex, the")
log("  MODULES copy (which the app prefers) does not. If the rest is identical, port JUST")
log("  the regex line into modules\\, then delete root. Full unified diff:")
log("  fc root\\pdf_survey_catalog.py modules\\pdf_survey_catalog.py   (Windows)")
open(os.path.join(ROOT,"dupe_diffs.txt"),"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to dupe_diffs.txt")

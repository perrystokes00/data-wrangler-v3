r"""
verify_patches_landed.py — the root and modules\ copies of pdf_survey_catalog.py have
DIVERGED, and the app mostly imports modules\. Check whether today's patches (broadened
UWI regex handling 'API Number:') are present in BOTH copies, so we know the live one has
the fix. Read-only. py verify_patches_landed.py
"""
import os
ROOT = os.getcwd()
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

checks = {
    # signature string -> what it proves
    "API Number regex (broadened)": r'NUM(?:BER)?',
    "survey col fix (md key)": None,   # that's survey_loader, checked separately
}

def scan(path, label):
    if not os.path.exists(path):
        log(f"  {label}: MISSING"); return
    s = open(path, encoding="utf-8", errors="replace").read()
    log(f"  {label}:")
    log(f"     has broadened UWI regex ('NUM(?:BER)?'): {'NUM(?:BER)?' in s}")
    log(f"     has old narrow regex ('API.?NUM|API.?NO'): {'API.?NUM|API.?NO' in s}")
    log(f"     size: {len(s)} chars")

log("=== pdf_survey_catalog.py — is the 'API Number:' regex fix in each copy? ===")
scan(os.path.join(ROOT,"pdf_survey_catalog.py"), "root  copy")
scan(os.path.join(ROOT,"modules","pdf_survey_catalog.py"), "modules copy")

log("\n=== survey_loader.py — is the column-key fix (md/incl/azim) in each copy? ===")
for p,lab in ((os.path.join(ROOT,"survey_loader.py"),"root"),
              (os.path.join(ROOT,"modules","survey_loader.py"),"modules")):
    if os.path.exists(p):
        s=open(p,encoding="utf-8",errors="replace").read()
        fixed = '"md":' in s and '"incl":' in s and '"azim":' in s
        old = '"station_md":' in s or '"inclination":' in s
        log(f"  {lab}: fixed(md/incl/azim)={fixed}  old(station_md/inclination)={old}")
    else:
        log(f"  {lab}: not present")

log("\n=== page_workbench.py — is the scorecard patch in each copy? ===")
for p,lab in ((os.path.join(ROOT,"page_workbench.py"),"root"),
              (os.path.join(ROOT,"modules","page_workbench.py"),"modules")):
    if os.path.exists(p):
        s=open(p,encoding="utf-8",errors="replace").read()
        log(f"  {lab}: has 'Stage scorecard'={'Stage scorecard' in s}  size={len(s)}")

log("\n=== VERDICT ===")
log("  For each file, the copy your app IMPORTS MOST (from module_dupes.txt) must show the")
log("  fix. If the live copy lacks it, re-apply the patch to THAT copy (or better: delete")
log("  the dead copy and keep one).")
log("  pdf_survey_catalog: app prefers modules\\ (15 vs 7) -> modules copy needs the regex fix")
log("  page_workbench:     app uses root (7 vs 0)          -> root copy needs the scorecard (it does)")
log("  survey_loader:      single file (no dupe)           -> just deploy the col fix once")
open(os.path.join(ROOT,"patches_landed.txt"),"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to patches_landed.txt")

r"""
analyze_tier3_versions.py — for each version-duplicate (foo_v3, foo_old, foo (1), foo - Copy),
check: does anything IMPORT it, does its NAME appear as a string anywhere, and how does it
compare to the current version. Tells you which are safe to delete vs which need an import
fix first. Read-only. py analyze_tier3_versions.py
"""
import os, re, difflib
ROOT = os.getcwd()
OUT = r"C:\Bulk\reports\tier3_versions.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

# gather all source text (excluding junk) to search for imports/refs
SKIP = ("venv",".git","__pycache__","download","_trash","_archive",".vs")
alltext = {}
for dp,dns,fns in os.walk(ROOT):
    if any(s in dp for s in SKIP):
        dns[:] = [d for d in dns if d not in SKIP]; continue
    for fn in fns:
        if fn.endswith(".py"):
            p=os.path.join(dp,fn)
            try: alltext[p]=open(p,encoding="utf-8",errors="replace").read()
            except: alltext[p]=""

def refs_to(stem, self_path):
    """files that import this stem or mention it as a string (excluding itself)."""
    imp=[]; strref=[]
    imp_pat = re.compile(rf'(?:^|\W)(?:import\s+{re.escape(stem)}\b|from\s+{re.escape(stem)}\s+import|from\s+modules\.{re.escape(stem)}\s+import|import\s+modules\.{re.escape(stem)}\b)', re.M)
    str_pat = re.compile(rf'["\']{re.escape(stem)}["\']')
    for p,txt in alltext.items():
        if p==self_path: continue
        if imp_pat.search(txt): imp.append(os.path.relpath(p,ROOT))
        elif str_pat.search(txt): strref.append(os.path.relpath(p,ROOT))
    return imp, strref

# candidate version-dupes: (old_file, current_file_or_None)
def find_current(oldpath):
    """given foo_v3.py or foo (1).py, guess the current foo.py."""
    d=os.path.dirname(oldpath); b=os.path.basename(oldpath)
    base=re.sub(r'[_ -]*(v\d+|old|bak|backup|copy|orig|prev|final|\(\d+\))(?=\.py$)','',b, flags=re.I)
    cur=os.path.join(d, base)
    return cur if os.path.exists(cur) and cur!=oldpath else None

VER_RX = re.compile(r'.*(_v\d+|_old|_bak|_backup|_copy|_orig|_prev|\(\d+\)| - Copy)\.py$', re.I)
candidates=[]
for dp,dns,fns in os.walk(ROOT):
    if any(s in dp for s in SKIP):
        dns[:] = [d for d in dns if d not in SKIP]; continue
    for fn in fns:
        p=os.path.join(dp,fn)
        if fn.endswith(".py") and VER_RX.match(fn):
            candidates.append(p)

log(f"found {len(candidates)} version-duplicate candidate(s)\n")
safe=[]; needsfix=[]
for old in sorted(candidates):
    stem=os.path.splitext(os.path.basename(old))[0]
    imp,strref = refs_to(stem, old)
    cur=find_current(old)
    log(f"### {os.path.relpath(old,ROOT)}")
    if cur:
        a=open(old,encoding="utf-8",errors="replace").read().splitlines()
        b=open(cur,encoding="utf-8",errors="replace").read().splitlines()
        sim=difflib.SequenceMatcher(None,a,b).ratio()
        log(f"    current version: {os.path.relpath(cur,ROOT)}  (similarity {sim:.0%})")
    else:
        log(f"    current version: (none found — this may be the only copy!)")
    log(f"    imported by: {imp if imp else 'nothing'}")
    if strref: log(f"    name as string in: {strref}")
    if not imp and not strref:
        log(f"    -> SAFE to delete (no imports, no string refs)")
        safe.append(old)
    else:
        log(f"    -> NEEDS FIX: repoint the import(s) to the current file, THEN delete")
        needsfix.append((old,cur,imp))
    log("")

log("=== SUMMARY ===")
log(f"SAFE to delete ({len(safe)}):")
for p in safe: log(f"   {os.path.relpath(p,ROOT)}")
log(f"\nNEEDS import fix first ({len(needsfix)}):")
for old,cur,imp in needsfix:
    log(f"   {os.path.relpath(old,ROOT)}  <- imported by {imp}")
    log(f"      fix: point those imports at {os.path.relpath(cur,ROOT) if cur else '(the real file)'}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)[:3000]); print("\n... full report in",OUT)

r"""
patch_triage_las_ready.py — stop LAS files being mislabeled NEEDS_UWI in triage.

_stage_extract skips .las (capture writes FILE_WELL_HEADER later via the BCP fast-
path), so at triage time a fresh-scan .las has no header row yet and triage's CASE
falls through to NEEDS_UWI. That's cosmetically wrong (LAS carries its UWI in the
header; capture resolves it) and it wrongly tiers these files LOW.

Fix: add a clause to the CATALOG_READINESS CASE — .las files are 'READY' (their UWI
resolves at capture). Narrowly scoped to .las, the only ext whose header comes from
capture rather than extract. In place, .bak, idempotent. py patch_triage_las_ready.py
"""
import sys, os, ast
P = "triage_inventory.py"
if not os.path.exists(P):
    P = os.path.join("modules", "triage_inventory.py")
if not os.path.exists(P):
    sys.exit("triage_inventory.py not found")
s = open(P, encoding="utf-8").read()
if "LAS carries its own UWI" in s:
    print("already patched"); sys.exit(0)

# Insert a .las READY clause right after the CATALOGED/PROMOTED preserve clause,
# so a captured/promoted state still wins, but a fresh .las is READY not NEEDS_UWI.
anchor = '''            WHEN g.CATALOG_READINESS IN ('CATALOGED','PROMOTED')
                 THEN g.CATALOG_READINESS'''
inject = '''            WHEN g.CATALOG_READINESS IN ('CATALOGED','PROMOTED')
                 THEN g.CATALOG_READINESS
            -- .las carries its own UWI in the header; _stage_extract skips .las
            -- (capture writes FILE_WELL_HEADER), so there's no header row at triage
            -- time. Mark READY — the UWI resolves at capture. (LAS carries its own UWI.)
            WHEN LOWER(g.FILE_EXT) = '.las' THEN 'READY' '''

if anchor not in s:
    sys.exit("FAILED: CATALOGED/PROMOTED preserve clause not found")
# only replace the FIRST occurrence (the CATALOG_READINESS CASE), not the TIER CASE
s = s.replace(anchor, inject, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: .las files now triage as READY (UWI resolves at capture)")

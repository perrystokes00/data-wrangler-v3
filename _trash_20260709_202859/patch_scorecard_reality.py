r"""
patch_scorecard_reality.py — fix the 'Inventory vs processed' scorecard so it counts
CAPTURED/CATALOGED from durable reality (CAPTURED_HASH / promoted), not the transient
CATALOG_READINESS='CATALOGED' flag that LAS files never get, and fix 'pending' so
promoted files don't count as pending.

Before: LAS shows cataloged=0, pending=98 even after 402 captured + 369 promoted,
because cat_* is staging that drains on promote and the readiness flag isn't set.
After: cataloged counts files that captured (CAPTURED_HASH set) — survives the drain.

In place, .bak, idempotent. py patch_scorecard_reality.py
"""
import sys, os, ast
P = "page_workbench.py"
if not os.path.exists(P):
    sys.exit("page_workbench.py not found")
s = open(P, encoding="utf-8").read()
if "captured (durable)" in s:
    print("already patched"); sys.exit(0)

old = '''                SUM(CASE WHEN g.CATALOG_READINESS='CATALOGED' {_seis}THEN 1 ELSE 0 END) AS cataloged,
                SUM(CASE WHEN g.VAULTED_AT  IS NOT NULL THEN 1 ELSE 0 END)        AS vaulted,
                SUM(CASE WHEN g.PROMOTED_AT IS NOT NULL {_seis}THEN 1 ELSE 0 END) AS promoted,
                SUM(CASE WHEN g.HEADER_EXTRACTED IS NULL OR g.HEADER_EXTRACTED IN ('N','')
                         THEN 1 ELSE 0 END)                                       AS pending,'''
new = '''                -- captured (durable): count files that WENT THROUGH capture via the
                -- CAPTURED_HASH stamp (survives promote, unlike the cat_* staging rows
                -- or the CATALOG_READINESS flag that LAS never gets set to CATALOGED).
                SUM(CASE WHEN g.CAPTURED_HASH IS NOT NULL
                         OR g.CATALOG_READINESS='CATALOGED'
                         OR g.PROMOTED_AT IS NOT NULL {_seis}THEN 1 ELSE 0 END)   AS cataloged,
                SUM(CASE WHEN g.VAULTED_AT  IS NOT NULL THEN 1 ELSE 0 END)        AS vaulted,
                SUM(CASE WHEN g.PROMOTED_AT IS NOT NULL {_seis}THEN 1 ELSE 0 END) AS promoted,
                -- pending: NOT extracted AND NOT captured (a captured-then-promoted
                -- file is done, not pending — key off CAPTURED_HASH so the drain of
                -- cat_* on promote doesn't resurrect it as 'pending').
                SUM(CASE WHEN (g.HEADER_EXTRACTED IS NULL OR g.HEADER_EXTRACTED IN ('N',''))
                          AND g.CAPTURED_HASH IS NULL
                          AND g.PROMOTED_AT IS NULL
                         THEN 1 ELSE 0 END)                                       AS pending,'''

if old not in s:
    sys.exit("FAILED: scorecard SELECT not found in expected form")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: scorecard counts captured/pending from durable reality")

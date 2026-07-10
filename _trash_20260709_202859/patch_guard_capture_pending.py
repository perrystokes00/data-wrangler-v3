r"""
patch_guard_capture_pending.py — THE fix for 'File Catalog Pipeline captures nothing
on Inventory-OFF'. The pipeline's no-op guard counts only files needing EXTRACTION
(HEADER_EXTRACTED='N'). Files already extracted but NOT captured (no cat_well row)
count as 0 pending -> the guard skips every stage incl. capture. So a re-run over an
already-inventoried catalog never captures, even with 400 eligible files.

Fix: _pending also counts capture-eligible-but-uncaptured files (self-parsing exts
with no cat_well row), so the guard lets capture run. In place, .bak, idempotent.
py patch_guard_capture_pending.py
"""
import sys, os, ast
P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found")
s = open(P, encoding="utf-8").read()
if "capture-pending" in s:
    print("already patched"); sys.exit(0)

old = '''            _pending = _c.execute(_tt(
                "SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g "
                "WHERE ISNULL(g.FLAG_DELETE,'N') <> 'Y' "
                "AND g.DUPLICATE_GROUP IS NULL "
                "AND (g.HEADER_EXTRACTED IS NULL OR g.HEADER_EXTRACTED = 'N')"
            )).scalar() or 0'''
new = '''            # pending = files needing EXTRACTION *or* capture-eligible-but-not-yet-
            # captured (extracted='Y' but no cat_well row). Without the second half,
            # a re-run over an already-inventoried catalog counts 0 pending and the
            # guard skips capture, so nothing ever gets captured. (capture-pending)
            _pending = _c.execute(_tt(
                "SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g "
                "WHERE ISNULL(g.FLAG_DELETE,'N') <> 'Y' "
                "AND g.DUPLICATE_GROUP IS NULL "
                "AND ( (g.HEADER_EXTRACTED IS NULL OR g.HEADER_EXTRACTED = 'N') "
                "      OR ( LOWER(g.FILE_EXT) IN ('.las','.pdf','.xlsx','.xls','.docx','.doc','.xml','.json') "
                "           AND ISNULL(g.CATALOG_READINESS,'') NOT IN ('SKIPPED','CATALOGED') "
                "           AND (g.CAPTURED_HASH IS NULL OR g.CAPTURED_HASH <> g.FILE_HASH) "
                "           AND NOT EXISTS (SELECT 1 FROM file_catalog.cat_well w "
                "                           WHERE w.INVENTORY_ID = g.INVENTORY_ID) ) )"
            )).scalar() or 0'''

if old not in s:
    sys.exit("FAILED: _pending query not found in expected form")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: guard now counts capture-pending files, so capture runs on re-runs")

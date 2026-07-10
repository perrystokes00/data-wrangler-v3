r"""
patch_skip_las_extract.py — complete the single-pass: skip the extract stage for
.las files (capture's BCP fast-path now writes FILE_WELL_HEADER too), and mark
those files HEADER_EXTRACTED='Y' after capture so they aren't re-processed and
downstream sees them as extracted. Requires patch_pipeline_bcp_capture.py first.
In place, .bak, idempotent.  py patch_skip_las_extract.py
"""
import sys, os, ast
P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found")
s = open(P, encoding="utf-8").read()
if "run_bcp_capture" not in s:
    sys.exit("run patch_pipeline_bcp_capture.py first (fast path not wired in)")
if "skip .las in extract" in s:
    print("already patched"); sys.exit(0)

# 1) skip LAS in both _stage_extract file-gathering queries
a1 = ("""                        WHERE (HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED='N')
                          AND ISNULL(HEADER_EXTRACTED,'') <> 'S'
                          AND DUPLICATE_GROUP IS NULL{_extf}""")
b1 = ("""                        WHERE (HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED='N')
                          AND ISNULL(HEADER_EXTRACTED,'') <> 'S'
                          AND LOWER(FILE_EXT) <> '.las'   -- skip .las in extract (capture writes FILE_WELL_HEADER)
                          AND DUPLICATE_GROUP IS NULL{_extf}""")
a2 = ("""                    WHERE (HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED='N')
                      AND ISNULL(HEADER_EXTRACTED,'') <> 'S'
                      AND DUPLICATE_GROUP IS NULL{_extf}""")
b2 = ("""                    WHERE (HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED='N')
                      AND ISNULL(HEADER_EXTRACTED,'') <> 'S'
                      AND LOWER(FILE_EXT) <> '.las'   -- skip .las in extract (capture writes FILE_WELL_HEADER)
                      AND DUPLICATE_GROUP IS NULL{_extf}""")
n1 = s.count(a1) + s.count(a2)
s = s.replace(a1, b1).replace(a2, b2)
if n1 < 2:
    print(f"WARN: matched {n1}/2 extract queries — check the file")

# 2) after the BCP fast path, mark those LAS files HEADER_EXTRACTED='Y'
anchor = "                files = _oth_rows"
mark = '''                # skip .las in extract: mark these files extracted (fast path wrote
                # FILE_WELL_HEADER) so they aren't re-processed by _stage_extract.
                try:
                    from sqlalchemy import text as _t2
                    _iids = [int(r[4]) for r in _las_rows if r[4] is not None]
                    with engine.begin() as _c2:
                        for _i in range(0, len(_iids), 1000):
                            _blk = ",".join(str(x) for x in _iids[_i:_i+1000])
                            if _blk:
                                _c2.execute(_t2(
                                    "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                                    "SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE() "
                                    "WHERE INVENTORY_ID IN (" + _blk + ")"))
                except Exception as _me:
                    log(f"[capture] (mark-extracted skipped: {str(_me)[:80]})")
                files = _oth_rows'''
if anchor not in s:
    sys.exit("FAILED: fast-path log/marker anchor not found")
s = s.replace(anchor, mark, 1)

ast.parse(s)
open(P + ".bak2", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: extract skips .las; fast path marks them HEADER_EXTRACTED='Y'")

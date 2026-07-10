"""patch_fix_mark_extracted.py — INVENTORY_ID is a hex string, not an int; fix the
mark-extracted UPDATE to quote string ids instead of int()-casting. In place, .bak,
idempotent.  py patch_fix_mark_extracted.py"""
import sys, os, ast
P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found")
s = open(P, encoding="utf-8").read()
if "mark these files extracted" not in s:
    sys.exit("skip-las patch not present — nothing to fix")
if "int(r[4])" not in s:
    print("already fixed (no int() cast present)"); sys.exit(0)

old = '''                    _iids = [int(r[4]) for r in _las_rows if r[4] is not None]
                    with engine.begin() as _c2:
                        for _i in range(0, len(_iids), 1000):
                            _blk = ",".join(str(x) for x in _iids[_i:_i+1000])
                            if _blk:
                                _c2.execute(_t2(
                                    "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                                    "SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE() "
                                    "WHERE INVENTORY_ID IN (" + _blk + ")"))'''

new = '''                    # INVENTORY_ID is a hex/uuid string -> quote each id safely
                    _iids = [str(r[4]).replace("'", "''") for r in _las_rows if r[4] is not None]
                    with engine.begin() as _c2:
                        for _i in range(0, len(_iids), 1000):
                            _blk = ",".join("'" + x + "'" for x in _iids[_i:_i+1000])
                            if _blk:
                                _c2.execute(_t2(
                                    "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                                    "SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE() "
                                    "WHERE INVENTORY_ID IN (" + _blk + ")"))'''

if old not in s:
    sys.exit("FAILED: mark-extracted block not found in expected form")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak3", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: mark-extracted now handles string INVENTORY_ID")

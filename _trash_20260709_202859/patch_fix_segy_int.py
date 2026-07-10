r"""
patch_fix_segy_int.py — fix the int(INVENTORY_ID) crash in the SEG-Y BCP fast-path's
mark-extracted step (the LAS one is already fixed in the deployed file). SEG-Y
INVENTORY_ID is a SHA1 hex string, so int() raises and the mark-extracted UPDATE is
silently skipped.

Fix mirrors the deployed LAS fix EXACTLY (str(r[4]).replace("'","''") + quoted values),
so the two fast-paths stay consistent. Matches the SEG-Y block byte-for-byte from the
deployed file; if it doesn't match, does NOTHING and reports. .bak, ast-verified before
write, idempotent. py patch_fix_segy_int.py
"""
import os, ast, sys

P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found (copy it here first)")
src = open(P, encoding="utf-8").read()

# exact old block (from show_int_exact.py repr, SEG-Y path)
old = (
    '                        _siid = [int(r[4]) for r in _segy_rows if r[4] is not None]\n'
    '                        with engine.begin() as _c3:\n'
    '                            for _j in range(0, len(_siid), 1000):\n'
    '                                _blk3 = ",".join(str(x) for x in _siid[_j:_j+1000])\n'
    '                                if _blk3:\n'
    '                                    _c3.execute(_t3(\n'
    '                                        "UPDATE file_catalog.GLOBAL_FILE_CATALOG "\n'
    "                                        \"SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE() \"\n"
    '                                        "WHERE INVENTORY_ID IN (" + _blk3 + ")"))'
)

if "int(r[4]) for r in _segy_rows" not in src:
    print("SEG-Y int(r[4]) not present — already fixed / nothing to do."); sys.exit(0)

if old not in src:
    print("SEG-Y block did not match expected bytes exactly. NOT modifying the file.")
    print("Re-run show_int_exact.py and paste the SEG-Y repr so I can match it.")
    sys.exit(0)

# new block — mirrors the deployed LAS fix style (quoted string ids, escaped quotes)
new = (
    '                        _siid = [str(r[4]).replace("\'", "\'\'") for r in _segy_rows if r[4] is not None]\n'
    '                        with engine.begin() as _c3:\n'
    '                            for _j in range(0, len(_siid), 1000):\n'
    '                                _blk3 = ",".join("\'" + x + "\'" for x in _siid[_j:_j+1000])\n'
    '                                if _blk3:\n'
    '                                    _c3.execute(_t3(\n'
    '                                        "UPDATE file_catalog.GLOBAL_FILE_CATALOG "\n'
    "                                        \"SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE() \"\n"
    '                                        "WHERE INVENTORY_ID IN (" + _blk3 + ")"))'
)

result = src.replace(old, new, 1)

# hard safety: whole file must still parse
try:
    ast.parse(result)
except SyntaxError as e:
    print(f"REFUSING to write — result would not parse: {e}"); sys.exit(1)

# and confirm exactly one replacement happened
if result == src:
    print("no change made (unexpected)."); sys.exit(1)

open(P + ".bak_segyint", "w", encoding="utf-8").write(src)
open(P, "w", encoding="utf-8").write(result)
print(f"patched {P}: SEG-Y int(INVENTORY_ID) fixed (mirrors the LAS fix). backup: .bak_segyint")

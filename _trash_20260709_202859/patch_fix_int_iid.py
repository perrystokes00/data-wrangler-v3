r"""
patch_fix_int_iid.py — fix the int(INVENTORY_ID) crash in the LAS BCP fast-path's
mark-extracted step. INVENTORY_ID is a SHA1 hex string, so int() raises ValueError and
the whole mark-extracted UPDATE is silently skipped (caught by its except). This drops
the int() cast and uses a parameterized IN :ids (safe for string ids), matching the
pattern the CAPTURED_HASH stamp block already uses.

SAFE BY DESIGN:
- Locates the block by the unique 'int(r[4]) for r in _las_rows' text.
- Replaces ONLY the _iids list-comp and the string-concat IN clause with a
  parameterized version. No other logic touched.
- If the exact block isn't found, does NOTHING and reports (so it can't corrupt the file).
- Writes .bak, verifies the whole file still parses (ast) BEFORE saving. Idempotent.

py patch_fix_int_iid.py
"""
import os, ast, sys, re

P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found (copy it here first)")
src = open(P, encoding="utf-8").read()

if "int(r[4]) for r in _las_rows" not in src:
    if "_bp_iid" in src or "WHERE INVENTORY_ID IN :ids" in src and "int(r[4])" not in src:
        print("already patched (no int(r[4]) present) — nothing to do"); sys.exit(0)
    print("int(r[4]) block not found — nothing changed (file may already be fixed).")
    sys.exit(0)

# The exact block to replace (from the deployed structure). We match flexibly on
# leading whitespace so CRLF/indent variations don't defeat it: capture the block
# from the _iids line through the WHERE ... IN (...) line.
pattern = re.compile(
    r"( *)_iids = \[int\(r\[4\]\) for r in _las_rows if r\[4\] is not None\]\n"
    r"( *)with engine\.begin\(\) as _c2:\n"
    r"( *)for _i in range\(0, len\(_iids\), 1000\):\n"
    r"( *)_blk = \",\"\.join\(str\(x\) for x in _iids\[_i:_i\+1000\]\)\n"
    r"( *)if _blk:\n"
    r"( *)_c2\.execute\(_t2\(\n"
    r'( *)"UPDATE file_catalog\.GLOBAL_FILE_CATALOG "\n'
    r"( *)\"SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE\(\) \"\n"
    r'( *)"WHERE INVENTORY_ID IN \(" \+ _blk \+ "\)"\)\)'
)

m = pattern.search(src)
if not m:
    print("The int() block did not match the expected shape exactly.")
    print("NOT modifying the file. Paste the show_int_bug.py output and I'll match it.")
    sys.exit(0)

ind = m.group(1)          # base indent of the _iids line
i2 = m.group(2)           # indent of 'with engine.begin()'
# build the replacement with the SAME indentation, parameterized IN :ids
repl = (
    f'{ind}_iids = [r[4] for r in _las_rows if r[4] is not None]  # INVENTORY_ID is a hex string\n'
    f'{i2}from sqlalchemy import bindparam as _bp_iid\n'
    f'{i2}with engine.begin() as _c2:\n'
    f'{i2}    for _i in range(0, len(_iids), 1000):\n'
    f'{i2}        _chunk = _iids[_i:_i+1000]\n'
    f'{i2}        if _chunk:\n'
    f'{i2}            _c2.execute(_t2(\n'
    f'{i2}                "UPDATE file_catalog.GLOBAL_FILE_CATALOG "\n'
    f"{i2}                \"SET HEADER_EXTRACTED='Y', ROW_CHANGED_DATE=GETUTCDATE() \"\n"
    f'{i2}                "WHERE INVENTORY_ID IN :ids"\n'
    f'{i2}            ).bindparams(_bp_iid("ids", expanding=True)), {{"ids": _chunk}})'
)

new = src[:m.start()] + repl + src[m.end():]

# hard safety: the whole file must still parse
try:
    ast.parse(new)
except SyntaxError as e:
    print(f"REFUSING to write — result would not parse: {e}")
    sys.exit(1)

open(P + ".bak_intfix", "w", encoding="utf-8").write(src)
open(P, "w", encoding="utf-8").write(new)
print(f"patched {P}: int(INVENTORY_ID) removed; mark-extracted now uses parameterized IN :ids")
print("backup written: pipeline_run.py.bak_intfix")

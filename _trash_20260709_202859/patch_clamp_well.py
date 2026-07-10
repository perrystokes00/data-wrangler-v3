"""
patch_clamp_well.py — hard-clamp every string well-param to its FILE_WELL_HEADER
column width before the batched MERGE, so no value can overflow (fixes
'String data, right truncation' from junk/mis-parsed values like '13-Oct-2017',
'Wed', or an over-long field, and the fast_executemany buffer-sizing quirk).
Edits page_workbench._write_enrichment_batch. Idempotent, .bak.
Run: py patch_clamp_well.py
"""
import sys, ast
P = "page_workbench.py"
s = open(P, encoding="utf-8").read()
if "_clamp_well" in s:
    print("already patched"); sys.exit(0)

helper = (
    'def _clamp_well(rows):\n'
    '    """Clamp each string well-param to its column width so no value overflows\n'
    '    (defends against mis-parsed dates/fields and fast_executemany under-sizing)."""\n'
    '    _w = {"uwi": 40, "wn": 255, "op": 255, "fld": 100, "st": 50, "co": 100,\n'
    '          "spud": 20, "rig": 20, "rt": 50, "stype": 50, "contr": 255,\n'
    '          "lat": 30, "lon": 30, "td": 20}\n'
    '    for r in rows:\n'
    '        for k, n in _w.items():\n'
    '            v = r.get(k)\n'
    '            if isinstance(v, str) and len(v) > n:\n'
    '                r[k] = v[:n]\n'
    '    return rows\n'
    '\n\n')
anchor = "def _write_enrichment_batch(con, items):\n"
if anchor not in s:
    print("FAILED: _write_enrichment_batch not found."); sys.exit(1)
s = s.replace(anchor, helper + anchor, 1)

old = ('    if well:\n'
       '        con.execute(_t(_SQL_WELL_MERGE), well)\n')
new = ('    if well:\n'
       '        con.execute(_t(_SQL_WELL_MERGE), _clamp_well(well))\n')
if old not in s:
    print("FAILED: well executemany anchor not found."); sys.exit(1)
s = s.replace(old, new, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: well params clamped to column widths before the batch MERGE")

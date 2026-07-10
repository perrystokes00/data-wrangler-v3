"""
patch_wellmerge_perrow.py — run the FILE_WELL_HEADER / seismic MERGE per-row
(same transaction) instead of via fast_executemany. The MERGE's USING(SELECT ?)
subquery defeats pyodbc column sizing, so fast_executemany under-sizes string
buffers and truncates a later long value ('length 28 buffer 22'). Per-row binds
each row at its true size. The plain GFC UPDATE stays batched. Ensures the
_clamp_well guard exists. Idempotent, .bak.  Run: py patch_wellmerge_perrow.py
"""
import sys, ast
P = "page_workbench.py"
s = open(P, encoding="utf-8").read()
if "per-row MERGE" in s:
    print("already patched"); sys.exit(0)

# ensure the clamp helper exists (adds it if patch_clamp_well wasn't applied)
if "_clamp_well" not in s:
    helper = (
        'def _clamp_well(rows):\n'
        '    """Clamp each string well-param to its column width (belt-and-suspenders)."""\n'
        '    _w = {"uwi": 40, "wn": 255, "op": 255, "fld": 100, "st": 50, "co": 100,\n'
        '          "spud": 20, "rig": 20, "rt": 50, "stype": 50, "contr": 255,\n'
        '          "lat": 30, "lon": 30, "td": 20}\n'
        '    for r in rows:\n'
        '        for k, n in _w.items():\n'
        '            v = r.get(k)\n'
        '            if isinstance(v, str) and len(v) > n:\n'
        '                r[k] = v[:n]\n'
        '    return rows\n\n\n')
    s = s.replace("def _write_enrichment_batch(con, items):\n",
                  helper + "def _write_enrichment_batch(con, items):\n", 1)

new = ('    # per-row MERGE: the USING(SELECT ?) subquery defeats pyodbc fast_executemany\n'
       '    # column sizing, under-sizing string buffers and truncating a later long\n'
       '    # value; per-row binds each at its true size (still one transaction).\n'
       '    for _w in _clamp_well(well):\n'
       '        con.execute(_t(_SQL_WELL_MERGE), _w)\n'
       '    for _sp in seis:\n'
       '        con.execute(_t(_SQL_SEIS_MERGE), _sp)\n')

variants = [
    ('    if well:\n        con.execute(_t(_SQL_WELL_MERGE), _clamp_well(well))\n'
     '    if seis:\n        con.execute(_t(_SQL_SEIS_MERGE), seis)\n'),
    ('    if well:\n        con.execute(_t(_SQL_WELL_MERGE), well)\n'
     '    if seis:\n        con.execute(_t(_SQL_SEIS_MERGE), seis)\n'),
]
hit = False
for old in variants:
    if old in s:
        s = s.replace(old, new, 1); hit = True; break
if not hit:
    print("FAILED: well/seis executemany block not found."); sys.exit(1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: well/seis MERGE now per-row (no fast_executemany truncation)")

r"""
patch_cap_invs_real.py — minimal fix for the 'capture stamps everything' bug.
Line 938 preloads _cap_invs with EVERY selected file, so the fingerprint stamp
(whatever form it's in) marks all of them CAPTURED even when only a few produced
cat_* rows. Files the BCP fast-path skipped are then excluded forever.

Fix: initialize _cap_invs empty, then AFTER capture, populate it with only the
INVENTORY_IDs that truly have a cat_well row. The existing stamp block then marks
only real captures. Works with either stamp form (#cap_ids or IN-list).
py patch_cap_invs_real.py
"""
import sys, os, ast
P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found")
s = open(P, encoding="utf-8").read()
if "populate _cap_invs from real" in s:
    print("already patched"); sys.exit(0)

# 1) init empty + remember candidates
old1 = '''    _cap_invs = [r[4] for r in files if r[4] is not None]
    log(f"[capture] {total:,} document(s) with a UWI → cat_* mirrors …")'''
new1 = '''    _cap_invs = []                                   # stamp only real captures
    _sel_invs = [r[4] for r in files if r[4] is not None]   # candidates this run
    log(f"[capture] {total:,} document(s) with a UWI → cat_* mirrors …")'''
if old1 not in s:
    sys.exit("FAILED: line-938 preload anchor not found")
s = s.replace(old1, new1, 1)

# 2) just before the stamp block runs, populate _cap_invs from files that truly
#    have a cat_well row. Anchor on the stamp guard 'if _cap_invs:'.
anchor = "    # Fingerprint skip"
if anchor not in s:
    # try alternate comment wording used by the #cap_ids patch
    anchor = "    if _cap_invs:"
    if anchor not in s:
        sys.exit("FAILED: stamp block start not found")

inject = '''    # populate _cap_invs from real cat_well rows (scoped to this run's candidates),
    # so only files that actually captured get their CAPTURED_HASH stamped. Files the
    # fast-path skipped (unresolved UWI) stay eligible for the next run.
    try:
        from sqlalchemy import text as _t_cap
        _cand = [str(x) for x in set(_sel_invs) if x is not None]
        if _cand:
            with engine.begin() as _cc:
                _cc.execute(_t_cap("IF OBJECT_ID('tempdb..#cap_real') IS NOT NULL DROP TABLE #cap_real"))
                _cc.execute(_t_cap("CREATE TABLE #cap_real (inv nvarchar(64) PRIMARY KEY)"))
                _rw = _cc.connection; _cu = _rw.cursor(); _cu.fast_executemany = True
                for _k in range(0, len(_cand), 1000):
                    _cu.executemany("INSERT INTO #cap_real (inv) VALUES (?)",
                                    [(v,) for v in _cand[_k:_k+1000]])
                _rows_real = _cc.execute(_t_cap(
                    "SELECT c.inv FROM #cap_real c WHERE EXISTS "
                    "(SELECT 1 FROM file_catalog.cat_well w WHERE w.INVENTORY_ID = c.inv)")).fetchall()
                _cc.execute(_t_cap("DROP TABLE #cap_real"))
            _cap_invs = list({r[0] for r in _rows_real}) + list(_cap_invs)
    except Exception as _e_cap:
        pass

'''

s = s.replace(anchor, inject + anchor, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: _cap_invs now populated from real cat_well rows before stamping")

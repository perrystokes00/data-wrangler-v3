r"""
patch_captured_hash_real.py — fix the capture 'stamps everything' bug. Line 938
pre-loads _cap_invs with EVERY selected file, so the fingerprint stamp marks all
of them CAPTURED even when the BCP fast-path only wrote a few cat_* rows (UWI
skips). Result: capture skips those files forever on later runs.

Fix: stamp CAPTURED_HASH only for INVENTORY_IDs that ACTUALLY have a cat_well row
(derive the stamp from reality, not the attempt list). In place, .bak, idempotent.
py patch_captured_hash_real.py
"""
import sys, os, ast
P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found")
s = open(P, encoding="utf-8").read()
if "stamp only real captures" in s:
    print("already patched"); sys.exit(0)

# 1) don't pre-load _cap_invs with all selected files; start empty and stamp by reality
old1 = '''    _cap_invs = [r[4] for r in files if r[4] is not None]
    log(f"[capture] {total:,} document(s) with a UWI → cat_* mirrors …")'''
new1 = '''    _cap_invs = []   # stamp only real captures — populated from cat_* after the run
    _sel_invs = [r[4] for r in files if r[4] is not None]   # candidates this run
    log(f"[capture] {total:,} document(s) with a UWI → cat_* mirrors …")'''
if old1 not in s:
    sys.exit("FAILED: _cap_invs init line not found")
s = s.replace(old1, new1, 1)

# 2) replace the stamp block: derive stamped ids from files that truly have a
#    cat_well row (scoped to this run's candidates), not the attempt list.
old2 = '''    # Fingerprint skip: record the hash we captured at so an unchanged
    # re-run of the same file skips capture entirely (SELECTs gate on it).
    if _cap_invs:
        try:
            from sqlalchemy import bindparam as _bp
            with engine.begin() as _con:
                _con.execute(_t("UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                    "SET CAPTURED_HASH = FILE_HASH WHERE INVENTORY_ID IN :ids")
                    .bindparams(_bp("ids", expanding=True)),
                    {"ids": list(set(_cap_invs))})
        except Exception as _e:
            log(f"[capture] fingerprint stamp skipped: {str(_e)[:160]}")'''
new2 = '''    # Fingerprint skip: stamp CAPTURED_HASH so an unchanged re-run skips capture.
    # CRITICAL: stamp ONLY files that actually produced a cat_well row this run —
    # deriving from reality (EXISTS cat_well) instead of the attempt list, so files
    # the BCP fast-path skipped (unresolved UWI) are NOT marked captured and remain
    # eligible next run. _cap_invs (JSON masters) union real cat_well successes.
    _stamp_ids = set(x for x in _cap_invs if x is not None)
    try:
        # add every candidate that now truly has a cat_well row
        _iid_all = [x for x in _sel_invs if x is not None]
        if _iid_all:
            with engine.begin() as _con:
                _con.execute(_t("IF OBJECT_ID('tempdb..#capstamp') IS NOT NULL DROP TABLE #capstamp"))
                _con.execute(_t("CREATE TABLE #capstamp (inv nvarchar(64) PRIMARY KEY)"))
                _raw = _con.connection; _cur = _raw.cursor(); _cur.fast_executemany = True
                _sids = [str(x) for x in set(_iid_all)]
                for _i in range(0, len(_sids), 1000):
                    _cur.executemany("INSERT INTO #capstamp (inv) VALUES (?)",
                                     [(v,) for v in _sids[_i:_i+1000]])
                # stamp only those with a real cat_well row
                _con.execute(_t(
                    "UPDATE g SET g.CAPTURED_HASH = g.FILE_HASH "
                    "FROM file_catalog.GLOBAL_FILE_CATALOG g "
                    "JOIN #capstamp c ON c.inv = g.INVENTORY_ID "
                    "WHERE EXISTS (SELECT 1 FROM file_catalog.cat_well w "
                    "              WHERE w.INVENTORY_ID = g.INVENTORY_ID)"))
                # plus any explicit _cap_invs (JSON masters) not covered above
                if _stamp_ids:
                    from sqlalchemy import bindparam as _bp
                    _con.execute(_t("UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                        "SET CAPTURED_HASH = FILE_HASH WHERE INVENTORY_ID IN :ids")
                        .bindparams(_bp("ids", expanding=True)),
                        {"ids": list(_stamp_ids)})
                _con.execute(_t("DROP TABLE #capstamp"))
    except Exception as _e:
        log(f"[capture] fingerprint stamp skipped: {str(_e)[:160]}")'''
if old2 not in s:
    sys.exit("FAILED: fingerprint stamp block not found (may already be patched to #cap_ids form)")
s = s.replace(old2, new2, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: CAPTURED_HASH now stamps only files with a real cat_well row")

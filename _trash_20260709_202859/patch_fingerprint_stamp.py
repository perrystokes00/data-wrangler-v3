r"""
patch_fingerprint_stamp.py — fix the '07002' fingerprint-stamp error. The stamp
UPDATE used `WHERE INVENTORY_ID IN :ids` with an expanding bindparam over
thousands of captured ids, blowing past ODBC's ~2100-parameter limit. Replace with
a temp-table join (batched insert of the ids, then a set-based UPDATE ... JOIN).
In place, .bak, idempotent.  py patch_fingerprint_stamp.py
"""
import sys, os, ast
P = "pipeline_run.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pipeline_run.py")
if not os.path.exists(P):
    sys.exit("pipeline_run.py not found")
s = open(P, encoding="utf-8").read()
if "#cap_ids" in s:
    print("already patched"); sys.exit(0)

old = '''    if _cap_invs:
        try:
            from sqlalchemy import bindparam as _bp
            with engine.begin() as _con:
                _con.execute(_t("UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                    "SET CAPTURED_HASH = FILE_HASH WHERE INVENTORY_ID IN :ids")
                    .bindparams(_bp("ids", expanding=True)),
                    {"ids": list(set(_cap_invs))})
        except Exception as _e:
            log(f"[capture] fingerprint stamp skipped: {str(_e)[:160]}")'''

new = '''    if _cap_invs:
        try:
            _ids = [str(x) for x in set(_cap_invs) if x is not None]
            with engine.begin() as _con:
                # temp-table join instead of a giant IN-list (ODBC caps params ~2100,
                # and captures run into the thousands -> 07002). Batched insert + join.
                _con.execute(_t("IF OBJECT_ID('tempdb..#cap_ids') IS NOT NULL "
                                "DROP TABLE #cap_ids"))
                _con.execute(_t("CREATE TABLE #cap_ids (inv nvarchar(64) PRIMARY KEY)"))
                _raw = _con.connection
                _cur = _raw.cursor()
                _cur.fast_executemany = True
                for _i in range(0, len(_ids), 1000):
                    _cur.executemany("INSERT INTO #cap_ids (inv) VALUES (?)",
                                     [(v,) for v in _ids[_i:_i+1000]])
                _con.execute(_t(
                    "UPDATE g SET g.CAPTURED_HASH = g.FILE_HASH "
                    "FROM file_catalog.GLOBAL_FILE_CATALOG g "
                    "JOIN #cap_ids c ON c.inv = g.INVENTORY_ID"))
                _con.execute(_t("DROP TABLE #cap_ids"))
        except Exception as _e:
            log(f"[capture] fingerprint stamp skipped: {str(_e)[:160]}")'''

if old not in s:
    sys.exit("FAILED: fingerprint-stamp block not found in expected form")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak6", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: fingerprint stamp uses a temp-table join (no more 07002)")

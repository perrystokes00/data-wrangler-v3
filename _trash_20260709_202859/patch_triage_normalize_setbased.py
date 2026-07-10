r"""
patch_triage_normalize_setbased.py — replace triage step-2 normalize (Python
round-trip: SELECT -> normalize in Python -> executemany 4,481 rows -> UPDATE,
~188s) with a single set-based T-SQL UPDATE reusing enrich's u14_sql/nn_sql
(~2s). Same result, ~90x faster. In place, .bak, idempotent.
py patch_triage_normalize_setbased.py
"""
import sys, os, ast
P = "triage_inventory.py"
if not os.path.exists(P):
    P = os.path.join("modules", "triage_inventory.py")
if not os.path.exists(P):
    sys.exit("triage_inventory.py not found (run in app root or modules)")
s = open(P, encoding="utf-8").read()
if "set-based normalize" in s:
    print("already patched"); sys.exit(0)

old = '''    rows = [(inv, norm14(su), name_norm(wn)) for inv, su, wn in cur.fetchall()]
    rows = [(inv, u, n) for inv, u, n in rows if u or n]
    if dry:
        say(f"  [dry] would set UWI14/NAME_NORM on {len(rows)} file(s)")
        return len(rows)
    if not rows:
        say("  identity already normalized (0)")
        return 0
    cur.execute("IF OBJECT_ID('tempdb..#norm') IS NOT NULL DROP TABLE #norm")
    cur.execute("CREATE TABLE #norm (inv varchar(64) PRIMARY KEY, "
                "u14 varchar(14), nn varchar(200))")
    cur.fast_executemany = True
    cur.executemany("INSERT INTO #norm (inv, u14, nn) VALUES (?, ?, ?)", rows)
    cur.execute(f"""
        UPDATE h SET
            UWI14     = CASE WHEN NULLIF(LTRIM(RTRIM(h.UWI14)),'') IS NULL
                             THEN n.u14 ELSE h.UWI14 END,
            NAME_NORM = CASE WHEN NULLIF(LTRIM(RTRIM(h.NAME_NORM)),'') IS NULL
                             THEN n.nn ELSE h.NAME_NORM END
        FROM {FWH} h JOIN #norm n ON h.INVENTORY_ID = n.inv
    """)
    nrow = cur.rowcount
    cur.execute("DROP TABLE #norm")
    say(f"  set UWI14/NAME_NORM on {nrow} file(s)")
    return nrow'''

new = '''    # set-based normalize: do UWI14 + NAME_NORM entirely in T-SQL (reusing enrich's
    # u14_sql/nn_sql) instead of a Python round-trip + executemany. ~90x faster.
    from enrich_file_headers import u14_sql as _u14, nn_sql as _nn
    _src_uwi = "COALESCE(NULLIF(LTRIM(RTRIM(h.UWI)),''), g.MATCHED_UWI)"
    _where = (f"(NULLIF(LTRIM(RTRIM(h.UWI14)),'') IS NULL AND {_src_uwi} IS NOT NULL) "
              f"OR (NULLIF(LTRIM(RTRIM(h.NAME_NORM)),'') IS NULL "
              f"AND NULLIF(LTRIM(RTRIM(h.WELL_NAME)),'') IS NOT NULL)")
    if dry:
        n = cur.execute(f"SELECT COUNT(*) FROM {FWH} h "
                        f"JOIN {GFC} g ON g.INVENTORY_ID = h.INVENTORY_ID "
                        f"WHERE {_where}").fetchone()[0]
        say(f"  [dry] would set UWI14/NAME_NORM on {n} file(s)")
        return n
    cur.execute(f"""
        UPDATE h SET
            UWI14     = CASE WHEN NULLIF(LTRIM(RTRIM(h.UWI14)),'') IS NULL
                             THEN {_u14(_src_uwi)} ELSE h.UWI14 END,
            NAME_NORM = CASE WHEN NULLIF(LTRIM(RTRIM(h.NAME_NORM)),'') IS NULL
                             THEN {_nn('h.WELL_NAME')} ELSE h.NAME_NORM END
        FROM {FWH} h JOIN {GFC} g ON g.INVENTORY_ID = h.INVENTORY_ID
        WHERE {_where}
    """)
    nrow = cur.rowcount
    say(f"  set UWI14/NAME_NORM on {nrow} file(s)")
    return nrow'''

if old not in s:
    sys.exit("FAILED: step-2 normalize block not found in expected form "
             "(the file may differ from the uploaded copy)")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: step-2 normalize is now set-based T-SQL (~188s -> ~2s)")

r"""
patch_gold_enrich_sargable.py — the post-promote gold-enrich joins
gold.uwi14 (char14) = CAST(dv_well.uwi AS char(14)), which is non-sargable and
scans 3.5M gold rows (~476s). Replace with a pre-cast, indexed char(14) key temp
so the join seeks IX_WM_UWI14 (~seconds). In place, .bak, idempotent.
py patch_gold_enrich_sargable.py
"""
import sys, os, ast
P = "promote_catalog.py"
if not os.path.exists(P):
    P = os.path.join("modules", "promote_catalog.py")
if not os.path.exists(P):
    sys.exit("promote_catalog.py not found")
s = open(P, encoding="utf-8").read()
if "#gk_uwi14" in s:
    print("already patched"); sys.exit(0)

# The dv_well UPDATE block: build the SQL from a pre-cast char(14) key temp and
# join gold seekably, instead of CAST(w.uwi AS char(14)) per row.
old = '''    sql = (
        f"UPDATE w SET\\n        {set_clause}\\n"
        f"    FROM {DV_SCHEMA}.dv_well w\\n"
        f"    JOIN {gold} g ON g.uwi14 = CAST(w.uwi AS char(14)){scope_join}\\n"
        f"    WHERE (w.surface_latitude IS NULL OR w.operator_name IS NULL\\n"
        f"           OR w.county IS NULL OR w.spud_date IS NULL\\n"
        f"           OR w.well_name = w.uwi){where}")
    try:
        cur.execute(sql, *params)
        n = cur.rowcount or 0
        log(f"-- enrich: {n} dv_well row(s) filled from {gold}")'''

new = '''    # Pre-cast the candidate UWIs to char(14) ONCE into an indexed temp so the
    # gold join seeks IX_WM_UWI14 instead of scanning 3.5M rows (CAST(w.uwi AS
    # char(14)) on every row is non-sargable). Candidates = rows needing a fill,
    # scoped to this run's uwis when provided.
    cur.execute("IF OBJECT_ID('tempdb..#gk') IS NOT NULL DROP TABLE #gk")
    cur.execute("CREATE TABLE #gk (uwi14 char(14) PRIMARY KEY, src_uwi nvarchar(80))")
    _scope_where = ""
    if uwis:
        cur.execute("IF OBJECT_ID('tempdb..#enr_uwi') IS NOT NULL DROP TABLE #enr_uwi")
        cur.execute("CREATE TABLE #enr_uwi (uwi nvarchar(80) PRIMARY KEY)")
        _uset = sorted({str(u).strip() for u in uwis if u and str(u).strip()})
        if _uset:
            cur.fast_executemany = True
            cur.executemany("INSERT INTO #enr_uwi (uwi) VALUES (?)", [(u,) for u in _uset])
            _scope_where = " AND w.uwi IN (SELECT uwi FROM #enr_uwi)"
    elif uwi:
        _scope_where = f" AND w.uwi = {_norm('?')}"
        params.append(uwi)
    # distinct char(14) keys for the wells that still need a fill
    cur.execute(
        f"INSERT INTO #gk (uwi14, src_uwi)\\n"
        f"SELECT MIN(CAST(w.uwi AS char(14))), w.uwi\\n"
        f"    FROM {DV_SCHEMA}.dv_well w\\n"
        f"    WHERE (w.surface_latitude IS NULL OR w.operator_name IS NULL\\n"
        f"           OR w.county IS NULL OR w.spud_date IS NULL\\n"
        f"           OR w.well_name = w.uwi)\\n"
        f"      AND LEN(LTRIM(RTRIM(w.uwi))) >= 10{_scope_where}\\n"
        f"    GROUP BY w.uwi", *params)
    sql = (
        f"UPDATE w SET\\n        {set_clause}\\n"
        f"    FROM {DV_SCHEMA}.dv_well w\\n"
        f"    JOIN #gk k ON k.src_uwi = w.uwi\\n"
        f"    JOIN {gold} g ON g.uwi14 = k.uwi14\\n"
        f"    WHERE (w.surface_latitude IS NULL OR w.operator_name IS NULL\\n"
        f"           OR w.county IS NULL OR w.spud_date IS NULL\\n"
        f"           OR w.well_name = w.uwi)")
    try:
        cur.execute(sql)   # #gk is pre-scoped; no params needed on the UPDATE
        n = cur.rowcount or 0
        cur.execute("DROP TABLE #gk")
        log(f"-- enrich: {n} dv_well row(s) filled from {gold} (sargable seek)")'''

if old not in s:
    sys.exit("FAILED: dv_well gold-enrich block not found in expected form "
             "(the file may differ from the uploaded copy)")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: gold-enrich join is now sargable via indexed char(14) key temp")

r"""
patch_enrich_scope_new_rows.py — make enrich pass 2 (fill blank attributes)
incremental: add a LAST_ENRICHED_AT marker, scope the fill to unstamped rows, and
stamp them after. Catch-up runs then fill only new wells (~2s) instead of
re-scanning the whole catalog against gold (~32s). In place, .bak, idempotent.
py patch_enrich_scope_new_rows.py
"""
import sys, os, ast
P = "enrich_file_headers.py"
if not os.path.exists(P):
    P = os.path.join("modules", "enrich_file_headers.py")
if not os.path.exists(P):
    sys.exit("enrich_file_headers.py not found (run in app root or modules)")
s = open(P, encoding="utf-8").read()
if "LAST_ENRICHED_AT" in s:
    print("already patched"); sys.exit(0)

# 1) ensure the marker column exists at the top of the WELL section (transaction-
#    scoped: committed on apply, rolled back on dry-run — present during the run
#    either way so the scoping predicate is valid).
a1 = '''    if not a.no_well:
        _tick("pass 0 — curate UWI14")'''
b1 = '''    if not a.no_well:
        cur.execute(
            "IF COL_LENGTH('file_catalog.FILE_WELL_HEADER','LAST_ENRICHED_AT') IS NULL "
            "ALTER TABLE file_catalog.FILE_WELL_HEADER ADD LAST_ENRICHED_AT datetime2 NULL")
        _tick("pass 0 — curate UWI14")'''

# 2) scope the reference aggregate to unstamped rows' UWIs only
a2 = '''            refagg = f"""SELECT UWI14, {agg_cols} FROM {ref}
                WHERE UWI_SUSPECT = 0 AND UWI14 <> '{ZERO_UWI}'
                  AND UWI14 IN ({u14_src})
                GROUP BY UWI14"""'''
b2 = '''            _p2_keys = ("SELECT UWI14 FROM file_catalog.FILE_WELL_HEADER "
                        "WHERE UWI14 IS NOT NULL AND LAST_ENRICHED_AT IS NULL")
            refagg = f"""SELECT UWI14, {agg_cols} FROM {ref}
                WHERE UWI_SUSPECT = 0 AND UWI14 <> '{ZERO_UWI}'
                  AND UWI14 IN ({_p2_keys})
                GROUP BY UWI14"""'''

# 3) scope the fill SELECT to unstamped rows
a3 = '''                FROM file_catalog.FILE_WELL_HEADER h
                JOIN r ON r.UWI14 = {u14H}
                WHERE ({any_blank})""")'''
b3 = '''                FROM file_catalog.FILE_WELL_HEADER h
                JOIN r ON r.UWI14 = {u14H}
                WHERE ({any_blank}) AND h.LAST_ENRICHED_AT IS NULL""")'''

# 4) scope the fill UPDATE to unstamped rows
a4 = '''                    FROM file_catalog.FILE_WELL_HEADER h
                    JOIN r ON r.UWI14 = {u14H}
                    WHERE ({any_blank})""")'''
b4 = '''                    FROM file_catalog.FILE_WELL_HEADER h
                    JOIN r ON r.UWI14 = {u14H}
                    WHERE ({any_blank}) AND h.LAST_ENRICHED_AT IS NULL""")'''

# 5) stamp enriched rows at the end of the WELL section (before SEIS)
a5 = '''                say("[WELL  ] applied fills")

    # ── SEIS pass: survey name from the file name (also server-side) ─────────'''
b5 = '''                say("[WELL  ] applied fills")

        # stamp rows we just enriched so the next run skips them (incremental)
        if not a.dry_run:
            cur.execute(
                "UPDATE file_catalog.FILE_WELL_HEADER SET LAST_ENRICHED_AT = SYSUTCDATETIME() "
                "WHERE LAST_ENRICHED_AT IS NULL AND UWI14 IS NOT NULL")

    # ── SEIS pass: survey name from the file name (also server-side) ─────────'''

for tag, a, b in (("1-col", a1, b1), ("2-refagg", a2, b2), ("3-select", a3, b3),
                  ("4-update", a4, b4), ("5-stamp", a5, b5)):
    if a not in s:
        sys.exit(f"FAILED at {tag}: anchor not found (file differs from expected)")
    s = s.replace(a, b, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: enrich pass 2 is now incremental via LAST_ENRICHED_AT (~32s -> ~2s)")

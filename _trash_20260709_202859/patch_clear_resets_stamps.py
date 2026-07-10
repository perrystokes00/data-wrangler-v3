r"""
patch_clear_resets_stamps.py — make the 'Clear catalog & data rows' button also null
CAPTURED_HASH / VAULTED_AT / PROMOTED_AT on GLOBAL_FILE_CATALOG.

Bug: clear wipes cat_*/dv_* rows but leaves CAPTURED_HASH stamped, so the next crawl's
capture stage skips those files (CAPTURED_HASH == FILE_HASH = "already captured") and
they never re-capture — LAS gets marked extracted but writes no cat_well/curves. This
adds a stamp reset right after _cc.clear so a cleared catalog truly re-captures.

Function-scoped edit in _pipeline_clear. .bak, idempotent, verifies parse.
py patch_clear_resets_stamps.py
"""
import os, ast, sys
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("pages", "page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "reset capture stamps on clear" in s:
    print("already patched"); sys.exit(0)

anchor = '''            rows = _cc.gather(cur, do_dv=True, keep=set())
            _cc.clear(cur, rows, _log)
            raw.commit(); raw.close()
            st.success("Catalog and catalog-derived dv_* rows cleared.")'''

inject = '''            rows = _cc.gather(cur, do_dv=True, keep=set())
            _cc.clear(cur, rows, _log)
            # reset capture stamps on clear: clearing cat_*/dv_* leaves CAPTURED_HASH
            # stamped, which makes the next crawl's capture skip these files as
            # "already captured" so they never re-capture. Null the stamps so a
            # cleared catalog truly re-processes every file.
            try:
                _rc = cur.execute(
                    "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
                    "SET CAPTURED_HASH = NULL, VAULTED_AT = NULL, PROMOTED_AT = NULL "
                    "WHERE CAPTURED_HASH IS NOT NULL OR VAULTED_AT IS NOT NULL "
                    "OR PROMOTED_AT IS NOT NULL").rowcount
                _log(f"reset capture/vault/promote stamps on {_rc or 0} catalog row(s)")
            except Exception as _se:
                _log(f"(stamp reset skipped: {str(_se)[:80]})")
            raw.commit(); raw.close()
            st.success("Catalog and catalog-derived dv_* rows cleared "
                       "(capture stamps reset — files will re-capture on next run).")'''

if anchor not in s:
    sys.exit("FAILED: clear-catalog anchor not found")
s = s.replace(anchor, inject, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: Clear now resets CAPTURED_HASH/VAULTED_AT/PROMOTED_AT")

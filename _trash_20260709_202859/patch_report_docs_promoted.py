r"""
patch_report_docs_promoted.py — fix the inventory report so document-path files (LAS,
PDF, Office, WITSML) show as promoted when their data actually reached dv_*, not only
when PROMOTED_AT is stamped.

Why: promote stamps PROMOTED_AT only WHERE CATALOG_READINESS='CATALOGED'. LAS (and other
document-path files) sit at READY after the fast-path, so they never get PROMOTED_AT even
though their data promoted into dv_well/dv_well_log/dv_well_log_curve. The report reads
PROMOTED_AT and wrongly shows 'not promoted'. Confirmed: 20/20 LAS wells + curves are in
dv_*, zero orphans — purely a display gap.

Fix: add a docs_done CTE (INVENTORY_IDs whose data reached any dv_* document table) and a
_docs credit fragment applied everywhere the existing _seis credit is. Mirrors the report's
own seis_done pattern exactly. Display-only; no pipeline behavior changes.

Function-scoped edit to _inventory_report_df. .bak, idempotent, verifies parse.
py patch_report_docs_promoted.py
"""
import os, ast, sys
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("pages", "page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "docs_done AS" in s and "_docs" in s:
    print("already patched"); sys.exit(0)

# 1) after the seis_ok block, build docs_done CTE + _docs fragment. Replace the
#    if/else that sets _cte/_join/_seis with a version that also sets _docs and
#    appends docs_done to the CTE + join.
anchor = '''        if _seis_ok:
            _cte = ("WITH seis_done AS ("
                    "SELECT DISTINCT sh.INVENTORY_ID "
                    "FROM file_catalog.FILE_SEIS_HEADER sh "
                    "JOIN dataview.dv_seis_set ss "
                    "ON ss.seis_set_name = sh.SURVEY_NAME) ")
            _join = "LEFT JOIN seis_done sd ON sd.INVENTORY_ID = g.INVENTORY_ID "
            _seis = "OR sd.INVENTORY_ID IS NOT NULL "
        else:
            _cte = _join = _seis = ""'''

replacement = '''        # docs_done: INVENTORY_IDs whose data reached any dv_* document table (LAS
        # log/curve, tops, surveys, production, completions). LAS etc. sit at READY
        # after capture so PROMOTED_AT is never stamped, but their data DID promote —
        # credit them here so the report reflects reality.
        _doc_tabs = ("dv_well_log", "dv_well_log_curve", "dv_well_formation_top",
                     "dv_well_dir_srvy_hdr", "dv_well_dir_srvy_sta",
                     "dv_well_completion", "dv_prod_volume")
        _doc_sel = []
        for _dt in _doc_tabs:
            try:
                _has = con.execute(_t(
                    "SELECT CASE WHEN OBJECT_ID(:o) IS NOT NULL AND EXISTS("
                    "SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(:o) "
                    "AND name='INVENTORY_ID') THEN 1 ELSE 0 END"),
                    {"o": f"dataview.{_dt}"}).scalar()
                if _has:
                    _doc_sel.append(f"SELECT INVENTORY_ID FROM dataview.{_dt} "
                                    f"WHERE INVENTORY_ID IS NOT NULL")
            except Exception:
                pass
        _docs_cte = ("docs_done AS (SELECT DISTINCT INVENTORY_ID FROM ("
                     + " UNION ALL ".join(_doc_sel) + ") _du) ") if _doc_sel else ""
        _docs_join = "LEFT JOIN docs_done dd ON dd.INVENTORY_ID = g.INVENTORY_ID " if _doc_sel else ""
        _docs = "OR dd.INVENTORY_ID IS NOT NULL " if _doc_sel else ""

        _ctes = []
        if _seis_ok:
            _ctes.append("seis_done AS ("
                         "SELECT DISTINCT sh.INVENTORY_ID "
                         "FROM file_catalog.FILE_SEIS_HEADER sh "
                         "JOIN dataview.dv_seis_set ss "
                         "ON ss.seis_set_name = sh.SURVEY_NAME) ")
        if _docs_cte:
            _ctes.append(_docs_cte)
        _cte = ("WITH " + ", ".join(_ctes) + " ") if _ctes else ""
        _join = (("LEFT JOIN seis_done sd ON sd.INVENTORY_ID = g.INVENTORY_ID "
                  if _seis_ok else "") + _docs_join)
        _seis = ("OR sd.INVENTORY_ID IS NOT NULL " if _seis_ok else "") + _docs'''

if anchor not in s:
    sys.exit("FAILED: seis_ok CTE anchor not found (report may differ)")
s = s.replace(anchor, replacement, 1)

ast.parse(s)
open(P + ".bak_docsrep", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: inventory report now credits document-path files (LAS/PDF/Office/WITSML)")
print("as promoted when their data reached dv_* (display-only fix)")

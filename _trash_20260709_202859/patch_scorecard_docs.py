r"""
patch_scorecard_docs.py — fix the file-type scorecard so DOCUMENT files (.pdf, .xlsx,
.csv, .docx) show as 'promoted' when their deep data actually landed in dv_*.

The scorecard credits 'promoted' only when GLOBAL_FILE_CATALOG.PROMOTED_AT IS NOT NULL.
Promote stamps that for well-header files, and there's a seis_done CTE for SEG-Y — but
document files whose tops/surveys/production/completion rows promote into dv_* never get
PROMOTED_AT stamped on their catalog row, so they show promoted=0 even though the data is
in dv_*. This adds a docs_done CTE (INVENTORY_IDs present in any dv_ document detail
table, matched by the INVENTORY_ID lineage promote copies down) and credits those files,
exactly mirroring the existing seismic pattern.

Function-scoped edit inside _inventory_scorecard only. .bak, idempotent, verifies parse.
py patch_scorecard_docs.py
"""
import os, ast, sys
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("pages", "page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "docs_done" in s:
    print("already patched"); sys.exit(0)

# 1) after the seismic-ok probe block, add a docs-ok probe + docs_done CTE pieces.
#    Anchor on the seismic CTE/join/seis assignment block (the if/else that sets
#    _cte, _join, _seis). We extend it to also compute _dcte, _djoin, _dprom.
anchor = '''        if _seis_ok:
            _cte = ("WITH seis_done AS ("
                    "SELECT DISTINCT sh.INVENTORY_ID "
                    "FROM file_catalog.FILE_SEIS_HEADER sh WITH (NOLOCK) "
                    "JOIN dataview.dv_seis_set ss "
                    "ON ss.seis_set_name = sh.SURVEY_NAME) ")
            _join = "LEFT JOIN seis_done sd ON sd.INVENTORY_ID = g.INVENTORY_ID "
            _seis = "OR sd.INVENTORY_ID IS NOT NULL "
        else:
            _cte = _join = _seis = ""'''

replacement = '''        if _seis_ok:
            _seis_cte = ("seis_done AS ("
                    "SELECT DISTINCT sh.INVENTORY_ID "
                    "FROM file_catalog.FILE_SEIS_HEADER sh WITH (NOLOCK) "
                    "JOIN dataview.dv_seis_set ss "
                    "ON ss.seis_set_name = sh.SURVEY_NAME) ")
            _join = "LEFT JOIN seis_done sd ON sd.INVENTORY_ID = g.INVENTORY_ID "
            _seis = "OR sd.INVENTORY_ID IS NOT NULL "
        else:
            _seis_cte = _join = _seis = ""

        # ── document promotion credit ────────────────────────────────────────
        # A .pdf/.xlsx/.csv/.docx is 'promoted' once its deep data (tops, dir
        # survey, production, completion, log curves) lands in dv_* — tracked by
        # the INVENTORY_ID lineage promote copies into each dv_ detail table.
        # Build a UNION over whichever dv_ document tables exist + carry
        # INVENTORY_ID, then credit any GFC row whose INVENTORY_ID appears there.
        _doc_tables = ("dv_well_formation_top", "dv_well_dir_srvy_hdr",
                       "dv_well_dir_srvy_sta", "dv_well_completion",
                       "dv_prod_volume", "dv_prod_entity", "dv_well_log",
                       "dv_well_log_curve", "dv_well_core", "dv_well_dst")
        _parts = []
        for _dt in _doc_tables:
            try:
                _has = con.execute(_t(
                    "SELECT CASE WHEN OBJECT_ID(:o) IS NOT NULL AND EXISTS("
                    "SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(:o) "
                    "AND name='INVENTORY_ID') THEN 1 ELSE 0 END"),
                    {"o": f"dataview.{_dt}"}).scalar() == 1
            except Exception:
                _has = False
            if _has:
                _parts.append(f"SELECT INVENTORY_ID FROM dataview.{_dt} WITH (NOLOCK) "
                              f"WHERE INVENTORY_ID IS NOT NULL")
        if _parts:
            _docs_cte = ("docs_done AS (SELECT DISTINCT INVENTORY_ID FROM ("
                         + " UNION ALL ".join(_parts) + ") _u) ")
            _djoin = "LEFT JOIN docs_done dd ON dd.INVENTORY_ID = g.INVENTORY_ID "
            _dprom = "OR dd.INVENTORY_ID IS NOT NULL "
        else:
            _docs_cte = _djoin = _dprom = ""

        # assemble the combined WITH clause from whichever CTEs are present
        _ctes = [c for c in (_seis_cte, _docs_cte) if c]
        _cte = ("WITH " + ", ".join(_ctes) + " ") if _ctes else ""
        _join = _join + _djoin'''

if anchor not in s:
    sys.exit("FAILED: seismic CTE anchor not found in _inventory_scorecard")
s = s.replace(anchor, replacement, 1)

# 2) credit docs in BOTH the cataloged and promoted SUMs (mirror how _seis is used).
#    cataloged: a doc with data in dv_ is certainly cataloged too.
s = s.replace(
    "SUM(CASE WHEN g.CATALOG_READINESS='CATALOGED' {_seis}THEN 1 ELSE 0 END) AS cataloged,",
    "SUM(CASE WHEN g.CATALOG_READINESS='CATALOGED' {_seis}{_dprom}THEN 1 ELSE 0 END) AS cataloged,")
s = s.replace(
    "SUM(CASE WHEN g.PROMOTED_AT IS NOT NULL {_seis}THEN 1 ELSE 0 END) AS promoted,",
    "SUM(CASE WHEN g.PROMOTED_AT IS NOT NULL {_seis}{_dprom}THEN 1 ELSE 0 END) AS promoted,")

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: scorecard now credits document files as promoted when their "
      f"data is in dv_*")

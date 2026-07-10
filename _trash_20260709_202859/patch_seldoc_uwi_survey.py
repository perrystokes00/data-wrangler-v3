"""
patch_seldoc_uwi_survey.py — map Documents grid: show and sort by UWI (wells) /
Survey Name (seismic). Adds a computed _ident, sorts on it, renames the grid
column to "UWI / Survey". Idempotent, .bak.  Run: py patch_seldoc_uwi_survey.py
"""
import sys, ast
P = "page_selected_documents.py"
s = open(P, encoding="utf-8").read()
if 'view["_ident"]' in s:
    print("already patched"); sys.exit(0)

ident_block = (
    '    # identify by UWI (wells) / Survey Name (seismic); sort + show by it\n'
    '    if not view.empty:\n'
    '        def _ident(r):\n'
    '            if str(r.get("entity_type", "")).lower() == "seismic":\n'
    '                return str(r.get("survey_name") or r.get("uwi") or "")\n'
    '            return str(r.get("uwi") or r.get("survey_name") or "")\n'
    '        view = view.copy()\n'
    '        view["_ident"] = view.apply(_ident, axis=1)\n'
    '        view = view.sort_values(["_ident", "file_name"],\n'
    '                                kind="stable").reset_index(drop=True)\n')

# 1) install the ident+sort — replace the group-wells sort if present, else insert
grp = ('    # group a well\'s multiple files together (stable order for grid selection)\n'
       '    _grp_cols = [c for c in ("well_name", "uwi", "file_name")\n'
       '                 if c in view.columns]\n'
       '    if _grp_cols and not view.empty:\n'
       '        view = view.sort_values(_grp_cols, kind="stable").reset_index(drop=True)\n')
if grp in s:
    s = s.replace(grp, ident_block, 1)
else:
    anchor = '    view = _apply_filters(docs, search, type_label)\n'
    if anchor not in s:
        print("FAILED: no sort block and no _apply_filters anchor."); sys.exit(1)
    s = s.replace(anchor, anchor + ident_block, 1)

# 2) grid column: Well -> UWI / Survey (from _ident)
col_old = '        "Well": [(r.get("well_name") or r.get("uwi") or "") for _, r in view.iterrows()],\n'
col_new = ('        "UWI / Survey": (list(view["_ident"]) if "_ident" in view.columns\n'
           '                         else [(r.get("uwi") or r.get("survey_name") or "")\n'
           '                               for _, r in view.iterrows()]),\n')
if col_old not in s:
    print("FAILED: grid Well column not found."); sys.exit(1)
s = s.replace(col_old, col_new, 1)

# 3) disabled list rename
s = s.replace('        disabled=["File", "Well", "Type", "Ext"],\n',
              '        disabled=["File", "UWI / Survey", "Type", "Ext"],\n', 1)

# 4) selected-doc caption uses the ident
s = s.replace('    wname = row.get("well_name") or row.get("uwi") or ""\n',
              '    wname = row.get("_ident") or row.get("uwi") or row.get("survey_name") or ""\n', 1)
s = s.replace('f"Well: {wname}', 'f"UWI/Survey: {wname}', 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: grid shows + sorts by UWI / Survey Name")

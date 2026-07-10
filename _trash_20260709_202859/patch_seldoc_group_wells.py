"""
patch_seldoc_group_wells.py — in the map Documents grid, group a well's multiple
files together (sort by well, then file) and show a well count. Idempotent, .bak.
Run: py patch_seldoc_group_wells.py
"""
import sys, ast
P = "page_selected_documents.py"
s = open(P, encoding="utf-8").read()
if "_grp_cols" in s:
    print("already patched"); sys.exit(0)

old = '    view = _apply_filters(docs, search, type_label)\n'
new = ('    view = _apply_filters(docs, search, type_label)\n'
       '    # group a well\'s multiple files together (stable order for grid selection)\n'
       '    _grp_cols = [c for c in ("well_name", "uwi", "file_name")\n'
       '                 if c in view.columns]\n'
       '    if _grp_cols and not view.empty:\n'
       '        view = view.sort_values(_grp_cols, kind="stable").reset_index(drop=True)\n')
if old not in s:
    print("FAILED: _apply_filters anchor not found."); sys.exit(1)
s = s.replace(old, new, 1)

# caption: add a well count alongside the document count
cap_old = ('    st.caption(f"{len(view):,} document(s) shown "\n'
           '               f"(of {len(docs):,} for the selection).")\n')
cap_new = ('    _nw = view["well_name"].nunique() if "well_name" in view.columns else (\n'
           '          view["uwi"].nunique() if "uwi" in view.columns else 0)\n'
           '    st.caption(f"{len(view):,} document(s) across {_nw:,} well(s) shown "\n'
           '               f"(of {len(docs):,} for the selection).")\n')
if cap_old in s:
    s = s.replace(cap_old, cap_new, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: files grouped by well; caption shows well count")

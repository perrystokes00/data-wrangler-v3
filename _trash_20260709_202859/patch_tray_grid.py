"""
patch_tray_grid.py — replace the tray's multiselect picker with a checkbox GRID.
Tick wells in the grid -> selected_in_results -> Documents / Scout Tickets scope
to exactly those wells (Export still sends all). Idempotent, .bak.
Run: py patch_tray_grid.py
"""
import sys, ast
P = "page_well_map.py"
s = open(P, encoding="utf-8").read()
if 'key="tray_grid"' in s:
    print("already patched"); sys.exit(0)

old = (
    '            _scout_opts = {}\n'
    '            for cu in list(result_uwis):\n'
    '                well = uwi_index.get(cu, {})\n'
    '                # Schema-aware label: GOM dicts use well_name + suffix and\n'
    '                # company_name; dv_well uses well_name and operator_name.\n'
    '                _wn_base = well.get("well_name") or cu\n'
    '                _wn_sfx  = well.get("well_name_suffix") or ""\n'
    '                wn = (f"{_wn_base} {_wn_sfx}".strip() if _wn_sfx else _wn_base)\n'
    '                op = (well.get("operator_name") or well.get("company_name") or "")\n'
    '                _lbl = f"{wn} \u2014 {op}" if op else f"{wn}"\n'
    '                if _lbl in _scout_opts:            # disambiguate duplicates\n'
    '                    _lbl = f"{_lbl}  [{cu}]"\n'
    '                _scout_opts[_lbl] = cu\n'
    '\n'
    '            _picked = st.multiselect(\n'
    '                "Wells for Scout Tickets",\n'
    '                options=list(_scout_opts.keys()),\n'
    '                default=[],\n'
    '                key="scout_pick",\n'
    '                placeholder="\U0001F50E Pick wells to generate Scout Tickets\u2026",\n'
    '            )\n'
    '            selected_in_results = [_scout_opts[l] for l in _picked]\n')

new = (
    '            # Tray grid \u2014 tick wells to scope Scout Tickets / Documents.\n'
    '            _grid_rows = []\n'
    '            for cu in list(result_uwis):\n'
    '                well = uwi_index.get(cu, {})\n'
    '                _wn_base = well.get("well_name") or cu\n'
    '                _wn_sfx  = well.get("well_name_suffix") or ""\n'
    '                wn = (f"{_wn_base} {_wn_sfx}".strip() if _wn_sfx else _wn_base)\n'
    '                op = (well.get("operator_name") or well.get("company_name") or "")\n'
    '                _grid_rows.append({"Select": False, "UWI": str(cu),\n'
    '                                   "Well": wn, "Operator": op})\n'
    '            _grid_df = pd.DataFrame(_grid_rows)\n'
    '            _tray_edit = st.data_editor(\n'
    '                _grid_df,\n'
    '                column_config={"Select": st.column_config.CheckboxColumn(\n'
    '                    "Select", width="small")},\n'
    '                disabled=["UWI", "Well", "Operator"],\n'
    '                hide_index=True, use_container_width=True,\n'
    '                height=min(360, 40 + 35 * max(1, len(_grid_df))),\n'
    '                key="tray_grid",\n'
    '            )\n'
    '            selected_in_results = [str(r["UWI"]) for _, r in _tray_edit.iterrows()\n'
    '                                   if bool(r["Select"])]\n')

if old not in s:
    print("FAILED: multiselect picker block not found."); sys.exit(1)
s = s.replace(old, new, 1)

# update the helper caption to mention the grid + Documents
s = s.replace(
    "                \"<b>Export</b> sends <b>all</b> results. Pick wells above to \"\n"
    "                \"generate <b>Scout Tickets</b> for just those.\"\n",
    "                \"<b>Export</b> sends <b>all</b> results. Tick wells in the grid \"\n"
    "                \"to scope <b>Documents</b> / <b>Scout Tickets</b> to just those.\"\n", 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: tray checkbox grid -> selected_in_results -> Documents/Scout")

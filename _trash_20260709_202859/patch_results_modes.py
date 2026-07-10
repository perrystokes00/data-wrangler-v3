"""
patch_results_modes.py — split the map Results panel into two views via a radio:
  🛢 Wells      — the tray checkbox grid (tick wells -> Scout/Documents/Export)
  📄 Documents  — a scannable grid of ALL documents for the tray wells; a button
                  jumps to the full Documents page to view them.
Idempotent, .bak.  Run: py patch_results_modes.py
"""
import sys, ast
P = "page_well_map.py"
s = open(P, encoding="utf-8").read()
if "_render_results_documents" in s:
    print("already patched"); sys.exit(0)

# ── 1) helper before run() ──────────────────────────────────────────────────
helper = '''def _render_results_documents(engine, uwis):
    """Scannable list of ALL documents for the tray wells; a button jumps to the
    full Documents page to view them."""
    if not uwis:
        st.info("No wells in the tray.")
        return
    try:
        import page_selected_documents as _psd
        docs = _psd._docs_for_wells(engine, list(uwis))
    except Exception as e:
        st.error(f"Could not resolve documents: {e}")
        return
    if docs is None or docs.empty:
        st.info("No catalogued documents for these wells.")
        return
    _disp = pd.DataFrame({
        "File": [r.get("file_name") for _, r in docs.iterrows()],
        "Well": [(r.get("well_name") or r.get("uwi") or "") for _, r in docs.iterrows()],
        "Type": [r.get("doc_type") for _, r in docs.iterrows()],
        "Ext":  [str(r.get("file_ext") or "").lower() for _, r in docs.iterrows()],
    })
    st.caption(f"{len(_disp):,} document(s) across {len(uwis):,} well(s) \\u2014 scan below.")
    st.dataframe(_disp, hide_index=True, use_container_width=True,
                 height=min(400, 40 + 35 * max(1, len(_disp))))
    if st.button("\\U0001F4C4 Open in Documents page \\u2192", key="results_docs_open",
                 use_container_width=True, type="primary"):
        st.session_state["selected_entities"] = [
            {"type": "well", "id": _u, "name": _u} for _u in uwis]
        st.session_state["wm_docs_page"] = True
        st.session_state["_export_scroll_pending"] = True
        st.rerun()


'''
if "def run(engine=None):\n" not in s:
    print("FAILED: run() not found."); sys.exit(1)
s = s.replace("def run(engine=None):\n", helper + "def run(engine=None):\n", 1)

# ── 2) swap the Wells grid block for the mode-aware version ──────────────────
start = "        else:\n            # Scout Tickets run on a chosen subset; Export sends every result.\n"
end   = "                unsafe_allow_html=True)\n"
i0 = s.find(start)
if i0 == -1:
    print("FAILED: results else-branch start not found."); sys.exit(1)
i1 = s.find(end, i0)
if i1 == -1:
    print("FAILED: results caption end not found."); sys.exit(1)
i1 += len(end)

new_block = (
'        else:\n'
'            _res_mode = st.radio(\n'
'                "Results view", ["\U0001F6E2 Wells", "\U0001F4C4 Documents"],\n'
'                horizontal=True, key="results_mode:v1",\n'
'                label_visibility="collapsed")\n'
'            selected_in_results = []\n'
'            if _res_mode == "\U0001F6E2 Wells":\n'
'                # Tray grid \u2014 tick wells to scope Scout Tickets / Documents.\n'
'                _grid_rows = []\n'
'                for cu in list(result_uwis):\n'
'                    well = uwi_index.get(cu, {})\n'
'                    _wn_base = well.get("well_name") or cu\n'
'                    _wn_sfx  = well.get("well_name_suffix") or ""\n'
'                    wn = (f"{_wn_base} {_wn_sfx}".strip() if _wn_sfx else _wn_base)\n'
'                    op = (well.get("operator_name") or well.get("company_name") or "")\n'
'                    _grid_rows.append({"Select": False, "UWI": str(cu),\n'
'                                       "Well": wn, "Operator": op})\n'
'                _grid_df = pd.DataFrame(_grid_rows)\n'
'                _tray_edit = st.data_editor(\n'
'                    _grid_df,\n'
'                    column_config={"Select": st.column_config.CheckboxColumn(\n'
'                        "Select", width="small")},\n'
'                    disabled=["UWI", "Well", "Operator"],\n'
'                    hide_index=True, use_container_width=True,\n'
'                    height=min(360, 40 + 35 * max(1, len(_grid_df))),\n'
'                    key="tray_grid:sel",\n'
'                )\n'
'                selected_in_results = [str(r["UWI"]) for _, r in _tray_edit.iterrows()\n'
'                                       if bool(r["Select"])]\n'
'                st.markdown(\n'
'                    "<div style=\'font-size:11px;color:#555;padding:4px 0 6px 0\'>"\n'
'                    "<b>Export</b> sends <b>all</b> results. Tick wells in the grid "\n'
'                    "to scope <b>Documents</b> / <b>Scout Tickets</b> to just those."\n'
'                    "</div>",\n'
'                    unsafe_allow_html=True)\n'
'            else:\n'
'                _render_results_documents(engine, list(result_uwis))\n')

s = s[:i0] + new_block + s[i1:]

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: Results split into 🛢 Wells / 📄 Documents (jump to docs page)")

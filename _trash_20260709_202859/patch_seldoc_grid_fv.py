"""
patch_seldoc_grid_fv.py — map Documents page: replace the per-file expanders
(which nest file_viewer's own expanders -> crash) with a GRID whose first column
is a View checkbox. The checked row calls the real file_viewer.view() BELOW the
grid, at top level. Idempotent, .bak.  Run: py patch_seldoc_grid_fv.py
"""
import sys, ast
P = "page_selected_documents.py"
s = open(P, encoding="utf-8").read()
if "seldoc_grid" in s:
    print("already patched"); sys.exit(0)

marker = "    # \u2500\u2500 document list \u2014 one expander per file, viewer inside \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
if marker not in s:
    # fall back to the _viewable line as the split point
    marker = "    _viewable = file_viewer is not None\n"
if marker not in s:
    print("FAILED: document-list marker not found."); sys.exit(1)

head = s[:s.index(marker)]
new_tail = (
    "    # \u2500\u2500 grid: a View checkbox in the first column selects a doc to open \u2500\u2500\n"
    "    disp = pd.DataFrame({\n"
    "        \"View\": [False] * len(view),\n"
    "        \"File\": [(r.get(\"file_name\") or \"(unnamed)\") for _, r in view.iterrows()],\n"
    "        \"Well\": [(r.get(\"well_name\") or r.get(\"uwi\") or \"\") for _, r in view.iterrows()],\n"
    "        \"Type\": [(r.get(\"doc_type\") or \"\") for _, r in view.iterrows()],\n"
    "        \"Ext\":  [str(r.get(\"file_ext\") or \"\").lower() for _, r in view.iterrows()],\n"
    "    })\n"
    "    sel = st.session_state.get(\"seldoc_sel\")\n"
    "    if isinstance(sel, int) and 0 <= sel < len(disp):\n"
    "        disp.loc[sel, \"View\"] = True\n"
    "\n"
    "    edited = st.data_editor(\n"
    "        disp,\n"
    "        column_config={\"View\": st.column_config.CheckboxColumn(\"View\", width=\"small\")},\n"
    "        disabled=[\"File\", \"Well\", \"Type\", \"Ext\"],\n"
    "        hide_index=True, use_container_width=True, key=\"seldoc_grid\",\n"
    "    )\n"
    "    checked = [i for i in range(len(edited)) if bool(edited.iloc[i][\"View\"])]\n"
    "    new_sel = None\n"
    "    if checked:\n"
    "        new_sel = next((i for i in checked if i != sel), checked[0])\n"
    "    if new_sel != sel:\n"
    "        st.session_state[\"seldoc_sel\"] = new_sel\n"
    "        st.rerun()\n"
    "\n"
    "    if new_sel is None:\n"
    "        st.info(\"Tick a row's **View** box to open a document below.\")\n"
    "        return\n"
    "\n"
    "    row   = view.iloc[new_sel]\n"
    "    path  = row.get(\"file_path\")\n"
    "    ext   = str(row.get(\"file_ext\") or \"\").lower()\n"
    "    fname = row.get(\"file_name\") or \"(unnamed)\"\n"
    "    wname = row.get(\"well_name\") or row.get(\"uwi\") or \"\"\n"
    "\n"
    "    st.markdown(\"---\")\n"
    "    st.markdown(f\"### \U0001F4C4 {fname}\")\n"
    "    st.caption(f\"Well: {wname}  \u00b7  Type: {row.get('doc_type') or '\u2014'}  \u00b7  {path or '\u2014'}\")\n"
    "    if st.button(\"\u2716 Close\", key=\"seldoc_close\"):\n"
    "        st.session_state[\"seldoc_sel\"] = None\n"
    "        st.rerun()\n"
    "\n"
    "    if not path:\n"
    "        st.warning(\"No file path recorded for this document.\")\n"
    "        return\n"
    "    if file_viewer is None:\n"
    "        st.code(str(path), language=\"text\")\n"
    "        st.caption(\"Inline viewer unavailable (file_viewer not importable).\")\n"
    "        return\n"
    "    # file_viewer.view runs at TOP LEVEL (not inside an expander), so its own\n"
    "    # expanders no longer nest -> fixes the nested-expander crash.\n"
    "    try:\n"
    "        file_viewer.view(str(path), ext or None)\n"
    "    except Exception as e:\n"
    "        st.error(f\"Viewer failed: {e}\")\n"
)
s = head + new_tail
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: grid + View checkbox; file_viewer.view() called at top level")

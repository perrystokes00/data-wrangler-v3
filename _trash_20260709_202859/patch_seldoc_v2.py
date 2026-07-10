"""
patch_seldoc_v2.py — map Documents page: (1) render .las as log curves (header +
curves + values + plot), (2) replace per-document expanders with a GRID whose
first column is a View checkbox; the checked row renders below the grid (fixes the
nested-expander crash). Idempotent, .bak.  Run: py patch_seldoc_v2.py
"""
import sys, ast
P = "page_selected_documents.py"
s = open(P, encoding="utf-8").read()

# ── Part 1: LAS viewer (only if not already present) ─────────────────────────
if "_render_las" not in s:
    s = s.replace(
        '_TEXT_EXTS = {"txt", "csv", "log", "json", "md", "las", "xml", "p190",\n'
        '              "witsml", "geojson", "kml"}\n',
        '_TEXT_EXTS = {"txt", "csv", "log", "json", "md", "xml", "p190",\n'
        '              "witsml", "geojson", "kml"}\n', 1)
    viewer = '''def _render_las(path):
    """Inline LAS viewer: well header, curve metadata, and curve VALUES."""
    try:
        import lasio
    except ImportError:
        st.error("lasio is not installed — run: pip install lasio")
        return
    try:
        las = lasio.read(path)
    except Exception as e:
        st.error(f"Could not parse LAS: {e}")
        return
    _hdr = {it.mnemonic: it.value for it in las.well}
    _wn = _hdr.get("WELL") or _hdr.get("UWI") or os.path.basename(path)
    st.markdown(f"**LAS** — {_wn}")
    st.markdown("**Well header**")
    st.dataframe(pd.DataFrame(
        [(it.mnemonic, it.unit, it.value, it.descr) for it in las.well],
        columns=["Mnemonic", "Unit", "Value", "Description"]),
        use_container_width=True, hide_index=True)
    st.markdown("**Curves**")
    st.dataframe(pd.DataFrame(
        [(c.mnemonic, c.unit, c.descr) for c in las.curves],
        columns=["Mnemonic", "Unit", "Description"]),
        use_container_width=True, hide_index=True)
    try:
        df = las.df().reset_index()
        depth_col = df.columns[0]
        st.markdown(f"**Curve values** — {len(df):,} samples")
        st.dataframe(df, use_container_width=True, height=380)
        num_cols = [c for c in df.columns[1:]
                    if pd.api.types.is_numeric_dtype(df[c])]
        if num_cols:
            sel = st.selectbox("Plot curve vs depth", num_cols,
                               key=f"las_plot_{os.path.basename(path)}")
            st.line_chart(df.set_index(depth_col)[[sel]])
    except Exception as e:
        st.warning(f"Could not build curve table: {e}")


'''
    s = s.replace("def _render_inline(path, ext, key):\n",
                  viewer + "def _render_inline(path, ext, key):\n", 1)
    s = s.replace(
        '            elif ext in _IMG_EXTS:\n'
        '                st.image(data, use_column_width=True)\n'
        '            elif ext in _TEXT_EXTS:\n',
        '            elif ext in _IMG_EXTS:\n'
        '                st.image(data, use_column_width=True)\n'
        '            elif ext == "las":\n'
        '                _render_las(path)\n'
        '            elif ext in _TEXT_EXTS:\n', 1)

# ── Part 2: grid + checkbox (replace the expander loop) ──────────────────────
if "seldoc_grid" not in s:
    marker = '    viewing = st.session_state.get("seldoc_view")'
    if marker not in s:
        print("FAILED: expander-loop marker not found."); sys.exit(1)
    head = s[:s.index(marker)]
    new_tail = '''    # ── grid: a View checkbox in the first column selects a doc to open ────
    disp = pd.DataFrame({
        "View":       [False] * len(view),
        "File":       [(r.get("file_name") or "(unnamed)") for _, r in view.iterrows()],
        "UWI/Survey": [(r.get("uwi14") or r.get("survey_name") or "") for _, r in view.iterrows()],
        "Type":       [(r.get("doc_type") or "") for _, r in view.iterrows()],
        "Ext":        [str(r.get("file_ext") or "").lower() for _, r in view.iterrows()],
        "Vault":      ["\\U0001F4E6" if (r.get("vault_path") and str(r.get("vault_path")).strip())
                       else "" for _, r in view.iterrows()],
    })
    sel = st.session_state.get("seldoc_view")
    if isinstance(sel, int) and 0 <= sel < len(disp):
        disp.loc[sel, "View"] = True

    edited = st.data_editor(
        disp,
        column_config={"View": st.column_config.CheckboxColumn("View", width="small")},
        disabled=["File", "UWI/Survey", "Type", "Ext", "Vault"],
        hide_index=True, use_container_width=True, key="seldoc_grid",
    )
    checked = [i for i in range(len(edited)) if bool(edited.iloc[i]["View"])]
    new_sel = None
    if checked:
        new_sel = next((i for i in checked if i != sel), checked[0])
    if new_sel != sel:
        st.session_state["seldoc_view"] = new_sel
        st.rerun()

    if new_sel is None:
        st.info("Tick a row's **View** box to open a document below.")
        return

    row   = view.iloc[new_sel]
    path  = row.get("open_path") or row.get("file_path")     # vault-preferred
    ext   = str(row.get("file_ext") or "").lower()
    fname = row.get("file_name") or "(unnamed)"
    st.markdown("---")
    st.markdown(f"### \\U0001F4C4 {fname}")
    st.caption(f"UWI/Survey: {row.get('uwi14') or row.get('survey_name') or ''}  ·  "
               f"Type: {row.get('doc_type') or '\\u2014'}  ·  {path or '\\u2014'}")

    oc1, oc2 = st.columns(2)
    if oc1.button("Open (native)", key="seldoc_open_sel", use_container_width=True):
        if not path or not os.path.exists(path):
            st.warning("File not found on disk.")
        elif _open_native:
            err = _open_native(path)
            st.success("Opened.") if err is None else st.error(err)
    if path and os.path.exists(path):
        try:
            with open(path, "rb") as fh:
                oc2.download_button("Download", fh.read(), file_name=fname,
                                    key="seldoc_dl_sel", use_container_width=True)
        except Exception as e:
            oc2.caption(f"unreadable: {str(e)[:30]}")

    if not path or not os.path.exists(path):
        st.warning("File not found on disk at the recorded path.")
    else:
        _render_inline(path, ext, key="sel")
'''
    s = head + new_tail

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: grid + View checkbox; .las -> log curves; no nested expanders")

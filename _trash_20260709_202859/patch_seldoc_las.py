"""
patch_seldoc_las.py — render .las in the map's document viewer as LOG CURVES
(header + curve metadata + curve values + a depth plot) instead of raw text.
Removes 'las' from the plain-text set and adds a lasio-backed _render_las().
In place, idempotent, .bak.

Run:  py patch_seldoc_las.py
"""
import sys, ast
P = "page_selected_documents.py"
s = open(P, encoding="utf-8").read()
if "_render_las" in s:
    print("already patched"); sys.exit(0)

# 1) stop treating .las as plain text
old_txt = ('_TEXT_EXTS = {"txt", "csv", "log", "json", "md", "las", "xml", "p190",\n'
           '              "witsml", "geojson", "kml"}\n')
new_txt = ('_TEXT_EXTS = {"txt", "csv", "log", "json", "md", "xml", "p190",\n'
           '              "witsml", "geojson", "kml"}\n')
if old_txt not in s:
    print("FAILED: _TEXT_EXTS anchor not found."); sys.exit(1)
s = s.replace(old_txt, new_txt, 1)

# 2) add the LAS viewer function before _render_inline
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

    with st.expander("Well header", expanded=False):
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
        df = las.df().reset_index()          # depth index -> first column
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
anchor_fn = "def _render_inline(path, ext, key):\n"
if anchor_fn not in s:
    print("FAILED: _render_inline anchor not found."); sys.exit(1)
s = s.replace(anchor_fn, viewer + anchor_fn, 1)

# 3) dispatch .las to the viewer in _render_inline
old_disp = ('            elif ext in _IMG_EXTS:\n'
            '                st.image(data, use_column_width=True)\n'
            '            elif ext in _TEXT_EXTS:\n')
new_disp = ('            elif ext in _IMG_EXTS:\n'
            '                st.image(data, use_column_width=True)\n'
            '            elif ext == "las":\n'
            '                _render_las(path)\n'
            '            elif ext in _TEXT_EXTS:\n')
if old_disp not in s:
    print("FAILED: dispatch anchor not found."); sys.exit(1)
s = s.replace(old_disp, new_disp, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: .las now renders as log curves (header + curves + values + plot)")

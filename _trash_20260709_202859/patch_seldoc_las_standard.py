"""
patch_seldoc_las_standard.py — replace the map's custom LAS viewer with the SAME
output as the workbench "Browse and View": curve values dataframe (via the app's
own _do_extract, lasio fallback). No custom header/curve/plot panels. Idempotent, .bak.

Run:  py patch_seldoc_las_standard.py
"""
import sys, ast
P = "page_selected_documents.py"
s = open(P, encoding="utf-8").read()
if "the app's standard path" in s:
    print("already standard"); sys.exit(0)
if "def _render_las(path):" not in s:
    print("FAILED: _render_las not found (run patch_seldoc_v2.py first)."); sys.exit(1)

start = s.index("def _render_las(path):")
end   = s.index("def _render_inline(path, ext, key):", start)

new_las = (
    'def _render_las(path):\n'
    '    """LAS log viewer — same output as the workbench Browse & View: the\n'
    '    curve values as a dataframe (metric + CSV download)."""\n'
    '    df = None\n'
    '    try:\n'
    '        from page_workbench import _do_extract          # the app\'s standard path\n'
    '        rows, _lbl = _do_extract(path, ".las")\n'
    '        if rows:\n'
    '            df = pd.DataFrame(rows).fillna("")\n'
    '    except Exception:\n'
    '        df = None\n'
    '    if df is None:\n'
    '        try:\n'
    '            import lasio\n'
    '            df = lasio.read(path).df().reset_index().fillna("")\n'
    '        except Exception as e:\n'
    '            st.error(f"Could not read LAS: {e}")\n'
    '            return\n'
    '    st.metric("Curve rows extracted", len(df))\n'
    '    st.dataframe(df, hide_index=True, use_container_width=True)\n'
    '    st.download_button(\n'
    '        "\\u2b07 Download Curve rows CSV", df.to_csv(index=False),\n'
    '        file_name=os.path.splitext(os.path.basename(path))[0] + "_curve_rows.csv",\n'
    '        mime="text/csv", key=f"las_csv_{os.path.basename(path)}")\n'
    '\n\n')

s = s[:start] + new_las + s[end:]
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: LAS view now matches the workbench Browse & View (curve values)")

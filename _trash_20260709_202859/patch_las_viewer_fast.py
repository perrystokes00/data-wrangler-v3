"""
patch_las_viewer_fast.py — fast LAS viewer:
  1) cache lasio.read via st.cache_resource (keyed path+mtime) — parse once, not
     on every curve-select rerun; shows a spinner instead of a grey screen
  2) decimate the plot to ~3000 pts/curve so huge logs render instantly
Idempotent, .bak.  Run: py patch_las_viewer_fast.py
"""
import sys, ast
P = "file_viewer.py"
s = open(P, encoding="utf-8").read()
if "_las_cached" in s:
    print("already patched"); sys.exit(0)

# 1) cached reader before _view_las
cached = ('@st.cache_resource(show_spinner="Loading log\u2026", max_entries=8)\n'
          'def _las_cached(file_path: str, _mtime: float):\n'
          '    """Parse a LAS once; cached on path+mtime so re-selecting curves\n'
          '    (a Streamlit rerun) doesn\'t re-read the whole file."""\n'
          '    import lasio\n'
          '    return lasio.read(file_path)\n\n\n')
if "def _view_las(file_path: str):\n" not in s:
    print("FAILED: _view_las not found."); sys.exit(1)
s = s.replace("def _view_las(file_path: str):\n", cached + "def _view_las(file_path: str):\n", 1)

# 2) one-line read swap
old = "        import lasio\n        las = lasio.read(file_path)\n"
new = "        import os\n        las = _las_cached(file_path, os.path.getmtime(file_path))\n"
if old not in s:
    print("FAILED: lasio.read line not found."); sys.exit(1)
s = s.replace(old, new, 1)

# 3) decimate the plot
a1 = "        n     = len(curves)\n        depth = df[depth_col].values\n"
n1 = ("        # decimate to ~3000 pts/curve so huge logs plot instantly\n"
      "        step  = max(1, len(df) // 3000)\n"
      "        dfp   = df.iloc[::step]\n"
      "        n     = len(curves)\n"
      "        depth = dfp[depth_col].values\n")
if a1 not in s:
    print("FAILED: plot depth line not found."); sys.exit(1)
s = s.replace(a1, n1, 1)
s = s.replace("            vals = df[curve].replace([np.inf, -np.inf], np.nan).values\n",
              "            vals = dfp[curve].replace([np.inf, -np.inf], np.nan).values\n", 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: cached parse + spinner + decimated plot")

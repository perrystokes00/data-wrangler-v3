"""patch_fix_batch_import.py — make page_workbench find pipeline_batch_ui by adding
modules\\ to sys.path before importing it. In place, .bak, idempotent.
py patch_fix_batch_import.py"""
import sys, os, ast
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("modules", "page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found")
s = open(P, encoding="utf-8").read()
if "pipeline_batch_ui" not in s:
    sys.exit("batch panel not wired yet — run patch_add_batch_ui.py first")
if "_bp_md" in s:
    print("already fixed"); sys.exit(0)

nl = "\r\n" if "\r\n" in s else "\n"
old = ("    try:" + nl +
       "        import pipeline_batch_ui" + nl +
       "        pipeline_batch_ui.render(engine)" + nl +
       "    except Exception as _bpe:" + nl +
       "        st.caption(f\"(batch panel unavailable: {_bpe})\")")
new = ("    try:" + nl +
       "        import os as _bp_os, sys as _bp_sys" + nl +
       "        _bp_md = _bp_os.path.join(_bp_os.path.dirname(_bp_os.path.abspath(__file__)), \"modules\")" + nl +
       "        if _bp_md not in _bp_sys.path:" + nl +
       "            _bp_sys.path.insert(0, _bp_md)" + nl +
       "        import pipeline_batch_ui" + nl +
       "        pipeline_batch_ui.render(engine)" + nl +
       "    except Exception as _bpe:" + nl +
       "        st.caption(f\"(batch panel unavailable: {_bpe})\")")

if old not in s:
    sys.exit("FAILED: batch panel block not found in expected form "
             "(paste the ~6 lines around 'import pipeline_batch_ui' and I'll match it)")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak4", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: adds modules\\ to sys.path before importing pipeline_batch_ui")

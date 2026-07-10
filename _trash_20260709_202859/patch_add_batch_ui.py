"""patch_add_batch_ui.py — add the batch-processing panel to the pipeline tab in
page_workbench.py, right under the Run Pipeline hero. In place, .bak, idempotent.
py patch_add_batch_ui.py"""
import sys, os, ast
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("modules", "page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (run in app root or modules)")
s = open(P, encoding="utf-8").read()
if "pipeline_batch_ui" in s:
    print("already patched"); sys.exit(0)

nl = "\r\n" if "\r\n" in s else "\n"
anchor = "    _pipeline_run_hero(engine, dialect)"
if anchor not in s:
    sys.exit("FAILED: _pipeline_run_hero(engine, dialect) anchor not found")

block = (anchor + nl + nl +
         "    st.divider()" + nl +
         "    try:" + nl +
         "        import pipeline_batch_ui" + nl +
         "        pipeline_batch_ui.render(engine)" + nl +
         "    except Exception as _bpe:" + nl +
         "        st.caption(f\"(batch panel unavailable: {_bpe})\")")
s = s.replace(anchor, block, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: batch panel added under the Run Pipeline hero in _tab_pipeline")

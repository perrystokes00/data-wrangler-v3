"""check_batch_ui.py — why the batch panel isn't showing. py check_batch_ui.py
(run in app root, above modules\\)"""
import os, sys

# 1) module present?
mod = next((p for p in ("modules/pipeline_batch_ui.py", "pipeline_batch_ui.py")
            if os.path.exists(p)), None)
print("1) pipeline_batch_ui.py :", os.path.abspath(mod) if mod else "NOT FOUND")

# 2) page_workbench patched?
pw = next((p for p in ("page_workbench.py", "modules/page_workbench.py")
           if os.path.exists(p)), None)
if pw:
    s = open(pw, encoding="utf-8", errors="replace").read()
    print("2) page_workbench call :", "pipeline_batch_ui.render" in s,
          "(" + os.path.abspath(pw) + ")")
else:
    print("2) page_workbench.py   : NOT FOUND")

# 3) does it import cleanly + expose render?
sys.path.insert(0, "modules"); sys.path.insert(0, ".")
try:
    import pipeline_batch_ui
    print("3) import + render     :", hasattr(pipeline_batch_ui, "render"))
except Exception as e:
    print("3) IMPORT ERROR        :", repr(e)[:200])

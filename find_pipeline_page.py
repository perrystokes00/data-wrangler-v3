"""find_pipeline_page.py — locate the app file that renders the pipeline UI, so you
know where to add pipeline_batch_ui.render(engine). py find_pipeline_page.py"""
import os, re
ROOT = "."
pat = re.compile(r"run_pipeline\s*\(|Pipeline Monitor|Run Pipeline|run_pipeline_batched|"
                 r"st\.button\(.*[Pp]ipeline", re.I)
hits = {}
for dirpath, dirs, files in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules")]
    for fn in files:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dirpath, fn)
        try:
            txt = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        lines = [i + 1 for i, ln in enumerate(txt.splitlines()) if pat.search(ln)]
        if lines and "run_pipeline(" in txt:      # the page that *calls* run_pipeline
            hits[p] = lines[:6]

print("files that call run_pipeline (candidate pages to edit):")
for p, lns in sorted(hits.items(), key=lambda x: -len(x[1])):
    print(f"  {p}   (lines {lns})")
if not hits:
    print("  (none found — run this in your app root, above modules\\)")

"""
patch_tray_grid_persist.py — stop the session-state persist loops from re-assigning
the 'tray_grid' data_editor key (data_editor values can't be set via session_state,
which caused: "Values for the widget with key 'tray_grid' cannot be set...").
Adds 'tray_grid' to both persist skip-sets. Idempotent, .bak.
Run: py patch_tray_grid_persist.py
"""
import sys, ast
P = "page_well_map.py"
s = open(P, encoding="utf-8").read()
n = 0

# skip-set on the docs page (loop @ ~4650)
o1 = ('            "close_summary_bottom", "open_docs_btn", "export_xlsx_btn",\n'
      '        }\n')
n1 = ('            "close_summary_bottom", "open_docs_btn", "export_xlsx_btn",\n'
      '            "tray_grid",\n'
      '        }\n')
if o1 in s and '"tray_grid",\n        }\n' not in s:
    s = s.replace(o1, n1, 1); n += 1

# skip-set on the export page (loop @ ~4734)
o2 = ('            "wells_clear_viewport", "view_summary", "clear_tray",\n'
      '            "close_summary_bottom",\n'
      '        }\n')
n2 = ('            "wells_clear_viewport", "view_summary", "clear_tray",\n'
      '            "close_summary_bottom", "tray_grid",\n'
      '        }\n')
if o2 in s:
    s = s.replace(o2, n2, 1); n += 1

if n == 0:
    print("FAILED: skip-set anchors not found (already patched?)."); sys.exit(1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched: 'tray_grid' added to {n} persist skip-set(s)")

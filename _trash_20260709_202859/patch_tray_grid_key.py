"""
patch_tray_grid_key.py — rename the tray grid's data_editor key to contain a ':'
so ALL session-state persist loops auto-skip it (they skip keys with \\ / :), and
a fresh key drops any stale 'tray_grid' value that was causing:
  "Values for the widget with key 'tray_grid' cannot be set using st.session_state"
Idempotent, .bak.  Run: py patch_tray_grid_key.py
"""
import sys, ast
P = "page_well_map.py"
s = open(P, encoding="utf-8").read()
if 'key="tray_grid:sel"' in s:
    print("already patched"); sys.exit(0)
if 'key="tray_grid",' not in s:
    print("FAILED: key=\"tray_grid\" not found (run patch_tray_grid.py first)."); sys.exit(1)
s = s.replace('key="tray_grid",', 'key="tray_grid:sel",', 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: tray grid key -> 'tray_grid:sel' (auto-skipped by all persist loops)")

r"""
patch_ui_defaults.py — set File Catalog Pipeline defaults: 'Use all CPU cores'
ON (routes to the process runner + BCP fast-path) and Parse workers = 6.
Only changes the DEFAULT used when the widget has no stored session value, so a
user can still toggle/adjust. In place, .bak, idempotent. py patch_ui_defaults.py
"""
import sys, os, ast
P = "page_workbench.py"
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (run in app root)")
s = open(P, encoding="utf-8").read()
if "# default: multi-core ON" in s:
    print("already patched"); sys.exit(0)

# 1) multi-core checkbox default False -> True
a1 = '''            fp_multicore = ccol.checkbox(
                "⚡ Use all CPU cores (multi-core parse)",
                value=bool(st.session_state.get("fp_multicore", False)),
                key="fp_multicore",'''
b1 = '''            fp_multicore = ccol.checkbox(
                "⚡ Use all CPU cores (multi-core parse)",
                value=bool(st.session_state.get("fp_multicore", True)),  # default: multi-core ON
                key="fp_multicore",'''

# 2) parse workers default -> 6
a2 = '''                value=int(st.session_state.get("fp_workers", min(12, os.cpu_count() or 8))),'''
b2 = '''                value=int(st.session_state.get("fp_workers", 6)),'''

for tag, a, b in (("1-multicore", a1, b1), ("2-workers", a2, b2)):
    if a not in s:
        sys.exit(f"FAILED at {tag}: anchor not found (file differs from expected)")
    s = s.replace(a, b, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: multi-core defaults ON, parse workers default 6")

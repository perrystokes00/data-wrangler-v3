r"""
patch_wire_fk_review.py — render the promote-stage FK review grid in the Run
Full Pipeline hero, right after a pipeline finishes. When a run HELD rows on an
unresolved reference code, the grid appears there so you Add/Map the code and
re-promote. Targets _pipeline_run_hero's 'Pipeline finished' message (the UI you
actually use), NOT the orphaned ⑧ expander. In place, .bak, idempotent.
py patch_wire_fk_review.py
"""
import os, ast, sys
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("pages", "page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "render_promote_fk" in s or "_render_promote_fk" in s:
    print("already wired"); sys.exit(0)

# Anchor: the 'Pipeline finished' success + the reports caption that follows, so
# we insert the grid right after the run completes (apply runs only).
anchor = '''                        _ap = st.session_state.get("fp_apply_run")
                        st.success(
                            f"Pipeline finished ({'APPLY' if _ap else 'dry-run'}). "
                            f"All reports saved under {_rr}.")'''

inject = '''                        _ap = st.session_state.get("fp_apply_run")
                        st.success(
                            f"Pipeline finished ({'APPLY' if _ap else 'dry-run'}). "
                            f"All reports saved under {_rr}.")
                        # ── reference FK review — surface rows the promote stage
                        # HELD on unseeded reference codes so you can Add/Map them
                        # and re-promote. Only meaningful after an apply run; the
                        # grid self-checks live DB state and shows a green ✅ when
                        # nothing is held.
                        if _ap:
                            try:
                                from modules.promote_fk_review import render as _render_promote_fk
                                _render_promote_fk(engine, st)
                            except Exception as _fkx:
                                st.caption(f"(FK review unavailable: {str(_fkx)[:100]})")'''

if anchor not in s:
    sys.exit("FAILED: 'Pipeline finished' anchor not found (page may differ)")
s = s.replace(anchor, inject, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: FK review grid now renders after a full pipeline run (hero)")

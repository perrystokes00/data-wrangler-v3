r"""patch_wire_report.py — render the honest promote report in the run hero, right
after 'Pipeline finished (APPLY)'. Sits above the FK review grid. Function-scoped,
.bak, idempotent. py patch_wire_report.py"""
import os, ast, sys
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("pages","page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found")
s = open(P, encoding="utf-8").read()
if "render_promote_report" in s:
    print("already wired"); sys.exit(0)

anchor = '''                        _ap = st.session_state.get("fp_apply_run")
                        st.success(
                            f"Pipeline finished ({'APPLY' if _ap else 'dry-run'}). "
                            f"All reports saved under {_rr}.")'''
inject = anchor + '''
                        # accurate 'what actually promoted' report (reads dv_* directly,
                        # unlike the per-file 'promoted' flag which only covers seismic)
                        if _ap:
                            try:
                                from modules.promote_report_ui import render as _render_promote_report
                                _render_promote_report(engine, st)
                            except Exception as _rx:
                                st.caption(f"(report unavailable: {str(_rx)[:100]})")'''
if anchor not in s:
    sys.exit("FAILED: 'Pipeline finished' anchor not found")
s = s.replace(anchor, inject, 1)
ast.parse(s)
open(P+".bak","w",encoding="utf-8").write(open(P,encoding="utf-8").read())
open(P,"w",encoding="utf-8").write(s)
print(f"patched {P}: honest promote report renders after a run")

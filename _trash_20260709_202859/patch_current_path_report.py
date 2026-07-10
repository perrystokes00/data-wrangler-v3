r"""
patch_current_path_report.py — add a 'This crawl only' button to the Inventory report
that scopes it to the folder currently in the Root-folder box (wb_scan_path), so you
don't have to Clear the catalog to see just what you're crawling now.

The report already filters on g.ROOT_PATH; this adds a one-click way to set that filter
to the current crawl path (matched by prefix, so subfolders count). Function-scoped edit
to the inventory-report expander. .bak, idempotent, verifies parse.
py patch_current_path_report.py
"""
import os, ast, sys
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("pages", "page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "rep_this_crawl" in s:
    print("already patched"); sys.exit(0)

# 1) add the button next to the root selector + recent checkbox
anchor = '''        recent = rc2.checkbox(
            "Scanned today", value=False, key="rep_recent",
            help="Limit to files whose SCAN_DATE is today.")
        if not st.button("Write report to reports folder", key="rep_run",
                         use_container_width=True):
            return'''

inject = '''        recent = rc2.checkbox(
            "Scanned today", value=False, key="rep_recent",
            help="Limit to files whose SCAN_DATE is today.")
        # one-click scope to the folder currently in the Root-folder box, so you can
        # see just what you're crawling now without clearing the catalog.
        _cur_path = (st.session_state.get("wb_scan_path")
                     or st.session_state.get("wb_last_scan_path") or "").strip()
        bc1, bc2 = st.columns(2)
        _this_crawl = bc1.button("📍 This crawl only", key="rep_this_crawl",
                                 use_container_width=True,
                                 help=f"Scope to the current Root folder:\\n{_cur_path}"
                                 if _cur_path else "Set a Root folder first")
        _whole = bc2.button("Write report to reports folder", key="rep_run",
                            use_container_width=True)
        if not (_this_crawl or _whole):
            return
        # if 'This crawl only' was clicked, force the root filter to the current path
        if _this_crawl and _cur_path:
            rsel = "__CURRENT_PATH__"'''

if anchor not in s:
    sys.exit("FAILED: report button anchor not found")
s = s.replace(anchor, inject, 1)

# 2) make the WHERE clause honor the current-path sentinel (prefix match, so
#    subfolders count) in addition to the exact-root dropdown.
anchor2 = '''                where, params = ["1=1"], {}
                if rsel and rsel != _ALL:
                    where.append("g.ROOT_PATH = :root")
                    params["root"] = rsel'''
inject2 = '''                where, params = ["1=1"], {}
                if rsel == "__CURRENT_PATH__" and _cur_path:
                    # prefix match on FILE_PATH so files under the current crawl
                    # folder (and its subfolders) are included regardless of the
                    # ROOT_PATH recorded at scan time.
                    where.append("g.FILE_PATH LIKE :curpath")
                    params["curpath"] = _cur_path.rstrip("\\\\/") + "%"
                elif rsel and rsel != _ALL:
                    where.append("g.ROOT_PATH = :root")
                    params["root"] = rsel'''
if anchor2 not in s:
    sys.exit("FAILED: report WHERE anchor not found")
s = s.replace(anchor2, inject2, 1)

ast.parse(s)
open(P + ".bak_curpath", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: added 'This crawl only' button to the Inventory report")

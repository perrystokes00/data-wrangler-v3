r"""
patch_scorecard_report.py — replace the "Inventory report" expander on the File Catalog
page with a file-by-file STAGE SCORECARD (EXTRACT / CAPTURE / PROMOTE per file), scoped to
the current crawl. Shows the table in-page and writes a CSV. Keeps the root-scoping UI.

Captured=Y means data reached cat_* OR dv_* (promote drains cat_*, so a promoted file
correctly reads captured). Promoted=Y means rows exist in dv_* for that file.

Replaces the block at the "📋 Inventory report" expander. .bak, idempotent, verifies parse.
py patch_scorecard_report.py
"""
import os, ast, sys
P = "page_workbench.py"
if not os.path.exists(P):
    P = os.path.join("modules", "page_workbench.py")
if not os.path.exists(P):
    sys.exit("page_workbench.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()

if "Stage scorecard" in s:
    print("already patched"); sys.exit(0)

# anchor: the whole expander block, from the 'with st.expander("📋 Inventory report'
start_anchor = '    with st.expander("📋 Inventory report — what happened to each file",'
end_anchor = '        tally = df["action_taken"].value_counts()\n        st.success(f"Report written to `{_path}`  ·  {len(df):,} file(s)")\n        st.caption("  ·  ".join(f"{k}: {v:,}" for k, v in tally.items()))\n'

i0 = s.find(start_anchor)
i1 = s.find(end_anchor)
if i0 == -1 or i1 == -1:
    sys.exit("FAILED: could not locate the inventory report block anchors")
i1_end = i1 + len(end_anchor)

new_block = r'''    with st.expander("📋 Stage scorecard — extract · capture · promote per file",
                     expanded=False):
        # Scope: default to THIS crawl (files scanned today), with an option to
        # widen to a scan root or the whole catalog.
        try:
            with engine.connect() as _c:
                _roots = [r[0] for r in _c.execute(_t(
                    "SELECT DISTINCT ROOT_PATH "
                    "FROM file_catalog.GLOBAL_FILE_CATALOG "
                    "WHERE NULLIF(LTRIM(RTRIM(ROOT_PATH)),'') IS NOT NULL "
                    "ORDER BY ROOT_PATH")).fetchall()]
        except Exception:
            _roots = []
        sc1, sc2 = st.columns([3, 1])
        _ALL = "(whole catalog)"
        scsel = sc1.selectbox(
            "Scan root", [_ALL] + _roots, index=0, key="score_root_sel",
            help="Limit to a scan root, or the whole catalog.")
        this_crawl = sc2.checkbox(
            "This crawl only", value=True, key="score_this_crawl",
            help="Limit to files scanned today (the current crawl).")
        if not st.button("Run scorecard", key="score_run",
                         use_container_width=True):
            return

        # detail tables: (cat_ staged, dv_ promoted, label). captured = rows in
        # cat_ OR dv_ ; promoted = rows in dv_. dv_ tables carry INVENTORY_ID.
        _DETAIL = [
            ("cat_well", "dv_well", "header"),
            ("cat_well_dir_srvy_sta", "dv_well_dir_srvy_sta", "survey"),
            ("cat_well_formation_top", "dv_well_formation_top", "tops"),
            ("cat_well_dst", "dv_well_dst", "welltest"),
            ("cat_well_completion", "dv_well_completion", "completion"),
            ("cat_prod_volume", "dv_prod_volume", "production"),
            ("cat_well_petro_interp", "dv_well_petro_interp", "petro"),
            ("cat_well_core", "dv_well_core", "core"),
            ("cat_well_log", "dv_well_log", "log"),
            ("cat_well_log_curve", "dv_well_log_curve", "curves"),
        ]
        try:
            with engine.connect() as con:
                where, params = ["1=1"], {}
                if scsel and scsel != _ALL:
                    where.append("g.ROOT_PATH = :root"); params["root"] = scsel
                if this_crawl:
                    where.append(
                        "CAST(g.SCAN_DATE AS date) = CAST(GETDATE() AS date)")
                base = con.execute(_t(f"""
                    SELECT g.FILE_NAME, g.INVENTORY_ID,
                           NULLIF(LTRIM(RTRIM(g.MATCHED_UWI)),'') AS uwi,
                           g.HEADER_EXTRACTED, wh.REPORT_TYPE
                    FROM file_catalog.GLOBAL_FILE_CATALOG g
                    LEFT JOIN file_catalog.FILE_WELL_HEADER wh
                           ON wh.INVENTORY_ID = g.INVENTORY_ID
                    WHERE {' AND '.join(where)}
                    ORDER BY g.FILE_NAME
                """), params).fetchall()

                def _cnt(tbl, inv):
                    try:
                        return con.execute(_t(
                            f"SELECT COUNT(*) FROM {tbl} WHERE INVENTORY_ID=:i"),
                            {"i": inv}).scalar() or 0
                    except Exception:
                        return 0

                rows = []
                for fn, inv, uwi, hx, rtype in base:
                    extracted = ("Y" if hx == "Y" else
                                 "ERR" if hx == "E" else
                                 "skip" if hx == "S" else "N")
                    cap = prom = 0; detail = []
                    for cat, dv, label in _DETAIL:
                        n_dv = _cnt("dataview." + dv, inv)
                        n_ct = _cnt("file_catalog." + cat, inv)
                        if n_dv:
                            prom += n_dv; cap += n_dv; detail.append(f"{label}:{n_dv}")
                        elif n_ct:
                            cap += n_ct; detail.append(f"{label}:{n_ct}(staged)")
                    rows.append({
                        "file": fn,
                        "type": rtype or "?",
                        "extract": extracted,
                        "capture": "Y" if cap else "N",
                        "promote": "Y" if prom else "N",
                        "uwi": uwi or "",
                        "detail": " ".join(detail) if detail else "no detail rows",
                    })
                df = pd.DataFrame(rows)
        except Exception as e:
            st.error(f"Scorecard failed: {type(e).__name__}: {e}")
            return

        if df.empty:
            st.info("No files in scope. Run a crawl, or widen the scope.")
            return

        n_ext = int((df["extract"] == "Y").sum())
        n_cap = int((df["capture"] == "Y").sum())
        n_prom = int((df["promote"] == "Y").sum())
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Files", len(df))
        m2.metric("Extracted", n_ext)
        m3.metric("Captured", n_cap)
        m4.metric("Promoted", n_prom)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption("captured=Y means data reached cat_* or dv_*; promoted=Y means it "
                   "reached dv_*. A promoted file shows captured=Y even though cat_* is "
                   "drained by promote — that's expected.")

        import time as _tm
        _rdir = st.session_state.get("fp_report", r"C:\Bulk\reports")
        try:
            os.makedirs(_rdir, exist_ok=True)
            _ts = _tm.strftime("%Y%m%d_%H%M%S")
            _path = os.path.join(_rdir, f"stage_scorecard_{_ts}.csv")
            df.to_csv(_path, index=False)
            st.success(f"Scorecard written to `{_path}`")
        except Exception as e:
            st.warning(f"Shown above; CSV write failed: {type(e).__name__}: {e}")
'''

s2 = s[:i0] + new_block + s[i1_end:]
ast.parse(s2)
open(P + ".bak_scorecard", "w", encoding="utf-8").write(s)
open(P, "w", encoding="utf-8").write(s2)
print(f"patched {P}: Inventory report replaced with Stage scorecard (scoped to current crawl)")

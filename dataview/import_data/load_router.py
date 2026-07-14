"""
load_router.py — one door for loading a directory. Look at what's in the folder and
send it down the right path:

    Route A  csv, xlsx/xlsm/xltx/xls        → page_dir_loader  (tabular: map → FK → promote)
    Route B  las, dlis, lis, xml/wml, pdf   → bulk_dir_loader   (well files: extract → stage)
    Route C  anything else                  → not supported (listed, not loaded)

Mixed folders are normal (a well folder often holds well_header.csv *and* scout.pdf),
so the router never guesses: it reports the counts and lets the operator pick a route.
Only when a single route matches does it hand off automatically.

Wire into app_v3.py:

    elif S.app_mode == "load_data":
        try:
            from dataview.import_data import load_router
            load_router.run(S.engine)
        except Exception as e:
            st.error(f"Load Data error: {e}")
"""
from __future__ import annotations
import os
import glob

try:
    import streamlit as st
except Exception:
    st = None

# route A — tabular
A_EXTS = (".csv", ".xlsx", ".xlsm", ".xltx", ".xls")
# route B — well / document files
B_EXTS = (".las", ".dlis", ".lis", ".xml", ".wml", ".pdf", ".docx", ".doc", ".odt")

_SHEET_DIR = "_xl_sheets"        # page_dir_loader's sidecar folder — not a source


def classify(directory, recursive=False):
    """→ {'A': [paths], 'B': [paths], 'C': [paths]} for one directory."""
    out = {"A": [], "B": [], "C": []}
    if not directory or not os.path.isdir(directory):
        return out
    pat = os.path.join(directory, "**", "*") if recursive else os.path.join(directory, "*")
    for p in glob.glob(pat, recursive=recursive):
        if not os.path.isfile(p):
            continue
        base = os.path.basename(p)
        if base.startswith("~$"):                       # Excel lock files
            continue
        if _SHEET_DIR in os.path.normpath(p).split(os.sep):   # our own generated sheets
            continue
        ext = os.path.splitext(p)[1].lower()
        if ext in A_EXTS:
            out["A"].append(p)
        elif ext in B_EXTS:
            out["B"].append(p)
        else:
            out["C"].append(p)
    return out


def _counts(paths):
    """{'.csv': 6, '.pdf': 2} for display."""
    c = {}
    for p in paths:
        e = os.path.splitext(p)[1].lower() or "(none)"
        c[e] = c.get(e, 0) + 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def _fmt(counts):
    return " · ".join(f"{n} {e}" for e, n in counts.items()) if counts else "—"


def _go_a(ss, directory):
    ss["dl_dir"] = directory          # pre-seed so page_dir_loader doesn't re-ask
    ss["dl_recursive"] = bool(ss.get("lr_recursive"))
    ss["dl_stage"] = "pick"
    ss["lr_route"] = "A"


def _go_b(ss, directory):
    ss["bdl_dir"] = directory         # pre-seed bulk_dir_loader's directory
    ss["bdl_recursive"] = bool(ss.get("lr_recursive"))   # carry recursion, or B scans flat
    ss["lr_route"] = "B"


def run(engine=None, dialect=None):
    if st is None:
        return
    ss = st.session_state

    # once routed, hand off to the chosen loader (with a way back)
    route = ss.get("lr_route")
    if route in ("A", "B"):
        top = st.columns([1, 4])
        if top[0].button("← Load another folder"):
            ss.pop("lr_route", None)
            st.rerun()
        top[1].caption(f"Route {route} · "
                       + ("tabular (CSV / Excel)" if route == "A" else "well files (LAS/DLIS/WITSML/PDF)"))
        if route == "A":
            try:
                from dataview.import_data import page_dir_loader as _a
            except Exception:
                import page_dir_loader as _a
            _a.run(engine, dialect)
        else:
            try:
                from dataview.import_data import bulk_dir_loader as _b
            except Exception:
                import bulk_dir_loader as _b
            _b.run()
        return

    st.title("📁 Directory Loader")
    st.caption("Drop in a folder — the extensions decide the path. "
               "**CSV / Excel** go to the tabular loader; **LAS, DLIS, LIS, WITSML, PDF** "
               "go to the well-file loader.")

    directory = st.text_input("Directory", value=ss.get("lr_dir", ss.get("dl_dir", "")))
    recursive = st.checkbox("Include subdirectories", value=ss.get("lr_recursive", False))
    ss["lr_dir"], ss["lr_recursive"] = directory, recursive

    if st.button("🔍 Scan & route", type="primary") and directory:
        if not os.path.isdir(directory):
            st.error("Not a directory.")
            return
        ss["lr_found"] = classify(directory, recursive)

    found = ss.get("lr_found")
    if not found:
        return

    a, b, c = found["A"], found["B"], found["C"]
    m = st.columns(3)
    m[0].metric("tabular (route A)", len(a), help=_fmt(_counts(a)) if a else None)
    m[1].metric("well files (route B)", len(b), help=_fmt(_counts(b)) if b else None)
    m[2].metric("not supported", len(c), help=_fmt(_counts(c)) if c else None)

    if a:
        st.caption(f"**A · tabular** — {_fmt(_counts(a))}")
    if b:
        st.caption(f"**B · well files** — {_fmt(_counts(b))}")

    if not a and not b:
        st.warning("Nothing loadable here. Supported: "
                   + ", ".join(A_EXTS + B_EXTS))
        if c:
            with st.expander(f"{len(c)} unsupported file(s)"):
                for p in sorted(c)[:200]:
                    st.markdown(f"- `{os.path.basename(p)}`")
        return

    # single route → go straight there (the system decides); mixed → ask, never guess
    if a and not b:
        _go_a(ss, directory); st.rerun()
    elif b and not a:
        _go_b(ss, directory); st.rerun()
    else:
        st.info("This folder holds **both** kinds. The two loaders stage differently, so run "
                "them one at a time — start with either, then come back for the other.")
        c1, c2 = st.columns(2)
        if c1.button(f"→ Tabular loader  ({len(a)} file(s))", use_container_width=True):
            _go_a(ss, directory); st.rerun()
        if c2.button(f"→ Well-file loader  ({len(b)} file(s))", use_container_width=True):
            _go_b(ss, directory); st.rerun()

    if c:
        with st.expander(f"{len(c)} unsupported file(s) — ignored"):
            for p in sorted(c)[:200]:
                st.markdown(f"- `{os.path.basename(p)}`")


render = main = show = app = run

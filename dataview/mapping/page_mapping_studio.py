"""
page_mapping_studio.py — the Mapping Studio page.

Flow:  domain -> scan a parent folder -> editable confirm list -> Confirm
       -> (next section) per-table mapping panels in FK order -> save snapshots
       -> FK reconciliation -> loader reads dv_table_mapping.

This file is the UI; all the logic lives in mapping_studio.py (scan/classify,
auto-match, snapshots, synonym learning) which is tested independently.

Section 1 (below) is the scan + confirm list. The mapping panels mount where
_render_mapping_panels() is stubbed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import streamlit as st

from dataview.mapping import mapping_studio as M

# small per-user preference store so things like the last-scanned folder
# survive an app restart (session_state only lives for the session).
_PREF_FILE = Path.home() / ".dataview_mapping_studio.json"


def _load_pref(key, default=None):
    try:
        return json.loads(_PREF_FILE.read_text(encoding="utf-8")).get(key, default)
    except Exception:
        return default


def _save_pref(key, value):
    try:
        d = {}
        if _PREF_FILE.exists():
            try:
                d = json.loads(_PREF_FILE.read_text(encoding="utf-8"))
            except Exception:
                d = {}
        d[key] = value
        _PREF_FILE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def render(engine, dialect=None):
    st.header("🗺  Mapping Studio")
    st.caption("Point at a folder. It detects what's there, proposes the target "
               "tables, and you map each one — saved as a reusable snapshot.")

    _schema_binding_controls(engine)
    _section_scan(engine)

    confirmed = st.session_state.get("ms_confirmed")
    if confirmed:
        st.divider()
        _render_mapping_panels(engine, confirmed)


# ── schema binding: point the Studio at any customer schema ──────────────────
def _schema_binding_controls(engine):
    """Apply (and optionally edit) the Studio's schema binding — which schema it
    reads target tables from, the table prefix, and the store schema where its
    registry (mappings/signatures/synonyms) lives. Defaults preserve the original
    DataView behaviour; a customer install overrides these per data model. The
    binding is pushed into mapping_studio via M.configure() on every render so it
    tracks the active session."""
    ss = st.session_state
    ts = ss.get("ms_bind_target_schema", M.TARGET_SCHEMA)
    tp = ss.get("ms_bind_target_prefix", M.TARGET_PREFIX)
    st_ = ss.get("ms_bind_store_schema", M.STORE_SCHEMA)
    rp = ss.get("ms_bind_ref_pattern", M.REF_TABLE_PATTERN)
    M.configure(target_schema=ts, target_prefix=tp, store_schema=st_,
                ref_table_pattern=rp)

    with st.expander(f"⚙ Schema binding — target `{ts}.{tp}*` · store `{st_}` "
                     f"· ref `{rp}*`", expanded=False):
        st.caption("Where the Studio reads target tables and writes its registry, "
                   "and how it recognizes controlled-vocabulary code tables (those "
                   "reconcile instead of halting). Defaults match DataView; change "
                   "these to point one Studio at a different customer schema.")
        c1, c2 = st.columns(2)
        n_ts = c1.text_input("Target schema", value=ts, key="ms_bind_ts_in")
        n_tp = c2.text_input("Target prefix", value=tp, key="ms_bind_tp_in")
        c3, c4 = st.columns(2)
        n_ss = c3.text_input("Store schema",  value=st_, key="ms_bind_ss_in")
        n_rp = c4.text_input("Ref-table pattern", value=rp, key="ms_bind_rp_in",
                             help="Substring identifying code/lookup tables, e.g. "
                                  "dv_r_ or ref_ or lookup_.")
        if st.button("Apply binding", key="ms_bind_apply"):
            ss["ms_bind_target_schema"] = n_ts.strip()
            ss["ms_bind_target_prefix"] = n_tp.strip()
            ss["ms_bind_store_schema"]  = n_ss.strip()
            ss["ms_bind_ref_pattern"]   = n_rp.strip()
            M.configure(target_schema=n_ts.strip(), target_prefix=n_tp.strip(),
                        store_schema=n_ss.strip(), ref_table_pattern=n_rp.strip())
            ss.pop("ms_schema", None)          # new target -> re-introspect
            ss.pop("ms_rarity", None)
            try:
                M.ensure_store(engine)         # new store -> create schema+tables
                st.success(f"Bound to `{n_ts}.{n_tp}*` · store `{n_ss}` "
                           f"· ref `{n_rp}*`. Schema cache cleared.")
            except Exception as e:
                st.error(f"Couldn't create store schema '{n_ss}': "
                         f"{type(e).__name__}: {e}")


# ── section 1: domain + scan + confirm list ──────────────────────────────────
def _section_scan(engine):
    domains = sorted({s["domain"] for s in M.SIGNATURES}) or ["Wells"]

    # pre-fill the folder box with the last folder scanned (persisted to disk)
    if "ms_root" not in st.session_state:
        st.session_state["ms_root"] = _load_pref("last_root", "")

    c1, c2, c3 = st.columns([1.1, 3, 1])
    domain = c1.selectbox("Data domain", domains, key="ms_domain")
    root = c2.text_input("Parent folder to scan",
                         key="ms_root", placeholder=r"C:\…\training_data")
    recurse = c3.checkbox("Recurse", value=True, key="ms_recurse")

    b1, b2, _ = st.columns([1.4, 1.6, 4])
    do_scan = b1.button("🔍  Scan folder", type="primary",
                        disabled=not root.strip(), key="ms_scan")
    if b2.button("↻  Refresh schema", key="ms_refresh_schema",
                 help="Re-read tables/columns — use after creating a table."):
        st.session_state.pop("ms_schema", None)
        st.session_state.pop("ms_rarity", None)
        st.session_state.pop("ms_resolved_cache", None)   # re-resolve against new schema
        st.toast("Schema cache cleared — next scan re-introspects.")

    if do_scan:
        _save_pref("last_root", root.strip())          # remember for next time
        try:
            # introspect the schema once and cache it (re-scans reuse it)
            if "ms_schema" not in st.session_state:
                sch = M.load_schema(engine)
                st.session_state["ms_schema"] = sch
                st.session_state["ms_rarity"] = M.column_rarity(sch) if sch else None
            with st.spinner("Scanning and classifying…"):
                t = {}
                items = M.scan_directory(engine, root.strip(), recursive=recurse,
                                         schema=st.session_state["ms_schema"],
                                         rarity=st.session_state["ms_rarity"],
                                         timings=t)
            st.session_state["ms_items"] = items
            st.session_state["ms_scan_timings"] = t
            st.session_state.pop("ms_confirmed", None)   # new scan resets downstream
        except Exception as e:
            st.error(f"Scan failed: {type(e).__name__}: {e}")

    items = st.session_state.get("ms_items")
    if items is None:
        return

    if not items:
        st.warning("No .csv/.tsv files found under that folder.")
        return

    # full data-type catalog -> proposed target tables (complete list, not gated
    # by what's been mapped). Each target carries an 'exists' flag for the (new) tag.
    try:
        dts = M.data_types(engine, domain=domain)
    except Exception:
        dts = [{"type": t, "targets": [{"table": tb, "exists": True} for tb in tbs]}
               for t, tbs in M.DATA_TYPE_CATALOG.get(domain, [])]
    cat_names = [d["type"] for d in dts]
    cat_targets = {d["type"]: [t["table"] for t in d["targets"]] for d in dts}
    tgt_exists = {t["table"]: t["exists"] for d in dts for t in d["targets"]}

    def _tgt_label(full):
        short = full.split(".")[-1]
        return short if tgt_exists.get(full, True) else f"{short}  (new)"

    badge = {"snapshot": "♻ reload", "detected": "✓ detected", "learned": "★ learned",
             "ambiguous": "≈ ambiguous", "unknown": "✗ unknown"}

    def _status(it):
        b = badge.get(it["status"], it["status"])
        if it["status"] == "unknown" and it.get("filename_clue"):
            b += f"  · name hints “{it['filename_clue']}”"
        elif it["status"] == "ambiguous" and len(it.get("candidates", [])) > 1:
            b += f"  · or {it['candidates'][1]['table_type']}"
        return b

    n_known = sum(1 for it in items if it["target_table"])
    n_snap = sum(1 for it in items if it["snapshot"])
    st.markdown(f"**{len(items)} file(s)** · {n_known} recognized · {n_snap} with a "
                f"saved snapshot · ordered parents-first for loading.")

    t = st.session_state.get("ms_scan_timings")
    if t:
        total = t.get("total", 0.0)
        order = ["learned signatures", "schema introspection", "column rarity",
                 "snapshot index", "canonicalize schema", "dependency ordering"]
        scan_key = next((k for k in t if k.startswith("scan + classify")), None)
        with st.expander(f"⏱ Scan timing — {total:.2f}s total", expanded=False):
            rows = []
            if scan_key:
                rows.append((scan_key, t[scan_key]))
            for k in order:
                if k in t:
                    rows.append((k, t[k]))
            for name, secs in sorted(rows, key=lambda r: -r[1]):
                pct = (secs / total * 100) if total else 0
                st.markdown(f"- **{secs*1000:.0f} ms** ({pct:.0f}%) — {name}")
    st.caption("Set **Action** to Map or Skip per file — Skip leaves it out (no "
               "type needed), and unrecognized files default to Skip. For mapped "
               "files pick the **Type** and **Target table** (“(new)” = not yet in "
               "your database). Overrides are remembered. "
               "♻ reload · ★ learned · ≈ ambiguous · ✗ unknown.")

    import pandas as pd
    type_opts = [""] + cat_names
    # full target list — every catalog table, full names, (new) marked
    label_to_full, full_to_label, target_opts = {}, {}, [""]
    for d in dts:
        for t in d["targets"]:
            full = t["table"]
            lbl = full + ("" if t["exists"] else "  (new)")
            if full not in full_to_label:
                label_to_full[lbl] = full
                full_to_label[full] = lbl
                target_opts.append(lbl)

    def _conf(it):
        return it["status"] in ("snapshot", "learned", "detected")

    df = pd.DataFrame([{
        "action": "Skip" if it["status"] == "unknown" else "Map",
        "file": it["name"],
        "rows": it["rows"],
        "status": _status(it),
        "type": (M.category_of_target(it["target_table"])
                 if _conf(it) and it.get("target_table") else ""),
        "target_table": (full_to_label.get(it["target_table"], "") if _conf(it) else ""),
    } for it in items])

    edited = st.data_editor(
        df, key="ms_confirm", hide_index=True, use_container_width=True,
        column_config={
            "action":       st.column_config.SelectboxColumn(
                                "Action", options=["Map", "Skip"], width="small",
                                help="Skip leaves the file out — no type needed."),
            "file":         st.column_config.TextColumn("File", disabled=True, width="medium"),
            "rows":         st.column_config.NumberColumn("Rows", disabled=True, width="small"),
            "status":       st.column_config.TextColumn("Detection", disabled=True, width="medium"),
            "type":         st.column_config.SelectboxColumn("Type", options=type_opts, width="medium"),
            "target_table": st.column_config.SelectboxColumn("Target table",
                                options=target_opts, width="large"),
        },
    )

    if st.button("✓  Confirm & start mapping", type="primary", key="ms_confirm_btn"):
        by_name = {it["name"]: it for it in items}
        confirmed, missing, learned_n, skipped = [], [], 0, 0
        for _, row in edited.iterrows():
            if str(row["action"]).strip() != "Map":      # Skip / blank -> leave out
                skipped += 1
                continue
            tgt_full = label_to_full.get(str(row["target_table"]).strip(), "")
            if not tgt_full:                       # picked a Type but no table -> propose it
                typ = str(row["type"]).strip()
                tgt_full = next((d["targets"][0]["table"] for d in dts
                                 if d["type"] == typ and d["targets"]), "") if typ else ""
            if not tgt_full:
                missing.append(row["file"])
                continue
            it = dict(by_name[row["file"]])
            ttype = next((s["table_type"] for s in M.SIGNATURES
                          if s["target_table"] == tgt_full), None) \
                    or it.get("table_type") or M.derive_table_type(tgt_full)
            if tgt_full != (it.get("target_table") or "") and it.get("columns"):
                try:
                    M.learn_signature(engine, it["columns"], ttype, tgt_full, domain=domain)
                    learned_n += 1
                except Exception:
                    pass
            it["table_type"] = ttype
            it["target_table"] = tgt_full
            confirmed.append(it)
        if missing:
            st.warning("Pick a Type or Target table for (or set them to Skip): "
                       + ", ".join(missing))
        elif not confirmed:
            st.warning("Set at least one file's Action to Map.")
        else:
            st.session_state["ms_confirmed"] = M.order_by_dependency(engine, confirmed)
            msg = f"Confirmed {len(confirmed)} table(s)"
            if skipped:
                msg += f", skipped {skipped}"
            msg += "."
            if learned_n:
                msg += f" Learned {learned_n} override(s) for next time."
            st.success(msg + " Mapping panels below.")


# ── section 2: mapping panels ────────────────────────────────────────────────
def _distinct_values(file_path, col):
    """Distinct non-empty values of one column from the source file, cached per
    (file, column) so editing the grid doesn't re-read the file each rerun."""
    key = f"ms_dv::{file_path}::{col}"
    if key in st.session_state:
        return st.session_state[key]
    import pandas as pd
    try:
        df = pd.read_csv(file_path, usecols=[col], dtype=str, sep=None,
                         engine="python", keep_default_na=False)
        vals = sorted({str(v).strip() for v in df[col] if str(v).strip()})
    except Exception:
        vals = []
    st.session_state[key] = vals
    return vals


def _fk_specs(engine, it, tgt_to_src):
    """Build fk_resolution specs for the mapped table: each FK to a controlled-
    vocabulary code table (dv_r_*), with the file's actual distinct values for
    the source column mapped to that FK column. `tgt_to_src` is {target_col:
    source_col} (from the panel grid or from Load-all's resolved mapping)."""
    try:
        from dataview.mapping.dv_table_loader import discover_fks
    except Exception:
        return []
    try:
        fks = discover_fks(engine, it["target_table"])
    except Exception:
        return []
    specs = []
    for fk in fks:
        if M.REF_TABLE_PATTERN.lower() not in fk.ref_table.lower():   # only code tables reconcile
            continue
        for local_col, ref_col in fk.cols:
            src = tgt_to_src.get(local_col)
            if not src:
                continue
            vals = _distinct_values(it["file"], src)
            if vals:
                specs.append({"constraint": fk.name, "ref_table": fk.ref_table,
                              "ref_col": ref_col, "fk_column": local_col,
                              "source_values": vals})
    return specs


def _tgt_to_src_from_cols(load_cols):
    """{target_col: source_col} from a resolved load-cols list (Load-all path)."""
    return {c["target_column"]: c["source_column"]
            for c in load_cols if c.get("source_column")}


def _resolve_item(engine, it):
    """Resolve a confirmed item to a load mapping WITHOUT opening its panel:
    reuse the saved snapshot if the layout is recognized, else auto-match.
    Returns a status dict used by the Load-all table."""
    target = it["target_table"]
    src_cols = it.get("columns") or []
    tcols = M.target_columns(engine, target)
    if not tcols:
        return {"it": it, "target": target, "ok": False, "status": "no table",
                "detail": "target table doesn't exist yet", "load_cols": [],
                "required": []}
    mappable = [c for c in tcols if not c["identity"] and not c.get("computed")]
    required = sorted(c["name"] for c in mappable if c["required"])
    snap = None
    try:
        snap = M.find_snapshot(engine, src_cols)
    except Exception:
        snap = None
    # only reuse a snapshot saved for THIS target — if the target was overridden
    # (e.g. survey header re-pointed from stations), a snapshot for the old table
    # must not hijack the column mapping; fall through to a fresh auto-match.
    if snap and (snap.get("meta", {}).get("target_table") or "").lower() != str(target).lower():
        snap = None
    if snap:
        load_cols = [{"target_column": c["target_column"],
                      "source_column": c.get("source_column"),
                      "transform": c.get("transform"),
                      "constant_value": c.get("constant_value")}
                     for c in snap["columns"]]
        kind = f"recognized v{snap['meta']['version']}"
    else:
        alias = M.load_alias_map(engine, target)
        am = M.auto_match(src_cols, [c["name"] for c in mappable],
                          required=set(required), alias_map=alias)
        load_cols = []
        for m in am["matches"]:
            tr = "" if m["source"] else M.propose_transform(m["target"], has_source=False)
            load_cols.append({"target_column": m["target"],
                              "source_column": m["source"] or None,
                              "transform": tr or None, "constant_value": None})
        kind = "auto-matched"
    # a required column is resolved if it has a real source, a constant, or a
    # seq_within transform (which the loader now generates at load time). Other
    # source-less transforms aren't executable yet, so they count as unresolved.
    def _resolved(c):
        if not c:
            return False
        return bool(c.get("source_column") or c.get("constant_value")
                    or (c.get("transform") or "").startswith("seq_within"))
    have = {c["target_column"]: c for c in load_cols}
    unresolved = [rq for rq in required if not _resolved(have.get(rq))]
    ok = not unresolved
    detail = kind if ok else ("needs: " + ", ".join(unresolved[:6])
                              + ("…" if len(unresolved) > 6 else ""))
    return {"it": it, "target": target, "ok": ok,
            "status": "ready" if ok else "needs mapping", "detail": detail,
            "load_cols": load_cols, "required": required}


def _section_load_all(engine, confirmed):
    import pandas as pd, hashlib, json
    # _resolve_item makes several DB round-trips per file, so re-running it on
    # every Streamlit rerun (e.g. just toggling the Apply checkbox) is what made
    # the page grey out for seconds. Cache the result, keyed by what actually
    # affects resolution — each file's name, target table, and source columns —
    # plus a "map version" counter that bumps whenever a mapping is saved (which
    # changes snapshots/synonyms). Unrelated reruns reuse the cache instantly.
    mv = st.session_state.get("ms_map_version", 0)
    key_src = [[it["name"], it.get("target_table"), list(it.get("columns") or [])]
               for it in confirmed]
    cache_key = hashlib.sha1(
        (json.dumps(key_src, sort_keys=True) + f"|v{mv}").encode()).hexdigest()
    cache = st.session_state.get("ms_resolved_cache")
    if cache and cache.get("key") == cache_key:
        resolved = cache["resolved"]
    else:
        resolved = [_resolve_item(engine, it) for it in confirmed]   # FK order
        st.session_state["ms_resolved_cache"] = {"key": cache_key, "resolved": resolved}
    ready = [r for r in resolved if r["ok"]]

    grid = pd.DataFrame([{
        "#": i,
        "File": r["it"]["name"],
        "Target": r["target"],
        "Status": ("✓ ready" if r["ok"] else
                   ("✗ no table" if r["status"] == "no table" else "⚠ needs mapping")),
        "Detail": r["detail"],
    } for i, r in enumerate(resolved, 1)])
    st.dataframe(grid, hide_index=True, use_container_width=True)

    # Reliable target override — st.selectbox always renders as a real dropdown,
    # unlike the in-cell SelectboxColumn (which can silently fall back to a text
    # cell). Pick a file, pick the right table, Apply → it re-resolves.
    files = [r["it"]["name"] for r in resolved]
    opts = ["— keep current —"] + sorted(M.list_target_tables(engine))
    f1, f2, f3 = st.columns([2, 2, 1])
    pick = f1.selectbox("Re-point a file", files, key="ms_fix_file")
    new_t = f2.selectbox("to target table", opts, key="ms_fix_target")
    cur = next((r["target"] for r in resolved if r["it"]["name"] == pick), "")
    with f3:
        st.write("")
        apply_fix = st.button("Apply", key="ms_fix_apply", use_container_width=True)
    st.caption(f"**{pick}** currently → `{cur}`")
    if apply_fix and new_t and new_t != "— keep current —":
        for r in resolved:
            if r["it"]["name"] == pick:
                r["it"]["target_table"] = new_t          # mutates the confirmed item
        st.session_state["ms_confirmed"] = confirmed
        st.session_state["ms_fix_target"] = "— keep current —"
        st.toast(f"{pick} → {new_t.split('.')[-1]}")
        st.rerun()

    c1, c2 = st.columns([1, 2])
    with c1:
        apply_all = st.checkbox("Apply — write", key="ms_apply_all")
    with c2:
        go = st.button(f"▶  Load all ready  ({len(ready)})", key="ms_load_all",
                       type="primary", disabled=not ready, use_container_width=True)
    if ready and len(ready) < len(resolved):
        st.caption(f"{len(resolved) - len(ready)} table(s) need a fix first — "
                   "open them below. The rest load now.")

    if go:
        from dataview.mapping import dv_table_loader as L
        out = []
        recon_pending = []
        prog = st.progress(0.0, text="Starting…")
        t_all = time.time()
        for i, r in enumerate(ready, 1):     # already parents-first
            it = r["it"]
            prog.progress((i - 1) / len(ready),
                          text=f"({i}/{len(ready)}) {it['name']} → {r['target']}")
            t0 = time.time()
            try:
                spec, _sk = M.build_table_spec(
                    engine, r["target"], r["load_cols"],
                    M.natural_key_for(engine, r["target"], r["required"]))
                logs = []
                res = L.load_table(engine, it["file"], spec, apply=apply_all,
                                   log=logs.append)
                secs = round(time.time() - t0, 2)
                if res and res.get("needs_reconcile"):
                    n = len(res["needs_reconcile"])
                    recon_pending.append({"target": r["target"], "name": it["name"],
                                          "file": it["file"], "it": it,
                                          "load_cols": r["load_cols"]})
                    out.append({"File": it["name"], "Target": r["target"],
                                "Result": "⚠ reconcile", "Secs": secs,
                                "Detail": f"{n} code value(s) need a decision"})
                elif res and res.get("unmatched"):
                    out.append({"File": it["name"], "Target": r["target"],
                                "Result": "✗ halt", "Secs": secs,
                                "Detail": f"unmatched: {res['unmatched']}"[:80]})
                else:
                    tail = next((str(x) for x in reversed(logs)
                                 if "->" in str(x) or "skip" in str(x)), "")
                    out.append({"File": it["name"], "Target": r["target"],
                                "Result": "✓", "Secs": secs, "Detail": tail[:80]})
            except Exception as e:
                out.append({"File": it["name"], "Target": r["target"],
                            "Result": "✗", "Secs": round(time.time() - t0, 2),
                            "Detail": f"{type(e).__name__}: {e}"[:80]})
        prog.progress(1.0, text="Done")
        total = time.time() - t_all
        st.session_state["ms_recon_pending"] = recon_pending
        st.dataframe(pd.DataFrame(out), hide_index=True, use_container_width=True)
        ok_n = sum(1 for x in out if x["Result"] == "✓")
        if recon_pending:
            st.warning(f"{len(recon_pending)} file(s) paused for FK reconciliation — "
                       "resolve below, then click Load all again.")
        if apply_all:
            st.success(f"Loaded {ok_n} of {len(ready)} tables in {total:.1f}s.")
        else:
            st.info(f"Dry run — nothing written ({total:.1f}s). Tick Apply to write.")

    # Reconciliation grids for any files Load-all paused on. Rendered outside the
    # `go` block so they persist across the Save→rerun cycle.
    pending = st.session_state.get("ms_recon_pending") or []
    if pending:
        st.divider()
        st.markdown("### Reconcile, then re-run Load all")
        st.caption("These files carry code values not yet in their reference tables. "
                   "Use the bulk actions or decide per row, **Save all decisions**, "
                   "then click **Load all** again — decisions persist, so each value "
                   "is only asked once.")
        from dataview.core import fk_resolution as FKR
        for p in pending:
            st.markdown(f"**{p['name']} → {p['target']}**")
            specs = _fk_specs(engine, p["it"], _tgt_to_src_from_cols(p["load_cols"]))
            if specs:
                try:
                    FKR.render_reconciliation(st, engine, specs,
                                              key_prefix=f"la_{p['target']}_")
                except Exception as e:
                    st.caption(f"reconciliation unavailable: {type(e).__name__}: {e}")
            else:
                st.caption("No reconcilable code columns found for this file.")

    return resolved


def _render_mapping_panels(engine, confirmed):
    st.subheader("Load")
    st.caption("Everything that's ready loads in one click, parents first. "
               "Open a table below only if it needs a mapping fix.")
    resolved = _section_load_all(engine, confirmed)
    ok = [r["ok"] for r in resolved]                  # aligned with confirmed by index
    n_need = sum(1 for v in ok if not v)

    st.divider()
    if st.checkbox(f"Adjust individual tables ({n_need} need a fix)"
                   if n_need else "Adjust individual tables",
                   key="ms_show_panels",
                   help="By default this lists only the tables that still need a "
                        "fix. Tick the option inside to also open a ready table — "
                        "e.g. to refine an auto-match or save a labeled snapshot."):
        show_ready = st.checkbox(
            "Also show tables that are already ready",
            key="ms_show_ready",
            help="Open a ready table to refine its column mapping, set a "
                 "transform/constant, reconcile FK values, or save a labeled "
                 "snapshot for next time.")
        shown = 0
        for i, it in enumerate(confirmed, 1):
            is_ok = ok[i - 1] if i - 1 < len(ok) else False
            if is_ok and not show_ready:
                continue
            shown += 1
            target = it["target_table"]
            head = f"{i}.  {it['name']}  →  {target}"
            head += "   ✓ ready" if is_ok else "   ⚠ needs a fix"
            if it.get("snapshot"):
                head += "   ♻ recognized"
            with st.expander(head, expanded=not is_ok):   # auto-open the ones to fix
                _one_panel(engine, it, idx=i)
        if shown == 0:
            st.caption("All tables are resolved — nothing needs a fix. Tick "
                       "“Also show tables that are already ready” to refine a "
                       "mapping anyway.")


def _one_panel(engine, it, *, idx):
    import pandas as pd
    target, src_cols = it["target_table"], it["columns"]

    tcols = M.target_columns(engine, target)
    if not tcols:
        st.warning(f"`{target}` doesn't exist in the database yet — create the "
                   f"table first, then it can be mapped. (Source columns: "
                   + ", ".join(src_cols) + ")")
        return

    # auto-match source -> target using real columns + learned synonyms
    alias = M.load_alias_map(engine, target)
    mappable = [c for c in tcols if not c["identity"] and not c.get("computed")]  # skip DB-generated
    required = {c["name"] for c in mappable if c["required"]}
    am = M.auto_match(src_cols, [c["name"] for c in mappable],
                      required=required, alias_map=alias)
    by_target = {m["target"]: m for m in am["matches"]}

    # if this exact layout was mapped before, reload the SAVED mapping (recognized
    # by fingerprint) instead of re-deriving — zero re-work on repeat loads.
    snap = None
    try:
        snap = M.find_snapshot(engine, src_cols)
    except Exception:
        snap = None
    saved = {c["target_column"]: c for c in snap["columns"]} if snap else {}
    if snap:
        st.success(f"♻ Recognized by fingerprint — reloaded saved mapping "
                   f"v{snap['meta']['version']}"
                   + (f" ({snap['meta']['label']})" if snap['meta'].get('label') else "")
                   + ". Adjust and re-save to make a new version.")

    src_opts = [""] + list(src_cols)
    rows = []
    for c in mappable:
        if c["name"] in saved:                               # from saved snapshot
            sv = saved[c["name"]]
            rows.append({
                "target": c["name"],
                "req": "●" if c["required"] else "",
                "source": sv.get("source_column") or "",
                "transform": sv.get("transform") or "",
                "constant": sv.get("constant_value") or "",
                "conf": sv.get("confidence") or 0.0,
            })
        else:                                                # auto-matched
            m = by_target.get(c["name"], {})
            src = m.get("source") or ""
            rows.append({
                "target": c["name"],
                "req": "●" if c["required"] else "",
                "source": src,
                "transform": M.propose_transform(c["name"], bool(src)),
                "constant": "",
                "conf": m.get("confidence") or 0.0,
            })
    df = pd.DataFrame(rows)

    # Every value actually present in the grid MUST be a valid dropdown option —
    # otherwise Streamlit's SelectboxColumn renders it as a blank, non-editable
    # cell (this is exactly what hid the proposed seq_within(log_id) on curve_id).
    tr_opts = list(M.TRANSFORMS) + [v for v in df["transform"].unique()
                                    if v and v not in M.TRANSFORMS]
    src_opts = src_opts + [v for v in df["source"].unique()
                           if v and v not in src_opts]

    st.caption(f"{len(mappable)} target columns · {len(am['matches']) - len(am['unmatched_sources'])} "
               f"auto-matched · ● = required. Leftover source columns: "
               + (", ".join(am["unmatched_sources"]) or "none"))
    if am["derived_required"]:
        st.info("Required with no source — set a transform or constant: "
                + ", ".join(am["derived_required"]))

    edited = st.data_editor(
        df, key=f"ms_map_{idx}", hide_index=True, use_container_width=True,
        column_config={
            "target":    st.column_config.TextColumn("Target column", disabled=True, width="medium"),
            "req":       st.column_config.TextColumn("Req", disabled=True, width="small"),
            "source":    st.column_config.SelectboxColumn("Source column", options=src_opts, width="medium"),
            "transform": st.column_config.SelectboxColumn("Transform", options=tr_opts, width="medium"),
            "constant":  st.column_config.TextColumn("Constant", width="small"),
            "conf":      st.column_config.NumberColumn("Match", disabled=True, format="%.2f", width="small"),
        },
    )

    label = st.text_input("Snapshot label (vendor / format name)",
                          key=f"ms_lbl_{idx}", placeholder="e.g. KGS survey export")

    def _collect():
        """Build the snapshot column list from the grid; returns (cols, unresolved)."""
        cols, unresolved = [], []
        for _, r in edited.iterrows():
            tgt = str(r["target"]).strip()
            src = str(r["source"]).strip()
            tr = str(r["transform"]).strip()
            const = str(r["constant"]).strip()
            if tgt in required and not src and not tr and not const:
                unresolved.append(tgt)
            cols.append({"target_column": tgt, "source_column": src or None,
                         "is_key": int(tgt in required),
                         "is_derived": int(bool(tr) and not src),
                         "transform": tr or None, "constant_value": const or None,
                         "confidence": float(r["conf"]) or None,
                         "method": by_target.get(tgt, {}).get("method")})
        return cols, unresolved

    def _confirm(quiet=False):
        cols, unresolved = _collect()
        if unresolved:
            if not quiet:
                st.error("These required columns still need a source, transform, or "
                         "constant: " + ", ".join(unresolved))
            return None
        res = M.save_mapping(engine, it.get("table_type") or "",
                             it.get("domain") or "Wells", target,
                             natural_key=sorted(required), columns=cols,
                             source_columns=src_cols, label=label or None)
        return res

    already_confirmed = bool(snap)
    st.caption("Confirming saves this mapping so the same layout is recognized and "
               "reloaded next time — optional, and done automatically the first "
               "time you load."
               + ("  This layout is already confirmed." if already_confirmed else ""))
    if st.button("✓  Confirm mapping", type="primary", key=f"ms_save_{idx}"):
        if already_confirmed:
            # already saved for this fingerprint — just reassure, don't churn versions
            st.success(f"Already confirmed — {target} is saved (v{snap['meta']['version']}). "
                       f"Nothing to re-save.")
        else:
            try:
                res = _confirm()
                if res:
                    st.session_state["ms_map_version"] = \
                        st.session_state.get("ms_map_version", 0) + 1   # refresh Load grid
                    st.success(f"Confirmed {target} mapping v{res['version']} "
                               f"(fingerprint {res['fingerprint'][:10]}…). "
                               f"Synonyms and signature learned for next time.")
            except Exception as e:
                st.error(f"Confirm failed: {type(e).__name__}: {e}")

    # ── foreign-key reconciliation (controlled-vocabulary code tables) ──────
    tgt_to_src = {str(r["target"]).strip(): str(r["source"]).strip()
                  for _, r in edited.iterrows() if str(r["source"]).strip()}
    fk_specs = _fk_specs(engine, it, tgt_to_src)
    if fk_specs:
        st.divider()
        st.markdown("**Foreign-key reconciliation** — code values checked against "
                    "their reference tables:")
        try:
            from dataview.core import fk_resolution as FKR
            FKR.render_reconciliation(st, engine, fk_specs, key_prefix=f"ms{idx}_")
        except Exception as e:
            st.caption(f"FK reconciliation unavailable: {type(e).__name__}: {e}")

    # ── load via the existing loader ────────────────────────────────────────
    st.divider()
    st.markdown("**Load** — stage and BCP this file into the target with the "
                "loader's FK governance. Plan first (dry run); tick Apply to write.")
    load_cols = []
    for _, r in edited.iterrows():
        load_cols.append({
            "target_column": str(r["target"]).strip(),
            "source_column": str(r["source"]).strip() or None,
            "transform": str(r["transform"]).strip() or None,
            "constant_value": str(r["constant"]).strip() or None,
        })
    apply = st.checkbox("Apply — write to the database (off = dry-run plan)",
                        key=f"ms_apply_{idx}")
    if st.button("▶  Plan / Load", key=f"ms_load_{idx}"):
        try:
            spec, skipped = M.build_table_spec(
                engine, target, load_cols,
                M.natural_key_for(engine, target, required))
        except Exception as e:
            st.error(f"Couldn't build the load spec: {type(e).__name__}: {e}")
            return
        if skipped:
            st.warning("Derived columns the loader can't compute yet (left unset): "
                       + ", ".join(f"{t} [{tr}]" for t, tr in skipped))
        logs = []
        try:
            from dataview.mapping import dv_table_loader as L
            t0 = time.time()
            with st.spinner(f"{'Loading' if apply else 'Planning'} {it['name']}…"):
                L.load_table(engine, it["file"], spec, apply=apply, log=logs.append)
            elapsed = time.time() - t0
            st.code("\n".join(str(x) for x in logs) or "(no log output)")
            if apply:
                # auto-confirm the mapping the first time it's loaded, so the
                # layout is remembered — no separate Confirm click needed.
                try:
                    already = M.find_snapshot(engine, src_cols)
                except Exception:
                    already = None
                note = ""
                if not already:
                    res = _confirm(quiet=True)
                    if res:
                        note = f" Mapping confirmed (v{res['version']}) for next time."
                st.success(f"Applied to the database in {elapsed:.1f}s." + note)
            else:
                st.success(f"Plan complete in {elapsed:.1f}s — dry run, nothing written.")
        except Exception as e:
            if logs:
                st.code("\n".join(str(x) for x in logs))
            st.error(f"Load {'apply' if apply else 'plan'} error: "
                     f"{type(e).__name__}: {e}")

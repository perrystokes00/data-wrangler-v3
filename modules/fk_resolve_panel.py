"""
fk_resolve_panel.py — Governance FK resolution panel for Stage 6
================================================================
Place in:  .../data_wrangler_v3/modules/fk_resolve_panel.py

Shows ONLY violated FK constraints. One table per violation, four columns:

    [ Add ] [ Source value ] [ Existing value ▼ ] [ Map ]

  • Add  (col 1) ticked            → add the source value to the reference table.
  • Existing value (col 3) dropdown → pick a canonical value (shows NAME [code]).
  • Map  (col 4) ticked            → conform: UPDATE staging rows to the chosen value.

Each table lives in its own st.form, so editing cells does NOT rerun the page —
nothing applies (and the violation check does not re-query) until you click
Apply for that table. Untouched rows are quarantined (skipped at promote).

Convenience: where a source value matches an existing reference value except
for case (GAS vs Gas, ACTIVE vs Active), the dropdown is pre-filled and Map is
pre-ticked so a single Apply conforms it. Review before applying.

check_fk_violations only checks source-mapped child columns, so this panel
covers reference/geo FKs and leaves derived SHA-1 entity FKs (operator_ba_id,
field_id) to the entity-seed path.
"""
from __future__ import annotations


# ── Midnight Gold styling ────────────────────────────────────────────
def _inject_style(st):
    st.markdown(
        """
        <style>
          .mgold-head { font-size:1.2rem; font-weight:700; color:#D4AF37;
              letter-spacing:.3px; border-bottom:1px solid rgba(212,175,55,.35);
              padding-bottom:.35rem; margin:.3rem 0 .5rem; }
          .mgold-sub { color:#C9B27A; font-size:.85rem; }
          div[data-testid="stExpander"] details summary {
              border-left:3px solid #D4AF37; padding-left:.5rem; }
          div[data-testid="stExpander"] details summary:hover { color:#E8C964; }
          div[data-testid="stFormSubmitButton"] button {
              background:linear-gradient(180deg,#D4AF37,#B8932B); color:#11141c;
              font-weight:700; border:1px solid #8a6d1f; }
          div[data-testid="stFormSubmitButton"] button:hover {
              background:linear-gradient(180deg,#E8C964,#D4AF37); color:#0b0e16;
              border-color:#D4AF37; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _staging_fqn(S):
    schema = getattr(S, "stg_schema", None) or "stg"
    table  = (getattr(S, "stg_table", None)
              or getattr(S, "stg_name", None)
              or "stg_well_header")
    return schema, table


def render(S, st):
    """Render the violated-only add/map resolution UI. Safe to call every render."""
    import pandas as pd
    from sqlalchemy import text
    from modules.fk import (check_fk_violations, get_reference_table_context,
                            insert_reference_rows)

    _inject_style(st)

    # Flash messages from the previous Apply survive the re-check rerun.
    _flash = getattr(S, "fk_apply_flash", None)
    if _flash:
        for _parent, _m in _flash:
            (st.success if (_m.startswith("✅") or _m.startswith("🔤"))
             else st.warning)(f"{_parent}: {_m}")
        S.fk_apply_flash = None

    _stg_tbl    = getattr(S, "stg_table", None)
    _use_server = bool(S.engine and not getattr(S, "demo", False) and _stg_tbl)
    df = S.staging_df if S.staging_df is not None else S.source_df
    if not S.col_mapping or not S.engine or (not _use_server and df is None):
        st.info("Staging data, a column mapping, and a DB connection are required.")
        return

    try:
        if _use_server:
            from modules.fk import check_fk_violations_server
            result = check_fk_violations_server(
                S.engine, getattr(S, "stg_schema", "stg"), _stg_tbl,
                S.col_mapping, S.fk_constraints or [],
                getattr(S, "fk_parent_pks", None) or {})
        else:
            result = check_fk_violations(
                df, S.col_mapping, S.fk_constraints or [],
                S.engine, getattr(S, "fk_parent_pks", None) or {})
    except Exception as exc:
        st.error(f"FK violation check failed: {exc}")
        st.exception(exc)
        return

    unresolved = [v for v in result.violations if v.missing_values]

    # ── Separate ENTITY FKs (SHA-1 keyed parents) from reference FKs ───
    # operator_ba_id / *_ba_id → dv_business_associate and field_id → dv_field
    # are keyed on SHA-1 hashes, so source names can't be Added/Mapped here —
    # they need the (pending) entity SHA-1 resolver. Showing them in the
    # Add/Map grid just makes them reappear forever. Keep them visible, but
    # in a separate "pending" note so the grid holds only what you can fix.
    _ENTITY_PARENT_HINTS = ("business_associate", "field")

    def _is_entity_parent(_v):
        _pt = (_v.constraint.parent_table or "").lower()
        return any(_h in _pt for _h in _ENTITY_PARENT_HINTS)

    entity_viols = [v for v in unresolved if _is_entity_parent(v)]
    unresolved   = [v for v in unresolved if not _is_entity_parent(v)]

    def _render_entity_pending():
        if not entity_viols:
            return
        _names = sorted({v.constraint.parent_table for v in entity_viols})
        with st.expander(
                f"⏳ {len(entity_viols)} entity FK(s) pending SHA-1 resolution "
                f"({', '.join(_names)})", expanded=False):
            st.markdown(
                "<div class='mgold-sub'>These reference SHA-1 keyed parents "
                "(operators, fields). They can't be resolved by Add/Map — they "
                "need the entity resolver that hashes the source name into the "
                "parent key. Not blocking this panel; tracked separately.</div>",
                unsafe_allow_html=True)
            for v in entity_viols:
                st.markdown(
                    f"• <code>{v.constraint.parent_table}</code> · "
                    f"[{(v.constraint.child_cols or ['?'])[0]}] · "
                    f"{len(v.missing_values)} value(s)", unsafe_allow_html=True)

    if not unresolved:
        if entity_viols:
            st.success("✅ All reference constraints conform. Remaining items are "
                       "entity (operator/field) FKs that resolve via SHA-1 keys.")
            _render_entity_pending()
        else:
            st.success("✅ No FK violations — every mapped source value conforms to its "
                       "reference table. Ready to promote.")
        return

    st.markdown(f"<div class='mgold-head'>🔴 {len(unresolved)} reference constraint(s) "
                f"need resolution</div>", unsafe_allow_html=True)
    st.markdown("<div class='mgold-sub'>For each value, choose ONE: tick <b>Add</b> to put it "
                "in the reference table, or pick an <b>Existing value</b> and tick <b>Map</b> to "
                "conform it. Leave a value with <b>nothing ticked and no Existing value</b> and it's "
                "treated as trash — the source is nulled on Apply (nullable columns only). "
                "Case-only matches are pre-filled. Nothing applies until you click "
                "<b>Apply all resolutions</b> at the bottom.</div>",
                unsafe_allow_html=True)
    _render_entity_pending()
    st.write("")

    # ── Pre-compute reference context for every unresolved violation ──
    prepared = []
    for vi, v in enumerate(unresolved):
        c         = v.constraint
        parent    = c.parent_table
        child_col = c.child_cols[0] if c.child_cols else "?"
        src_col   = (v.source_cols[0] if v.source_cols else child_col)
        # Nullability of the FK child column — gates the "null it out" action.
        child_nullable = next((fc.nullable for fc in c.columns
                               if fc.fk_col == child_col), True)
        ctx       = get_reference_table_context(S.engine, v)
        if ctx.get("error"):
            st.warning(f"{parent}: could not load reference context — {ctx['error']}")
            continue
        pk_col   = ctx.get("pk_col", "")
        name_col = ctx.get("name_col", pk_col)

        # Build friendly dropdown options:  "Name [code]" -> pk value.
        # Dedupe the list (a composite ref like dv_county repeats county_name
        # across states) and disambiguate with a state column when present.
        label_to_pk = {}
        options     = [""]
        _seen       = set()
        _rows       = ctx.get("existing_rows", [])
        _state_key  = next(
            (k for k in (_rows[0].keys() if _rows else [])
             if k.upper() in ("PROVINCE_STATE_ID", "PROVINCE_STATE", "STATE")), None)
        for r in _rows:
            pkv = str(r.get(pk_col, "")).strip()
            if not pkv:
                continue
            nm = (str(r.get(name_col, "")).strip()
                  if name_col and name_col != pk_col else "")
            label = f"{nm}  [{pkv}]" if nm and nm.upper() != pkv.upper() else pkv
            if _state_key:
                _sv = str(r.get(_state_key, "")).strip()
                if _sv and _sv.upper() != pkv.upper():
                    label = f"{label}  ·  {_sv}"
            if label in _seen:
                continue
            _seen.add(label)
            label_to_pk[label] = pkv
            options.append(label)

        pk_upper_to_label = {pkv.upper(): lbl for lbl, pkv in label_to_pk.items()}
        viol_vals = [str(t[0]).strip() for t in v.missing_values
                     if t and str(t[0]).strip()]
        pre_existing, pre_map = [], []
        for val in viol_vals:
            lbl = pk_upper_to_label.get(val.upper())
            pre_existing.append(lbl or "")
            pre_map.append(bool(lbl))

        prepared.append(dict(
            vi=vi, v=v, parent=parent, child_col=child_col, src_col=src_col,
            ctx=ctx, pk_col=pk_col, options=options, label_to_pk=label_to_pk,
            viol_vals=viol_vals, pre_existing=pre_existing, pre_map=pre_map,
            child_nullable=child_nullable))

    if not prepared:
        return

    # ── ONE form for ALL constraints, ONE Apply ──────────────────────
    editors = []   # (prepared_entry, edited_df)
    with st.form(key="fk_form_all"):
        for p in prepared:
            n_pre = sum(p["pre_map"])
            with st.expander(
                    f"🔴 {p['parent']}  ·  [{p['child_col']}]  ·  "
                    f"{len(p['viol_vals'])} value(s) not in reference  ·  "
                    f"{p['v'].rows_affected} row(s)"
                    + (f"  ·  {n_pre} case-match pre-filled" if n_pre else ""),
                    expanded=True):
                st.markdown(
                    f"<span class='mgold-sub'>Source <code>{p['src_col']}</code> → "
                    f"reference <code>{p['parent']}.{p['pk_col']}</code>  ·  "
                    f"{len(p['label_to_pk'])} existing value(s)</span>",
                    unsafe_allow_html=True)
                editor_df = pd.DataFrame({
                    "Add":            [False] * len(p["viol_vals"]),
                    "Source value":   p["viol_vals"],
                    "Existing value": p["pre_existing"],
                    "Map":            p["pre_map"],
                })
                _editor_key = f"fk_res_{p['vi']}_{p['parent']}"
                _edited_ret = st.data_editor(
                    editor_df,
                    key=_editor_key,
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Add": st.column_config.CheckboxColumn(
                            width="small",
                            help="Add this source value to the reference table as new vocabulary."),
                        "Source value": st.column_config.TextColumn(
                            disabled=True, width="medium"),
                        "Existing value": st.column_config.SelectboxColumn(
                            width="medium", options=p["options"],
                            help="Pick an existing reference value (shown as Name [code])."),
                        "Map": st.column_config.CheckboxColumn(
                            width="small",
                            help="Apply the mapping: rewrite staging rows to the chosen value."),
                    },
                )
                editors.append((p, editor_df, _editor_key, _edited_ret))

        submitted = st.form_submit_button(
            f"✅ Apply all resolutions  ({len(prepared)} constraint(s))",
            use_container_width=True, type="primary")

    if submitted:
        results, any_change = [], False
        for p, base_df, ekey, ed_return in editors:
            # Prefer the data_editor's returned frame — it reflects the
            # submitted edits reliably on form submit in current Streamlit.
            # Fall back to reconstructing from the session-state delta only
            # if the return value isn't a usable frame.
            if isinstance(ed_return, pd.DataFrame) and "Add" in ed_return.columns:
                edited = ed_return
            else:
                edited = _read_editor_state(st, base_df, ekey)
            changed, msgs = _apply(
                S, p["v"], p["ctx"], edited,
                p["src_col"], p["pk_col"], p["label_to_pk"],
                p["child_nullable"])
            any_change = any_change or changed
            results.extend((p["parent"], m) for m in msgs)

        if any_change:
            # Flash results after the single re-check, then close satisfied
            # constraints by rebuilding once (re-reads staging, clears cache).
            S.fk_apply_flash = results
            try:
                from modules.fk import clear_parent_values_cache
                clear_parent_values_cache()
            except Exception:
                pass
            for _ck in list(st.session_state.keys()):
                if _ck.startswith("_fk_exists_") or _ck.startswith("_fk_graph_"):
                    st.session_state.pop(_ck, None)
            S.fk_checked = False
            st.rerun()
        elif results:
            for parent, m in results:
                (st.success if (m.startswith("✅") or m.startswith("🔤"))
                 else st.warning)(f"{parent}: {m}")
        else:
            st.info("Nothing applied. Values with neither **Add** nor **Map** "
                    "ticked are treated as garbage and nulled automatically on "
                    "Apply (when the column is nullable); if the column is NOT "
                    "NULL, remove those rows from source instead.")


def _read_editor_state(st, base_df, key):
    """Reconstruct the edited DataFrame from st.data_editor's session state.
    Inside an st.form the widget return value is unreliable, but the edits
    are always recorded in session_state[key]['edited_rows'] as
    {row_idx: {col: new_value}}. We overlay those onto the pre-filled base."""
    edited = base_df.copy()
    state = st.session_state.get(key)
    if isinstance(state, dict):
        for _ridx, _changes in (state.get("edited_rows") or {}).items():
            try:
                ridx = int(_ridx)
            except (TypeError, ValueError):
                continue
            if 0 <= ridx < len(edited) and isinstance(_changes, dict):
                for col, val in _changes.items():
                    if col in edited.columns:
                        edited.iat[ridx, edited.columns.get_loc(col)] = val
    return edited


def _apply(S, violation, ctx, edited, src_col, pk_col, label_to_pk,
           child_nullable=True):
    """Apply Add/Map/Null for ONE constraint. Returns (changed, msgs).
    Three outcomes per row:
      • Add ticked          -> insert the value into the reference table
      • Map ticked + value   -> rewrite staging rows to the chosen reference value
      • none of the above    -> trash: null the staging value (if the column is
                                nullable), so the FK passes on NULL
    A row with an Existing value chosen but Map un-ticked is treated as an
    unfinished map (left unchanged) — never nulled.
    No Streamlit output and no rerun — the caller batches and re-checks once."""
    from sqlalchemy import text
    from modules.fk import insert_reference_rows

    name_col   = ctx.get("name_col", pk_col)
    insertable = ctx.get("insertable_cols", [])
    schema, table = _staging_fqn(S)

    add_rows  = []
    remaps    = []   # (old_value, new_pk_value)
    null_vals = []   # neither Add nor Map ticked -> garbage, null it out
    conflicts = []

    for _, r in edited.iterrows():
        val       = str(r["Source value"]).strip()
        add       = bool(r.get("Add", False))
        sel_label = str(r.get("Existing value", "") or "").strip()
        mapchk    = bool(r.get("Map", False))
        mapsel    = label_to_pk.get(sel_label, sel_label)   # label -> pk code
        do_map    = mapchk and bool(sel_label)

        if add and do_map:
            conflicts.append(f"'{val}' — both Add and Map ticked; pick one")
            continue
        if mapchk and not sel_label:
            conflicts.append(f"'{val}' — Map ticked but no Existing value chosen")
            continue

        if do_map:
            if mapsel != val:
                remaps.append((val, mapsel))
        elif add:
            row_vals = {pk_col: val}
            if name_col and name_col != pk_col:
                row_vals[name_col] = val
            for col in insertable:
                if col in row_vals:
                    continue
                row_vals[col] = "Y" if col.lower() == "active_ind" else val
            add_rows.append(row_vals)
        elif sel_label:
            # Existing value chosen but Map not ticked — unfinished, don't null.
            conflicts.append(
                f"'{val}' — Existing value chosen but Map not ticked (left unchanged)")
        else:
            # Neither Add nor Map ticked, no Existing value -> garbage. Null
            # it out (if the column is nullable) so the FK passes on NULL.
            null_vals.append(val)

    msgs    = []
    changed = False

    if conflicts:
        msgs.append("⚠️ Skipped (ambiguous): " + "; ".join(conflicts))

    if add_rows:
        try:
            ok, msg = insert_reference_rows(S.engine, violation, add_rows, ctx)
            msgs.append(("✅ " if ok else "⚠️ ") + f"Add: {msg}")
            changed = changed or ok
        except Exception as e:
            msgs.append(f"⚠️ Add failed: {e}")

    if remaps:
        try:
            with S.engine.begin() as con:
                for old, new in remaps:
                    con.execute(
                        text(f"UPDATE [{schema}].[{table}] "
                             f"SET [{src_col}] = :new "
                             f"WHERE LTRIM(RTRIM([{src_col}])) = :old"),
                        {"new": new, "old": old})
            msgs.append(f"✅ Mapped {len(remaps)} value(s) → existing reference.")
            changed = True

            # Teach dv_value_map so future loads conform this automatically.
            try:
                from modules.value_standardize import upsert_value_map
                _tgt_col = (violation.constraint.child_cols[0]
                            if violation.constraint.child_cols else src_col)
                _tgt_tab = getattr(S, "target_table", "dv_well") or "dv_well"
                for old, new in remaps:
                    upsert_value_map(S.engine, _tgt_tab, _tgt_col, old, new,
                                     by="FK_PANEL",
                                     remark="learned from FK resolution")
                msgs.append(f"🔤 Saved {len(remaps)} mapping(s) to dv_value_map.")
            except Exception as _te:
                msgs.append(f"⚠️ Mapped, but could not save to dv_value_map: {_te}")
        except Exception as e:
            msgs.append(f"⚠️ Map failed: {e}")

    if null_vals:
        if not child_nullable:
            _pv = ", ".join(null_vals[:8]) + ("…" if len(null_vals) > 8 else "")
            msgs.append(
                f"⚠️ {len(null_vals)} garbage value(s) left as-is — [{src_col}] "
                f"maps to a NOT NULL column, so they can't be nulled: {_pv}. "
                f"Remove these rows from source instead.")
        else:
            try:
                with S.engine.begin() as con:
                    for badv in null_vals:
                        con.execute(
                            text(f"UPDATE [{schema}].[{table}] "
                                 f"SET [{src_col}] = NULL "
                                 f"WHERE LTRIM(RTRIM([{src_col}])) = :old"),
                            {"old": badv})
                changed = True
                _pv = ", ".join(null_vals[:8]) + ("…" if len(null_vals) > 8 else "")
                msgs.append(f"🗑️ Nulled {len(null_vals)} garbage value(s): {_pv}")
            except Exception as e:
                msgs.append(f"⚠️ Null-out failed: {e}")

    return changed, msgs

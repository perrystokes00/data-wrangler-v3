"""
page_rules.py  —  PPDM Loader · Rules Manager
==============================================
Single page for managing both:
  • Normalization Rules — column-level transforms applied after Stage 3
  • Validation Rules    — data quality checks applied at Stage 7

Rules are stored in modules/user_rules.json.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from dataview.reference_tables.user_rules import (
    load_store, save_norm_rules, save_val_rules,
    load_norm_rules, load_val_rules,
    next_norm_id, next_val_id,
    apply_norm_rules, get_val_rules_for_table,
    _build_val_check,
)

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════

NORM_TYPES = {
    "case":          "Case — convert to UPPER / lower / Title Case",
    "replace":       "Replace — find and replace a literal string",
    "regex_replace": "Regex Replace — find and replace using a pattern",
    "null_sub":      "Null Substitute — fill empty values with a default",
    "pad":           "Pad — left or right pad to a fixed width",
    "truncate":      "Truncate — trim value to a maximum length",
    "strip_chars":   "Strip Characters — remove specific characters",
}

VAL_TYPES = {
    "not_empty":    "Not Empty — column must have a value",
    "range":        "Range — numeric value within min / max bounds",
    "compare_cols": "Compare Columns — col A must be <op> col B",
    "date_order":   "Date Order — date A must be on or before date B",
    "regex":        "Pattern Match — value must match a regex",
}

OPERATORS   = ["<", "<=", ">", ">=", "==", "!="]
SEVERITIES  = ["ERROR", "WARNING"]

PPDM_TABLES = [
    "*  (all tables)",
    "well", "well_dir_srvy", "well_dir_srvy_station",
    "strat_well_section", "well_log", "well_log_curve",
    "well_core", "well_core_sample", "prod_string",
    "prod_string_month", "well_test", "well_formation",
    "business_associate", "field", "well_area",
]


def _tbl_key(display: str) -> str:
    """Extract the raw table name from a display string like 'well  (all tables)'."""
    return display.split()[0]


def _tbl_display(tbl: str) -> str:
    for t in PPDM_TABLES:
        if t.split()[0] == tbl:
            return t
    return tbl


# ═══════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════

def _init():
    defaults = {
        "rules_norm_edit":   None,   # id of norm rule being edited
        "rules_val_edit":    None,   # id of val rule being edited
        "rules_norm_add":    False,
        "rules_val_add":     False,
        "rules_test_result": None,   # {"norm_changes": [...], "val_report": report}
        "rules_test_table":  None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ═══════════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _table_picker(key: str, current: str) -> str:
    opts   = PPDM_TABLES
    keys   = [_tbl_key(o) for o in opts]
    idx    = keys.index(current) if current in keys else 0
    chosen = st.selectbox("Target table  (* = all tables)", opts,
                          index=idx, key=key)
    return _tbl_key(chosen)


def _sev_color(sev: str) -> str:
    return "#c0392b" if sev == "ERROR" else "#c45c00"


def _rule_group(rules: list[dict], label_fn) -> dict[str, list[dict]]:
    """Group rules by table, with '*' first."""
    groups: dict[str, list[dict]] = {}
    for r in rules:
        tbl = r.get("table", "*")
        groups.setdefault(tbl, []).append(r)
    ordered = {}
    if "*" in groups:
        ordered["*"] = groups.pop("*")
    for k in sorted(groups):
        ordered[k] = groups[k]
    return ordered


# ═══════════════════════════════════════════════════════════════════════════
# NORMALIZATION RULE FORM
# ═══════════════════════════════════════════════════════════════════════════

def _norm_form(prefix: str, initial: dict | None = None, d: dict | None = None):
    """Render norm rule form. Returns rule dict | 'CANCEL' | None."""
    d = initial or d or {}
    c1, c2 = st.columns([3, 1])
    name = c1.text_input("Rule name *", value=d.get("name", ""),
                         key=f"{prefix}_name",
                         placeholder="e.g. Well name title case")
    # Norm rules have severity INFO (they don't block rows)
    st.caption("ℹ️ Normalization rules transform data — they don't produce errors or warnings.")

    desc = st.text_input("Description", value=d.get("description", ""),
                         key=f"{prefix}_desc",
                         placeholder="Plain English explanation")

    table = _table_picker(f"{prefix}_tbl", d.get("table", "*"))

    col = st.text_input(
        "PPDM column to transform *",
        value=d.get("column", ""),
        key=f"{prefix}_col",
        placeholder="e.g. WELL_NAME",
    ).upper().strip()

    type_opts   = list(NORM_TYPES.keys())
    type_labels = list(NORM_TYPES.values())
    cur_type    = d.get("type", "case")
    type_idx    = type_opts.index(cur_type) if cur_type in type_opts else 0
    rtype_lbl   = st.selectbox("Transform type *", type_labels,
                               index=type_idx, key=f"{prefix}_type")
    rtype = type_opts[type_labels.index(rtype_lbl)]

    st.divider()
    extra: dict = {}

    if rtype == "case":
        case_opts = ["upper", "lower", "title"]
        ci = case_opts.index(d.get("case", "upper"))
        extra["case"] = st.selectbox("Case style", case_opts, index=ci,
                                     key=f"{prefix}_case",
                                     format_func=lambda x: {
                                         "upper": "UPPER CASE",
                                         "lower": "lower case",
                                         "title": "Title Case",
                                     }[x])

    elif rtype == "replace":
        rc1, rc2 = st.columns(2)
        extra["find"]         = rc1.text_input("Find (literal)",
                                               value=d.get("find", ""),
                                               key=f"{prefix}_find")
        extra["replace_with"] = rc2.text_input("Replace with",
                                               value=d.get("replace_with", ""),
                                               key=f"{prefix}_rep",
                                               placeholder="(leave blank to delete)")

    elif rtype == "regex_replace":
        import re as _re
        extra["pattern"]      = st.text_input("Regex pattern *",
                                              value=d.get("pattern", ""),
                                              key=f"{prefix}_pat",
                                              placeholder=r"e.g. \s+ to strip spaces")
        extra["replace_with"] = st.text_input("Replace with",
                                              value=d.get("replace_with", ""),
                                              key=f"{prefix}_rep",
                                              placeholder="(leave blank to delete matches)")
        if extra["pattern"]:
            try:
                _re.compile(extra["pattern"])
                st.caption("✅ Valid regex pattern")
            except _re.error as e:
                st.error(f"Invalid regex: {e}")
                extra["pattern"] = ""

    elif rtype == "null_sub":
        extra["substitute"] = st.text_input("Substitute value *",
                                            value=d.get("substitute", ""),
                                            key=f"{prefix}_sub",
                                            placeholder="e.g. UNKNOWN")

    elif rtype == "pad":
        pc1, pc2, pc3 = st.columns(3)
        dir_opts = ["left", "right"]
        di = dir_opts.index(d.get("direction", "left"))
        extra["direction"] = pc1.selectbox("Direction", dir_opts, index=di,
                                           key=f"{prefix}_dir")
        extra["width"]     = pc2.number_input("Width *", min_value=1,
                                              max_value=200,
                                              value=int(d.get("width", 10)),
                                              key=f"{prefix}_wid")
        extra["char"]      = pc3.text_input("Pad char",
                                            value=d.get("char", "0"),
                                            key=f"{prefix}_char",
                                            max_chars=1)
        st.caption(f"Example: '123' → '{'0' * (int(extra['width']) - 3)}123'")

    elif rtype == "truncate":
        extra["max_length"] = st.number_input("Max length *", min_value=1,
                                              max_value=4000,
                                              value=int(d.get("max_length", 40)),
                                              key=f"{prefix}_maxlen")

    elif rtype == "strip_chars":
        extra["chars"] = st.text_input("Characters to strip *",
                                       value=d.get("chars", ""),
                                       key=f"{prefix}_chars",
                                       placeholder="e.g. -() to strip dashes and parens")

    st.markdown("")
    sb1, sb2 = st.columns([1, 4])
    saved    = sb1.button("💾 Save", type="primary",
                          use_container_width=True, key=f"{prefix}_save")
    canceled = sb2.button("Cancel", use_container_width=True,
                          key=f"{prefix}_cancel")

    if canceled:
        return "CANCEL"

    if saved:
        errs = []
        if not name.strip():
            errs.append("Rule name is required.")
        if not col:
            errs.append("Column name is required.")
        if rtype == "replace" and not extra.get("find"):
            errs.append("Find string is required.")
        if rtype == "regex_replace" and not extra.get("pattern"):
            errs.append("Regex pattern is required.")
        if rtype == "null_sub" and not extra.get("substitute"):
            errs.append("Substitute value is required.")
        if rtype == "strip_chars" and not extra.get("chars"):
            errs.append("Characters to strip are required.")
        for e in errs:
            st.error(e)
        if errs:
            return None

        return {
            "id":          d.get("id", ""),
            "name":        name.strip(),
            "description": desc.strip(),
            "table":       table,
            "column":      col,
            "severity":    "INFO",
            "enabled":     d.get("enabled", True),
            "type":        rtype,
            **extra,
        }
    return None


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION RULE FORM
# ═══════════════════════════════════════════════════════════════════════════

def _val_form(prefix: str, initial: dict | None = None, d: dict | None = None):
    """Render validation rule form. Returns rule dict | 'CANCEL' | None."""
    d = initial or d or {}
    c1, c2 = st.columns([3, 1])
    name = c1.text_input("Rule name *", value=d.get("name", ""),
                         key=f"{prefix}_name",
                         placeholder="e.g. KB elevation above ground")
    sev_idx = SEVERITIES.index(d.get("severity", "WARNING"))
    severity = c2.selectbox("Severity", SEVERITIES, index=sev_idx,
                             key=f"{prefix}_sev",
                             help="ERROR blocks the row from being promoted. WARNING flags it but still allows promote.")

    desc  = st.text_input("Description", value=d.get("description", ""),
                          key=f"{prefix}_desc",
                          placeholder="Plain English explanation")
    table = _table_picker(f"{prefix}_tbl", d.get("table", "*"))

    type_opts   = list(VAL_TYPES.keys())
    type_labels = list(VAL_TYPES.values())
    cur_type    = d.get("type", "not_empty")
    type_idx    = type_opts.index(cur_type) if cur_type in type_opts else 0
    rtype_lbl   = st.selectbox("Rule type *", type_labels,
                               index=type_idx, key=f"{prefix}_type")
    rtype = type_opts[type_labels.index(rtype_lbl)]

    st.divider()
    extra: dict = {}

    if rtype == "not_empty":
        extra["column"] = st.text_input("PPDM column *",
                                        value=d.get("column", ""),
                                        key=f"{prefix}_col",
                                        placeholder="e.g. WELL_NAME").upper().strip()

    elif rtype == "range":
        extra["column"] = st.text_input("PPDM column *",
                                        value=d.get("column", ""),
                                        key=f"{prefix}_col",
                                        placeholder="e.g. FINAL_TD").upper().strip()
        rc1, rc2 = st.columns(2)
        mn = rc1.text_input("Minimum  (blank = no lower bound)",
                            value="" if d.get("min") is None else str(d["min"]),
                            key=f"{prefix}_min")
        mx = rc2.text_input("Maximum  (blank = no upper bound)",
                            value="" if d.get("max") is None else str(d["max"]),
                            key=f"{prefix}_max")
        extra["min"] = float(mn) if mn.strip() else None
        extra["max"] = float(mx) if mx.strip() else None

    elif rtype == "compare_cols":
        cc1, cc2, cc3 = st.columns([2, 1, 2])
        extra["col_a"]    = cc1.text_input("Column A *",
                                           value=d.get("col_a", ""),
                                           key=f"{prefix}_ca",
                                           placeholder="e.g. KB_ELEV").upper().strip()
        op_idx = OPERATORS.index(d.get("operator", "<="))
        extra["operator"] = cc2.selectbox("Op", OPERATORS,
                                          index=op_idx, key=f"{prefix}_op")
        extra["col_b"]    = cc3.text_input("Column B *",
                                           value=d.get("col_b", ""),
                                           key=f"{prefix}_cb",
                                           placeholder="e.g. GROUND_ELEV").upper().strip()
        st.caption(f"Rule passes when **Column A {extra['operator']} Column B**")

    elif rtype == "date_order":
        dc1, dc2 = st.columns(2)
        extra["col_before"] = dc1.text_input("Earlier date column *",
                                             value=d.get("col_before", ""),
                                             key=f"{prefix}_cbef",
                                             placeholder="e.g. SPUD_DATE").upper().strip()
        extra["col_after"]  = dc2.text_input("Later date column *",
                                             value=d.get("col_after", ""),
                                             key=f"{prefix}_caft",
                                             placeholder="e.g. ABANDONMENT_DATE").upper().strip()
        st.caption("Rule passes when **Earlier date ≤ Later date**")

    elif rtype == "regex":
        import re as _re
        extra["column"]  = st.text_input("PPDM column *",
                                         value=d.get("column", ""),
                                         key=f"{prefix}_col",
                                         placeholder="e.g. WELL_NAME").upper().strip()
        extra["pattern"] = st.text_input("Regex pattern *",
                                         value=d.get("pattern", ""),
                                         key=f"{prefix}_pat",
                                         placeholder=r"e.g. ^\d{14}$ for 14-digit API")
        extra["message"] = st.text_input("Failure message",
                                         value=d.get("message", ""),
                                         key=f"{prefix}_msg",
                                         placeholder="Shown when the pattern doesn't match")
        if extra["pattern"]:
            try:
                _re.compile(extra["pattern"])
                st.caption("✅ Valid regex pattern")
            except _re.error as e:
                st.error(f"Invalid regex: {e}")
                extra["pattern"] = ""

    st.markdown("")
    sb1, sb2 = st.columns([1, 4])
    saved    = sb1.button("💾 Save", type="primary",
                          use_container_width=True, key=f"{prefix}_save")
    canceled = sb2.button("Cancel", use_container_width=True,
                          key=f"{prefix}_cancel")

    if canceled:
        return "CANCEL"

    if saved:
        errs = []
        if not name.strip():
            errs.append("Rule name is required.")
        if rtype in ("not_empty", "range", "regex") and not extra.get("column"):
            errs.append("Column name is required.")
        if rtype == "compare_cols":
            if not extra.get("col_a"): errs.append("Column A is required.")
            if not extra.get("col_b"): errs.append("Column B is required.")
        if rtype == "date_order":
            if not extra.get("col_before"): errs.append("Earlier date column is required.")
            if not extra.get("col_after"):  errs.append("Later date column is required.")
        if rtype == "regex" and not extra.get("pattern"):
            errs.append("A valid regex pattern is required.")
        for e in errs:
            st.error(e)
        if errs:
            return None

        return {
            "id":          d.get("id", ""),
            "name":        name.strip(),
            "description": desc.strip(),
            "table":       table,
            "severity":    severity,
            "enabled":     d.get("enabled", True),
            "type":        rtype,
            **extra,
        }
    return None


# ═══════════════════════════════════════════════════════════════════════════
# RULE ROW WIDGETS
# ═══════════════════════════════════════════════════════════════════════════

def _norm_summary(rule: dict) -> str:
    rtype = rule.get("type", "")
    col   = rule.get("column", "?")
    if rtype == "case":
        return f"`{col}` → {rule.get('case','upper').upper()} CASE"
    if rtype == "replace":
        return f"`{col}`: replace `{rule.get('find','')}` with `{rule.get('replace_with','')}`"
    if rtype == "regex_replace":
        return f"`{col}`: regex replace `{rule.get('pattern','')}` → `{rule.get('replace_with','')}`"
    if rtype == "null_sub":
        return f"`{col}`: empty → `{rule.get('substitute','')}`"
    if rtype == "pad":
        return f"`{col}`: {rule.get('direction','left')}-pad to {rule.get('width',0)} chars with `{rule.get('char','0')}`"
    if rtype == "truncate":
        return f"`{col}`: truncate to {rule.get('max_length',0)} chars"
    if rtype == "strip_chars":
        return f"`{col}`: strip chars `{rule.get('chars','')}`"
    return rtype


def _val_summary(rule: dict) -> str:
    rtype = rule.get("type", "")
    if rtype == "not_empty":
        return f"`{rule.get('column','?')}` must not be empty"
    if rtype == "range":
        col  = rule.get("column", "?")
        mn   = rule.get("min")
        mx   = rule.get("max")
        bits = []
        if mn is not None: bits.append(f"≥ {mn}")
        if mx is not None: bits.append(f"≤ {mx}")
        return f"`{col}` {' and '.join(bits)}"
    if rtype == "compare_cols":
        return f"`{rule.get('col_a','?')}` {rule.get('operator','?')} `{rule.get('col_b','?')}`"
    if rtype == "date_order":
        return f"`{rule.get('col_before','?')}` ≤ `{rule.get('col_after','?')}`"
    if rtype == "regex":
        return f"`{rule.get('column','?')}` matches `{rule.get('pattern','?')}`"
    return rtype


def _render_rule_card(rule: dict, all_rules: list[dict],
                      summary_fn, form_fn, edit_key: str,
                      save_fn, id_prefix: str):
    """Generic rule card for both norm and val rules."""
    rid      = rule["id"]
    enabled  = rule.get("enabled", True)
    sev      = rule.get("severity", "INFO")
    is_edit  = st.session_state[edit_key] == rid

    with st.container(border=True):
        h1, h2, h3, h4, h5 = st.columns([0.5, 3.5, 0.8, 0.8, 0.8])

        new_ena = h1.checkbox("Enable", value=enabled, key=f"{id_prefix}_ena_{rid}",
                              help="Enable / disable", label_visibility="collapsed")
        if new_ena != enabled:
            for r in all_rules:
                if r["id"] == rid:
                    r["enabled"] = new_ena
            save_fn(all_rules)
            st.rerun()

        h2.markdown(
            f"**{rule.get('name', rid)}**  \n"
            f"<small style='color:#888'>{summary_fn(rule)}</small>",
            unsafe_allow_html=True,
        )

        if sev != "INFO":
            h3.markdown(
                f"<span style='color:{_sev_color(sev)};font-weight:600;"
                f"font-size:11px'>{sev}</span>",
                unsafe_allow_html=True,
            )

        if h4.button("✏️", key=f"{id_prefix}_edit_{rid}",
                     use_container_width=True, help="Edit"):
            st.session_state[edit_key] = rid
            st.rerun()

        if h5.button("🗑", key=f"{id_prefix}_del_{rid}",
                     use_container_width=True, help="Delete"):
            new_rules = [r for r in all_rules if r["id"] != rid]
            save_fn(new_rules)
            if st.session_state[edit_key] == rid:
                st.session_state[edit_key] = None
            st.rerun()

        if is_edit:
            st.divider()
            result = form_fn(f"edit_{id_prefix}_{rid}", initial=rule)
            if result == "CANCEL":
                st.session_state[edit_key] = None
                st.rerun()
            elif result is not None:
                result["id"]      = rid
                result["enabled"] = rule.get("enabled", True)
                for i, r in enumerate(all_rules):
                    if r["id"] == rid:
                        all_rules[i] = result
                        break
                save_fn(all_rules)
                st.session_state[edit_key] = None
                st.success("Rule updated.")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def _run_test(S):
    from dataview.core.validate import validate as _validate, ValidationIssue

    target_table = S.get("target_table", "")
    df = (S.get("norm_df") or S.get("staging_df") or S.get("source_df"))
    col_mapping  = S.get("col_mapping")

    if df is None or not col_mapping or not target_table:
        st.error("No staged data or mapping found. Complete at least Stage 5 in the pipeline first.")
        return

    col_map = {
        m.ppdm_col.upper(): (m.source_col or "")
        for m in col_mapping.mapped
    }

    # ── Normalization test — run on copy ──────────────────────────────
    with st.spinner("Applying normalization rules to a preview copy…"):
        df_norm, norm_changes = apply_norm_rules(df.copy(), target_table, col_mapping)

    # ── Validation test ───────────────────────────────────────────────
    user_rules = get_val_rules_for_table(target_table)
    issues = []
    if user_rules:
        with st.spinner(f"Running {len(user_rules)} validation rule(s) against {len(df_norm):,} rows…"):
            for idx, row in df_norm.iterrows():
                for r in user_rules:
                    msg = r["check"](row, col_map)
                    if msg:
                        issues.append(ValidationIssue(
                            row_idx=idx, ppdm_col="", src_col="",
                            value="", rule=r["name"],
                            severity=r["severity"], message=msg,
                        ))

    st.session_state.rules_test_result = {
        "norm_changes": norm_changes,
        "val_issues":   issues,
        "row_count":    len(df),
    }
    st.session_state.rules_test_table = target_table
    st.rerun()


def _show_test_results(result: dict, target_table: str):
    nc   = result.get("norm_changes", [])
    vi   = result.get("val_issues",   [])
    rows = result.get("row_count",    0)

    st.markdown(f"### 🧪 Test Results — `{target_table}` ({rows:,} rows)")

    t1, t2 = st.tabs(["Normalization Changes", "Validation Issues"])

    with t1:
        if not nc:
            st.success("No normalization changes — data already matches all enabled rules.")
        else:
            rows_data = []
            for c in nc:
                if c.get("error"):
                    rows_data.append({
                        "Rule ID": c["id"], "Rule": c["name"],
                        "Column": c["column"], "Changed": "ERROR",
                        "Detail": c["error"],
                    })
                else:
                    rows_data.append({
                        "Rule ID": c["id"], "Rule": c["name"],
                        "Column": c["column"],
                        "Changed": c["changed"],
                        "Detail": c.get("type", ""),
                    })
            st.dataframe(pd.DataFrame(rows_data), use_container_width=True,
                         hide_index=True)
            total = sum(c.get("changed", 0) for c in nc if not c.get("error")
                        and isinstance(c.get("changed"), int))
            st.caption(f"{len(nc)} rule(s) produced changes — {total:,} cell(s) would be modified.")

    with t2:
        if not vi:
            st.success("No validation issues found for enabled rules.")
        else:
            df_vi = pd.DataFrame([{
                "Row":     i.row_idx,
                "Severity": i.severity,
                "Rule":    i.rule,
                "Message": i.message,
            } for i in vi])
            n_err  = sum(1 for i in vi if i.severity == "ERROR")
            n_warn = sum(1 for i in vi if i.severity == "WARNING")
            mc1, mc2 = st.columns(2)
            mc1.metric("Errors",   n_err)
            mc2.metric("Warnings", n_warn)
            sev_filter = st.multiselect("Filter severity",
                                        ["ERROR", "WARNING"],
                                        default=["ERROR", "WARNING"],
                                        key="test_sev_filter")
            df_show = df_vi[df_vi["Severity"].isin(sev_filter)]
            st.dataframe(df_show, use_container_width=True, hide_index=True,
                         height=350)

    if st.button("✕ Clear test results", key="clear_test"):
        st.session_state.rules_test_result = None
        st.session_state.rules_test_table  = None
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN RENDER
# ═══════════════════════════════════════════════════════════════════════════

def render(S):
    _init()

    st.markdown("## 📋 Rules Manager")
    st.caption(
        "Manage **Normalization Rules** (column transforms applied after Stage 3) and "
        "**Validation Rules** (data quality checks applied at Stage 7).  "
        "Rules are saved to `modules/user_rules.json`."
    )

    # ── Toolbar ───────────────────────────────────────────────────────────
    has_data = (S.get("norm_df") is not None
                or S.get("staging_df") is not None
                or S.get("source_df") is not None)
    can_test = has_data and bool(S.get("target_table")) and bool(S.get("col_mapping"))

    tb1, tb2, tb3 = st.columns([2, 2, 4])
    if tb2.button("▶ Test Now", use_container_width=True,
                  disabled=not can_test, key="rules_test_btn",
                  help="Run rules against currently staged data.  Requires Stage 5 complete."):
        _run_test(S)

    if not can_test:
        tb2.caption("Load and map data in pipeline first.")

    # Export / Import
    store = load_store()
    tb3.download_button(
        "⬇ Export all rules",
        data=json.dumps(store, indent=2),
        file_name="user_rules.json",
        mime="application/json",
        use_container_width=True,
        key="rules_export",
    )

    # ── Test results ──────────────────────────────────────────────────────
    if st.session_state.rules_test_result is not None:
        _show_test_results(
            st.session_state.rules_test_result,
            st.session_state.rules_test_table or "",
        )
        st.divider()

    # ── Two tabs ──────────────────────────────────────────────────────────
    tab_norm, tab_val = st.tabs([
        "🔧 Normalization Rules",
        "✅ Validation Rules",
    ])

    # ─────────────────────────────────────────────────────────────────────
    # NORMALIZATION TAB
    # ─────────────────────────────────────────────────────────────────────
    with tab_norm:
        st.caption(
            "Normalization rules transform specific columns after the global "
            "normalize step (Stage 3).  They never block rows — they just "
            "reshape the data before it reaches the mapping and validation stages."
        )

        norm_rules = load_norm_rules()

        # Add button
        if st.button("➕ Add Normalization Rule", type="primary",
                     key="norm_add_btn"):
            st.session_state.rules_norm_add  = True
            st.session_state.rules_norm_edit = None
            st.rerun()

        if st.session_state.rules_norm_add:
            with st.container(border=True):
                st.markdown("### ➕ New Normalization Rule")
                result = _norm_form("norm_add")
                if result == "CANCEL":
                    st.session_state.rules_norm_add = False
                    st.rerun()
                elif result is not None:
                    result["id"] = next_norm_id(norm_rules)
                    norm_rules.append(result)
                    save_norm_rules(norm_rules)
                    st.session_state.rules_norm_add = False
                    st.success(f"Rule {result['id']} saved.")
                    st.rerun()
            st.divider()

        if not norm_rules:
            st.info("No normalization rules yet. Click **➕ Add Normalization Rule** to create one.")
        else:
            groups = _rule_group(norm_rules, lambda r: r.get("table", "*"))
            for tbl, grp in groups.items():
                label     = "🌐 All Tables" if tbl == "*" else f"📋 {tbl}"
                n_enabled = sum(1 for r in grp if r.get("enabled", True))
                with st.expander(f"{label}  —  {len(grp)} rule(s), {n_enabled} enabled",
                                 expanded=True):
                    for rule in grp:
                        _render_rule_card(
                            rule, norm_rules,
                            summary_fn=_norm_summary,
                            form_fn=_norm_form,
                            edit_key="rules_norm_edit",
                            save_fn=save_norm_rules,
                            id_prefix="nr",
                        )

        # Import
        st.divider()
        uploaded = st.file_uploader("⬆ Import rules (JSON)",
                                    type=["json"],
                                    key="norm_import",
                                    help="Import a previously exported user_rules.json")
        if uploaded:
            try:
                imported = json.load(uploaded)
                if isinstance(imported, dict) and "normalization_rules" in imported:
                    save_norm_rules(imported["normalization_rules"])
                    st.success(f"Imported {len(imported['normalization_rules'])} normalization rule(s).")
                    st.rerun()
                elif isinstance(imported, list):
                    save_norm_rules(imported)
                    st.success(f"Imported {len(imported)} normalization rule(s).")
                    st.rerun()
                else:
                    st.error("Unrecognised format — expected user_rules.json or a list of rules.")
            except Exception as e:
                st.error(f"Import failed: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # VALIDATION TAB
    # ─────────────────────────────────────────────────────────────────────
    with tab_val:
        st.caption(
            "Validation rules run at Stage 7.  **ERROR** rules block the row from "
            "being promoted.  **WARNING** rules flag the row but still allow promote."
        )

        val_rules = load_val_rules()

        if st.button("➕ Add Validation Rule", type="primary",
                     key="val_add_btn"):
            st.session_state.rules_val_add  = True
            st.session_state.rules_val_edit = None
            st.rerun()

        if st.session_state.rules_val_add:
            with st.container(border=True):
                st.markdown("### ➕ New Validation Rule")
                result = _val_form("val_add")
                if result == "CANCEL":
                    st.session_state.rules_val_add = False
                    st.rerun()
                elif result is not None:
                    result["id"] = next_val_id(val_rules)
                    val_rules.append(result)
                    save_val_rules(val_rules)
                    st.session_state.rules_val_add = False
                    st.success(f"Rule {result['id']} saved.")
                    st.rerun()
            st.divider()

        if not val_rules:
            st.info("No validation rules yet. Click **➕ Add Validation Rule** to create one.")
        else:
            groups = _rule_group(val_rules, lambda r: r.get("table", "*"))
            for tbl, grp in groups.items():
                label     = "🌐 All Tables" if tbl == "*" else f"📋 {tbl}"
                n_enabled = sum(1 for r in grp if r.get("enabled", True))
                with st.expander(f"{label}  —  {len(grp)} rule(s), {n_enabled} enabled",
                                 expanded=True):
                    for rule in grp:
                        _render_rule_card(
                            rule, val_rules,
                            summary_fn=_val_summary,
                            form_fn=_val_form,
                            edit_key="rules_val_edit",
                            save_fn=save_val_rules,
                            id_prefix="vr",
                        )

        st.divider()
        uploaded_v = st.file_uploader("⬆ Import rules (JSON)",
                                      type=["json"],
                                      key="val_import")
        if uploaded_v:
            try:
                imported = json.load(uploaded_v)
                if isinstance(imported, dict) and "validation_rules" in imported:
                    save_val_rules(imported["validation_rules"])
                    st.success(f"Imported {len(imported['validation_rules'])} validation rule(s).")
                    st.rerun()
                elif isinstance(imported, list):
                    save_val_rules(imported)
                    st.success(f"Imported {len(imported)} validation rule(s).")
                    st.rerun()
                else:
                    st.error("Unrecognised format.")
            except Exception as e:
                st.error(f"Import failed: {e}")

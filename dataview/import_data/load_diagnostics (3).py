"""
load_diagnostics.py — turn a raw SQL Server / pyodbc load or promote failure into a
plain-language diagnosis: what column/table broke, what it means, and how to fix it in
the loader UI. Deterministic pattern-matching over the known SQL Server error numbers —
no AI, no network. Wrap the promote/load call in try/except and pass the exception here.

    from load_diagnostics import diagnose, render
    try:
        _apply_table_load(...)
    except Exception as e:
        render(e, table=table)          # Streamlit: trap → explain → advise + raw details
        # or:  d = diagnose(e);  print(d.title); print(d.advice)

Recognized (by SQL Server error number):
    515  NULL into NOT-NULL column          2627/2601 PK / unique duplicate
    257/206  type mismatch on INSERT        547  FK / CHECK constraint conflict
    2628/8152 truncation                    245/8114 conversion failed
    208  invalid object                     229/262/297 permission
Anything else → a generic "unrecognized" diagnosis that still shows the cleaned message.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Diagnosis:
    code: str                      # NULL_NOT_ALLOWED, TYPE_MISMATCH, FK_VIOLATION, ...
    title: str                     # one-line plain summary
    explanation: str               # what it means
    advice: List[str] = field(default_factory=list)   # concrete fixes, most-likely first
    table: Optional[str] = None
    column: Optional[str] = None
    sql_number: Optional[int] = None
    raw: str = ""                  # cleaned (de-duplicated) original message

    def as_text(self) -> str:
        loc = f" [{self.table}.{self.column}]" if (self.table and self.column) else (
              f" [{self.column}]" if self.column else "")
        lines = [f"{self.title}{loc}", "", self.explanation, ""]
        if self.advice:
            lines.append("How to fix:")
            lines += [f"  • {a}" for a in self.advice]
        return "\n".join(lines)


# ── message cleanup ──────────────────────────────────────────────────────────────
def _clean(msg: str) -> str:
    """pyodbc repeats the same line once per row in an executemany; collapse to unique
    lines in order, and drop the noisy driver prefix."""
    seen, out = set(), []
    for ln in str(msg).replace("\\n", "\n").splitlines():
        s = re.sub(r"\[[^\]]*Microsoft\]\[[^\]]*\]\[SQL Server\]\s*", "", ln).strip()
        s = re.sub(r"\((?:515|3621|257|547|2627|2601|2628|8152|245|8114|208)\)\s*$", "", s).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return "\n".join(out)


def _sqlnum(msg: str) -> Optional[int]:
    m = re.search(r"\((\d{3,5})\)\s*(?:\(SQLExec|\(SQLExecute|$|\n)", msg)
    if m:
        return int(m.group(1))
    # fall back: first parenthesized 3-5 digit code
    m = re.search(r"\b(515|257|206|547|2627|2601|2628|8152|245|8114|208|229|262|297)\b", msg)
    return int(m.group(1)) if m else None


def _looks_like_key(col: str) -> bool:
    c = (col or "").lower()
    return c.endswith("_id") or c == "id" or c.endswith("_hash") or c.endswith("_key")


# ── the interpreters ─────────────────────────────────────────────────────────────
def diagnose(exc) -> Diagnosis:
    raw = str(getattr(exc, "orig", None) or exc)
    cleaned = _clean(raw)
    num = _sqlnum(raw)

    # 515 — NULL into NOT-NULL column
    m = re.search(r"Cannot insert the value NULL into column '([^']+)', table '([^']+)'", raw)
    if m:
        col, tbl = m.group(1), m.group(2).split(".")[-1]
        key = _looks_like_key(col)
        adv = []
        if key:
            adv.append(f"'{col}' looks like a generated key with no value in your CSV. In "
                       f"**④ Derived columns (functions)** add a rule for {col}: use `concat` "
                       f"(e.g. arg `{{uwi}}` or `{{uwi}}_{{seq}}`) or `seq_num` to generate it.")
        else:
            adv.append(f"Map a source column to '{col}' in the {tbl} mapping step, or give it a "
                       f"default in **④ Derived columns** (`constant`).")
        adv.append(f"If you don't need {tbl}, set it to **skip** in Files→tables (its FK children "
                   f"cascade out with it).")
        adv.append(f"If '{col}' should legitimately allow blanks, make the column nullable in the DDL.")
        return Diagnosis("NULL_NOT_ALLOWED",
                         f"Required column '{col}' got no value",
                         f"{tbl}.{col} is NOT NULL, but the load supplied no value for it, so SQL "
                         f"Server rejected every row.",
                         adv, table=tbl, column=col, sql_number=num or 515, raw=cleaned)

    # 257 / 206 — type mismatch on INSERT (e.g. text mapped into a binary/numeric column)
    m = re.search(r"Implicit conversion from data type (\w+) to (\w+) is not allowed", raw) \
        or re.search(r"Operand type clash: (\w+) is incompatible with (\w+)", raw)
    if m:
        src_t, tgt_t = m.group(1), m.group(2)
        col = _column_from_insert(raw, prefer_type=tgt_t)
        note = ""
        if col and col.lower().endswith("_hash"):
            note = (f" '{col}' is a spatial/hash column — it should have **no source mapping** and "
                    f"be left NULL for the H3 backfill to populate, not mapped from a text column.")
        adv = [f"A {src_t} source value is being loaded into a {tgt_t} column"
               + (f" ('{col}')" if col else "") + ". This is almost always a **wrong mapping**.",
               f"In the mapping step, set that target to **skip** or map a {tgt_t}-compatible source." + note,
               "Don't 'fix' it with CONVERT — forcing incompatible types stores garbage."]
        return Diagnosis("TYPE_MISMATCH",
                         f"Incompatible type: {src_t} → {tgt_t}"
                         + (f" for '{col}'" if col else ""),
                         f"A column mapped a {src_t} source into a {tgt_t} target, which SQL Server "
                         f"won't convert implicitly. The whole statement rolled back.",
                         adv, column=col, sql_number=num or 257, raw=cleaned)

    # 547 — FK / CHECK constraint
    m = re.search(r'conflicted with the (FOREIGN KEY|REFERENCE|CHECK) constraint "([^"]+)"', raw)
    if m:
        kind, cons = m.group(1), m.group(2)
        t2 = re.search(r'table "([^"]+)", column \'([^\']+)\'', raw)
        tbl = t2.group(1).split(".")[-1] if t2 else None
        col = t2.group(2) if t2 else None
        if kind == "CHECK":
            adv = [f"A value violates the CHECK constraint {cons}"
                   + (f" on {col}" if col else "") + " — the value isn't in the allowed set.",
                   "Fix or remap the offending source value, or skip the column."]
            return Diagnosis("CHECK_VIOLATION", f"CHECK constraint {cons} failed",
                             "A value fell outside what the column's CHECK constraint permits.",
                             adv, table=tbl, column=col, sql_number=num or 547, raw=cleaned)
        adv = [f"A value in {col or 'a FK column'} points to a parent row that doesn't exist "
               f"(constraint {cons}).",
               "In the **FK grid**, check **Add** to seed the missing parent value, or pick "
               "**Map to existing + Remap** to point it at a value that's already there.",
               "For reference/standards tables, prefer **Map to existing** — imports shouldn't "
               "mint new canonical codes."]
        return Diagnosis("FK_VIOLATION", f"Unresolved foreign key ({cons})",
                         "A child value references a parent that isn't in the target table.",
                         adv, table=tbl, column=col, sql_number=num or 547, raw=cleaned)

    # 2628 (named) / 8152 — truncation
    m = re.search(r"String or binary data would be truncated in table '([^']+)', column '([^']+)'", raw)
    if m:
        tbl, col = m.group(1).split(".")[-1], m.group(2)
        adv = [f"A value in '{col}' is longer than the column allows.",
               "Trim/clean the source value, widen the column in the DDL, or skip the column.",
               "The loader's LEFT() truncation normally guards this — check the mapping didn't "
               "bypass it for a function-derived column."]
        return Diagnosis("TRUNCATION", f"Value too long for '{col}'",
                         f"{tbl}.{col} received a value exceeding its defined length.",
                         adv, table=tbl, column=col, sql_number=num or 2628, raw=cleaned)
    if re.search(r"String or binary data would be truncated", raw):
        return Diagnosis("TRUNCATION", "A value is too long for its column",
                         "SQL Server didn't name the column (older version). Look for the widest "
                         "text/varchar value in this table's source.",
                         ["Widen the column, or trim/skip the oversized source values.",
                          "Upgrade note: SQL Server 2019+ reports the exact column here."],
                         sql_number=num or 8152, raw=cleaned)

    # 2627 / 2601 — duplicate primary/unique key
    m = re.search(r"Violation of (PRIMARY KEY|UNIQUE KEY) constraint '([^']+)'", raw) \
        or re.search(r"Cannot insert duplicate key row in object '([^']+)'", raw)
    if m:
        cons = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)
        dv = re.search(r"The duplicate key value is \(([^)]*)\)", raw)
        val = dv.group(1) if dv else None
        adv = [f"Two rows produced the same key" + (f" ({val})" if val else "") + ".",
               "Dedup the source, or fix the key rule in **④ Derived columns** so it's unique "
               "(add a partition/sequence column to the `concat`/`seq_num`).",
               "If the row already exists in the target, this may be a re-run — the load is "
               "idempotent-guarded elsewhere; check the key isn't colliding with existing data."]
        return Diagnosis("DUPLICATE_KEY", f"Duplicate key ({cons})",
                         "The generated key isn't unique across the incoming rows.",
                         adv, sql_number=num or 2627, raw=cleaned)

    # 245 / 8114 — conversion failed on a specific value
    m = re.search(r"Conversion failed when converting the (\w+) value '([^']*)' to data type (\w+)", raw) \
        or re.search(r"Error converting data type (\w+) to (\w+)", raw)
    if m:
        adv = ["A source value can't be converted to the target column's type "
               "(e.g. non-numeric text into a numeric column, or a bad date).",
               "Clean the offending value, remap the column, or rely on the loader's "
               "TRY_CONVERT path (which nulls bad values instead of failing).",
               "Check the mapping isn't sending a text column into a numeric/date target."]
        val = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        return Diagnosis("CONVERT_FAILED",
                         "A value couldn't be converted to its column type"
                         + (f" (offending value: '{val}')" if val else ""),
                         "SQL Server hit a value it couldn't cast to the target type.",
                         adv, sql_number=num or 245, raw=cleaned)

    # 207 — invalid column name (often a function rule given the wrong argument shape)
    m = re.search(r"Invalid column name '([^']*)'", raw)
    if m:
        col = m.group(1)
        tmpl = "{" in col and "}" in col
        if tmpl:
            adv = [f"A **function rule** was given a `concat` template (`{col}`) where a plain "
                   f"column name was expected, so SQL Server looked for a column literally "
                   f"called that.",
                   "In **④ Derived columns**, the argument shape differs per function: "
                   "`seq_num` takes partition **column names** (`uwi,log_id` — no braces); "
                   "`concat` takes a **template** (`{uwi}_{log_id}_{curve_name}`).",
                   "If you want a generated key, switch that rule's function to **concat**. "
                   "If you want a running number, keep `seq_num` and give it bare column names."]
            title = f"Function rule mismatch: template used where a column name was expected"
        else:
            adv = [f"The load referenced a column '{col}' that doesn't exist in the staging "
                   f"table or the target.",
                   "Check the mapping for a stale/renamed column, or re-scan so staging matches "
                   "the file.",
                   "A function rule naming a source column that isn't in this file will do this too."]
            title = f"Invalid column name: '{col}'"
        return Diagnosis("INVALID_COLUMN", title,
                         f"SQL Server couldn't resolve the column '{col}'.",
                         adv, column=col, sql_number=num or 207, raw=cleaned)

    # 208 — invalid object
    m = re.search(r"Invalid object name '([^']+)'", raw)
    if m:
        obj = m.group(1)
        return Diagnosis("INVALID_OBJECT", f"Table/object not found: {obj}",
                         f"The load referenced '{obj}', which doesn't exist in this database.",
                         [f"Confirm '{obj}' exists in the target schema, and that you're connected "
                          f"to the right database.",
                          "A staging table may not have been created — re-run the stage step."],
                         table=obj, sql_number=num or 208, raw=cleaned)

    # permission
    if re.search(r"permission was denied|The (INSERT|SELECT|EXECUTE) permission", raw):
        return Diagnosis("PERMISSION", "Permission denied",
                         "The connected login lacks rights for this operation.",
                         ["Grant the login INSERT/SELECT on the target schema, or connect as a "
                          "user that has them."],
                         sql_number=num, raw=cleaned)

    # fallback — still useful: show the cleaned one-line-per-issue message
    first = cleaned.splitlines()[0] if cleaned else str(exc)
    return Diagnosis("UNRECOGNIZED", "Load failed (unrecognized SQL error)",
                     "This error isn't in the known-pattern set, but here's the cleaned message.",
                     ["Read the message below; the raw traceback is under Details.",
                      "If this recurs, it's worth adding a pattern for it to load_diagnostics.py."],
                     sql_number=num, raw=first if first else cleaned)


def _column_from_insert(raw: str, prefer_type: str = "") -> Optional[str]:
    """Best-effort: pull the target column near a type-mismatch. Works when the failing
    INSERT text is in the message (SQLAlchemy appends [SQL: ...])."""
    # e.g. MIN([KB_ELEV]) AS [h3_coord_hash]  → target is h3_coord_hash
    for m in re.finditer(r"AS \[([a-z0-9_]+)\]", raw, re.I):
        c = m.group(1)
        if prefer_type and ("hash" in c.lower() or "coord" in c.lower()):
            return c
    m = re.search(r"AS \[([a-z0-9_]+)\]\s*FROM", raw, re.I)
    return m.group(1) if m else None


# ── Streamlit rendering ──────────────────────────────────────────────────────────
def render(exc, table: str = None, context: str = None, tb: str = None):
    """Trap → explain → advise in the UI, with the raw traceback tucked away.

    `tb` — the traceback captured AT EXCEPTION TIME. Pass it whenever render() runs on a
    later rerun (Streamlit's usual pattern: store the error, render it next pass), because
    traceback.format_exc() only works inside the live `except` block — elsewhere it returns
    "NoneType: None" and the panel silently shows no stack at all."""
    try:
        import streamlit as st
    except Exception:
        print(diagnose(exc).as_text())
        return
    d = diagnose(exc)
    head = d.title + (f"  ·  {table}" if table and not d.table else "")
    st.error(f"❌ {head}")
    st.markdown(f"**What happened.** {d.explanation}")
    if d.advice:
        st.markdown("**How to fix:**")
        for a in d.advice:
            st.markdown(f"- {a}")

    import traceback
    if not tb:
        tb = traceback.format_exc()
    full = str(exc)                      # SQLAlchemy puts the offending statement in here

    def _details():
        if d.sql_number:
            st.caption(f"SQL Server error {d.sql_number} · {d.code}")
        if full:
            st.caption("Full error (includes the generated SQL):")
            st.code(full, language="text")
        if tb and tb.strip() != "NoneType: None":
            st.caption("Traceback:")
            st.code(tb, language="text")
        elif not full:
            st.caption("(no traceback captured — pass tb= from the except block)")

    # This is an error path — it can fire from anywhere, including inside an expander,
    # and Streamlit forbids nesting them. Never let the *reporting* of an error become a
    # second error that hides the first.
    try:
        with st.expander("Technical details (SQL error + traceback)"):
            _details()
    except Exception:
        st.caption("Technical details")
        _details()
    return d

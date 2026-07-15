"""
staging_repair.py — repair what is *deterministically* repairable in staging, and refuse the
rest. Runs after mapping (so the target type is known) and before promote.

The line this module will not cross: a repair must be reversible reasoning, not a guess. If
the original value can't be recovered from what's on disk, the answer is to flag it and make
the operator re-export — never to invent something plausible.

  REPAIRED (deterministic → numeric target)
    "1,234.5"        → 1234.5      thousands separators
    "13-3/8"  13 3/8 → 13.375      mixed fraction (casing OD in inches)
    "3/8"            → 0.375       bare fraction
    "3217.3 ft"      → 3217.3      trailing unit
    "(5.2)"          → -5.2        accounting negative
    "1 234"          → 1234        non-breaking / thin space grouping
  REPAIRED (any target)
    NULL bytes, control characters      → removed
    smart quotes / en-dash / nbsp       → ASCII equivalents

  REFUSED (flagged, never "fixed")
    "4.23291E+13" in an identifier — Excel kept 6 of 14 significant digits, so the low-order
    digits are gone. Expanding it yields 42329100000000 for a well that is really
    42329100010000. Two different wells collapse to the same value. There is no repair;
    re-export the source with the column formatted as text.
    "n/a", "unknown", "-" in a numeric column — no defensible value, leave it to load as NULL.

Write-back is set-based: values are computed in Python, pushed to a temp table, and applied
with one JOIN UPDATE. Never per-row pyodbc.
"""
from __future__ import annotations
import re
import unicodedata

_NUMERIC = ("numeric", "decimal", "float", "real", "int", "bigint", "smallint", "tinyint",
            "money", "smallmoney")

# unicode junk → ASCII. Safe for every target type.
_PUNCT = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u2009": " ",
    "\u00b4": "'", "\u02bc": "'",
}
_CTRL = {c: None for c in range(32) if c not in (9, 10, 13)}
_CTRL[127] = None

_SCI = re.compile(r"^[+-]?\d(?:\.\d+)?[eE][+-]?\d+$")
_MIXED_FRAC = re.compile(r"^([+-]?\d+)[\s\-](\d+)\s*/\s*(\d+)$")
_BARE_FRAC = re.compile(r"^([+-]?\d+)\s*/\s*(\d+)$")
_TRAILING_UNIT = re.compile(r"^([+-]?[\d,]*\.?\d+)\s*[a-zA-Z\"'°%/]+\.?$")
_ACCT_NEG = re.compile(r"^\(\s*([\d,]*\.?\d+)\s*\)$")


def clean_text(v):
    """Always-safe: strip control characters/NULL bytes and normalize unicode punctuation.
    Never changes the meaning of a value — only its encoding damage."""
    if v is None:
        return None
    s = str(v)
    s = unicodedata.normalize("NFKC", s)
    for a, b in _PUNCT.items():
        s = s.replace(a, b)
    return s.translate(_CTRL)


def looks_mangled(v):
    """Scientific notation that used to be an identifier — unrecoverable, must be refused."""
    return bool(v) and bool(_SCI.match(str(v).strip()))


def coerce_number(v):
    """→ (value, note) where value is a decimal string, or (None, reason) if it must not be
    guessed at. Only deterministic transformations."""
    if v is None:
        return None, None
    s = clean_text(v).strip()
    if not s:
        return None, None
    if _SCI.match(s):
        return None, "scientific notation — precision already lost, cannot recover"

    # An inch mark or unit suffix must come off BEFORE the fraction match, or the classic
    # casing OD 9-5/8" never parses.
    s2 = re.sub(r'\s*(?:"|\u2033|\u201d|\'\'|in\.?|inch(?:es)?|ft\.?|feet|m\.?)$', "", s,
                flags=re.I).strip()
    unit_note = " (unit removed)" if s2 != s else ""
    s = s2 or s

    m = _ACCT_NEG.match(s)
    if m:
        inner, note = coerce_number(m.group(1))
        return (f"-{inner}", "accounting negative") if inner else (None, note)

    m = _MIXED_FRAC.match(s)
    if m:
        whole, num, den = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if den == 0:
            return None, "division by zero"
        val = abs(whole) + num / den
        return (f"{-val:g}" if whole < 0 else f"{val:g}"), "mixed fraction" + unit_note

    m = _BARE_FRAC.match(s)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        if den == 0:
            return None, "division by zero"
        return f"{num / den:g}", "fraction" + unit_note

    m = _TRAILING_UNIT.match(s)
    if m:
        inner, _ = coerce_number(m.group(1))
        return (inner, "trailing unit removed") if inner else (None, None)

    t = s.replace(",", "").replace(" ", "")
    try:
        float(t)
        return (t, "thousands separator") if t != s else (s, None)
    except ValueError:
        return None, None                       # not a number — leave it, promote will NULL it


def plan(engine, stg_table, cmap, coltypes, limit=50000):
    """Work out what would change. → (fixes, refusals) without touching anything.

    fixes    — [{row_id, column, old, new, why}]
    refusals — [{row_id, column, value, why}]   things we will NOT guess at
    """
    from sqlalchemy import text
    cols = list(cmap)
    if not cols:
        return [], []
    sel = ", ".join(f"s.[{c}]" for c in cols)
    with engine.connect() as cx:
        rows = cx.execute(text(
            f"SELECT TOP {int(limit)} s._row_id, {sel} FROM {stg_table} s")).mappings().all()

    fixes, refuse = [], []
    for r in rows:
        for c in cols:
            raw = r.get(c)
            if raw is None:
                continue
            tgt = str(cmap[c]).lower()
            is_num = (coltypes.get(tgt) or "").lower() in _NUMERIC
            cleaned = clean_text(raw)
            if is_num:
                new, why = coerce_number(raw)
                if why and new is None:
                    refuse.append({"row_id": r["_row_id"], "column": c, "value": str(raw),
                                   "why": why})
                    continue
                if new is not None and new != str(raw).strip():
                    fixes.append({"row_id": r["_row_id"], "column": c, "old": str(raw),
                                  "new": new, "why": why or "normalized"})
                    continue
            if cleaned != str(raw):
                fixes.append({"row_id": r["_row_id"], "column": c, "old": repr(str(raw))[:40],
                              "new": cleaned, "why": "control chars / unicode punctuation"})
    return fixes, refuse


def apply(engine, stg_table, fixes):
    """Apply the planned fixes with ONE JOIN UPDATE per column — never row by row."""
    from sqlalchemy import text
    if not fixes:
        return 0
    by_col = {}
    for f in fixes:
        by_col.setdefault(f["column"], []).append(f)
    n = 0
    with engine.begin() as cx:
        for col, items in by_col.items():
            cx.execute(text("CREATE TABLE #fix (_row_id bigint, v nvarchar(4000))"))
            cx.execute(text("INSERT INTO #fix (_row_id, v) VALUES (:r, :v)"),
                       [{"r": i["row_id"], "v": i["new"]} for i in items])
            res = cx.execute(text(
                f"UPDATE s SET s.[{col}] = f.v FROM {stg_table} s "
                f"JOIN #fix f ON f._row_id = s._row_id"))
            n += res.rowcount or 0
            cx.execute(text("DROP TABLE #fix"))
    return n


# ═══════════════════════ date format detection ═══════════════════════
# 03/04/2021 is 3 April or 4 March depending on who exported it, and SQL Server decides by
# the session's DATEFORMAT — which has nothing to do with where the data came from. Getting
# it wrong is silent: every row loads, every date is real, and a third of them are wrong.
# So: infer the format from the COLUMN's own values, and where the column can't disambiguate
# itself, say so rather than pick.

_DMY_LIKE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$")
_ISO_LIKE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")


def detect_date_format(values):
    """→ (fmt, confidence, why) where fmt is 'ISO' | 'DMY' | 'MDY' | None.

    The evidence is arithmetic, not guesswork: if any first component exceeds 12 it cannot be
    a month, so the column is DMY. If any second component exceeds 12, it's MDY. If both
    happen the column is inconsistent. If neither happens, every value is ambiguous and we
    refuse to guess."""
    first_gt12 = second_gt12 = iso = ambiguous = total = 0
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        total += 1
        if _ISO_LIKE.match(s):
            iso += 1
            continue
        m = _DMY_LIKE.match(s)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12:
            first_gt12 += 1
        elif b > 12 and a <= 12:
            second_gt12 += 1
        elif a <= 12 and b <= 12:
            ambiguous += 1

    if not total:
        return None, "none", "no values"
    if iso and not (first_gt12 or second_gt12 or ambiguous):
        return "ISO", "certain", f"all {iso} value(s) are yyyy-mm-dd"
    if first_gt12 and second_gt12:
        return None, "conflict", (f"{first_gt12} value(s) can only be d/m and {second_gt12} "
                                  f"can only be m/d — the column holds BOTH formats")
    if first_gt12:
        return "DMY", "certain", (f"{first_gt12} value(s) have a first part > 12, so it can't "
                                  f"be the month")
    if second_gt12:
        return "MDY", "certain", (f"{second_gt12} value(s) have a second part > 12, so it "
                                  f"can't be the month")
    if ambiguous:
        return None, "ambiguous", (f"all {ambiguous} value(s) have both parts ≤ 12 — nothing "
                                   f"in the data says whether 03/04 is 3 Apr or 4 Mar")
    return ("ISO", "certain", f"{iso} ISO value(s)") if iso else (None, "none", "no dates")


def iso_from(v, fmt):
    """Rewrite one value to yyyy-mm-dd given a KNOWN format. Returns None if it can't."""
    if v is None or not fmt:
        return None
    s = str(v).strip()
    if _ISO_LIKE.match(s):
        return None                       # already unambiguous
    m = _DMY_LIKE.match(s)
    if not m:
        return None
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000 if y < 50 else 1900
    d, mo = (a, b) if fmt == "DMY" else (b, a)
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"

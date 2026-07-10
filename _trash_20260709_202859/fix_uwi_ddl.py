r"""
fix_uwi_ddl.py — regenerate the schema DDL with governed UWI-key columns set to
char(14) COLLATE SQL_Latin1_General_CP1_CI_AS (to match gold.uwi14, so joins seek
without CAST). ONLY governed tables are tightened; staging (stg.*, dv_stg_*),
export (dv_export, EXPORTED_WELLS), and raw masters (WELL_MASTER) stay wide so raw
document UWIs aren't truncated on ingest.

Reads/writes UTF-16 (the DDL's encoding). py fix_uwi_ddl.py
"""
import re, sys

SRC = "dataview_demo_07072026_ddl.sql"
OUT = "dataview_demo_07072026_ddl_uwi14.sql"
COLLATE = "COLLATE SQL_Latin1_General_CP1_CI_AS"
TARGET = f"[char](14) {COLLATE}"

# schemas/tables whose UWI columns must stay WIDE (raw / staging / export)
KEEP_WIDE_TABLE = re.compile(
    r'\[(stg|dbo)\]\.\[|\[dataview\]\.\[dv_stg_|\[dataview\]\.\[dv_export\]|'
    r'\[dbo\]\.\[EXPORTED_WELLS\]|\[well_ref\]\.\[WELL_MASTER\]', re.I)

s = open(SRC, encoding="utf-16").read()

# Split into CREATE TABLE blocks so we know which table each column belongs to.
# We rewrite a UWI column only when its owning CREATE TABLE is NOT keep-wide.
create_re = re.compile(r'CREATE TABLE (\[[^\]]+\]\.\[[^\]]+\])\(', re.I)
# column def we tighten: [uwi]/[UWI14]/[matched_uwi] as (n)varchar/char(N) [NULL|NOT NULL]
col_re = re.compile(
    r'(\[(?:uwi|uwi14|matched_uwi)\]\s+)\[(?:n?varchar|n?char)\]\s*\(\s*(?:\d+|max)\s*\)'
    r'(\s+(?:NOT\s+)?NULL)?', re.I)

# find table spans
spans = []
for m in create_re.finditer(s):
    tbl = m.group(1)
    spans.append((m.start(), tbl))
spans.append((len(s), None))

changed = 0
kept = 0
out_parts = []
prev = 0
for i in range(len(spans) - 1):
    start, tbl = spans[i]
    end = spans[i + 1][0]
    # emit text before this table's body untouched
    out_parts.append(s[prev:start])
    body = s[start:end]
    keep_wide = bool(KEEP_WIDE_TABLE.search(tbl))
    if keep_wide:
        kept += len(col_re.findall(body))
        out_parts.append(body)
    else:
        def repl(mm):
            global changed
            changed += 1
            nn = mm.group(2) or ""
            return f"{mm.group(1)}{TARGET}{nn}"
        out_parts.append(col_re.sub(repl, body))
    prev = end
out_parts.append(s[prev:])
s2 = "".join(out_parts)

open(OUT, "w", encoding="utf-16").write(s2)
print(f"governed UWI columns tightened to char(14): {changed}")
print(f"raw/staging/export UWI columns left wide  : {kept}")
print(f"wrote {OUT} (UTF-16)")

"""
patch_dateonly.py — write SPUD_DATE / RIG_RELEASE (and seismic SURVEY_DATE) as
date-only (mm/dd/yyyy), dropping any trailing time, so they stay short and never
overflow the 20-char date columns. Edits page_workbench._well_params /
_seis_params. Idempotent, .bak.  Run: py patch_dateonly.py
"""
import sys, ast
P = "page_workbench.py"
s = open(P, encoding="utf-8").read()
if "_date_only" in s:
    print("already patched"); sys.exit(0)

helper = (
    'def _date_only(v):\n'
    '    """Keep just the date part (drops any trailing time), so a mm/dd/yyyy\n'
    '    value stays ~10 chars and never overflows the 20-char date columns.\n'
    '    Preserves the source date format; only strips the time."""\n'
    '    if v is None:\n'
    '        return None\n'
    '    s = str(v).strip()\n'
    '    if not s:\n'
    '        return None\n'
    '    return s.replace("T", " ").split(" ", 1)[0][:20]\n'
    '\n\n')
anchor = "def _well_params(inv_id, fields):\n"
if anchor not in s:
    print("FAILED: _well_params not found."); sys.exit(1)
s = s.replace(anchor, helper + anchor, 1)

# use date-only for the date columns (well + seismic)
s = s.replace('"spud":   _trunc(fields.get("spud_date"), 20),',
              '"spud":   _date_only(fields.get("spud_date")),', 1)
s = s.replace('"rig":    _trunc(fields.get("rig_release"), 20),',
              '"rig":    _date_only(fields.get("rig_release")),', 1)
s = s.replace('"sd":       _trunc(fields.get("survey_date"), 20),',
              '"sd":       _date_only(fields.get("survey_date")),', 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: SPUD_DATE / RIG_RELEASE / SURVEY_DATE written date-only")

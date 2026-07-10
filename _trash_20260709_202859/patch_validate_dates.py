"""
patch_validate_dates.py — validate SPUD_DATE / RIG_RELEASE / SURVEY_DATE: keep
them (normalized to mm/dd/yyyy) only if they parse as a real date in a known
format; otherwise write NULL. Nulls out mis-parsed junk ('Wed', 'Fri', '',
over-long text). Edits page_workbench. Idempotent, .bak.  Run: py patch_validate_dates.py
"""
import sys, ast
P = "page_workbench.py"
s = open(P, encoding="utf-8").read()
if "_valid_date" in s:
    print("already patched"); sys.exit(0)

helper = (
    'def _valid_date(v):\n'
    '    """Return the date as mm/dd/yyyy if v parses as a real date in a known\n'
    '    format; else None. Nulls out mis-parsed junk (\'Wed\', \'Fri\', \'\', long text)."""\n'
    '    if v is None:\n'
    '        return None\n'
    '    s = str(v).strip()\n'
    '    if not s:\n'
    '        return None\n'
    '    from datetime import datetime as _dtm\n'
    '    cands = [s]\n'
    '    if " " in s:\n'
    '        cands.append(s.split(" ", 1)[0])      # drop a trailing time\n'
    '    fmts = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y",\n'
    '            "%m-%d-%Y", "%d/%m/%Y", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y",\n'
    '            "%B %d, %Y", "%d.%m.%Y", "%m.%d.%Y", "%Y%m%d", "%b-%d-%Y",\n'
    '            "%d-%B-%Y", "%m/%d/%Y %H:%M:%S")\n'
    '    for c in cands:\n'
    '        for f in fmts:\n'
    '            try:\n'
    '                return _dtm.strptime(c, f).strftime("%m/%d/%Y")\n'
    '            except ValueError:\n'
    '                continue\n'
    '    return None\n'
    '\n\n')
anchor = "def _well_params(inv_id, fields):\n"
if anchor not in s:
    print("FAILED: _well_params not found."); sys.exit(1)
s = s.replace(anchor, helper + anchor, 1)

# swap the date fields to the validator (handle either _date_only or _trunc form)
repls = [
    ('"spud":   _date_only(fields.get("spud_date")),',
     '"spud":   _valid_date(fields.get("spud_date")),'),
    ('"spud":   _trunc(fields.get("spud_date"), 20),',
     '"spud":   _valid_date(fields.get("spud_date")),'),
    ('"rig":    _date_only(fields.get("rig_release")),',
     '"rig":    _valid_date(fields.get("rig_release")),'),
    ('"rig":    _trunc(fields.get("rig_release"), 20),',
     '"rig":    _valid_date(fields.get("rig_release")),'),
    ('"sd":       _date_only(fields.get("survey_date")),',
     '"sd":       _valid_date(fields.get("survey_date")),'),
    ('"sd":       _trunc(fields.get("survey_date"), 20),',
     '"sd":       _valid_date(fields.get("survey_date")),'),
]
n = 0
for old, new in repls:
    if old in s:
        s = s.replace(old, new, 1); n += 1
if n < 3:
    print(f"WARNING: only {n} date field(s) swapped (expected 3).")

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched: dates validated (mm/dd/yyyy or NULL); {n} field(s) swapped")

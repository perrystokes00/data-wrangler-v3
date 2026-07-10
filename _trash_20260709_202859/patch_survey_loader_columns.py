r"""
patch_survey_loader_columns.py — fix survey stations loading with NULL md/incl/azim.

Root cause (confirmed from survey_loader.py source): the loader reads MD/INC/AZI from each
station dict correctly (real values), but files them under dict keys that DON'T match the
cat_well_dir_srvy_sta columns:
    station_md      -> should be  md
    inclination     -> should be  incl
    azimuth         -> should be  azim
    station_tvd     -> should be  tvd
    ns_deviation    -> should be  ns_offset
    ew_deviation    -> should be  ew_offset
    dogleg_severity -> should be  dls
capture() only writes keys that match column names, so the mismatched ones drop to NULL.
This renames the keys to the real column names. Values were always parsed; they just
landed under the wrong keys.

Function-scoped edit to the sta_rows.append block. .bak, idempotent, verifies parse.
py patch_survey_loader_columns.py
"""
import os, ast, sys
P = "survey_loader.py"
if not os.path.exists(P):
    P = os.path.join("modules", "survey_loader.py")
if not os.path.exists(P):
    sys.exit("survey_loader.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()

old = '''                "station_md":      _f(s.get("MD")),
                "inclination":     _f(s.get("INC")),
                "azimuth":         _f(s.get("AZI")),
                "station_tvd":     _f(s.get("TVD")),
                "ns_deviation":    _f(s.get("NS")),
                "ew_deviation":    _f(s.get("EW")),
                "dogleg_severity": _f(s.get("DLS")),'''

new = '''                "md":              _f(s.get("MD")),
                "incl":            _f(s.get("INC")),
                "azim":            _f(s.get("AZI")),
                "tvd":             _f(s.get("TVD")),
                "ns_offset":       _f(s.get("NS")),
                "ew_offset":       _f(s.get("EW")),
                "dls":             _f(s.get("DLS")),'''

if '"md":              _f(s.get("MD"))' in s:
    print("already patched"); sys.exit(0)
if old not in s:
    sys.exit("FAILED: sta_rows mapping block not found (file may differ — paste lines 175-192)")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak_srvycols", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: station keys renamed to match columns (md/incl/azim/tvd/ns_offset/ew_offset/dls)")

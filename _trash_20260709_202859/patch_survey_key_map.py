r"""
patch_survey_key_map.py — fix empty directional-survey stations (md/incl/azim all NULL).

Root cause: pdf_survey_catalog._parse_station_row emits station dicts keyed by CANONICAL
names (MD, INC, AZI, TVD, NS, EW, DLS, VSEC), but cat_well_dir_srvy_sta columns are
md/incl/azim/tvd/ns_offset/ew_offset/dls. The loader looks up the lowercase column names,
finds only the uppercase canonical keys, and writes NULLs. The VALUES parse fine — they're
just under the wrong keys.

Fix: in worker_core._load_directional, remap each station dict's canonical keys to the
loader's column names BEFORE handing rows to the loader. Adds both the canonical AND the
column-name keys (keeps back-compat), so whichever the loader reads, the value is present.

Function-scoped, .bak, idempotent, verifies parse. py patch_survey_key_map.py
"""
import os, ast, sys
P = "worker_core.py"
if not os.path.exists(P):
    P = os.path.join("modules", "worker_core.py")
if not os.path.exists(P):
    sys.exit("worker_core.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "_SURVEY_KEY_MAP" in s:
    print("already patched"); sys.exit(0)

anchor = '''def _load_directional(engine, dialect, well_info, rows, say):
    """Directional survey loader — CORRECTED path first (survey_loader, which
    writes cat_well_dir_srvy_hdr/_sta), falling back to legacy load_to_ppdm if
    the survey_loader refactor isn't deployed. Returns the loader's result dict.
    """'''

inject = '''# Canonical station keys emitted by pdf_survey_catalog._parse_station_row -> the
# cat_well_dir_srvy_sta column names the survey loader expects. Without this remap the
# stations load with NULL md/incl/azim (values parsed under MD/INC/AZI, loader reads
# md/incl/azim).
_SURVEY_KEY_MAP = {
    "MD": "md", "INC": "incl", "AZI": "azim", "TVD": "tvd",
    "NS": "ns_offset", "EW": "ew_offset", "DLS": "dls", "VSEC": "vsec",
}


def _remap_station_keys(rows):
    """Add lowercase column-name keys alongside the canonical keys so the loader
    finds the values whichever naming it uses."""
    out = []
    for st in (rows or []):
        if not isinstance(st, dict):
            out.append(st); continue
        m = dict(st)
        for canon, col in _SURVEY_KEY_MAP.items():
            if canon in st and col not in m:
                m[col] = st[canon]
        out.append(m)
    return out


def _load_directional(engine, dialect, well_info, rows, say):
    """Directional survey loader — CORRECTED path first (survey_loader, which
    writes cat_well_dir_srvy_hdr/_sta), falling back to legacy load_to_ppdm if
    the survey_loader refactor isn't deployed. Returns the loader's result dict.
    """
    rows = _remap_station_keys(rows)   # canonical MD/INC/AZI -> md/incl/azim columns'''

if anchor not in s:
    sys.exit("FAILED: _load_directional anchor not found")
s = s.replace(anchor, inject, 1)
ast.parse(s)
open(P + ".bak_srvymap", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: survey station keys remapped (MD/INC/AZI -> md/incl/azim) before load")

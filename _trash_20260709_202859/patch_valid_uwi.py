"""
patch_valid_uwi.py — skip LAS files whose UWI is missing or garbage. A UWI is
'valid' if its first 10 chars are digits forming a plausible API10 (2-digit
state code 01-62). Gates worker_core._do_las: invalid UWI -> skip the file
(no junk well). In place, .bak, idempotent.  Run: py patch_valid_uwi.py
"""
import sys, ast
P = "worker_core.py"
s = open(P, encoding="utf-8").read()
if "_valid_uwi" in s:
    print("already patched"); sys.exit(0)

helper = (
    'def _valid_uwi(uwi):\n'
    '    """UWI looks valid if its first 10 chars are digits forming a plausible\n'
    '    API10 (2-digit state code 01-62). Rejects blanks, FN_ fallbacks, garbage."""\n'
    '    if not uwi:\n'
    '        return False\n'
    '    d = "".join(ch for ch in str(uwi) if ch.isdigit())\n'
    '    if len(d) < 10:\n'
    '        return False\n'
    '    try:\n'
    '        return 1 <= int(d[:2]) <= 62      # API state codes: 01-50 states, 55-62 offshore\n'
    '    except ValueError:\n'
    '        return False\n\n\n')
anchor_fn = "def _do_las(engine, fpath, uwi, inv, say) -> FileResult:\n"
if anchor_fn not in s:
    print("FAILED: _do_las def not found."); sys.exit(1)
s = s.replace(anchor_fn, helper + anchor_fn, 1)

# gate right after the header-UWI override
old = ("    if _hdr_uwi:\n"
       "        uwi = _hdr_uwi      # header UWI wins — it's the real well identity\n")
new = old + (
    "\n"
    "    if not _valid_uwi(uwi):\n"
    "        say(f\"skip (invalid UWI {uwi!r}): {fpath}\")\n"
    "        res.status = \"skip\"\n"
    "        res.detail[\"note\"] = f\"invalid UWI: {uwi!r}\"\n"
    "        return res\n")
if old not in s:
    print("FAILED: _hdr_uwi override anchor not found."); sys.exit(1)
s = s.replace(old, new, 1)

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print("patched: _do_las skips files with invalid/garbage UWI")

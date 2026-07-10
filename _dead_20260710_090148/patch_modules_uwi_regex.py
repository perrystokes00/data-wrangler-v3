r"""
patch_modules_uwi_regex.py — the app imports modules\pdf_survey_catalog.py (15 refs) but
the 'API Number:' UWI regex fix landed on the ROOT copy. The two files are 99.9% identical
(only this one line differs). Port the broadened regex into the modules\ copy so the fix is
live. .bak, idempotent, verifies parse. py patch_modules_uwi_regex.py
"""
import os, ast, sys
P = os.path.join("modules", "pdf_survey_catalog.py")
if not os.path.exists(P):
    sys.exit("modules\\pdf_survey_catalog.py not found — run from the app root")
s = open(P, encoding="utf-8").read()

old = r"""        r'(?:UWI|API|API.?NUM|API.?NO)[:\s]+([0-9\-]{10,20})',"""
new = r"""        r'(?:UWI|API)(?:\s*(?:NUM(?:BER)?|NO|#|/\s*UWI|/\s*API))?\s*[:#]?\s+([0-9\-]{10,20})',"""

if new.strip() in s:
    print("already patched — modules copy has the broadened regex"); sys.exit(0)
if old not in s:
    sys.exit("FAILED: old regex not found in modules copy (unexpected — check manually)")
s = s.replace(old, new, 1)
ast.parse(s)
open(P + ".bak_uwirx", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: broadened UWI regex ('API Number:' etc.) now in the LIVE copy")
print("modules\\ and root copies of pdf_survey_catalog.py should now be identical.")
print("You can delete the root copy after confirming imports (or keep as a shim).")

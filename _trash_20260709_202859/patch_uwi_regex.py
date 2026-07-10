r"""
patch_uwi_regex.py — broaden the classifier's UWI regex so real-world label variants
resolve. Currently '(?:UWI|API|API.?NUM|API.?NO)[:\s]+...' misses 'API Number:' (matches
'API' then fails on ' Number:'). This adds NUMBER/NO/# variants and allows an optional
word between API and the colon.

Fixes files like Scout_Ticket ('API Number: 15007243240000'). Function-scoped edit to
INFO_PATTERNS. .bak, idempotent, verifies parse. py patch_uwi_regex.py
"""
import os, ast, sys, re
P = "pdf_survey_catalog.py"
if not os.path.exists(P):
    P = os.path.join("modules", "pdf_survey_catalog.py")
if not os.path.exists(P):
    sys.exit("pdf_survey_catalog.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()

old = r"""        r'(?:UWI|API|API.?NUM|API.?NO)[:\s]+([0-9\-]{10,20})',"""
new = r"""        r'(?:UWI|API)(?:\s*(?:NUM(?:BER)?|NO|#|/\s*UWI|/\s*API))?\s*[:#]?\s+([0-9\-]{10,20})',"""

if new.strip() in s:
    print("already patched"); sys.exit(0)
if old not in s:
    sys.exit("FAILED: uwi regex anchor not found (file may differ)")
s = s.replace(old, new, 1)

# quick self-test of the new regex against the known labels
test_rx = re.compile(r'(?:UWI|API)(?:\s*(?:NUM(?:BER)?|NO|#|/\s*UWI|/\s*API))?\s*[:#]?\s+([0-9\-]{10,20})', re.IGNORECASE)
cases = {
    "API Number: 15007243240000": "15007243240000",
    "UWI / API: 15007243240000": "15007243240000",
    "API / UWI: 15007243240000": "15007243240000",
    "UWI: 42-317-12345-00-00": "42-317-12345-00-00",
    "API NO: 15007243240000": "15007243240000",
}
print("regex self-test:")
allok = True
for txt, exp in cases.items():
    m = test_rx.search(txt)
    got = m.group(1) if m else None
    ok = got == exp
    allok &= ok
    print(f"  {'OK ' if ok else 'XX '} {txt!r} -> {got!r}")
if not allok:
    sys.exit("regex self-test FAILED — not writing")

ast.parse(s)
open(P + ".bak_uwirx", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"\npatched {P}: UWI regex now handles 'API Number:', 'API NO:', '#', etc.")

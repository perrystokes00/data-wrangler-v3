"""fix_scout_uwi.py — the Scout Ticket has a doubled UWI (1500724324000105007243240000)
from the position-fix tool inserting on top of the original. This finds the mangled
run of digits after the API label and replaces it with the single clean target. Reads
what's there, shows it, and (with --apply) writes a corrected copy.
  py fix_scout_uwi.py --file "C:\\...\\Scout_Ticket_PERMIAN_4H.pdf" --target 15007243240000 [--apply]"""
import sys, os, re
f = target = None; apply = "--apply" in sys.argv
if "--file" in sys.argv: f = sys.argv[sys.argv.index("--file")+1]
if "--target" in sys.argv: target = sys.argv[sys.argv.index("--target")+1]
if not f or not target:
    print("usage: --file <scout pdf> --target 15007243240000 [--apply]"); sys.exit()
import fitz, pdfplumber

# show current text around API
with pdfplumber.open(f) as pdf:
    t = pdf.pages[0].extract_text() or ""
print("=== current API/UWI line(s) ===")
for line in t.splitlines():
    if re.search(r'\b(API|UWI)\b', line, re.I):
        print("  " + line.strip()[:100])

# find the doubled/long digit run (14+ digits) near the label and any digit blob
doc = fitz.open(f)
fixed = False
for page in doc:
    txt = page.get_text()
    # any run of 15+ digits is the doubled UWI
    for m in re.finditer(r'\d{15,}', txt):
        bad = m.group(0)
        print(f"\n  found long digit run: {bad}  (len {len(bad)})")
        if apply:
            for inst in page.search_for(bad):
                page.add_redact_annot(inst, text=target, fontname="helv", fontsize=9)
            page.apply_redactions()
            fixed = True
if apply and fixed:
    out = os.path.join(os.path.dirname(f), "_fixed_" + os.path.basename(f))
    doc.save(out, garbage=4, deflate=True); doc.close()
    with pdfplumber.open(out) as v:
        vt = v.pages[0].extract_text() or ""
    ok = target in vt and not re.search(r'\d{15,}', vt)
    print(f"\n  wrote {out}")
    print(f"  verify: clean single target present = {ok}")
    print(f"  -> replace the original with this _fixed_ copy (or crawl it)")
elif not apply:
    doc.close()
    print("\n(preview) re-run with --apply to fix")
else:
    doc.close(); print("\n  no long digit run found — maybe already clean or different pattern")

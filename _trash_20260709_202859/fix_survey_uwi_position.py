r"""
fix_survey_uwi_position.py — for PDFs where the flattened UWI landed away from the label
(e.g. Survey_ANADARKO: 'Well Name: ANADARKO 1H UWI:' with nothing after), insert the
target UWI's text right AFTER the 'UWI:' / 'API:' label so the classifier regex resolves
it. Operates on the _flattened folder. Verifies with the classifier regex.

  py fix_survey_uwi_position.py --dir "..._flattened" --target 15007243240000 [--apply]
"""
import sys, os, glob, re
d = target = None; apply = "--apply" in sys.argv
if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
if "--target" in sys.argv: target = sys.argv[sys.argv.index("--target")+1]
if not d or not target:
    print("usage: --dir <_flattened folder> --target <uwi> [--apply]"); sys.exit()
import fitz, pdfplumber
RX = re.compile(r'(?:UWI|API|API.?NUM|API.?NO)[:\s]+([0-9\-]{10,20})', re.IGNORECASE)
LABELS = ["UWI / API:", "API / UWI:", "API Number:", "UWI:", "API:"]

for p in sorted(glob.glob(os.path.join(d,"*.pdf"))):
    with pdfplumber.open(p) as pdf:
        t = pdf.pages[0].extract_text() or ""
    if RX.search(t):
        print(f"  {os.path.basename(p)}: already resolves — skip")
        continue
    # needs fixing: find a label with nothing after it and insert the UWI there
    doc = fitz.open(p); done = False
    for page in doc:
        for lab in LABELS:
            rects = page.search_for(lab)
            if rects:
                r = rects[0]
                if apply:
                    # insert immediately to the right of the label
                    page.insert_text((r.x1 + 3, r.y1 - 2), " " + target,
                                     fontname="helv", fontsize=9)
                done = True; break
        if done: break
    if not done:
        print(f"  {os.path.basename(p)}: no label found"); doc.close(); continue
    print(f"  {os.path.basename(p)}: inserted {target} after label" + ("" if apply else " (preview)"))
    if apply:
        doc.save(p, incremental=False, garbage=4, deflate=True) if False else None
        outp = p  # overwrite in _flattened
        doc.save(outp + ".tmp", garbage=4, deflate=True); doc.close()
        os.replace(outp + ".tmp", outp)
        with pdfplumber.open(outp) as v:
            vt = v.pages[0].extract_text() or ""
        print(f"      verify regex now matches: {bool(RX.search(vt))}")
    else:
        doc.close()
if not apply:
    print("\n(preview) re-run with --apply")

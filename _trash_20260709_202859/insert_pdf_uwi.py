r"""
insert_pdf_uwi.py — the UWI VALUE was deleted from these PDFs (typewriter annotations
don't write to the text layer), leaving empty 'UWI / API:' / 'API Number:' labels. This
INSERTS the target UWI into the text layer right after that label, so the extractor reads
it. Verifies each output with pdfplumber.

Handles label variants: 'UWI / API:', 'API / UWI:', 'API Number:', 'UWI:', 'API:'.
Writes new files to _uwi_inserted; originals untouched.

  pip install pymupdf pdfplumber --break-system-packages
  py insert_pdf_uwi.py --dir "C:\\...\\sample_pdfs" --target 15-007-24324-00-00          # preview
  py insert_pdf_uwi.py --dir "C:\\...\\sample_pdfs" --target 15-007-24324-00-00 --apply
"""
import sys, os, re, glob

LABELS = ["UWI / API:", "API / UWI:", "API Number:", "API / UWI :",
          "UWI/API:", "API/UWI:", "UWI:", "API:"]

def main():
    d = target = None; apply = "--apply" in sys.argv
    if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
    if "--target" in sys.argv: target = sys.argv[sys.argv.index("--target")+1]
    if not d or not target:
        print("usage: --dir <folder> --target <UWI e.g. 15-007-24324-00-00> [--apply]"); return
    try:
        import fitz, pdfplumber
    except ImportError:
        print("pip install pymupdf pdfplumber --break-system-packages"); return

    out_dir = os.path.join(d, "_uwi_inserted")
    os.makedirs(out_dir, exist_ok=True)
    pdfs = sorted(glob.glob(os.path.join(d, "*.pdf")))
    print(f"{len(pdfs)} PDFs; target = {target}  {'(APPLY)' if apply else '(preview)'}\n")

    for p in pdfs:
        doc = fitz.open(p)
        placed = False
        already = False
        for page in doc:
            words = page.get_text()  # quick check: does it already have the target?
            if target.replace("-","") in words.replace("-",""):
                already = True; break
            # find a label instance on the page to anchor the insert
            for lab in LABELS:
                rects = page.search_for(lab)
                if rects:
                    r = rects[0]
                    # insert point: just to the right of the label text
                    x = r.x1 + 4
                    y = r.y1 - 1  # baseline-ish
                    if apply:
                        page.insert_text((x, y), " " + target,
                                         fontname="helv", fontsize=9)
                    placed = True
                    break
            if placed:
                break
        if already:
            print(f"  {os.path.basename(p)}: already has target UWI — skipped")
            doc.close(); continue
        if not placed:
            print(f"  {os.path.basename(p)}: no UWI/API label found to anchor insert "
                  f"(check the label text)")
            doc.close(); continue
        print(f"  {os.path.basename(p)}: insert '{target}' after UWI/API label"
              + ("" if apply else "  (preview)"))
        if apply:
            outp = os.path.join(out_dir, os.path.basename(p))
            doc.save(outp, garbage=4, deflate=True); doc.close()
            # verify extractable
            with pdfplumber.open(outp) as v:
                vt = v.pages[0].extract_text() or ""
            ok = target.replace("-","") in vt.replace("-","")
            print(f"      verify: target UWI now extractable = {ok}"
                  + ("" if ok else "  <-- insert didn't land in text layer"))
        else:
            doc.close()

    if apply:
        print(f"\nwrote to: {out_dir}\ncrawl THAT folder. Where verify=True, the extractor will read {target}.")
    else:
        print("\n(preview) re-run with --apply to insert + verify.")

if __name__ == "__main__":
    main()

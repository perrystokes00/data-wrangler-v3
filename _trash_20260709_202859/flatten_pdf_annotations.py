r"""
flatten_pdf_annotations.py — your typed UWIs are annotations (pymupdf sees them,
pdfplumber/the extractor does NOT). This bakes each annotation's text into the real page
text layer at the annotation's position, then removes the annotation — so pdfplumber
reads it. Verifies each output with pdfplumber.

Writes new files to _flattened; originals untouched.
  pip install pymupdf pdfplumber --break-system-packages
  py flatten_pdf_annotations.py --dir "C:\\...\\sample_pdfs" --target 15-007-24324-00-00          # preview
  py flatten_pdf_annotations.py --dir "C:\\...\\sample_pdfs" --target 15-007-24324-00-00 --apply
"""
import sys, os, glob

def main():
    d = target = None; apply = "--apply" in sys.argv
    if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
    if "--target" in sys.argv: target = sys.argv[sys.argv.index("--target")+1]
    if not d:
        print("usage: --dir <folder> [--target <uwi>] [--apply]"); return
    try:
        import fitz, pdfplumber
    except ImportError:
        print("pip install pymupdf pdfplumber --break-system-packages"); return
    tnorm = (target or "").replace("-","").replace(" ","")

    out_dir = os.path.join(d, "_flattened")
    os.makedirs(out_dir, exist_ok=True)
    pdfs = sorted(glob.glob(os.path.join(d, "*.pdf")))
    print(f"{len(pdfs)} PDFs  {'(APPLY)' if apply else '(preview)'}\n")

    for p in pdfs:
        doc = fitz.open(p)
        n_annots = 0
        baked = []
        for page in doc:
            annots = list(page.annots() or [])
            for a in annots:
                content = (a.info.get("content","") or "").strip()
                rect = a.rect
                if content:
                    n_annots += 1
                    baked.append(content)
                    if apply:
                        # write the annotation's text into the real page text layer,
                        # positioned at the annotation rectangle
                        page.insert_text((rect.x0, rect.y1 - 2), content,
                                         fontname="helv", fontsize=9)
                        page.delete_annot(a)
        if n_annots == 0:
            print(f"  {os.path.basename(p)}: no text annotations to flatten")
            doc.close(); continue
        print(f"  {os.path.basename(p)}: {n_annots} annotation(s) -> text layer: {baked}"
              + ("" if apply else "  (preview)"))
        if apply:
            outp = os.path.join(out_dir, os.path.basename(p))
            doc.save(outp, garbage=4, deflate=True); doc.close()
            with pdfplumber.open(outp) as v:
                vt = " ".join((pg.extract_text() or "") for pg in v.pages)
            ok = (tnorm in vt.replace("-","").replace(" ","")) if tnorm else True
            print(f"      verify: pdfplumber now sees target = {ok}"
                  + ("" if ok else "  <-- still not extractable"))
        else:
            doc.close()

    if apply:
        print(f"\nwrote to: {out_dir}\ncrawl THAT folder — the extractor (pdfplumber) will now read the UWI.")
    else:
        print("\n(preview) re-run with --apply to flatten + verify.")

if __name__ == "__main__":
    main()

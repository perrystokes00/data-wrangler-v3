r"""
substitute_pdf_uwi_v2.py — replace the UWI in the TEXT LAYER of test PDFs (not an overlay),
so pdfplumber/the extractor actually reads the new value. Then VERIFY by re-reading each
output with pdfplumber and confirming the new UWI is extractable.

Uses pymupdf redaction (removes old text glyphs, inserts new) — a true text-stream change.
Writes new files to a _uwi_substituted subfolder; originals untouched.

  pip install pymupdf pdfplumber --break-system-packages
  py substitute_pdf_uwi_v2.py --dir "C:\\...\\sample_pdfs" --target 15-007-24324-00-00          # preview
  py substitute_pdf_uwi_v2.py --dir "C:\\...\\sample_pdfs" --target 15-007-24324-00-00 --apply
"""
import sys, os, re, glob

def main():
    d = target = None; apply = "--apply" in sys.argv
    if "--dir" in sys.argv: d = sys.argv[sys.argv.index("--dir")+1]
    if "--target" in sys.argv: target = sys.argv[sys.argv.index("--target")+1]
    if not d or not target:
        print("usage: --dir <folder> --target <UWI e.g. 15-007-24324-00-00> [--apply]"); return
    try:
        import fitz  # pymupdf
    except ImportError:
        print("pip install pymupdf --break-system-packages"); return
    try:
        import pdfplumber
    except ImportError:
        print("pip install pdfplumber --break-system-packages"); return

    # match any api-shaped number (labelled or not), so we catch every occurrence
    API_RX = re.compile(r'\b\d{2}[- ]?\d{3}[- ]?\d{5}(?:[- ]?\d{2}[- ]?\d{2})?\b')
    out_dir = os.path.join(d, "_uwi_substituted")
    os.makedirs(out_dir, exist_ok=True)
    pdfs = sorted(glob.glob(os.path.join(d, "*.pdf")))
    print(f"{len(pdfs)} PDFs; target = {target}  {'(APPLY)' if apply else '(preview)'}\n")

    for p in pdfs:
        doc = fitz.open(p)
        replaced_any = False
        found = set()
        for page in doc:
            text = page.get_text()
            for old in set(API_RX.findall(text)):
                if old.replace(" ","").replace("-","") == target.replace(" ","").replace("-",""):
                    continue
                found.add(old)
                if apply:
                    for inst in page.search_for(old):
                        # redaction = real text-layer removal, then insert new text
                        page.add_redact_annot(inst, text=target, fontname="helv", fontsize=9)
                    replaced_any = True
            if apply and replaced_any:
                page.apply_redactions()
        if not found:
            print(f"  {os.path.basename(p)}: no api-shaped number in text layer "
                  f"(image-only? nothing to replace)")
            doc.close(); continue
        print(f"  {os.path.basename(p)}: {found} -> {target}" + ("" if apply else "  (preview)"))
        if apply:
            outp = os.path.join(out_dir, os.path.basename(p))
            doc.save(outp, garbage=4, deflate=True)
            doc.close()
            # VERIFY the new UWI is now extractable
            with pdfplumber.open(outp) as v:
                vt = v.pages[0].extract_text() or ""
            ok = target.replace("-","").replace(" ","") in vt.replace("-","").replace(" ","")
            print(f"      verify: new UWI extractable = {ok}"
                  + ("" if ok else "  <-- STILL NOT IN TEXT LAYER (font/encoding issue)"))
        else:
            doc.close()

    if apply:
        print(f"\nwrote to: {out_dir}\ncrawl THAT folder. If 'verify' was True, the extractor will read the new UWI.")
    else:
        print("\n(preview) re-run with --apply to write + verify.")

if __name__ == "__main__":
    main()

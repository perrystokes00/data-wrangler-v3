"""test_scout_synth_extract.py — does extract_scout_ticket hang or return on scout_synth?
Run it with a timeout-ish guard (just call it and time it). py test_scout_synth_extract.py --file "...pdf" """
import sys, os, time, traceback
f = None
if "--file" in sys.argv: f = sys.argv[sys.argv.index("--file")+1]
if not f:
    # find scout_synth in the flattened folder
    import glob
    for cand in glob.glob(r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs\_flattened\scout_synth*.pdf"):
        f = cand; break
print("file:", f)
if not f or not os.path.exists(f):
    print("scout_synth not found — pass --file"); sys.exit()
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP,"modules"))
try:
    from modules.pdf_survey_catalog import extract_scout_ticket, extended_classify_pdf
except Exception:
    from pdf_survey_catalog import extract_scout_ticket, extended_classify_pdf

print("calling extended_classify_pdf (timing)...")
t0=time.time()
try:
    cl = extended_classify_pdf(f)
    print(f"  classify done in {time.time()-t0:.1f}s: type={cl.get('report_type')} uwi={cl.get('uwi')}")
except Exception:
    print("  classify EXCEPTION:\n"+traceback.format_exc()[-800:])

print("calling extract_scout_ticket (timing)...")
t0=time.time()
try:
    sc = extract_scout_ticket(f)
    dt=time.time()-t0
    print(f"  extract done in {dt:.1f}s")
    print(f"  header WELL_NAME={sc.get('header',{}).get('WELL_NAME')!r}")
    for k in ("tops","dst","survey","completion"):
        v=sc.get(k); print(f"  {k}: {len(v) if isinstance(v,list) else v}")
    if dt>15: print("  ^^ SLOW — this is why extract looked stuck")
except Exception:
    print("  extract EXCEPTION:\n"+traceback.format_exc()[-800:])
print("\nIf this returns fast, the file is fine — the crawl just caught it mid-run.")
print("If it hangs here too, the scout grid/OCR path is the culprit on synthetic layout.")

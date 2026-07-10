"""diag_missing_loaders.py — why 4 files produced no detail: check (1) does load_rft import,
(2) is there a RT_DDR loader, (3) why did petro classify UNKNOWN. py diag_missing_loaders.py"""
import os, sys, traceback
OUT = r"C:\Bulk\reports\missing_loaders.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP,"modules"))

log("=== 1) does load_rft import? (RFT skips silently if not) ===")
try:
    from modules.pdf_db_loader import load_rft
    log("  load_rft: IMPORTS OK -> RFT should load")
except Exception as e:
    log(f"  load_rft: IMPORT FAILS -> {str(e)[:100]}")
    log("  -> this is why RFT_MDT produced no detail")

log("\n=== 2) is there a load_ddr / RT_DDR path? ===")
try:
    from modules.pdf_db_loader import load_ddr
    log("  load_ddr: exists in pdf_db_loader")
except Exception:
    log("  load_ddr: NOT in pdf_db_loader")
# check worker_core routing
wc = open(os.path.join(APP,"modules","worker_core.py") if os.path.exists(os.path.join(APP,"modules","worker_core.py")) else os.path.join(APP,"worker_core.py"), encoding="utf-8", errors="replace").read()
log(f"  worker_core has 'RT_DDR' routing branch: {'RT_DDR' in wc and 'elif' in wc[wc.find('RT_DDR')-40:wc.find('RT_DDR')] if 'RT_DDR' in wc else False}")
log(f"  worker_core references RT_DDR at all: {'RT_DDR' in wc}")

log("\n=== 3) why did Petrophysical classify UNKNOWN? run the classifier ===")
try:
    from modules.pdf_survey_catalog import extended_classify_pdf
    f = os.path.join(APP.replace('data_wrangler_v3',''),'training','test_crawl','sample_pdfs','_flattened','Petrophysical_Interpretation_WOLFCAMP_5H.pdf')
    if not os.path.exists(f):
        # try without _flattened
        f = f.replace('\\_flattened','')
    log(f"  file exists: {os.path.exists(f)}  ({f})")
    if os.path.exists(f):
        r = extended_classify_pdf(f)
        log(f"  classified as: {r.get('report_type')}  confidence: {r.get('confidence')}")
        log(f"  -> if UNKNOWN, the petro keyword patterns don't match this file's text")
except Exception as e:
    log(f"  classify err: {str(e)[:100]}")

log("\n=== VERDICT / fixes needed ===")
log("  RFT: if load_rft import fails -> fix the import/loader")
log("  DDR: no RT_DDR routing -> add a load_ddr branch in _do_pdf (or DDR is header-only)")
log("  PETRO: classified UNKNOWN -> classifier keyword patterns need the petro terms")
log("  SCOUT: doubled UWI -> re-flatten that one file cleanly")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

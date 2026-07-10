"""verify_fixed_scout.py — confirm the FIXED scout_synth.pdf (with | separators) parses
the header correctly BEFORE crawling. py verify_fixed_scout.py --file "...scout_synth.pdf" """
import sys, os
f = None
if "--file" in sys.argv: f = sys.argv[sys.argv.index("--file")+1]
if not f:
    import glob
    # prefer the one WITHOUT (1) — the fixed version
    cands = glob.glob(r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs\_flattened\scout_synth*.pdf")
    cands.sort(key=lambda p: ("(1)" in p, p))  # non-(1) first
    f = cands[0] if cands else None
print("file:", f)
if not f or not os.path.exists(f):
    print("not found — pass --file"); sys.exit()
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP,"modules"))
from pdf_survey_catalog import _scout_all_rows, _scout_parse_header, extract_scout_ticket, extended_classify_pdf

rows = _scout_all_rows(f)
print(f"\nfirst header rows:")
for i,r in enumerate(rows[:5]):
    print(f"  [{i}] {r}")
h = _scout_parse_header(rows)
print(f"\nparsed: WELL_NAME={h.get('WELL_NAME')!r} UWI={h.get('UWI')!r} API={h.get('API')!r}")
cl = extended_classify_pdf(f)
print(f"classify: type={cl.get('report_type')} uwi={cl.get('uwi')}")
ok = h.get('WELL_NAME') and (cl.get('uwi') or h.get('UWI'))
print(f"\n{'READY TO CRAWL — header + UWI resolve' if ok else 'STILL BROKEN — header not splitting'}")

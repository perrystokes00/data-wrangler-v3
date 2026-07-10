"""diag_scout_header.py — the synthetic scout extracts detail (tops/survey/etc) but header
WELL_NAME/UWI come back None. See what _scout_grid_rows produces for the header area vs
what _scout_parse_header expects (label row then value row, positionally zipped).
py diag_scout_header.py --file "...scout_synth.pdf" """
import sys, os
f = None
if "--file" in sys.argv: f = sys.argv[sys.argv.index("--file")+1]
if not f:
    import glob
    for cand in glob.glob(r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\sample_pdfs\_flattened\scout_synth*.pdf"):
        f=cand; break
print("file:", f)
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP,"modules"))
try:
    from modules.pdf_survey_catalog import _scout_all_rows, _scout_parse_header
except Exception:
    from pdf_survey_catalog import _scout_all_rows, _scout_parse_header

rows = _scout_all_rows(f)
print(f"\n_scout_grid_rows produced {len(rows)} rows. First 12:")
for i,r in enumerate(rows[:12]):
    print(f"  [{i}] {r}")

print("\n_scout_parse_header wants: label row containing both 'API' and 'WELL NAME',")
print("then the NEXT row's cells zipped positionally to [API, WELL_NAME, WELL_TYPE, STATUS].")
h = _scout_parse_header(rows)
print(f"\nparsed header: {h}")
print("\n=== DIAGNOSIS ===")
print("If the rows show 'API Well Name Well Type Status' as ONE combined cell instead of")
print("4 separate cells, the positional zip fails -> WELL_NAME/UWI stay None. The synthetic")
print("PDF needs the header cells spaced so the grid parser splits them into columns,")
print("OR the generator should emit the label/value rows the parser can split.")

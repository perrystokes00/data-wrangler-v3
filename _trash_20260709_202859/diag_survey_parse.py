"""diag_survey_parse.py — the dir-survey stations promote with NULL md/incl/azim. Is the
PARSE returning empty values, or is the LOADER mapping the wrong keys? Run extract_stations
on the actual PDF and dump what it returns. py diag_survey_parse.py --file "C:\\...\\Survey_CONTINENTAL_1H_Simple.pdf" """
import sys, os, glob, traceback, json
OUT = r"C:\Bulk\reports\survey_parse.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

# find a survey PDF
f=None
if "--file" in sys.argv: f=sys.argv[sys.argv.index("--file")+1]
else:
    for d in (r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl",):
        g=glob.glob(os.path.join(d,"**","Survey_*.pdf"),recursive=True)
        if g: f=g[0]; break
if not f or not os.path.exists(f):
    log("no survey PDF found — pass --file"); open(OUT,"w").write("\n".join(L)); raise SystemExit
log("file:", os.path.basename(f))

# import the extractor the same way worker_core does
try:
    try:
        from pdf_survey_catalog import extract_stations, RT_DIRECTIONAL, extended_classify_pdf
    except Exception:
        from modules.pdf_survey_catalog import extract_stations, RT_DIRECTIONAL, extended_classify_pdf
    log("imported pdf_survey_catalog OK")
except Exception:
    log("import failed:\n"+traceback.format_exc()); open(OUT,"w").write("\n".join(L)); raise SystemExit

# classify first (does it even see it as directional?)
try:
    cl = extended_classify_pdf(f)
    log("classify: " + str(cl if not hasattr(cl,'get') else {k:cl.get(k) for k in list(cl)[:8]}))
except Exception as e:
    log("classify err: "+str(e)[:80])

# run extract_stations and dump the raw output
log("\n=== extract_stations() raw output ===")
try:
    res = extract_stations(f)
    log("keys: " + str(list(res.keys()) if hasattr(res,'keys') else type(res)))
    stations = res.get("stations", []) if hasattr(res,'get') else []
    log("station count: " + str(len(stations)))
    log("\nfirst 3 station dicts (RAW keys+values):")
    for st in stations[:3]:
        log("  " + json.dumps(st, default=str))
    if stations:
        log("\nstation dict KEYS: " + str(list(stations[0].keys())))
        # which keys carry md/incl/azim-ish data?
        for k in stations[0].keys():
            vals = [s.get(k) for s in stations[:5]]
            log(f"    {k}: {vals}")
except Exception as e:
    log("extract_stations err:\n"+traceback.format_exc()[-600:])

log("\n=== VERDICT ===")
log("  If station dicts have md/incl/azim with REAL values -> parse OK, LOADER maps wrong")
log("  keys (survey_loader expects different names). If dicts are empty/null -> the PDF")
log("  table parse itself fails (column detection in extract_stations).")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

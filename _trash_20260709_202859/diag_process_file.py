"""diag_process_file.py — call worker_core.process_file EXACTLY as the parallel
capture worker (_capture_proc_one) does, to see if the regression is there vs in
_do_las (which we proved works). Also tests the extract_core._extract_fields for LAS
(the single-pass gate). writes to file.
  py diag_process_file.py --file "C:\\...\\17_031_10176_0000.las" """
import sys, os, glob, traceback
OUT = r"C:\Bulk\reports\process_file.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

f=None
if "--file" in sys.argv: f=sys.argv[sys.argv.index("--file")+1]
else:
    for d in (r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl\las_files",
              r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\test_crawl"):
        g=glob.glob(os.path.join(d,"**","*.las"),recursive=True)
        if g: f=g[0]; break
if not f or not os.path.exists(f):
    log("no LAS found, pass --file"); open(OUT,"w").write("\n".join(L)); raise SystemExit
log("file:", f)

# engine
from sqlalchemy import create_engine
url = "mssql+pyodbc://@localhost\\SQLEXPRESS/DataView_Demo?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&Encrypt=no"
eng = create_engine(url, fast_executemany=True)

# 1) test extract_core._extract_fields for LAS (the single-pass gate at line 768)
log("\n=== 1) extract_core._extract_fields on the LAS (single-pass gate) ===")
try:
    import extract_core
    fields = extract_core._extract_fields(f, ".las")
    log("   uwi:", repr(fields.get("uwi")))
    log("   well_name:", repr(fields.get("well_name")))
    log("   skip_reason:", repr(fields.get("skip_reason")))
except Exception as e:
    log("   extract_fields ERROR:", traceback.format_exc()[-500:])

# 2) call process_file EXACTLY as _capture_proc_one does
log("\n=== 2) worker_core.process_file (as the parallel capture worker calls it) ===")
try:
    import worker_core as wc
    rec = {"FILE_PATH": f, "FILE_EXT": ".las", "FILE_NAME": os.path.basename(f),
           "INVENTORY_ID": "DIAG_PF_TEST", "MATCHED_UWI": "", "uwi": ""}
    res = wc.process_file(eng, rec)
    log("   status:", getattr(res,"status",None))
    log("   rows_written:", getattr(res,"rows_written",None))
    log("   error:", getattr(res,"error",None))
    log("   detail:", getattr(res,"detail",None))
except Exception as e:
    log("   process_file ERROR:", traceback.format_exc()[-500:])

# 3) call process_file the single-pass way (with UWI from fields)
log("\n=== 3) process_file single-pass style (UWI passed from extract fields) ===")
try:
    import worker_core as wc
    rec = {"FILE_PATH": f, "FILE_EXT": ".las",
           "UWI": (fields.get("uwi") or ""), "MATCHED_UWI": (fields.get("uwi") or ""),
           "INVENTORY_ID": "DIAG_PF_TEST2"}
    res = wc.process_file(eng, rec)
    log("   status:", getattr(res,"status",None), "rows:", getattr(res,"rows_written",None),
        "detail:", getattr(res,"detail",None))
except Exception as e:
    log("   ERROR:", traceback.format_exc()[-400:])

open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

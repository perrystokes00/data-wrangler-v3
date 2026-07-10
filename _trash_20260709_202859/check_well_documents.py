"""check_well_documents.py — the map reads dataview.well_documents / v_well_documents for
'wells with documents'. Find its definition and whether LAS/SEG-Y wells appear in it.
py check_well_documents.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\well_documents.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== does well_documents (table) or v_well_documents (view) exist? ===")
for nm in ("well_documents","v_well_documents"):
    oid = one(f"SELECT OBJECT_ID('dataview.{nm}')")
    typ = one(f"SELECT type_desc FROM sys.objects WHERE object_id=OBJECT_ID('dataview.{nm}')")
    log(f"  dataview.{nm}: object_id={oid} type={typ}")

log("\n=== the VIEW definition (this is the source of doc_count/log_count/seismic_count) ===")
for nm in ("v_well_documents","well_documents"):
    d = one(f"SELECT OBJECT_DEFINITION(OBJECT_ID('dataview.{nm}'))")
    if d and not str(d).startswith("ERR") and d != "None":
        log(f"--- dataview.{nm} ---")
        for line in str(d).splitlines():
            log("  " + line.rstrip())
        break

log("\n=== do LAS wells appear in well_documents? (log_count) ===")
for u in ("17031100350000","38105100680000","42475100200000"):
    for nm in ("well_documents","v_well_documents"):
        r = one(f"SELECT doc_count FROM dataview.{nm} WHERE uwi=?", u)
        if not str(r).startswith("ERR"):
            log(f"  {nm}: uwi={u} doc_count={r}")
            break

log("\n=== counts feeding the view ===")
log("  dv_well_log rows:        " + str(one("SELECT COUNT(*) FROM dataview.dv_well_log")))
log("  dv_well_log distinct uwi:" + str(one("SELECT COUNT(DISTINCT uwi) FROM dataview.dv_well_log")))
log("  dv_seis_set rows:        " + str(one("SELECT COUNT(*) FROM dataview.dv_seis_set")))
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

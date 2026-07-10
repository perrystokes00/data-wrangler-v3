"""check_doc_promote.py — these PDF/xlsx/docx/xml docs have valid UWIs, extracted, but
didn't promote. Why? Check: (1) is the stored UWI actually mangled (sci-notation) or
just displayed that way, (2) is the well in dv_well (parent exists?), (3) did their
document data reach cat_* / dv_* at all. py check_doc_promote.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\doc_promote.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:35]}"

log("=== the document files: RAW stored MATCHED_UWI (is it mangled?) ===")
rows = c.execute("""SELECT FILE_NAME, FILE_EXT, MATCHED_UWI, CATALOG_READINESS, INVENTORY_ID
    FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE FILE_EXT IN ('.pdf','.xlsx','.docx','.xml','.shp')
      AND MATCHED_UWI IS NOT NULL AND LTRIM(RTRIM(MATCHED_UWI))<>''
    ORDER BY FILE_NAME""").fetchall()
NORM = "LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),?),'-',''),' ',''),'/','')))+'00000000000000',14)"
for r in rows:
    fn, ext, muwi, ready, inv = r
    # is the raw value in scientific notation / non-numeric?
    raw = str(muwi)
    mangled = "E+" in raw.upper() or "." in raw
    # normalized form
    norm = one(f"SELECT {NORM}", muwi)
    # is that well in dv_well?
    indv = one("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=?", norm) if norm else "?"
    log(f"  {fn}")
    log(f"      raw_uwi={raw!r} {'<-- MANGLED (sci-notation)' if mangled else ''}")
    log(f"      normalized={norm!r}  in_dv_well={indv}  readiness={ready}")

log("\n=== summary: how many have mangled UWIs? ===")
n_mangled = one("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE FILE_EXT IN ('.pdf','.xlsx','.docx','.xml','.shp')
      AND (MATCHED_UWI LIKE '%E+%' OR MATCHED_UWI LIKE '%.%')""")
log(f"  files with sci-notation/decimal in MATCHED_UWI: {n_mangled}")

log("\n=== are these wells in dv_well at all? (parent well existence) ===")
log("  dv_well total: " + str(one("SELECT COUNT(*) FROM dataview.dv_well")))
# sample a few normalized UWIs
for u in ("42461200000000","42317100000000","35101100000000"):
    log(f"    prefix {u[:8]}...: dv_well matches = " + str(one(f"SELECT COUNT(*) FROM dataview.dv_well WHERE LEFT(uwi,8)='{u[:8]}'")))

log("\n=== did their doc data land in cat_* (staged) or get held? ===")
for t in ("cat_well_formation_top","cat_well_dir_srvy_hdr","cat_prod_volume","cat_well_completion"):
    tot = one(f"SELECT COUNT(*) FROM file_catalog.{t}")
    held = one(f"SELECT COUNT(*) FROM file_catalog.{t} WHERE PROMOTED=0")
    log(f"  {t}: {tot} rows, {held} held (PROMOTED=0)")

log("\n=== VERDICT candidates ===")
log("  If raw_uwi shows E+ notation: the UWI was Excel-mangled at extract -> normalize")
log("    may produce a wrong 14-digit value that doesn't match any dv_well.")
log("  If normalized looks right but in_dv_well=0: parent well missing (these synthetic")
log("    wells aren't in gold / no LAS) -> promote correctly HOLDS the doc data.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

"""probe_backfill_sources.py — confirm what we can backfill MATCHED_UWI FROM.
Checks FILE_WELL_HEADER (las/lis/dlis) and FILE_SEIS_HEADER (segy) for a usable UWI
column, and how they join to GLOBAL_FILE_CATALOG (INVENTORY_ID). py probe_backfill_sources.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\backfill_sources.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
def cols(t):
    return [r[0] for r in c.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME=?", t).fetchall()]
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:40]}"

log("=== FILE_WELL_HEADER columns ===")
fwh = cols("FILE_WELL_HEADER")
log("  " + ", ".join(fwh))
log("  UWI populated: " + str(one("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER WHERE NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL")) if "UWI" in fwh else "  (no UWI col)")
if "UWI14" in fwh:
    log("  UWI14 populated: " + str(one("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER WHERE NULLIF(LTRIM(RTRIM(UWI14)),'') IS NOT NULL")))
log("  has INVENTORY_ID: " + str("INVENTORY_ID" in fwh))

log("\n=== FILE_SEIS_HEADER columns ===")
fsh = cols("FILE_SEIS_HEADER")
log("  " + ", ".join(fsh))
log("  has INVENTORY_ID: " + str("INVENTORY_ID" in fsh))
# seismic identity is survey name, not UWI — check what UWI-ish col exists
for cand in ("UWI","UWI14","MATCHED_UWI","SURVEY_NAME"):
    if cand in fsh:
        log(f"  {cand} populated: " + str(one(f"SELECT COUNT(*) FROM file_catalog.FILE_SEIS_HEADER WHERE NULLIF(LTRIM(RTRIM({cand})),'') IS NOT NULL")))

log("\n=== can we join GFC -> FILE_WELL_HEADER by INVENTORY_ID for the blank-UWI LAS? ===")
n = one("""SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG g
    JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID = g.INVENTORY_ID
    WHERE g.FILE_EXT IN ('.las','.lis','.dlis')
      AND NULLIF(LTRIM(RTRIM(g.MATCHED_UWI)),'') IS NULL
      AND NULLIF(LTRIM(RTRIM(h.UWI)),'') IS NOT NULL""")
log(f"  las/lis/dlis with blank MATCHED_UWI that HAVE a FILE_WELL_HEADER.UWI: {n}")

log("\n=== seismic: what does v_well_documents even use for seismic? (it needs a UWI) ===")
log("  NOTE: seismic files map to SURVEYS, not wells. The map's v_well_documents is")
log("  keyed on well UWI — seismic may belong on a SURVEY layer, not 'wells with docs'.")
log("  Confirm: do segy files have any per-well UWI, or only a survey name?")
log("  segy MATCHED_UWI populated: " + str(one("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.segy' AND NULLIF(LTRIM(RTRIM(MATCHED_UWI)),'') IS NOT NULL")))
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

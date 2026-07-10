"""check_lis_dlis.py — the LIS/DLIS files: what are their filenames, does
_uwi_from_filename resolve a UWI, and did they write cat_well / reach dv_well?
py check_lis_dlis.py"""
import pyodbc, os, re
OUT = r"C:\Bulk\reports\lis_dlis.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)

# replicate _uwi_from_filename to test each name
def uwi_from_filename(base):
    stem = os.path.splitext(base)[0]
    for _rx in (r"(\d{2}-\d{3}-\d{5}-\d{2}-\d{2})", r"(\d{2}_\d{3}_\d{5}_\d{2}_\d{2})",
                r"(\d{2}_\d{3}_\d{5}_\d{4})", r"(?<!\d)(\d{14})(?!\d)", r"(?<!\d)(\d{10})(?!\d)"):
        m = re.search(_rx, base)
        if m:
            d = re.sub(r"\D","",m.group(1))
            if len(d)>=10:
                u = d[:14] if len(d)>=14 else d.ljust(14,"0")
                if u!="0"*14: return u
    if re.fullmatch(r"[\d_\-]+", stem):
        d = re.sub(r"\D","",stem)
        if 10<=len(d)<=14:
            u = d[:14] if len(d)>=14 else d.ljust(14,"0")
            if u!="0"*14: return u
    return None

c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()

log("=== LIS / DLIS files: name -> filename-UWI -> in dv_well? ===")
rows = c.execute("""SELECT FILE_NAME, FILE_EXT, MATCHED_UWI, CATALOG_READINESS, INVENTORY_ID
    FROM file_catalog.GLOBAL_FILE_CATALOG
    WHERE FILE_EXT IN ('.lis','.dlis','.dlf','.dis') ORDER BY FILE_EXT, FILE_NAME""").fetchall()
NORM = "LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),?),'-',''),' ',''),'/','')))+'00000000000000',14)"
for r in rows:
    fn, ext, muwi, ready, inv = r
    fnuwi = uwi_from_filename(fn)
    # is this well in dv_well?
    indv = "?"
    if fnuwi:
        indv = "YES" if c.execute("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=?", fnuwi).fetchone()[0] else "no"
    # did it write cat_well?
    cw = c.execute("SELECT COUNT(*) FROM file_catalog.cat_well WHERE INVENTORY_ID=?", inv).fetchone()[0] if inv else 0
    log(f"  {ext} {fn}")
    log(f"      matched_uwi={muwi!r} filename_uwi={fnuwi!r} readiness={ready} cat_well={cw} dv_well={indv}")

log("\n=== summary counts ===")
for ext in (".lis",".dlis"):
    tot = c.execute("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT=?", ext).fetchone()[0]
    log(f"  {ext}: {tot} file(s)")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

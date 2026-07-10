"""prep_fcp_run.py — one-shot prep so the File Catalog Pipeline captures cleanly.
Verifies patches are deployed, clears stale CAPTURED_HASH, and reports the exact
capture-selection count BEFORE you run. If it says 'select ~400', the FCP run WILL
capture them. py prep_fcp_run.py"""
import os, pyodbc

def has(path, needle):
    try: return needle in open(path, encoding="utf-8", errors="ignore").read()
    except Exception: return False

print("=== patch deployment check ===")
pr = "pipeline_run.py" if os.path.exists("pipeline_run.py") else "modules/pipeline_run.py"
print(f"  pipeline_run.py cap_invs fix : {has(pr, '_sel_invs') and has(pr, '#cap_real')}")
print(f"  (if False -> run: py patch_cap_invs_real.py)")

c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]
T = "file_catalog.GLOBAL_FILE_CATALOG"

print("\n=== current state ===")
print("  .las in catalog              :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las'"))
print("  .las with CAPTURED_HASH set  :", f(f"SELECT COUNT(*) FROM {T} WHERE LOWER(FILE_EXT)='.las' AND CAPTURED_HASH IS NOT NULL"))
print("  cat_well rows                :", f("SELECT COUNT(*) FROM file_catalog.cat_well"))

# clear stale hash (files stamped but no cat_well row)
n = c.execute(f"""UPDATE g SET g.CAPTURED_HASH=NULL FROM {T} g
    WHERE LOWER(g.FILE_EXT)='.las' AND g.CAPTURED_HASH IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM file_catalog.cat_well w WHERE w.INVENTORY_ID=g.INVENTORY_ID)""").rowcount
print(f"\n  cleared stale CAPTURED_HASH on {n} .las file(s)")

sel = f(f"""SELECT COUNT(*) FROM {T} g WHERE LOWER(g.FILE_EXT)='.las'
    AND ISNULL(g.FLAG_DELETE,'N')<>'Y'
    AND ISNULL(g.CATALOG_READINESS,'') NOT IN ('SKIPPED','CATALOGED')
    AND g.DUPLICATE_GROUP IS NULL
    AND (g.CAPTURED_HASH IS NULL OR g.CAPTURED_HASH <> g.FILE_HASH)""")
print(f"\n  >>> capture will now select: {sel} .las file(s) <<<")
print("\nIf that number is ~400, run the File Catalog Pipeline NOW:")
print("  Inventory OFF · Capture ON · Promote ON · Apply ON · Multi-core ON")
print("  (Inventory OFF so it uses the existing catalog — don't re-scan/re-stamp)")

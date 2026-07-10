"""verify_report_fix.py — confirm the deployed page_workbench.py has the docs_done report
fix, and independently compute what the report SHOULD show for LAS (promoted via dv_*).
py verify_report_fix.py"""
import os, pyodbc
APP = r"C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\data_wrangler_v3"
p = os.path.join(APP, "page_workbench.py")
if not os.path.exists(p): p = os.path.join(APP, "pages", "page_workbench.py")
s = open(p, encoding="utf-8", errors="replace").read()
print("=== 1) is the docs_done fix in the deployed file? ===")
print("  docs_done present:", "docs_done AS" in s or "docs_done" in s)
print("  _docs credit present:", "_docs" in s)
print("  _doc_tabs present:", "_doc_tabs" in s)

print("\n=== 2) what the report SHOULD now show for LAS (independent check) ===")
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
# replicate the docs_done logic: LAS inventory ids that have data in dv_well_log
q = """
WITH docs_done AS (
  SELECT DISTINCT INVENTORY_ID FROM dataview.dv_well_log WHERE INVENTORY_ID IS NOT NULL
  UNION SELECT DISTINCT INVENTORY_ID FROM dataview.dv_well_log_curve WHERE INVENTORY_ID IS NOT NULL
)
SELECT COUNT(*) AS las_total,
  SUM(CASE WHEN dd.INVENTORY_ID IS NOT NULL THEN 1 ELSE 0 END) AS las_credited_promoted
FROM file_catalog.GLOBAL_FILE_CATALOG g
LEFT JOIN docs_done dd ON dd.INVENTORY_ID = g.INVENTORY_ID
WHERE g.FILE_EXT='.las'
"""
try:
    r = c.execute(q).fetchone()
    print(f"  LAS files: {r[0]}   would now show 'promoted': {r[1]}")
    print("  (expect 20 / 20 — the fix credits them via dv_well_log)")
except Exception as e:
    print("  check err:", str(e)[:100])

print("\n=== 3) verdict ===")
print("  If the fix is present (1) and the credit count is 20 (2), the ONLY thing left")
print("  is to RESTART STREAMLIT so it loads the patched page_workbench.py. The report")
print("  reads live code; an already-running Streamlit serves the old in-memory version.")

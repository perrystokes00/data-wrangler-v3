"""diag_promote_dirsrvy.py — the dir survey is staged (cat_well_dir_srvy_hdr=3,
_sta=78) but not promoted (dv_=0). Does promote's discover_tables even SEE these
tables, and what happens when we promote them? py diag_promote_dirsrvy.py"""
import pyodbc
conn = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
conn.autocommit = False
cur = conn.cursor()

# 1) does discover_tables include the dir_srvy pair?
try:
    from build_catalog_mirror import discover_tables
    tabs = list(discover_tables(cur))
    print("=== discover_tables returned", len(tabs), "dv tables ===")
    dir_tabs = [t for t in tabs if "dir_srvy" in str(t).lower()]
    top_tabs = [t for t in tabs if "formation_top" in str(t).lower()]
    print("   dir_srvy tables discovered :", dir_tabs or "NONE  <-- would explain no promote")
    print("   formation_top discovered   :", top_tabs or "NONE")
    print("   (sample of all:", tabs[:8], "...)")
except Exception as e:
    print("discover_tables failed:", e)

# 2) try promoting just this well and watch dir_srvy specifically
print("\n=== attempt promote_table for dv_well_dir_srvy_hdr / _sta (uwi-scoped) ===")
UWI = "42317123450000"
try:
    import promote_catalog as pc
    for dv in ("dv_well_dir_srvy_hdr", "dv_well_dir_srvy_sta", "dv_well_formation_top"):
        try:
            res = pc.promote_table(cur, dv, UWI, apply=True)
            print(f"   {dv}: {res}")
        except Exception as e:
            print(f"   {dv}: ERROR {str(e)[:120]}")
    conn.rollback()   # don't actually commit from the diagnostic
    print("\n(rolled back — this was a dry run; nothing committed)")
except Exception as e:
    conn.rollback()
    print("promote_table call failed:", str(e)[:160])
finally:
    conn.close()

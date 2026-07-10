"""diag_promoted_flag.py — promote only lifts cat_ rows WHERE PROMOTED=0. Are the
staged dir_srvy / tops rows stuck at PROMOTED=1, so promote skips them? py diag_promoted_flag.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

for tbl in ("cat_well_dir_srvy_hdr", "cat_well_dir_srvy_sta",
            "cat_well_formation_top", "cat_well_completion"):
    try:
        total = c.execute(f"SELECT COUNT(*) FROM file_catalog.{tbl}").fetchone()[0]
        # does the table even have a PROMOTED column?
        haspr = c.execute("""SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME=? AND COLUMN_NAME='PROMOTED'""", tbl).fetchone()[0]
        if haspr:
            p0 = c.execute(f"SELECT COUNT(*) FROM file_catalog.{tbl} WHERE PROMOTED=0").fetchone()[0]
            p1 = c.execute(f"SELECT COUNT(*) FROM file_catalog.{tbl} WHERE PROMOTED=1").fetchone()[0]
            pn = c.execute(f"SELECT COUNT(*) FROM file_catalog.{tbl} WHERE PROMOTED IS NULL").fetchone()[0]
            print(f"{tbl}: total={total}  PROMOTED=0:{p0}  =1:{p1}  NULL:{pn}")
            if total and p0 == 0:
                print(f"    ^^^ ALL rows PROMOTED<>0 -> promote SKIPS them (this is the bug)")
        else:
            print(f"{tbl}: total={total}  (no PROMOTED column!)")
    except Exception as e:
        print(f"{tbl}: {str(e)[:70]}")

"""LAS files are eligible (20 selected, real UWIs) but cat_well_log_curve=0.
Did the capture stage actually run? Check for ANY cat_ rows sourced from LAS,
and the most recent pipeline run's stage record."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== ANY cat_ rows sourced from a .las file? (join cat_ INVENTORY_ID → GFC) ===")
    for tbl in ["cat_well","cat_well_log","cat_well_log_curve"]:
        try:
            n = c.execute(text(f"""
                SELECT COUNT(*) FROM file_catalog.{tbl} m
                JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID=m.INVENTORY_ID
                WHERE LOWER(g.FILE_EXT)='.las'""")).scalar()
            print(f"   {tbl:22} from .las: {n}")
        except Exception as ex:
            print(f"   {tbl:22} err {str(ex)[:40]}")

    print("\n=== total cat_ rows (any source) ===")
    for tbl in ["cat_well","cat_well_log","cat_well_log_curve","cat_well_formation_top"]:
        n = c.execute(text(f"SELECT COUNT(*) FROM file_catalog.{tbl}")).scalar()
        print(f"   {tbl:26} {n}")

    print("\n=== most recent PIPELINE_RUN rows (did capture run?) ===")
    try:
        for r in c.execute(text("""
            SELECT TOP 3 * FROM (
              SELECT RUN_ID, STARTED_AT, STATUS
              FROM file_catalog.PIPELINE_RUN ORDER BY STARTED_AT DESC) q""")).fetchall():
            print(f"   run {r[0]} {r[1]} {r[2]}")
    except Exception as ex:
        print(f"   (no PIPELINE_RUN table or err: {str(ex)[:50]})")

    print("\n=== what set MATCHED_UWI+hx=Y on the LAS files? PROC_STATUS tells us ===")
    for ps, n in c.execute(text("""
        SELECT COALESCE(PROC_STATUS,'(null)'), COUNT(*)
        FROM file_catalog.GLOBAL_FILE_CATALOG WHERE LOWER(FILE_EXT)='.las'
        GROUP BY PROC_STATUS""")).fetchall():
        print(f"   PROC_STATUS={ps}: {n}  (done=pool ran; null=pool didn't)")

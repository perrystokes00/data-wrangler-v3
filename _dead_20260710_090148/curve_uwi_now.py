"""The promote said 146 curves moved, but eligibility still shows 6 UWIs, 0 in
dv_well, all PROMOTED=0. Let's see the ACTUAL current UWI values and whether
they're real or still FN_, and reconcile with dv_well."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== the distinct UWIs on cat_well_log_curve RIGHT NOW ===")
    for (u,) in c.execute(text("""
        SELECT DISTINCT UWI FROM file_catalog.cat_well_log_curve
        WHERE NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL""")).fetchall():
        indv = c.execute(text("SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=:u"),
                         {"u": u}).scalar()
        kind = "FN_ (still bad)" if str(u).startswith("FN_") else "real"
        print(f"   '{u}'  [{kind}]  in dv_well: {indv}")

    print("\n=== cat_well_log UWIs (the headers) ===")
    for (u,) in c.execute(text("""
        SELECT DISTINCT UWI FROM file_catalog.cat_well_log
        WHERE NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL""")).fetchall():
        kind = "FN_ (bad)" if str(u).startswith("FN_") else "real"
        print(f"   '{u}'  [{kind}]")

    print("\n=== PROMOTED flag on cat_well_log_curve ===")
    for p, n in c.execute(text("""
        SELECT COALESCE(CAST(PROMOTED AS INT),-1), COUNT(*)
        FROM file_catalog.cat_well_log_curve GROUP BY PROMOTED""")).fetchall():
        print(f"   PROMOTED={p}: {n}")

    print("\n=== sample dv_well UWIs (to compare format) ===")
    for (u,) in c.execute(text(
        "SELECT TOP 5 uwi FROM dataview.dv_well WHERE uwi IS NOT NULL")).fetchall():
        print(f"   dv_well: '{u}'")

    print("\n=== did dv_well_log / dv_well_log_curve actually get rows? ===")
    for sch, tbl in [("dataview","dv_well_log"),("dataview","dv_well_log_curve")]:
        try:
            n = c.execute(text(f"SELECT COUNT(*) FROM {sch}.{tbl}")).scalar()
            print(f"   {sch}.{tbl}: {n}")
        except Exception as ex:
            print(f"   {sch}.{tbl}: err {str(ex)[:50]}")

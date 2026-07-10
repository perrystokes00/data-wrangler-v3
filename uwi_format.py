"""The curves are eligible but their 6 UWIs match 0 rows in dv_well. Is it a
format mismatch? Show the actual UWI values on both sides."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== the 6 distinct UWIs on cat_well_log_curve ===")
    for (u,) in c.execute(text("""
        SELECT DISTINCT UWI FROM file_catalog.cat_well_log_curve
        WHERE NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL""")).fetchall():
        print(f"   curve UWI: '{u}'  (len {len(u or '')})")

    print("\n=== sample UWIs in dv_well ===")
    for (u,) in c.execute(text(
        "SELECT TOP 8 uwi FROM dataview.dv_well WHERE uwi IS NOT NULL")).fetchall():
        print(f"   dv_well uwi: '{u}'  (len {len(u or '')})")

    print("\n=== cat_well (the log HEADER) UWIs — do THESE match dv_well? ===")
    for (u,) in c.execute(text("""
        SELECT DISTINCT UWI FROM file_catalog.cat_well_log
        WHERE NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL""")).fetchall():
        indv = c.execute(text(
            "SELECT COUNT(*) FROM dataview.dv_well WHERE uwi=:u"),
            {"u": u}).scalar()
        print(f"   cat_well_log UWI: '{u}'  in dv_well: {indv}")

    # are the LAS wells even in cat_well (the main well mirror that feeds dv_well)?
    print("\n=== are the curve UWIs present in cat_well (main well mirror)? ===")
    r = c.execute(text("""
        SELECT COUNT(DISTINCT clc.UWI) tot,
               SUM(CASE WHEN cw.UWI IS NOT NULL THEN 1 ELSE 0 END) in_catwell
        FROM (SELECT DISTINCT UWI FROM file_catalog.cat_well_log_curve
              WHERE NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL) clc
        LEFT JOIN (SELECT DISTINCT UWI FROM file_catalog.cat_well) cw
               ON cw.UWI = clc.UWI""")).fetchone()
    print(f"   curve UWIs: {r[0]}, in cat_well: {r[1]}")

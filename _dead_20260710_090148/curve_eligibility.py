"""Why does promote see 0 eligible cat_well_log_curve rows when 1,086 exist?
Check PROMOTED flag and UWI presence — the two things eligibility gates on."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    for tbl in ["cat_well_log", "cat_well_log_curve"]:
        print(f"=== {tbl} ===")
        n = c.execute(text(f"SELECT COUNT(*) FROM file_catalog.{tbl}")).scalar()
        print(f"  total rows: {n}")
        try:
            prom = c.execute(text(
                f"SELECT COALESCE(CAST(PROMOTED AS INT),-1) p, COUNT(*) n "
                f"FROM file_catalog.{tbl} GROUP BY PROMOTED")).fetchall()
            for p, cnt in prom:
                lbl = {0:"PROMOTED=0 (eligible)",1:"PROMOTED=1 (already done)",
                       -1:"PROMOTED=NULL"}.get(p, f"PROMOTED={p}")
                print(f"    {lbl}: {cnt}")
        except Exception as ex:
            print(f"    PROMOTED check err: {ex}")
        try:
            uwi = c.execute(text(
                f"SELECT SUM(CASE WHEN NULLIF(LTRIM(RTRIM(UWI)),'') IS NULL "
                f"THEN 1 ELSE 0 END) blank, COUNT(*) tot "
                f"FROM file_catalog.{tbl}")).fetchone()
            print(f"    blank UWI: {uwi[0]} of {uwi[1]}")
        except Exception as ex:
            print(f"    UWI check err: {ex}")
        # how many would be eligible by the promote gate (PROMOTED=0)
        try:
            elig = c.execute(text(
                f"SELECT COUNT(*) FROM file_catalog.{tbl} WHERE PROMOTED=0")).scalar()
            print(f"    >>> eligible (PROMOTED=0): {elig}")
        except Exception as ex:
            print(f"    eligible check err: {ex}")
        print()

    # does dv_well have the UWIs these curves reference?
    print("=== do the curve UWIs exist in dv_well? ===")
    try:
        r = c.execute(text("""
            SELECT COUNT(DISTINCT clc.UWI) total_uwi,
                   SUM(CASE WHEN w.uwi IS NOT NULL THEN 1 ELSE 0 END) in_dvwell
            FROM (SELECT DISTINCT UWI FROM file_catalog.cat_well_log_curve
                  WHERE NULLIF(LTRIM(RTRIM(UWI)),'') IS NOT NULL) clc
            LEFT JOIN dataview.dv_well w ON w.uwi = clc.UWI""")).fetchone()
        print(f"  distinct curve UWIs: {r[0]}, of those in dv_well: {r[1]}")
    except Exception as ex:
        print(f"  err: {ex}")

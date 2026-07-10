"""Confirm Model A: surveys (parent) with their volumes (child) grouped
correctly. Shows the multi-volume surveys and the survey/line/geom totals."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as con:
    con.execute(text("SET QUOTED_IDENTIFIER ON"))
    surveys = con.execute(text("SELECT COUNT(*) FROM dataview.dv_seis_set")).scalar()
    lines   = con.execute(text("SELECT COUNT(*) FROM dataview.dv_seis_line")).scalar()
    withgeo = con.execute(text("SELECT COUNT(*) FROM dataview.dv_seis_set WHERE geog IS NOT NULL")).scalar()
    orphans = con.execute(text("""
        SELECT COUNT(*) FROM dataview.dv_seis_line l
        LEFT JOIN dataview.dv_seis_set s ON s.seis_set_id = l.seis_set_id
        WHERE s.seis_set_id IS NULL""")).scalar()
    print(f"surveys (dv_seis_set) : {surveys}")
    print(f"  with geometry       : {withgeo}")
    print(f"lines   (dv_seis_line): {lines}")
    print(f"orphan lines (no parent): {orphans}")
    print()
    print("=== surveys with the most volumes (the ones that were duplicated before) ===")
    rows = con.execute(text("""
        SELECT ss.seis_set_name, COUNT(l.line_id) AS vols
        FROM dataview.dv_seis_set ss
        JOIN dataview.dv_seis_line l ON l.seis_set_id = ss.seis_set_id
        GROUP BY ss.seis_set_name
        HAVING COUNT(l.line_id) > 1
        ORDER BY COUNT(l.line_id) DESC""")).fetchall()
    for nm, v in rows:
        print(f"   {v:>3} volumes  {nm}")
    if not rows:
        print("   (no multi-volume surveys — every survey has exactly one file)")

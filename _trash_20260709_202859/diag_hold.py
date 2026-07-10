"""diag_hold.py — why curves are held even after seeding. Checks ref rows landed,
compares codes exactly (case/space), and shows the promote gate's own view."""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
f = lambda q: c.execute(q).fetchone()[0]

print("dv_r_uom rows   :", f("SELECT COUNT(*) FROM dataview.dv_r_uom"))
print("dv_r_source rows:", f("SELECT COUNT(*) FROM dataview.dv_r_source"))
print("dv_r_source values:", [r[0] for r in c.execute("SELECT source FROM dataview.dv_r_source").fetchall()])
print("dv_r_uom sample   :", [r[0] for r in c.execute("SELECT TOP 20 uom_code FROM dataview.dv_r_uom").fetchall()])

print("\n-- exact-match test: curve codes that DON'T find a uom row --")
for r in c.execute("""
    SELECT DISTINCT lc.curve_unit
    FROM file_catalog.cat_well_log_curve lc
    WHERE lc.curve_unit IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM dataview.dv_r_uom u WHERE u.uom_code = lc.curve_unit)
""").fetchall():
    print("   curve_unit no-match:", repr(r[0]))
for r in c.execute("""
    SELECT DISTINCT lc.depth_ouom
    FROM file_catalog.cat_well_log_curve lc
    WHERE lc.depth_ouom IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM dataview.dv_r_uom u WHERE u.uom_code = lc.depth_ouom)
""").fetchall():
    print("   depth_ouom no-match:", repr(r[0]))
for r in c.execute("""
    SELECT DISTINCT lc.source
    FROM file_catalog.cat_well_log_curve lc
    WHERE lc.source IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM dataview.dv_r_source s WHERE s.source = lc.source)
""").fetchall():
    print("   source no-match:", repr(r[0]))

print("\n-- are the curve rows even unpromoted? --")
print("cat_well_log_curve total     :", f("SELECT COUNT(*) FROM file_catalog.cat_well_log_curve"))
print("  PROMOTED=1                 :", f("SELECT COUNT(*) FROM file_catalog.cat_well_log_curve WHERE PROMOTED=1"))
print("  PROMOTED=0/null            :", f("SELECT COUNT(*) FROM file_catalog.cat_well_log_curve WHERE ISNULL(PROMOTED,0)=0"))
print("  with a UWI in dv_well      :", f("""SELECT COUNT(*) FROM file_catalog.cat_well_log_curve lc
       WHERE EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi = lc.uwi)"""))

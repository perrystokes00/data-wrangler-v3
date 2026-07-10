"""h3_spread.py — how spread out are the wells, and do they aggregate into H3
cells? Run AFTER run_h3.py populates h3_r4..h3_r7.  py h3_spread.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()

r = cur.execute(
    "SELECT MIN(surface_latitude), MAX(surface_latitude), "
    "MIN(surface_longitude), MAX(surface_longitude), COUNT(*) "
    "FROM dataview.dv_well "
    "WHERE surface_latitude IS NOT NULL AND surface_longitude IS NOT NULL").fetchone()
print(f"bounding box: lat {r[0]:.3f}..{r[1]:.3f}  lon {r[2]:.3f}..{r[3]:.3f}")
print(f"wells with coords: {r[4]:,}\n")

print("resolution   cells   wells   avg wells/cell   busiest cell")
for col in ("h3_r4", "h3_r5", "h3_r6", "h3_r7"):
    cells = cur.execute(f"SELECT COUNT(DISTINCT {col}) FROM dataview.dv_well "
                        f"WHERE {col} IS NOT NULL").fetchone()[0]
    wells = cur.execute(f"SELECT COUNT(*) FROM dataview.dv_well "
                        f"WHERE {col} IS NOT NULL").fetchone()[0]
    if not cells:
        print(f"  {col}:  (not populated — run run_h3.py first)"); continue
    busiest = cur.execute(f"SELECT MAX(n) FROM (SELECT COUNT(*) n FROM dataview.dv_well "
                          f"WHERE {col} IS NOT NULL GROUP BY {col}) x").fetchone()[0]
    print(f"  {col:6}   {cells:6,}  {wells:6,}   {wells/cells:6.1f}          {busiest:,}")

print("\nRead: avg ~1 wells/cell = points spread out (use coarse res for density);")
print("      avg >> 1 = wells cluster (fine res shows structure).")

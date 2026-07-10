"""run_promote_now.py — run promote, write results to a file (paste has been
dropping console output). Reads back at the end. py run_promote_now.py
Then upload C:\Bulk\reports\promote_result.txt or open it in notepad."""
import pyodbc, io, os

OUT = r"C:\Bulk\reports\promote_result.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
buf = io.StringIO()
def log(*a):
    line = " ".join(str(x) for x in a)
    print(line); buf.write(line + "\n")

conn = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
conn.autocommit = False
cur = conn.cursor()

def cnt(schema, tbl, uwicol="uwi"):
    try: return cur.execute(f"SELECT COUNT(*) FROM {schema}.{tbl} WHERE {uwicol}='42317123450000'").fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:30]}"

log("BEFORE promote (ANADARKO 42317123450000):")
log("  dv_well_dir_srvy_hdr :", cnt("dataview","dv_well_dir_srvy_hdr"))
log("  dv_well_dir_srvy_sta :", cnt("dataview","dv_well_dir_srvy_sta"))
log("  dv_well_formation_top:", cnt("dataview","dv_well_formation_top"))
log("  dv_well_completion   :", cnt("dataview","dv_well_completion"))

log("\nrunning promote...\n")
try:
    import promote_catalog as pc
    pc.run_promote(cur, uwi=None, apply=True, log=log)
    conn.commit()
    log("\n=== committed ===")
except Exception as e:
    conn.rollback()
    import traceback
    log("promote failed, rolled back:", e)
    log(traceback.format_exc()[-600:])
    open(OUT,"w",encoding="utf-8").write(buf.getvalue())
    raise SystemExit

log("\nAFTER promote (ANADARKO 42317123450000):")
log("  dv_well_dir_srvy_hdr :", cnt("dataview","dv_well_dir_srvy_hdr"))
log("  dv_well_dir_srvy_sta :", cnt("dataview","dv_well_dir_srvy_sta"))
log("  dv_well_formation_top:", cnt("dataview","dv_well_formation_top"))
log("  dv_well_completion   :", cnt("dataview","dv_well_completion"))
conn.close()

open(OUT,"w",encoding="utf-8").write(buf.getvalue())
print("\n\n>>> results also written to", OUT)
print(">>> open that file in notepad, or upload it here")

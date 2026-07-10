"""probe_scan_write.py — decisive test: write a probe row to DataView_Demo's
GLOBAL_FILE_CATALOG with SCAN_DATE=now, read it back, then delete it. Proves whether
writes to THIS db are visible to these reads (rules out db/read mismatch), and confirms
the table accepts a fresh SCAN_DATE. py probe_scan_write.py"""
import pyodbc, os, datetime
OUT = r"C:\Bulk\reports\probe_scan.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
conn = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
c = conn.cursor()
def one(q,*a):
    try: return c.execute(q,*a).fetchone()[0]
    except Exception as e: return f"ERR {str(e)[:45]}"

log("connected DB: " + str(one("SELECT DB_NAME()")))
now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
log("writing probe row with SCAN_DATE=" + now)

probe_id = "PROBE_" + datetime.datetime.utcnow().strftime("%H%M%S")
try:
    c.execute("""INSERT INTO file_catalog.GLOBAL_FILE_CATALOG
        (INVENTORY_ID, FILE_PATH, FILE_NAME, FILE_EXT, SCAN_DATE, ROW_CREATED_DATE, ROW_CHANGED_DATE)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        probe_id, "C:\\__probe__\\probe.txt", "probe.txt", ".txt", now, now, now)
    conn.commit()
    log("insert committed.")
except Exception as e:
    log("INSERT failed: " + str(e)[:150])
    log(" -> if this fails, the table has NOT NULL cols we skipped; tell me and I'll adjust.")

# read it back
rb = one("SELECT SCAN_DATE FROM file_catalog.GLOBAL_FILE_CATALOG WHERE INVENTORY_ID=?", probe_id)
log("read back SCAN_DATE: " + str(rb))
mx = one("SELECT MAX(TRY_CAST(SCAN_DATE AS DATETIME2)) FROM file_catalog.GLOBAL_FILE_CATALOG")
log("MAX SCAN_DATE now:   " + str(mx))

# clean up
try:
    c.execute("DELETE FROM file_catalog.GLOBAL_FILE_CATALOG WHERE INVENTORY_ID=?", probe_id)
    conn.commit()
    log("probe row deleted.")
except Exception as e:
    log("cleanup err: " + str(e)[:60])

log("\n=== VERDICT ===")
log("  If read-back shows the fresh time AND MAX jumped to now: writes+reads agree on")
log("  DataView_Demo. So the scan simply didn't run against this DB today -> re-run the")
log("  Phase-1 scan and re-check. If MAX did NOT jump: something else is writing/reading")
log("  a different place than expected.")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n".join(L)); print("\n>>> written to",OUT)

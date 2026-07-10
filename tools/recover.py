"""recover.py — after a hung run: show/kill blocking DB sessions and reset stuck
files to pending. py recover.py           (diagnose)
                   py recover.py --kill    (kill blockers + reset stuck)"""
import sys, pyodbc
CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
cur = pyodbc.connect(CONN, autocommit=True).cursor()

# blocking / open transactions from app or python sessions
rows = cur.execute("""
    SELECT s.session_id, s.login_name, s.host_name, s.program_name,
           s.status, r.blocking_session_id,
           DB_NAME(r.database_id) db, r.wait_type
    FROM sys.dm_exec_sessions s
    LEFT JOIN sys.dm_exec_requests r ON r.session_id = s.session_id
    WHERE s.is_user_process = 1 AND s.session_id <> @@SPID
      AND (r.blocking_session_id > 0 OR s.open_transaction_count > 0
           OR s.program_name LIKE '%python%' OR s.program_name LIKE '%streamlit%')
""").fetchall()
if rows:
    print("active app/python sessions (possible blockers):")
    for r in rows:
        print(f"  spid {r.session_id} · {r.status} · blocked_by={r.blocking_session_id} "
              f"· {r.program_name} · wait={r.wait_type}")
else:
    print("no blocking / open-transaction app sessions found.")

if "--kill" in sys.argv:
    for r in rows:
        try:
            cur.execute(f"KILL {r.session_id}")
            print(f"  killed spid {r.session_id}")
        except Exception as e:
            print(f"  spid {r.session_id}: {e}")
    n = cur.execute(
        "UPDATE file_catalog.GLOBAL_FILE_CATALOG "
        "SET HEADER_EXTRACTED='N', CATALOG_READINESS=NULL, ROW_CHANGED_DATE=GETUTCDATE() "
        "WHERE HEADER_EXTRACTED='Y' AND INVENTORY_ID NOT IN "
        "(SELECT INVENTORY_ID FROM file_catalog.cat_well WHERE INVENTORY_ID IS NOT NULL)"
    ).rowcount
    print(f"reset {n} stuck file(s) to pending")
    print("\nsafe to restart the app now.")
else:
    print("\n--kill to kill those sessions + reset stuck files.")

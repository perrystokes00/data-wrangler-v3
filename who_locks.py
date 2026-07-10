"""who_locks.py — find what's holding locks / blocking (the 1222 timeout).
  py who_locks.py            # show active requests, blockers, open transactions
  py who_locks.py --kill 57  # KILL session 57 (the blocker)
"""
import sys, pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = c.cursor()

if "--kill" in sys.argv:
    spid = sys.argv[sys.argv.index("--kill") + 1]
    cur.execute("KILL " + str(int(spid)))
    print(f"killed session {spid}")
    sys.exit(0)

print("=== active user requests ===")
q = ("SELECT r.session_id, r.blocking_session_id, r.status, r.command, "
     "CAST(r.wait_time/1000.0 AS DECIMAL(10,1)) AS wait_s, r.wait_type, "
     "s.login_name, s.program_name, SUBSTRING(ISNULL(t.text,''),1,90) AS sql_text "
     "FROM sys.dm_exec_requests r "
     "JOIN sys.dm_exec_sessions s ON s.session_id=r.session_id "
     "OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) t "
     "WHERE s.is_user_process=1 AND r.session_id<>@@SPID "
     "ORDER BY r.blocking_session_id DESC, r.wait_time DESC")
any_req = False
for r in cur.execute(q).fetchall():
    any_req = True
    print(f"  spid {r.session_id} | blocked_by {r.blocking_session_id} | {r.status} "
          f"| {r.command} | wait {r.wait_s}s {r.wait_type or ''} | {r.program_name}")
    print(f"      sql: {r.sql_text}")
if not any_req:
    print("  (none)")

print("\n=== sessions holding OPEN transactions (likely the culprit) ===")
q2 = ("SELECT s.session_id, s.login_name, s.program_name, s.host_name, "
      "s.last_request_end_time, r.status AS req_status "
      "FROM sys.dm_tran_session_transactions st "
      "JOIN sys.dm_exec_sessions s ON s.session_id=st.session_id "
      "LEFT JOIN sys.dm_exec_requests r ON r.session_id=s.session_id "
      "WHERE s.is_user_process=1")
any_tx = False
for r in cur.execute(q2).fetchall():
    any_tx = True
    st = r.req_status or "sleeping (idle open tran)"
    print(f"  spid {r.session_id} | {r.program_name} | {r.host_name} | "
          f"status: {st} | last active {r.last_request_end_time}")
if not any_tx:
    print("  (none)")

print("\n=> to clear it: py who_locks.py --kill <spid of the blocker / idle open tran>")
print("   an idle 'sleeping (idle open tran)' from a Python/SSMS session is safe to kill.")

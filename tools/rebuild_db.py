"""rebuild_db.py — drop & recreate an EMPTY DataView_Demo, then run the corrected
DDL to build the schema with char(14) UWI keys. py rebuild_db.py

Safe: connects to master to drop/create the db (must have no other connections),
then runs the UTF-16 DDL batch-by-batch (split on GO).
"""
import pyodbc, sys, os

DDL = "dataview_demo_07072026_ddl_clean.sql"
if not os.path.exists(DDL):
    sys.exit(f"{DDL} not found — put the corrected DDL here first")

MASTER = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
          r"DATABASE=master;Trusted_Connection=yes;Encrypt=no")
DB = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
      r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")

# 1) drop + recreate empty database (kick other connections first)
m = pyodbc.connect(MASTER, autocommit=True).cursor()
print("dropping DataView_Demo (if exists) …")
m.execute("""
    IF DB_ID('DataView_Demo') IS NOT NULL
    BEGIN
        ALTER DATABASE [DataView_Demo] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
        DROP DATABASE [DataView_Demo];
    END""")
print("creating empty DataView_Demo …")
m.execute("CREATE DATABASE [DataView_Demo]")

# 2) run the DDL batch-by-batch (split on lines that are exactly GO)
sql = open(DDL, encoding="utf-16").read()
import re
batches, cur_b = [], []
for line in sql.splitlines():
    if line.strip().upper() == "GO":
        if cur_b:
            batches.append("\n".join(cur_b)); cur_b = []
    else:
        cur_b.append(line)
if cur_b:
    batches.append("\n".join(cur_b))

c = pyodbc.connect(DB, autocommit=True).cursor()
ok = err = 0
for i, b in enumerate(batches, 1):
    if not b.strip():
        continue
    try:
        c.execute(b); ok += 1
    except Exception as e:
        err += 1
        print(f"  [batch {i}] ERROR: {str(e)[:160]}")
        print(f"            SQL head: {' '.join(b.split())[:100]}")
print(f"\ndone: {ok} batches ok, {err} errors")
if err == 0:
    print("schema rebuilt clean with char(14) UWI keys.")

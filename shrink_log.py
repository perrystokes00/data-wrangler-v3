"""Shrink the bloated log only — the standalone step that failed. ALTER DATABASE
needs a connection with autocommit set BEFORE any statement runs."""
import pyodbc

# direct pyodbc with autocommit=True from the start (no SQLAlchemy wrapper that
# may open an implicit transaction). ALTER DATABASE must run outside any txn.
cs = ("DRIVER={ODBC Driver 17 for SQL Server};SERVER=localhost\\SQLEXPRESS;"
      "DATABASE=DataView_Demo;Trusted_Connection=yes;")
conn = pyodbc.connect(cs, autocommit=True)
cur = conn.cursor()

cur.execute("ALTER DATABASE DataView_Demo SET RECOVERY SIMPLE")
print("recovery model → SIMPLE")

cur.execute("SELECT name FROM sys.database_files WHERE type_desc='LOG'")
logname = cur.fetchone()[0]
cur.execute(f"DBCC SHRINKFILE (N'{logname}', 512)")
print(f"shrank log '{logname}' toward 512 MB")

# confirm new sizes
cur.execute("SELECT name, size*8.0/1024 FROM sys.database_files")
print("\n── DB file sizes now ──")
for name, mb in cur.fetchall():
    print(f"  {name:24} {mb:8.1f} MB")
conn.close()

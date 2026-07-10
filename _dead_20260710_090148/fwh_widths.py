"""fwh_widths.py — list FILE_WELL_HEADER string columns by width to find the one
overflowing (buffer 22 = varchar(22) or nvarchar(11)). Read-only.
Run: py fwh_widths.py"""
import pyodbc

cn = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True)
cur = cn.cursor()

print(f"{'column':22} {'type':10} {'chars':>6} {'bytes':>6}  flag")
rows = cur.execute("""
    SELECT c.name, t.name AS typ, c.max_length,
           CASE WHEN c.max_length = -1 THEN -1
                WHEN t.name IN ('nchar','nvarchar') THEN c.max_length/2
                ELSE c.max_length END AS chars
    FROM sys.columns c
    JOIN sys.types t ON t.user_type_id = c.user_type_id
    WHERE c.object_id = OBJECT_ID('file_catalog.FILE_WELL_HEADER')
      AND t.name IN ('char','nchar','varchar','nvarchar','text','ntext')
    ORDER BY chars""").fetchall()

for r in rows:
    chars = r.chars
    byts = r.max_length
    flag = ""
    # buffer 22 -> varchar(22) or nvarchar(11); anything <=24 chars is suspect
    if chars != -1 and chars <= 24:
        flag = "<-- suspect (narrow)"
    if byts == 22 or (r.typ in ("nvarchar", "nchar") and chars == 11):
        flag = "<== LIKELY THE ONE (buffer 22)"
    print(f"{r.name:22} {r.typ:10} {str(chars):>6} {str(byts):>6}  {flag}")

print("\nWiden the flagged column, e.g.:")
print("  ALTER TABLE file_catalog.FILE_WELL_HEADER "
      "ALTER COLUMN <col> VARCHAR(64) NULL;")

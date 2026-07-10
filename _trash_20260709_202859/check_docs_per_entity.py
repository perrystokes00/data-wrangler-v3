"""check_docs_per_entity.py — do wells/surveys have multiple documents? Determines
whether grouping the grid by well/survey matters. py check_docs_per_entity.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

print("=== documents per WELL (UWI14) ===")
print("  wells with >1 document:",
      c.execute("""SELECT COUNT(*) FROM (
          SELECT UWI14 FROM file_catalog.GLOBAL_FILE_CATALOG
          WHERE NULLIF(LTRIM(RTRIM(UWI14)),'') IS NOT NULL
          GROUP BY UWI14 HAVING COUNT(*) > 1) x""").fetchone()[0])
print("  max docs on one well  :",
      c.execute("""SELECT ISNULL(MAX(n),0) FROM (
          SELECT COUNT(*) n FROM file_catalog.GLOBAL_FILE_CATALOG
          WHERE NULLIF(LTRIM(RTRIM(UWI14)),'') IS NOT NULL GROUP BY UWI14) x""").fetchone()[0])
print("  top wells by doc count:")
for r in c.execute("""SELECT TOP 8 UWI14, COUNT(*) n
      FROM file_catalog.GLOBAL_FILE_CATALOG
      WHERE NULLIF(LTRIM(RTRIM(UWI14)),'') IS NOT NULL
      GROUP BY UWI14 ORDER BY n DESC""").fetchall():
    print(f"     {r[0]:16} {r[1]} docs")

print("\n=== documents per SURVEY ===")
print("  surveys with >1 document:",
      c.execute("""SELECT COUNT(*) FROM (
          SELECT SURVEY_NAME FROM file_catalog.GLOBAL_FILE_CATALOG
          WHERE NULLIF(LTRIM(RTRIM(SURVEY_NAME)),'') IS NOT NULL
          GROUP BY SURVEY_NAME HAVING COUNT(*) > 1) x""").fetchone()[0])
print("  max docs on one survey :",
      c.execute("""SELECT ISNULL(MAX(n),0) FROM (
          SELECT COUNT(*) n FROM file_catalog.GLOBAL_FILE_CATALOG
          WHERE NULLIF(LTRIM(RTRIM(SURVEY_NAME)),'') IS NOT NULL GROUP BY SURVEY_NAME) x""").fetchone()[0])

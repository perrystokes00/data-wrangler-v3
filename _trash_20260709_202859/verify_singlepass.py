import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
s = lambda q: cur.execute(q).fetchone()[0]
print("LAS files, HEADER_EXTRACTED='Y':",
      s("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' AND HEADER_EXTRACTED='Y'"))
print("LAS files still pending (NULL/N):",
      s("SELECT COUNT(*) FROM file_catalog.GLOBAL_FILE_CATALOG WHERE FILE_EXT='.las' AND (HEADER_EXTRACTED IS NULL OR HEADER_EXTRACTED='N')"))
print("FILE_WELL_HEADER rows:", s("SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER"))
print("dv_well with coords:",
      s("SELECT COUNT(*) FROM dataview.dv_well WHERE surface_latitude IS NOT NULL AND NOT (surface_latitude=0 AND surface_longitude=0)"))

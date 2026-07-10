import pyodbc
cur = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()
n = cur.execute("""UPDATE file_catalog.GLOBAL_FILE_CATALOG
    SET HEADER_EXTRACTED='N', CATALOG_READINESS=NULL
    WHERE HEADER_EXTRACTED='Y' AND INVENTORY_ID NOT IN
    (SELECT INVENTORY_ID FROM file_catalog.cat_well WHERE INVENTORY_ID IS NOT NULL)""").rowcount
print("reset", n, "stuck file(s)")

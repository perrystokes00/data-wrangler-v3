from sqlalchemy import create_engine, text
e = create_engine(
    "mssql+pyodbc://@localhost\\SQLEXPRESS/DataView"
    "?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"
)
with e.connect() as c:
    print("SERVER/DB:", c.execute(text("SELECT @@SERVERNAME, DB_NAME()")).fetchone())
    print("H3 COLS  :", c.execute(text("""
        SELECT name FROM sys.columns
        WHERE object_id = OBJECT_ID('dataview.dv_well')
          AND name LIKE 'h3%'
    """)).fetchall())

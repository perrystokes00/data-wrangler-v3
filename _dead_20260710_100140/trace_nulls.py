"""Find the NULL-period rows still in cat_prod_volume and trace them to their
source file/path so we know WHICH loader wrote them."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    n = c.execute(text("SELECT COUNT(*) FROM file_catalog.cat_prod_volume")).scalar()
    nulls = c.execute(text(
        "SELECT COUNT(*) FROM file_catalog.cat_prod_volume "
        "WHERE period_date IS NULL OR LTRIM(RTRIM(period_date))=''")).scalar()
    print(f"cat_prod_volume: {n} rows, {nulls} with NULL/blank period_date\n")

    if nulls:
        # what columns does cat_prod_volume have for provenance?
        cols = [r[0] for r in c.execute(text("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
             WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='cat_prod_volume'
        """)).fetchall()]
        print("columns:", cols, "\n")
        prov = [x for x in ("SOURCE","SOURCE_PATH","INVENTORY_ID","FILE_PATH")
                if x in cols]
        sel = ", ".join(prov) if prov else "TOP 1 *"
        print("sample NULL-period rows with provenance:")
        q = (f"SELECT TOP 10 {', '.join(prov)} FROM file_catalog.cat_prod_volume "
             f"WHERE period_date IS NULL OR LTRIM(RTRIM(period_date))=''") \
            if prov else \
            ("SELECT TOP 5 * FROM file_catalog.cat_prod_volume "
             "WHERE period_date IS NULL")
        for row in c.execute(text(q)).fetchall():
            print("  ", tuple(row))

"""Delete cat_prod_volume rows with NULL/blank period_date — stale rows that
block promote (period_date is NOT NULL in dv_prod_volume). After this + a
reprocess with the hardened loader, no new NULL-period rows are written."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.begin() as c:
    n = c.execute(text(
        "DELETE FROM file_catalog.cat_prod_volume "
        "WHERE period_date IS NULL OR LTRIM(RTRIM(period_date))=''")).rowcount
    print(f"deleted {n} NULL/blank period_date row(s) from cat_prod_volume")

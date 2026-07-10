import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.begin() as c:
    n = c.execute(text(
        "DELETE FROM file_catalog.cat_well WHERE SOURCE IN ('DLIS','LIS')")).rowcount
    print(f"cleared {n} DLIS/LIS cat_well rows")

"""Collapse duplicate (prod_entity_id, period_date, fluid_type) rows in
cat_prod_volume to one each, so promote's insert doesn't hit the PK. Keeps the
row with the smallest internal id; deletes the rest. Idempotent."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.begin() as c:
    # find the PK column of the mirror so we can keep one deterministically
    before = c.execute(text(
        "SELECT COUNT(*) FROM file_catalog.cat_prod_volume")).scalar()
    # delete all but one row per (entity, period, fluid). Use ROW_NUMBER over a
    # stable ordering; if there's no natural id, %%physloc%% gives a tiebreak.
    n = c.execute(text("""
        WITH ranked AS (
            SELECT ROW_NUMBER() OVER (
                       PARTITION BY prod_entity_id, period_date, fluid_type
                       ORDER BY (SELECT 1)) AS rn
              FROM file_catalog.cat_prod_volume)
        DELETE FROM ranked WHERE rn > 1
    """)).rowcount
    after = c.execute(text(
        "SELECT COUNT(*) FROM file_catalog.cat_prod_volume")).scalar()
    print(f"cat_prod_volume: {before} → {after} rows  (removed {n} duplicates)")
    # verify no dups remain
    rem = c.execute(text("""
        SELECT COUNT(*) FROM (
          SELECT 1 FROM file_catalog.cat_prod_volume
           GROUP BY prod_entity_id, period_date, fluid_type
          HAVING COUNT(*) > 1) d
    """)).scalar()
    print(f"remaining duplicate keys: {rem}")

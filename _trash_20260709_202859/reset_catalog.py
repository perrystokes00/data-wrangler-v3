"""Truncate the cat_* / dv_* mirror tables for a CLEAN reprocess. Does NOT touch
GLOBAL_FILE_CATALOG (the inventory/queue). Test-DB only."""
import worker_core as w
from sqlalchemy import text

TABLES = ["cat_well","cat_well_log","cat_well_log_curve","cat_well_formation_top",
          "cat_well_dir_srvy_hdr","cat_well_dir_srvy_sta","cat_well_completion",
          "cat_well_core","cat_well_core_sample","cat_well_dst","cat_prod_entity",
          "cat_prod_volume","cat_well_petro_interp","cat_well_petro_zone",
          "cat_well_stimulation","dv_seis_set"]

e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.begin() as c:
    for t in TABLES:
        try:
            c.execute(text(f"TRUNCATE TABLE file_catalog.{t}"))
            print(f"  truncated {t}")
        except Exception as ex:
            # some may be in dataview schema, not file_catalog
            try:
                c.execute(text(f"TRUNCATE TABLE dataview.{t}"))
                print(f"  truncated dataview.{t}")
            except Exception:
                print(f"  skip {t} ({str(ex)[:50]})")
print("\ncatalog mirrors cleared — ready for a clean reprocess")

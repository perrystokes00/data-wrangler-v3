"""How many FILE_WELL_HEADER wells actually match well_master_gold by UWI14, and
of those, how many gold rows have coordinates? Sets expectations for the map."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
gold = "WELL_REF.well_ref.well_master_gold"
with e.connect() as c:
    fwh = c.execute(text(
        "SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER "
        "WHERE NULLIF(LTRIM(RTRIM(UWI14)),'') IS NOT NULL")).scalar()
    print(f"FILE_WELL_HEADER rows with UWI14: {fwh}")

    matched = c.execute(text(f"""
        SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER h
          JOIN {gold} g ON g.uwi14 = h.UWI14""")).scalar()
    print(f"  ...that match a gold UWI14: {matched}")

    withcoord = c.execute(text(f"""
        SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER h
          JOIN {gold} g ON g.uwi14 = h.UWI14
         WHERE g.surface_latitude IS NOT NULL
           AND g.surface_longitude IS NOT NULL""")).scalar()
    print(f"  ...whose gold row HAS coordinates: {withcoord}")

    # how many FWH wells already have their own coords (from the document)?
    own = c.execute(text("""
        SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER
         WHERE NULLIF(LTRIM(RTRIM(LATITUDE)),'') IS NOT NULL
           AND NULLIF(LTRIM(RTRIM(LONGITUDE)),'') IS NOT NULL""")).scalar()
    print(f"\nFWH wells that ALREADY have their own coordinates: {own}")

    # sample a few UWI14s from each side to eyeball format
    print("\nsample FWH.UWI14:", [r[0] for r in c.execute(text(
        "SELECT TOP 5 UWI14 FROM file_catalog.FILE_WELL_HEADER "
        "WHERE UWI14 IS NOT NULL")).fetchall()])
    print("sample gold.uwi14:", [r[0] for r in c.execute(text(
        f"SELECT TOP 5 uwi14 FROM {gold} WHERE uwi14 IS NOT NULL")).fetchall()])

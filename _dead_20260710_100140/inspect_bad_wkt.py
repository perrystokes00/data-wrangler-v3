"""The 2 bad SEG-Y surveys throw on STGeomFromText — their SURVEY_OUTLINE WKT is
malformed. Show the raw WKT so we can see what's broken and decide: fix the
SEG-Y geometry extraction, or just null/skip these."""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as con:
    for nm in ("BRECON 3D", "TARATA 3D MERGE, ACQUIRED BY SAE EXPLORATN"):
        wkt = con.execute(text(
            "SELECT TOP 1 SURVEY_OUTLINE FROM file_catalog.FILE_SEIS_HEADER "
            "WHERE SURVEY_NAME=:n AND SURVEY_OUTLINE IS NOT NULL"),
            {"n": nm}).scalar()
        print(f"=== {nm} ===")
        print(f"   full WKT: {wkt}")
        print()
        # also show bbox for these — maybe the bbox is fine even if outline isn't
        bb = con.execute(text("""
            SELECT BBOX_MIN_LAT, BBOX_MAX_LAT, BBOX_MIN_LON, BBOX_MAX_LON, EPSG_CODE
            FROM file_catalog.FILE_SEIS_HEADER WHERE SURVEY_NAME=:n"""),
            {"n": nm}).fetchone()
        print(f"   bbox: lat {bb[0]}..{bb[1]}  lon {bb[2]}..{bb[3]}  epsg={bb[4]}")
        print()

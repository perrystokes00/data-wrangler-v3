"""lasfiles_gold_match.py — how many of my LAS-file wells match the gold master
(on the rebuilt uwi14)? Runs on the server. py lasfiles_gold_match.py"""
import urllib.parse as _u
from sqlalchemy import create_engine, text

CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))
REF = "WELL_REF.well_ref.well_master_gold"
FWH = "file_catalog.FILE_WELL_HEADER"
CW  = "file_catalog.cat_well"

CWN = ("LEFT(REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LTRIM(RTRIM(w.UWI)),'-',''),' ',''),"
       "'/',''),'.',''),'_','') + '00000000000000', 14)")
GOODC = ("g.surface_latitude IS NOT NULL AND NOT (g.surface_latitude=0 AND g.surface_longitude=0)")

with eng.begin() as c:
    f = lambda q: c.execute(text(q)).scalar()

    print("=== LAS-file headers (FILE_WELL_HEADER.UWI14) vs gold ===")
    tot = f(f"SELECT COUNT(DISTINCT UWI14) FROM {FWH} WHERE UWI14 IS NOT NULL")
    m   = f(f"SELECT COUNT(DISTINCT h.UWI14) FROM {FWH} h JOIN {REF} g ON g.uwi14=h.UWI14 "
            f"WHERE h.UWI14 IS NOT NULL")
    mc  = f(f"SELECT COUNT(DISTINCT h.UWI14) FROM {FWH} h JOIN {REF} g ON g.uwi14=h.UWI14 "
            f"WHERE h.UWI14 IS NOT NULL AND {GOODC}")
    print(f"  distinct LAS-file UWI14     : {tot:,}")
    print(f"  matching gold uwi14         : {m:,}  ({100.0*m/max(1,tot):.1f}%)")
    print(f"  of those, gold has coords   : {mc:,}")

    print("\n=== captured wells (cat_well) vs gold ===")
    ctot = f(f"SELECT COUNT(DISTINCT UWI) FROM {CW} WHERE UWI IS NOT NULL")
    cm   = f(f"SELECT COUNT(DISTINCT w.UWI) FROM {CW} w JOIN {REF} g ON g.uwi14={CWN} "
             f"WHERE w.UWI IS NOT NULL")
    cmc  = f(f"SELECT COUNT(DISTINCT w.UWI) FROM {CW} w JOIN {REF} g ON g.uwi14={CWN} "
             f"WHERE w.UWI IS NOT NULL AND {GOODC}")
    print(f"  distinct cat_well UWI       : {ctot:,}")
    print(f"  matching gold uwi14         : {cm:,}  ({100.0*cm/max(1,ctot):.1f}%)")
    print(f"  of those, gold has coords   : {cmc:,}")

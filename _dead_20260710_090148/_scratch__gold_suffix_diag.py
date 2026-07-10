"""gold_suffix_diag.py — what does gold.uwi14 actually look like? length, the
last-4 (directional/event) distribution, and how much ends in '0000'.
py gold_suffix_diag.py"""
import urllib.parse as _u
from sqlalchemy import create_engine, text

CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))
REF = "WELL_REF.well_ref.well_master_gold"

with eng.begin() as c:
    tot = c.execute(text(f"SELECT COUNT(*) FROM {REF}")).scalar()
    print(f"gold rows: {tot:,}\n")

    print("uwi14 length distribution:")
    for r in c.execute(text(f"SELECT LEN(uwi14) L, COUNT(*) n FROM {REF} "
                            f"GROUP BY LEN(uwi14) ORDER BY n DESC")).fetchall()[:8]:
        print(f"  len {r.L}: {r.n:,}")

    end0 = c.execute(text(f"SELECT COUNT(*) FROM {REF} WHERE RIGHT(uwi14,4)='0000'")).scalar()
    print(f"\nend in '0000' : {end0:,}  ({100.0*end0/tot:.1f}%)")
    print(f"end in other  : {tot-end0:,}  ({100.0*(tot-end0)/tot:.1f}%)")

    print("\ntop 12 last-4 (suffix) values overall:")
    for r in c.execute(text(f"SELECT RIGHT(uwi14,4) sfx, COUNT(*) n FROM {REF} "
                            f"GROUP BY RIGHT(uwi14,4) ORDER BY n DESC")).fetchall()[:12]:
        print(f"  {r.sfx!r}: {r.n:,}")

    print("\nKansas (15…) suffix breakdown:")
    ks = c.execute(text(f"SELECT COUNT(*) FROM {REF} WHERE uwi14 LIKE '15%'")).scalar()
    ks0 = c.execute(text(f"SELECT COUNT(*) FROM {REF} WHERE uwi14 LIKE '15%' AND RIGHT(uwi14,4)='0000'")).scalar()
    print(f"  Kansas rows: {ks:,}   ending 0000: {ks0:,}")

    print("\n10 sample Kansas uwi14 (state|county|well|suffix):")
    for r in c.execute(text(f"SELECT TOP 10 uwi14 FROM {REF} WHERE uwi14 LIKE '15%' "
                            f"ORDER BY uwi14")).fetchall():
        u = str(r.uwi14)
        if len(u) == 14:
            print(f"  {u[:2]}|{u[2:5]}|{u[5:10]}|{u[10:]}   ({u})")
        else:
            print(f"  (len {len(u)}) {u!r}")

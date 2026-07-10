"""gold_key_columns.py — find gold's real API/UWI key columns. Lists text columns,
counts Kansas ('15%') in each, and samples rows so we can see how uwi14 got
mangled vs which column holds the clean API. py gold_key_columns.py"""
import urllib.parse as _u
from sqlalchemy import create_engine, text

CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))
REF = "WELL_REF.well_ref.well_master_gold"

with eng.begin() as c:
    coldefs = c.execute(text(
        "SELECT c.name, t.name typ, c.max_length "
        "FROM WELL_REF.sys.columns c JOIN WELL_REF.sys.types t "
        "ON t.user_type_id=c.user_type_id "
        "WHERE c.object_id=OBJECT_ID('%s') ORDER BY c.column_id" % REF)).fetchall()
    print("gold columns (name / type):")
    idlike = []
    for r in coldefs:
        tag = ""
        if any(k in r.name.lower() for k in ("uwi", "api", "well_id", "id", "num")):
            idlike.append(r.name); tag = "  <-- key candidate"
        print("  %-26s %-12s%s" % (r.name, r.typ, tag))

    print("\nKansas ('15%%') count per key-candidate column:")
    for col in idlike:
        try:
            n = c.execute(text("SELECT COUNT(*) FROM %s WHERE CONVERT(NVARCHAR(50),[%s]) LIKE '15%%'"
                               % (REF, col))).scalar()
            print("  %-26s %s" % (col, format(n, ",")))
        except Exception as e:
            print("  %-26s (err %s)" % (col, str(e)[:40]))

    print("\nsample rows (key candidates + coords):")
    sel = ", ".join("[%s]" % c2 for c2 in idlike[:6]) or "uwi14"
    for r in c.execute(text(
            "SELECT TOP 6 %s, surface_latitude, surface_longitude FROM %s "
            "WHERE surface_latitude IS NOT NULL ORDER BY NEWID()" % (sel, REF))).fetchall():
        print("  ", tuple(r))

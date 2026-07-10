"""
docs_per_well.py — how many wells have more than one catalogued document?

Counts documents per well two ways:
  (1) via the stamped GLOBAL_FILE_CATALOG.UWI14 tag (what the map query uses)
  (2) via the FULL INVENTORY_ID linkage (FILE_WELL_HEADER + every dv_* detail
      table with uwi+INVENTORY_ID) → the true count, independent of tagging.

    py docs_per_well.py                           # defaults below
    py docs_per_well.py "PERRY\\SQLEXPRESS" DataView_Demo
"""
import sys
import worker_core as w
from sqlalchemy import text

SERVER = sys.argv[1] if len(sys.argv) > 1 else r"PERRY\SQLEXPRESS"
DB     = sys.argv[2] if len(sys.argv) > 2 else "DataView_Demo"
e = w.make_engine(SERVER, DB)


def _report(c, label, sql):
    rows = c.execute(text(sql)).fetchall()          # (uwi, n_docs)
    total = len(rows)
    multi = sum(1 for _, n in rows if n > 1)
    print(f"\n=== {label} ===")
    print(f"  wells with a document : {total}")
    print(f"  wells with > 1 doc    : {multi}")
    print(f"  wells with exactly 1  : {total - multi}")
    if rows:
        mx = max(n for _, n in rows)
        print(f"  max docs on one well  : {mx}")
        print("  top wells:")
        for uwi, n in sorted(rows, key=lambda r: -r[1])[:8]:
            print(f"    {uwi}  {n} docs")


with e.connect() as c:
    # (1) via the UWI14 tag
    _report(c, "via GLOBAL_FILE_CATALOG.UWI14 tag", """
        SELECT UWI14, COUNT(*) AS n
        FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE NULLIF(LTRIM(RTRIM(UWI14)),'') IS NOT NULL
        GROUP BY UWI14""")

    # (2) via the full INVENTORY_ID linkage (tag-independent)
    branches = []
    hc = {r[0].upper(): r[0] for r in c.execute(text(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='FILE_WELL_HEADER'"))}
    hu = hc.get("UWI14") or hc.get("UWI")
    N14 = "REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{c}),'-',''),' ',''),'/','')"
    if hu:
        branches.append(
            f"SELECT g.INVENTORY_ID, LEFT(LTRIM(RTRIM({N14.format(c='h.['+hu+']')}))"
            f"+'00000000000000',14) AS uwi14 "
            f"FROM file_catalog.GLOBAL_FILE_CATALOG g "
            f"JOIN file_catalog.FILE_WELL_HEADER h ON h.INVENTORY_ID=g.INVENTORY_ID "
            f"WHERE NULLIF(LTRIM(RTRIM(CONVERT(varchar(64),h.[{hu}]))),'') IS NOT NULL")
    for (t,) in c.execute(text(
            "SELECT c1.TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS c1 "
            "JOIN INFORMATION_SCHEMA.COLUMNS c2 ON c1.TABLE_SCHEMA=c2.TABLE_SCHEMA "
            "AND c1.TABLE_NAME=c2.TABLE_NAME WHERE c1.TABLE_SCHEMA='dataview' "
            "AND UPPER(c1.COLUMN_NAME)='UWI' AND UPPER(c2.COLUMN_NAME)='INVENTORY_ID' "
            "AND c1.TABLE_NAME LIKE 'dv[_]%' GROUP BY c1.TABLE_NAME")).fetchall():
        branches.append(
            f"SELECT g.INVENTORY_ID, LEFT(LTRIM(RTRIM({N14.format(c='d.uwi')}))"
            f"+'00000000000000',14) AS uwi14 "
            f"FROM file_catalog.GLOBAL_FILE_CATALOG g "
            f"JOIN dataview.[{t}] d ON d.INVENTORY_ID=g.INVENTORY_ID "
            f"WHERE d.uwi IS NOT NULL")
    if branches:
        union = " UNION ".join(branches)   # UNION dedups (INVENTORY_ID, uwi14)
        _report(c, "via full INVENTORY_ID linkage (untagged included)", f"""
            SELECT uwi14, COUNT(DISTINCT INVENTORY_ID) AS n FROM ({union}) s
            GROUP BY uwi14""")

print("\ndone.")

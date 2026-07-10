"""
backfill_uwi14.py — fill FILE_WELL_HEADER.UWI14 from the already-populated
UWI column so the 32 wells that HAVE documents finally link.

Pure set-based UPDATE (no per-row pyodbc). Idempotent: only touches rows where
UWI14 IS NULL. Rows whose UWI isn't 14 clean digits are left NULL and printed
for a manual look rather than silently mangled.

    py backfill_uwi14.py                       # defaults below
    py backfill_uwi14.py "PERRY\\SQLEXPRESS" DataView_Demo
"""
import sys
import worker_core as w
from sqlalchemy import text

SERVER = sys.argv[1] if len(sys.argv) > 1 else r"PERRY\SQLEXPRESS"
DB     = sys.argv[2] if len(sys.argv) > 2 else "DataView_Demo"
e = w.make_engine(SERVER, DB)

CLEAN = "LEN(LTRIM(RTRIM(UWI))) = 14 AND LTRIM(RTRIM(UWI)) NOT LIKE '%[^0-9]%'"

with e.connect() as c:
    before = c.execute(text(
        "SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER WHERE UWI14 IS NULL")).scalar()
    print(f"UWI14 NULL before: {before}")

    dirty = c.execute(text(f"""
        SELECT WELL_HEADER_ID, UWI, LEN(LTRIM(RTRIM(UWI))) AS ln
        FROM file_catalog.FILE_WELL_HEADER
        WHERE UWI14 IS NULL AND NOT ({CLEAN})""")).fetchall()
    if dirty:
        print(f"\nrows skipped (UWI not 14 clean digits): {len(dirty)}")
        for hid, uwi, ln in dirty:
            print(f"   {hid}  UWI={uwi!r}  len={ln}")

with e.begin() as c:
    res = c.execute(text(f"""
        UPDATE file_catalog.FILE_WELL_HEADER
        SET UWI14 = LTRIM(RTRIM(UWI))
        WHERE UWI14 IS NULL AND ({CLEAN})"""))
    print(f"\nrows updated: {res.rowcount}")

with e.connect() as c:
    after = c.execute(text(
        "SELECT COUNT(*) FROM file_catalog.FILE_WELL_HEADER WHERE UWI14 IS NULL")).scalar()
    linked = c.execute(text("""
        SELECT COUNT(*) FROM dataview.dv_well g
        WHERE EXISTS (SELECT 1 FROM file_catalog.FILE_WELL_HEADER h
                      WHERE h.UWI14 = g.uwi)""")).scalar()
    orphan = c.execute(text("""
        SELECT COUNT(*) FROM dataview.dv_well g
        WHERE NOT EXISTS (SELECT 1 FROM file_catalog.FILE_WELL_HEADER h
                          WHERE h.UWI14 = g.uwi)""")).scalar()
    print(f"UWI14 NULL after : {after}")
    print(f"\ngold wells now linked      : {linked}")
    print(f"gold wells w/o document    : {orphan}   (was 213; the gap = the "
          "four header-less handlers)")

print("\ndone.")

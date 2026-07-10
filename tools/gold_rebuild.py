"""
gold_rebuild.py — fix well_master_gold (or WELL_MASTER) WITHOUT losing real wells.
All work is set-based on the server; Python just orchestrates.

uwi14 (PK) is a surrogate for ~620k rows; api_10 is the correct key but has dupes.
Dedup by api_10 would drop ~63k real directional wells, so instead: fix ONLY the
corrupted uwi14, then dedup on the FULL uwi14 (directional wells keep distinct
suffixes -> preserved; only corrupted twins collide and drop).

  py gold_rebuild.py                         # preview well_master_gold
  py gold_rebuild.py --apply                 # rebuild (backs up first)
  py gold_rebuild.py --table WELL_MASTER --apply   # fix the source too
  py gold_rebuild.py --apply --no-backup
"""
import sys, urllib.parse as _u
from sqlalchemy import create_engine, text

CONN = (r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
        r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no")
eng = create_engine("mssql+pyodbc:///?odbc_connect=" + _u.quote_plus(CONN))

TBL = sys.argv[sys.argv.index("--table") + 1] if "--table" in sys.argv else "well_master_gold"
REF = f"WELL_REF.well_ref.{TBL}"
BAK = f"WELL_REF.well_ref.{TBL}_bak"
apply = "--apply" in sys.argv

def conn():
    return eng.connect().execution_options(isolation_level="AUTOCOMMIT")

with conn() as c:
    sc = lambda q: c.execute(text(q)).scalar()
    tot = sc(f"SELECT COUNT(*) FROM {REF}")
    corrupt = sc(f"SELECT COUNT(*) FROM {REF} WHERE api_10 IS NOT NULL "
                 f"AND LEN(RTRIM(api_10))=10 AND LEFT(uwi14,10)<>RTRIM(api_10)")
    twins = sc(f"""SELECT COUNT(*) FROM {REF} b
        WHERE b.api_10 IS NOT NULL AND LEN(RTRIM(b.api_10))=10
          AND LEFT(b.uwi14,10)<>RTRIM(b.api_10)
          AND EXISTS (SELECT 1 FROM {REF} g WHERE g.uwi14=RTRIM(b.api_10)+'0000'
                      AND LEFT(g.uwi14,10)=RTRIM(g.api_10))""")
    print(f"table                        : {REF}")
    print(f"rows                         : {tot:,}")
    print(f"corrupted uwi14              : {corrupt:,}")
    print(f"corrupted twins to drop      : {twins:,}   <- ONLY these are deleted")
    print(f"expected rows after          : ~{tot - twins:,}   (real wells preserved)")

if not apply:
    print("\n[dry run] add --apply to rebuild (backs up first unless --no-backup).")
    sys.exit(0)

with conn() as c:
    if "--no-backup" not in sys.argv:
        print("\n[1/6] backup …", flush=True)
        c.execute(text(f"IF OBJECT_ID('{BAK}') IS NOT NULL DROP TABLE {BAK}"))
        c.execute(text(f"SELECT * INTO {BAK} FROM {REF}"))
        print(f"      -> {BAK}: {c.execute(text(f'SELECT COUNT(*) FROM {BAK}')).scalar():,} rows")

    pk = c.execute(text("SELECT name FROM WELL_REF.sys.key_constraints "
                        f"WHERE parent_object_id=OBJECT_ID('{REF}') AND type='PK'")).scalar()
    print(f"[2/6] drop PK ({pk}) …", flush=True)
    if pk:
        c.execute(text(f"ALTER TABLE {REF} DROP CONSTRAINT [{pk}]"))

    print("[3/6] flag corrupted rows …", flush=True)
    if c.execute(text(f"SELECT COL_LENGTH('WELL_REF.well_ref.{TBL}','_was_corrupt')")).scalar() is None:
        c.execute(text(f"ALTER TABLE {REF} ADD _was_corrupt BIT NULL"))
    c.execute(text(f"UPDATE {REF} SET _was_corrupt = CASE WHEN api_10 IS NOT NULL "
                   f"AND LEN(RTRIM(api_10))=10 AND LEFT(uwi14,10)<>RTRIM(api_10) THEN 1 ELSE 0 END"))

    print("[4/6] rebuild ONLY corrupted uwi14 = api_10 + '0000' …", flush=True)
    n4 = c.execute(text(f"UPDATE {REF} SET uwi14 = RTRIM(api_10)+'0000' "
                        f"WHERE _was_corrupt=1 AND api_10 IS NOT NULL AND LEN(RTRIM(api_10))=10")).rowcount
    print(f"      rebuilt {n4:,}")

    print("[5/6] dedup on full uwi14 (valid original wins; directional kept) …", flush=True)
    n5 = c.execute(text(f"""
        WITH r AS (SELECT ROW_NUMBER() OVER (PARTITION BY uwi14 ORDER BY
            _was_corrupt ASC,
            CASE WHEN surface_latitude IS NOT NULL THEN 0 ELSE 1 END,
            CASE WHEN ISNULL(coord_suspect,0)=0 THEN 0 ELSE 1 END,
            ISNULL(quality_score,0) DESC, ISNULL(source_count,0) DESC) rn
          FROM {REF})
        DELETE FROM r WHERE rn > 1""")).rowcount
    print(f"      dropped {n5:,} corrupted twins")

    print("[6/6] drop flag + restore PK …", flush=True)
    c.execute(text(f"ALTER TABLE {REF} DROP COLUMN _was_corrupt"))
    dup = c.execute(text(f"SELECT COUNT(*) FROM (SELECT uwi14 FROM {REF} "
                         f"GROUP BY uwi14 HAVING COUNT(*)>1) x")).scalar()
    if dup:
        print(f"      ABORT: {dup:,} uwi14 still duplicated — PK not added (restore from {BAK})")
        sys.exit(1)
    c.execute(text(f"ALTER TABLE {REF} ADD CONSTRAINT PK_{TBL} PRIMARY KEY (uwi14)"))
    fin = c.execute(text(f"SELECT COUNT(*) FROM {REF}")).scalar()
    ks  = c.execute(text(f"SELECT COUNT(*) FROM {REF} WHERE uwi14 LIKE '15%'")).scalar()
    print(f"\ndone. {REF}: {fin:,} rows   Kansas (uwi14 '15…'): {ks:,}")
    print(f"(restore: drop PK; TRUNCATE {REF}; INSERT {REF} SELECT * FROM {BAK})")

"""Which files produced the non-seismic 'surveys' (Active Leases TX, blocks)?
Find the source file + its extension — how did a non-SEGY reach FILE_SEIS_HEADER?"""
import worker_core as w
from sqlalchemy import text
e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")
with e.connect() as c:
    print("=== FILE_SEIS_HEADER rows whose SURVEY_NAME looks non-seismic ===")
    # show the columns available first
    cols = [r[0] for r in c.execute(text("""
        SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='file_catalog' AND TABLE_NAME='FILE_SEIS_HEADER'
        ORDER BY ORDINAL_POSITION""")).fetchall()]
    print("FILE_SEIS_HEADER columns:", ", ".join(cols))
    print()

    # find the suspicious survey rows and their source files
    for name in ['Active Leases TX', 'blocks']:
        print(f"--- SURVEY_NAME = '{name}' ---")
        rows = c.execute(text("""
            SELECT sh.SURVEY_NAME, sh.INVENTORY_ID,
                   g.FILE_NAME, g.FILE_EXT, g.FILE_PATH
            FROM file_catalog.FILE_SEIS_HEADER sh
            LEFT JOIN file_catalog.GLOBAL_FILE_CATALOG g
              ON g.INVENTORY_ID = sh.INVENTORY_ID
            WHERE sh.SURVEY_NAME = :n"""), {"n": name}).fetchall()
        for sn, inv, fname, fext, fpath in rows:
            print(f"   file={fname}  ext={fext}")
            print(f"   path={fpath}")
        if not rows:
            print("   (no matching header rows — survey may have no INVENTORY_ID link)")
        print()

    # broader: any FILE_SEIS_HEADER whose source file is NOT a seismic extension?
    print("=== ALL FILE_SEIS_HEADER rows from NON-seismic source files ===")
    bad = c.execute(text("""
        SELECT g.FILE_EXT, COUNT(*) n
        FROM file_catalog.FILE_SEIS_HEADER sh
        JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID = sh.INVENTORY_ID
        WHERE LOWER(g.FILE_EXT) NOT IN ('.segy','.sgy','.sgm')
        GROUP BY g.FILE_EXT ORDER BY n DESC""")).fetchall()
    if bad:
        for ext, n in bad:
            print(f"   {ext}: {n} seismic-header rows  <-- NOT a SEG-Y file!")
    else:
        print("   (none — all seismic headers come from real SEG-Y files)")

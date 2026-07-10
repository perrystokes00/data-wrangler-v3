"""check_dup_hashes.py — are the dedup 'duplicates' truly identical files, or
different wells colliding on FILE_HASH? Compares file size + a real content hash
for a few flagged duplicate pairs. py check_dup_hashes.py"""
import pyodbc, hashlib, os
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

# find pairs: a 'duplicate' and the file it duplicates (same FILE_HASH)
rows = c.execute("""
    SELECT g.FILE_HASH, g.FILE_NAME, g.FILE_PATH, g.DUPLICATE_GROUP
    FROM file_catalog.GLOBAL_FILE_CATALOG g
    WHERE LOWER(g.FILE_EXT)='.las'
      AND g.FILE_HASH IN (
        SELECT FILE_HASH FROM file_catalog.GLOBAL_FILE_CATALOG
        WHERE LOWER(FILE_EXT)='.las' GROUP BY FILE_HASH HAVING COUNT(*) > 1)
    ORDER BY g.FILE_HASH, g.FILE_NAME""").fetchall()

from collections import defaultdict
groups = defaultdict(list)
for r in rows:
    groups[r[0]].append((r[1], r[2]))

print(f"{len(groups)} FILE_HASH value(s) shared by multiple .las files\n")
def real_sha1(p):
    try:
        h = hashlib.sha1()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest().upper(), os.path.getsize(p)
    except Exception as e:
        return f"(err {e})", None

for i, (fh, members) in enumerate(list(groups.items())[:5]):
    print(f"=== FILE_HASH {fh[:20]}… ({len(members)} files) ===")
    for name, path in members[:3]:
        rh, sz = real_sha1(path)
        print(f"   {name:22} size={sz} real_sha1={rh[:20]}…")
    # are the real hashes actually the same?
    hashes = {real_sha1(p)[0] for _, p in members}
    print("   -> truly identical files?" , "YES (real dupes)" if len(hashes)==1 else "NO — DIFFERENT files colliding on FILE_HASH!")
    print()

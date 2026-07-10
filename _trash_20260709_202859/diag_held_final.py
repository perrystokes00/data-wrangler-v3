"""diag_held_final.py — for the tops/prod held rows WITH a parent well: are they
eligible (would promote+clear) or held by an unseeded ref code? Check each ref FK
column's values against its reference. writes to file. py diag_held_final.py"""
import pyodbc, os
OUT = r"C:\Bulk\reports\held_final.txt"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
L=[]
def log(*a):
    s=" ".join(str(x) for x in a); print(s); L.append(s)
c = pyodbc.connect(r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no",autocommit=True).cursor()
NORM=("LEFT(LTRIM(RTRIM(REPLACE(REPLACE(REPLACE(CONVERT(varchar(64),{col}),'-',''),' ',''),'/','')))+'00000000000000',14)")

for cat, dv in (("cat_well_formation_top","dv_well_formation_top"),
                ("cat_prod_volume","dv_prod_volume")):
    log(f"\n=== {cat}: check every dv_r_* FK column for unseeded values (parent-well rows only) ===")
    # discover the ref FK columns on dv table
    fks = c.execute("""
        SELECT cpa.name, rt.name, cref.name
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id
        JOIN sys.tables pt ON pt.object_id=fk.parent_object_id
        JOIN sys.schemas ps ON ps.schema_id=pt.schema_id
        JOIN sys.tables rt ON rt.object_id=fk.referenced_object_id
        JOIN sys.columns cpa ON cpa.object_id=fkc.parent_object_id AND cpa.column_id=fkc.parent_column_id
        JOIN sys.columns cref ON cref.object_id=fkc.referenced_object_id AND cref.column_id=fkc.referenced_column_id
        WHERE ps.name='dataview' AND pt.name=? AND rt.name LIKE 'dv[_]r[_]%'""", dv).fetchall()
    log(f"   ref FK columns: {[(f[0],f[1]) for f in fks]}")
    for localcol, reftab, refcol in fks:
        # is this column present on the cat table?
        has = c.execute("SELECT COUNT(*) FROM sys.columns cc JOIN sys.tables t ON t.object_id=cc.object_id JOIN sys.schemas s ON s.schema_id=t.schema_id WHERE s.name='file_catalog' AND t.name=? AND cc.name=?", cat, localcol).fetchone()[0]
        if not has:
            continue
        try:
            miss = c.execute(f"""
                SELECT DISTINCT LTRIM(RTRIM(CONVERT(varchar(64),m.[{localcol}])))
                FROM file_catalog.{cat} m
                WHERE m.PROMOTED=0 AND m.[{localcol}] IS NOT NULL
                  AND EXISTS (SELECT 1 FROM dataview.dv_well w WHERE w.uwi={NORM.format(col='m.UWI')})
                  AND NOT EXISTS (SELECT 1 FROM dataview.{reftab} r WHERE r.[{refcol}]=m.[{localcol}])
            """).fetchall()
            vals = [r[0] for r in miss]
            if vals:
                log(f"   [{localcol}] -> {reftab}: UNSEEDED holding rows: {vals}")
            else:
                log(f"   [{localcol}] -> {reftab}: all values seeded OK")
        except Exception as e:
            log(f"   [{localcol}]: err {str(e)[:50]}")
open(OUT,"w",encoding="utf-8").write("\n".join(L))
print("\n>>> written to",OUT,"— upload it")

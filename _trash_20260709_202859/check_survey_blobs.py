"""check_survey_blobs.py — did the survey blob enclose ALL its lines? Compares each
dv_seis_set polygon's vertex count / area against its line count. A blob around many
lines should have more vertices + larger area than a single-line hull.
py check_survey_blobs.py"""
import pyodbc
c = pyodbc.connect(
    r"DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost\SQLEXPRESS;"
    r"DATABASE=DataView_Demo;Trusted_Connection=yes;Encrypt=no", autocommit=True).cursor()

print("=== per-survey: lines vs blob geometry ===")
rows = c.execute("""
    SELECT ss.seis_set_name,
           (SELECT COUNT(*) FROM file_catalog.FILE_SEIS_HEADER h
            WHERE UPPER(LTRIM(RTRIM(h.SURVEY_NAME))) = UPPER(LTRIM(RTRIM(ss.seis_set_name)))) AS n_lines,
           CASE WHEN ss.geog IS NULL THEN NULL ELSE ss.geog.STNumPoints() END AS blob_pts,
           CASE WHEN ss.geog IS NULL THEN NULL
                ELSE ROUND(ss.geog.STArea()/1000000.0, 1) END AS blob_km2
    FROM dataview.dv_seis_set ss
    ORDER BY n_lines DESC""").fetchall()
multi = 0
for r in rows[:20]:
    name, nl, pts, km2 = r
    flag = ""
    if nl and nl > 1:
        multi += 1
        # a multi-line survey whose blob has only ~4-5 points MIGHT still be one line's hull
        flag = "  <-- multi-line" + ("  (blob looks aggregated)" if (pts or 0) >= 4 else "")
    print(f"   {str(name)[:34]:34} lines={nl or 0:>3}  blob_pts={pts or '-':>4}  km2={km2 or '-'}{flag}")
print(f"\nmulti-line surveys: {multi}")
print("If multi-line surveys now show larger blob_pts/km2 than a single line would,")
print("the union-hull worked. If they're tiny, re-promote hasn't run yet.")

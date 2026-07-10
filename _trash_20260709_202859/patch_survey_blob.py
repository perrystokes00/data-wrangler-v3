r"""
patch_survey_blob.py — fix 'convex hull not drawing around all lines in a survey'.

promote_seismic builds dv_seis_set.geog from MAX(SURVEY_OUTLINE) — ONE arbitrary
line's hull per survey, not a blob around all lines. This adds a pass right after
the MERGE that recomputes geog as the CONVEX HULL of the UNION of every line's
outline in the survey (geography::UnionAggregate -> STConvexHull), so the survey
outline encloses ALL its lines. In place, .bak, idempotent. py patch_survey_blob.py
"""
import sys, os, ast
P = "promote_catalog.py"
if not os.path.exists(P):
    P = os.path.join("modules", "promote_catalog.py")
if not os.path.exists(P):
    sys.exit("promote_catalog.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()
if "survey-blob aggregation" in s:
    print("already patched"); sys.exit(0)

anchor = '''    merged = cur.rowcount or 0
    cur.execute("IF OBJECT_ID('tempdb..#badseis') IS NOT NULL DROP TABLE #badseis")'''
inject = '''    merged = cur.rowcount or 0

    # ── survey-blob aggregation ──────────────────────────────────────────────
    # The MERGE set geog from ONE line's outline (MAX(SURVEY_OUTLINE)). Recompute
    # it here as the CONVEX HULL of the UNION of EVERY line's outline in the
    # survey, so the survey polygon encloses ALL its lines — not just one. Built
    # server-side via geography::UnionAggregate over the valid per-line outlines,
    # then .STConvexHull(). Surveys flagged in #badseis (invalid geom) are left as
    # the MERGE set them. Grouped by the SAME normalized name the MERGE used.
    try:
        cur.execute(f"""
            WITH line_geo AS (
                SELECT {_norm} AS nkey,
                       geography::STGeomFromText(s.SURVEY_OUTLINE,4326).MakeValid() AS g
                FROM file_catalog.FILE_SEIS_HEADER s
                LEFT JOIN #badseis bs ON bs.sn = s.SURVEY_NAME
                WHERE s.SURVEY_OUTLINE IS NOT NULL
                  AND bs.sn IS NULL
                  AND NULLIF(LTRIM(RTRIM(s.SURVEY_NAME)),'') IS NOT NULL
                  AND geography::STGeomFromText(s.SURVEY_OUTLINE,4326).MakeValid().STIsValid() = 1
            ),
            survey_blob AS (
                SELECT nkey,
                       geography::UnionAggregate(g) AS ug
                FROM line_geo
                GROUP BY nkey
            )
            UPDATE tgt SET tgt.geog =
                CASE WHEN sb.ug IS NULL THEN tgt.geog
                     WHEN sb.ug.STConvexHull().STArea()/1000000.0 > 255000000
                       THEN sb.ug.STConvexHull().ReorientObject()
                     ELSE sb.ug.STConvexHull()
                END
            FROM dataview.dv_seis_set tgt
            JOIN survey_blob sb
              ON UPPER(LTRIM(RTRIM(tgt.seis_set_name))) = sb.nkey
        """)
        _nblob = cur.rowcount or 0
        if _nblob:
            log(f"  seismic survey-blob: rebuilt {_nblob} survey outline(s) as "
                f"the hull enclosing ALL lines")
    except Exception as _bx:
        log(f"  seismic survey-blob skipped: {str(_bx).splitlines()[0][:100]}")

    cur.execute("IF OBJECT_ID('tempdb..#badseis') IS NOT NULL DROP TABLE #badseis")'''

if anchor not in s:
    sys.exit("FAILED: post-MERGE anchor not found")
s = s.replace(anchor, inject, 1)
ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: survey outline now encloses ALL lines (union-hull per survey)")

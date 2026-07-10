r"""
patch_survey_blob_resilient.py — make the survey-blob rebuild resilient to bad geoms.

The original survey-blob pass runs ONE geography::UnionAggregate across ALL surveys.
If a single survey has a geometry UnionAggregate can't handle (the .NET Framework
error seen on BRECON 3D / TARATA 3D MERGE), the WHOLE statement throws and EVERY
survey's blob is skipped. This replaces that single set-based UPDATE with a
per-survey loop: each survey's hull is built and committed independently inside its
own TRY/CATCH, so one bad survey is skipped and logged while all the good ones still
get their union-hull outline.

Works whether or not patch_survey_blob.py is already applied:
 - if the old block is present, it's REPLACED with the resilient version
 - if not, the resilient block is INJECTED after the MERGE
In place, .bak, idempotent. py patch_survey_blob_resilient.py
"""
import sys, os, ast
P = "promote_catalog.py"
if not os.path.exists(P):
    P = os.path.join("modules", "promote_catalog.py")
if not os.path.exists(P):
    sys.exit("promote_catalog.py not found (copy it here first)")
s = open(P, encoding="utf-8").read()

if "survey-blob resilient" in s:
    print("already patched (resilient)"); sys.exit(0)

# The resilient block: per-survey loop. Uses T-SQL server-side cursor over the
# distinct normalized survey names, building each hull in its own TRY/CATCH so a
# bad geometry skips ONE survey, not all. Runs entirely server-side (one exec).
resilient = r'''    merged = cur.rowcount or 0

    # ── survey-blob resilient ────────────────────────────────────────────────
    # Rebuild each dv_seis_set.geog as the CONVEX HULL of the UNION of every valid
    # line outline in that survey. Done PER SURVEY inside a T-SQL loop with its own
    # TRY/CATCH, so a survey whose geometry UnionAggregate can't process (the .NET
    # Framework error on some merged/degenerate 3D surveys) is skipped and counted
    # WITHOUT killing the rebuild for every other survey. Grouped by the same
    # normalized name the MERGE used.
    try:
        cur.execute(f"""
        SET NOCOUNT ON;
        DECLARE @ok int = 0, @bad int = 0;
        DECLARE @nkey nvarchar(255), @hull geography;

        IF OBJECT_ID('tempdb..#surv') IS NOT NULL DROP TABLE #surv;
        SELECT DISTINCT {_norm} AS nkey
        INTO #surv
        FROM file_catalog.FILE_SEIS_HEADER s
        LEFT JOIN #badseis bs ON bs.sn = s.SURVEY_NAME
        WHERE s.SURVEY_OUTLINE IS NOT NULL
          AND bs.sn IS NULL
          AND NULLIF(LTRIM(RTRIM(s.SURVEY_NAME)),'') IS NOT NULL;

        DECLARE surv_cur CURSOR LOCAL FAST_FORWARD FOR SELECT nkey FROM #surv;
        OPEN surv_cur;
        FETCH NEXT FROM surv_cur INTO @nkey;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            BEGIN TRY
                SET @hull = NULL;
                ;WITH line_geo AS (
                    SELECT geography::STGeomFromText(s.SURVEY_OUTLINE,4326).MakeValid() AS g
                    FROM file_catalog.FILE_SEIS_HEADER s
                    LEFT JOIN #badseis bs ON bs.sn = s.SURVEY_NAME
                    WHERE bs.sn IS NULL
                      AND s.SURVEY_OUTLINE IS NOT NULL
                      AND {_norm} = @nkey
                      AND geography::STGeomFromText(s.SURVEY_OUTLINE,4326).MakeValid().STIsValid() = 1
                )
                SELECT @hull = geography::UnionAggregate(g).STConvexHull() FROM line_geo;

                IF @hull IS NOT NULL
                BEGIN
                    IF @hull.STArea()/1000000.0 > 255000000 SET @hull = @hull.ReorientObject();
                    UPDATE tgt SET tgt.geog = @hull
                    FROM dataview.dv_seis_set tgt
                    WHERE UPPER(LTRIM(RTRIM(tgt.seis_set_name))) = @nkey;
                    SET @ok = @ok + 1;
                END
            END TRY
            BEGIN CATCH
                SET @bad = @bad + 1;   -- this survey's geom failed; leave MERGE value
            END CATCH
            FETCH NEXT FROM surv_cur INTO @nkey;
        END
        CLOSE surv_cur; DEALLOCATE surv_cur;
        IF OBJECT_ID('tempdb..#surv') IS NOT NULL DROP TABLE #surv;
        SELECT @ok AS rebuilt, @bad AS skipped;
        """)
        _row = cur.fetchone()
        _ok = int(_row[0]) if _row else 0
        _bad = int(_row[1]) if _row else 0
        if _ok:
            log(f"  seismic survey-blob: rebuilt {_ok} survey outline(s) as the "
                f"hull enclosing ALL lines" + (f"; {_bad} skipped (bad geom)" if _bad else ""))
        elif _bad:
            log(f"  seismic survey-blob: {_bad} survey(s) skipped (bad geom); none rebuilt")
    except Exception as _bx:
        log(f"  seismic survey-blob skipped: {str(_bx).splitlines()[0][:100]}")

    cur.execute("IF OBJECT_ID('tempdb..#badseis') IS NOT NULL DROP TABLE #badseis")'''

# Case A: the old (non-resilient) survey-blob block is present -> replace it.
old_start = "    merged = cur.rowcount or 0\n\n    # \u2500\u2500 survey-blob aggregation"
if "# \u2500\u2500 survey-blob aggregation" in s or "survey-blob aggregation" in s:
    # replace from 'merged = cur.rowcount or 0' (the one before the aggregation
    # comment) through the closing '#badseis' DROP that follows the block.
    import re
    # find the block: starts at the 'merged = cur.rowcount or 0' that precedes
    # 'survey-blob aggregation', ends at the DROP TABLE #badseis line after it.
    m = re.search(
        r"    merged = cur\.rowcount or 0\n\n    # .*?survey-blob aggregation.*?"
        r"cur\.execute\(\"IF OBJECT_ID\('tempdb\.\.#badseis'\) IS NOT NULL DROP TABLE #badseis\"\)",
        s, flags=re.S)
    if not m:
        sys.exit("FAILED: found aggregation marker but couldn't bound the block")
    s = s[:m.start()] + resilient + s[m.end():]
    mode = "replaced non-resilient block"
else:
    # Case B: no survey-blob patch yet -> inject after the MERGE anchor.
    anchor = '''    merged = cur.rowcount or 0
    cur.execute("IF OBJECT_ID('tempdb..#badseis') IS NOT NULL DROP TABLE #badseis")'''
    if anchor not in s:
        sys.exit("FAILED: post-MERGE anchor not found (and no existing block to replace)")
    s = s.replace(anchor, resilient, 1)
    mode = "injected fresh"

ast.parse(s)
open(P + ".bak", "w", encoding="utf-8").write(open(P, encoding="utf-8").read())
open(P, "w", encoding="utf-8").write(s)
print(f"patched {P}: survey-blob now per-survey resilient ({mode})")

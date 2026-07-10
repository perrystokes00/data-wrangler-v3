"""Identify which seismic survey (and any spatial feature) has geometry that
fails SQL Server geography validation — the row that aborted promote_seismic.

Checks each SURVEY_OUTLINE WKT individually via STGeomFromText().MakeValid()
.STIsValid(), and reports the offenders with their file path so you can fix the
source shapefile (or accept NULL geog for it)."""
import worker_core as w
from sqlalchemy import text

e = w.make_engine(r"localhost\SQLEXPRESS", "DataView_Demo")

def _check_table(con, label, name_sql, wkt_sql, from_sql):
    """Run per-row validity check; return list of (name, reason, extra)."""
    rows = con.execute(text(
        f"SELECT {name_sql} AS nm, {wkt_sql} AS wkt {from_sql}")).fetchall()
    bad = []
    for nm, wkt in rows:
        if not wkt:
            continue
        # ask SQL Server to validate this single instance
        try:
            valid, area = con.execute(text("""
                SET ANSI_WARNINGS OFF;
                DECLARE @g geography = geography::STGeomFromText(:wkt,4326).MakeValid();
                SELECT @g.STIsValid(),
                       CASE WHEN @g.STIsValid()=1 THEN @g.STArea()/1000000.0 ELSE NULL END
            """), {"wkt": wkt}).fetchone()
            if valid != 1:
                bad.append((nm, "INVALID after MakeValid", f"{len(wkt)}ch wkt"))
        except Exception as ex:
            bad.append((nm, f"THROWS: {str(ex).splitlines()[0][:70]}", f"{len(wkt)}ch"))
    return bad, len(rows)

with e.connect() as con:
    print("=== SEISMIC surveys (FILE_SEIS_HEADER.SURVEY_OUTLINE) ===")
    bad, total = _check_table(
        con, "seismic",
        "s.SURVEY_NAME", "s.SURVEY_OUTLINE",
        """FROM file_catalog.FILE_SEIS_HEADER s
           WHERE NULLIF(LTRIM(RTRIM(s.SURVEY_NAME)),'') IS NOT NULL
             AND s.SURVEY_OUTLINE IS NOT NULL""")
    print(f"   checked {total} surveys with geometry; {len(bad)} bad:")
    for nm, reason, extra in bad:
        # find the file path for this survey
        fp = con.execute(text("""
            SELECT TOP 1 g.FILE_PATH FROM file_catalog.FILE_SEIS_HEADER s
            JOIN file_catalog.GLOBAL_FILE_CATALOG g ON g.INVENTORY_ID=s.INVENTORY_ID
            WHERE s.SURVEY_NAME=:n"""), {"n": nm}).scalar()
        print(f"   ✗ {nm}: {reason}  [{extra}]")
        print(f"       file: {fp}")
    if not bad:
        print("   ✓ all seismic geometry valid")

    # also check the spatial cat_ tables
    for lbl, tbl, ncol in [("fields","cat_field","FIELD_NAME"),
                           ("land_tract","cat_land_tract","TRACT_NAME"),
                           ("pipelines","cat_pipeline","PIPELINE_NAME")]:
        print(f"\n=== {lbl} ({tbl}.SPATIAL_OUTLINE) ===")
        try:
            bad, total = _check_table(
                con, lbl, ncol, "SPATIAL_OUTLINE",
                f"FROM file_catalog.{tbl} WHERE SPATIAL_OUTLINE IS NOT NULL")
            print(f"   checked {total}; {len(bad)} bad:")
            for nm, reason, extra in bad:
                print(f"   ✗ {nm}: {reason} [{extra}]")
            if not bad:
                print(f"   ✓ all {lbl} geometry valid")
        except Exception as ex:
            print(f"   (skip: {str(ex)[:60]})")
